import React, { useEffect, useState } from 'react';
import { mountRoot } from '../settings/root';
import { RatingScaleEditor } from './RatingScaleEditor';
import { palette as basePalette } from './mountCollectionCopyFields';
import { draftFromScale, draftPayload, newDraft } from './ratingScaleModel';

// The sheet sits on the page background, so its grouped cards (the surface colour) stand out.
const palette = { ...basePalette, surfaceDim: 'var(--color-page-bg)' };

function csrf(props) {
  const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
  return props.csrfToken || (match ? decodeURIComponent(match[1]) : '');
}

async function call(props, method, path, body) {
  const response = await fetch(`/api/v1/user/rating-scales/${path}`, {
    method,
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf(props) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || props.labels?.saveError || 'The rating scale could not be saved.');
  return data;
}

// The preferences page's Rating Scale menu opens this through a window event; it tells the menu about the
// result with another, so the menu keeps the person's other unsaved preference changes.
function Adapter({ props }) {
  const [draft, setDraft] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    async function open(event) {
      setError('');
      const id = event.detail?.id;
      if (!id) { setDraft(newDraft()); return; }
      const list = await call(props, 'GET', '');
      const scale = list.results.find(item => item.id === id);
      setDraft(scale ? draftFromScale(scale) : newDraft());
    }
    window.addEventListener('floppy:rating-scale-editor', open);
    return () => window.removeEventListener('floppy:rating-scale-editor', open);
  }, [props]);

  async function publish(select) {
    const list = await call(props, 'GET', '');
    window.dispatchEvent(new CustomEvent('floppy:rating-scales', { detail: { scales: list.results, select } }));
  }

  async function save(next) {
    setBusy(true);
    setError('');
    try {
      const payload = draftPayload(next);
      const saved = next.id ? await call(props, 'PUT', `${next.id}/`, payload) : await call(props, 'POST', '', payload);
      await publish(next.id ? null : saved.id);
      setDraft(null);
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    try {
      await call(props, 'DELETE', `${draft.id}/`);
      await publish(null);
      setDraft(null);
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  }

  return <RatingScaleEditor open={Boolean(draft)} draft={draft} onChange={setDraft} onSave={save} onDelete={remove}
    onClose={() => setDraft(null)} busy={busy} error={error} palette={palette} labels={props.labels} />;
}

export function mountRatingScaleEditor(host, props) {
  return mountRoot(host, <Adapter props={props || {}} />);
}
