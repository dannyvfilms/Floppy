import React, { useEffect, useRef, useState } from 'react';
import { Button, SelectField, Spinner } from './controls';

// The Add-to-lists popup body. The server's lists_modal view answers with a JSON
// form model (?format=json) and list_item_toggle with {success, hasItem}; every
// permission, smart-list rule and error message stays in those views.

const ALL = '';

export function ListsForm({ url, vals, labels, targetId, onClose }) {
  const text = (key, name = '') => (labels[key] || '').replace('%s', name);
  const [model, setModel] = useState(null);
  const [failed, setFailed] = useState(false);
  const [tag, setTag] = useState(ALL);
  const [membership, setMembership] = useState({});
  const [pending, setPending] = useState({});
  const [errors, setErrors] = useState({});
  const [attempt, setAttempt] = useState(0);
  const closeButton = useRef(null);

  useEffect(() => {
    const controller = new AbortController();
    setFailed(false);
    const query = new URLSearchParams({ ...(vals || {}), format: 'json' });
    fetch(`${url}?${query}`, { credentials: 'same-origin', headers: { Accept: 'application/json' }, signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error(String(response.status)); return response.json(); })
      .then((data) => {
        setModel(data);
        setMembership(Object.fromEntries(data.lists.map((list) => [list.id, list.hasItem])));
      })
      .catch((error) => { if (error.name !== 'AbortError') setFailed(true); });
    return () => controller.abort();
  }, [url, attempt]);

  useEffect(() => { closeButton.current?.focus(); }, []);

  async function toggle(list) {
    if (pending[list.id]) return;
    setPending((current) => ({ ...current, [list.id]: true }));
    setErrors((current) => ({ ...current, [list.id]: '' }));
    let message = '';
    try {
      const body = new URLSearchParams({ custom_list_id: list.id, item_id: model.itemId, format: 'json' });
      const response = await fetch(model.toggleUrl, {
        method: 'POST', credentials: 'same-origin', body,
        headers: { 'X-CSRFToken': model.csrfToken, Accept: 'application/json' },
      });
      const data = await response.json().catch(() => ({}));
      if (response.ok && data.success) {
        setMembership((current) => ({ ...current, [list.id]: data.hasItem }));
        window.dispatchEvent(new CustomEvent('floppy-list-toggled', { detail: { listId: list.id, hasItem: data.hasItem } }));
      }
      else message = data.error || text('toggleFailed');
    } catch {
      message = text('toggleFailed');
    }
    setPending((current) => ({ ...current, [list.id]: false }));
    setErrors((current) => ({ ...current, [list.id]: message }));
  }

  const onCount = model ? model.lists.filter((list) => membership[list.id]).length : 0;
  const countLabel = text(onCount === 1 ? 'countOne' : 'countMany', onCount);
  const shown = model ? model.lists.filter((list) => !tag || list.tags.some((entry) => entry.toLowerCase() === tag.toLowerCase())) : [];

  return <div className="ui-modal-card ui-modal-lists" data-lists-form="" id={targetId}>
    <div className="ui-modal-header">
      <h2 id="ui-modal-title">{text('title')}</h2>
      <button ref={closeButton} type="button" className="ui-modal-close" aria-label={text('close')} onClick={onClose}>×</button>
    </div>
    {!model && !failed && <div className="ui-modal-status" role="status"><Spinner /><span>{text('loading')}</span></div>}
    {failed && <div className="ui-modal-status" role="alert">
      <p>{text('loadFailed')}</p>
      <Button type="button" secondary small auto onClick={() => { setModel(null); setAttempt(attempt + 1); }}>{text('retry')}</Button>
    </div>}
    {model && <>
      {model.tags.length > 0
        ? <div className="ui-modal-filter">
          <SelectField id="lists-tag-filter" label={text('filterByTag')} value={tag} onChange={(event) => setTag(event.target.value)}
            options={[{ value: ALL, label: text('allLists') }, ...model.tags.map((entry) => ({ value: entry, label: entry }))]} />
          {onCount > 0 && <span className="ui-modal-count">{countLabel}</span>}
        </div>
        : onCount > 0 && <div className="ui-modal-filter"><span className="ui-modal-count">{countLabel}</span></div>}
      <ul className="ui-modal-list">
        {shown.map((list) => {
          const has = membership[list.id];
          return <li key={list.id}>
            <span className="ui-modal-list-name">{list.name}</span>
            <Button type="button" small auto secondary={!has} disabled={Boolean(pending[list.id])} aria-busy={Boolean(pending[list.id])}
              aria-label={has ? text('removeFrom', list.name) : text('addTo', list.name)}
              onClick={() => toggle(list)}>
              {pending[list.id] ? <Spinner size={14} /> : has ? text('remove') : text('add')}
            </Button>
            {errors[list.id] && <p className="ui-modal-error" role="alert">{errors[list.id]}</p>}
          </li>;
        })}
        {shown.length === 0 && <li className="ui-modal-empty">{model.lists.length ? text('emptyTag') : text('emptyLists')}</li>}
      </ul>
    </>}
  </div>;
}
