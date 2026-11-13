import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { mountRoot } from '../settings/root';
import { CollectionContextCard, CollectionCopyEditor, CollectionEntryGroup, CollectionEpisodeList, CollectionEpisodeToggle, CollectionSectionHeading, collectionSeasonEpisodes } from './CollectionCopies';

const palette = {
  text: 'var(--color-text)',
  textSecondary: 'var(--color-text-secondary)',
  textMuted: 'var(--color-text-muted)',
  surface: 'var(--color-surface)',
  surfaceStrong: 'var(--color-surface-strong)',
  surfaceMuted: 'var(--color-surface-muted)',
  border: 'var(--color-surface-border)',
  accent: 'var(--color-accent)',
  accentStrong: 'var(--color-accent-strong)',
  accentContrast: 'var(--color-accent-contrast)',
  danger: 'var(--color-error-text)',
  success: 'var(--color-status-clean)',
  warning: 'var(--color-warning-text)',
  overlay: 'rgba(0, 0, 0, 0.55)',
  focusStyle: {},
};

function CopyFieldsAdapter({ host, props }) {
  const [values, setValues] = useState(props.values || {});

  useEffect(() => {
    const form = host.closest('form');
    if (!form) return;
    form.querySelectorAll('input[data-collection-copy-hidden]').forEach((input) => input.remove());
    (props.fields || []).forEach((field) => {
      const value = values[field.name];
      if (field.type === 'checkbox') {
        if (!value) return;
      } else if (value === '' || value === null || value === undefined) {
        return;
      }
      const input = document.createElement('input');
      input.type = 'hidden';
      input.name = field.name;
      input.value = value === true ? 'on' : String(value);
      input.setAttribute('data-collection-copy-hidden', '');
      form.appendChild(input);
    });
  }, [host, props.fields, values]);

  return <CollectionCopyEditor
    fields={props.fields || []}
    values={values}
    errors={props.errors || {}}
    palette={palette}
    canMutate
    onChange={(name, value) => setValues((current) => ({ ...current, [name]: value }))} />;
}

export function mountCollectionCopyFields(host, props) {
  return mountRoot(host, <CopyFieldsAdapter host={host} props={props} />);
}

function CollectionContextAdapter({ props }) {
  const [context, setContext] = useState(null);
  useEffect(() => {
    const controller = new AbortController();
    fetch(props.url, { credentials: 'same-origin', signal: controller.signal })
      .then(response => { if (!response.ok) throw new Error('Collection unavailable'); return response.json(); })
      .then(payload => setContext({ stats: payload.stats, copies: payload.context_copies || [], resolutionCounts: payload.resolution_counts }))
      .catch(error => { if (error.name !== 'AbortError') setContext({ error: true }); });
    return () => controller.abort();
  }, [props.url]);
  return <CollectionContextCard context={context} palette={palette} variant="web" />;
}

export function mountCollectionContext(host, props) {
  return mountRoot(host, <CollectionContextAdapter props={props} />);
}

function WebSeasonDisclosure({ episodes, toggleHost }) {
  const [expanded, setExpanded] = useState(false);
  if (!episodes.length || !toggleHost) return null;
  return <>
    {createPortal(<CollectionEpisodeToggle expanded={expanded} onPress={() => setExpanded(value => !value)} palette={palette} />, toggleHost)}
    {expanded ? <CollectionEpisodeList episodes={episodes} palette={palette} variant="web" /> : null}
  </>;
}

// Retain the original HTMX/Alpine form nodes and their handlers inside the
// shared card; the server remains responsible for edit and delete operations.
function EntryGroupAdapter({ nodes, props }) {
  const slot = useRef(null);
  useLayoutEffect(() => { slot.current.append(...nodes); }, [nodes]);
  useEffect(() => {
    const placeholders = [...slot.current.querySelectorAll('[data-collection-season-disclosure]')];
    if (!placeholders.length || !props.url) return undefined;
    const controller = new AbortController();
    const dispose = [];
    fetch(props.url, { credentials: 'same-origin', signal: controller.signal })
      .then(response => { if (!response.ok) throw new Error('Collection unavailable'); return response.json(); })
      .then(payload => placeholders.forEach(host => {
        const season = Number(host.dataset.collectionSeasonDisclosure);
        const row = (payload.audit_entries || []).find(entry => entry.season_number === season);
        const episodes = collectionSeasonEpisodes(row?.episodes || []);
        const toggleHost = host.parentElement?.querySelector('[data-collection-season-toggle]');
        dispose.push(mountRoot(host, <WebSeasonDisclosure episodes={episodes} toggleHost={toggleHost} />));
      }))
      .catch(error => { if (error.name !== 'AbortError') console.error('Collection episode details could not load', error); });
    return () => { controller.abort(); dispose.forEach(unmount => unmount()); };
  }, [props.url]);
  return <CollectionEntryGroup palette={palette} variant="web" contentRef={slot} />;
}

export function mountCollectionEntryGroup(host, props) {
  const nodes = [...host.childNodes];
  const fallbackClass = host.className;
  const heading = host.parentElement?.parentElement?.querySelector('[data-collection-section-heading]');
  const headingTitle = heading?.textContent.trim();
  const unmountHeading = heading && headingTitle
    ? mountRoot(heading, <CollectionSectionHeading title={headingTitle} palette={palette} variant="web" />) : null;
  const fragment = document.createDocumentFragment();
  fragment.append(...nodes);
  const dispose = mountRoot(host, <EntryGroupAdapter nodes={nodes} props={props} />);
  host.className = '';
  return () => { dispose(); unmountHeading?.(); host.className = fallbackClass; host.append(...nodes); };
}
