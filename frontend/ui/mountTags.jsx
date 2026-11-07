import React, { useEffect, useMemo, useState } from 'react';
import { mountRoot } from '../settings/root';
import { TagsPageView } from '../pages/TagsPageView';
import {
  TagAssignmentDialog,
  TagIndex,
  TagMediaFilter,
  TagPreview,
} from './TagManagement';

const palette = {
  background: 'var(--color-page-bg)',
  surface: 'var(--color-surface)',
  surfaceStrong: 'var(--color-surface-strong)',
  surfaceMuted: 'var(--color-surface-muted)',
  border: 'var(--color-surface-border)',
  text: 'var(--color-text)',
  textSecondary: 'var(--color-text-secondary)',
  textMuted: 'var(--color-text-muted)',
  accent: 'var(--color-accent)',
  accentStrong: 'var(--color-accent)',
  accentText: 'var(--color-accent-contrast)',
  danger: 'var(--color-error-text)',
  success: 'var(--color-status-clean)',
  warning: 'var(--color-warning-text)',
  overlay: 'rgba(0, 0, 0, 0.55)',
  badgeBorder: 'var(--color-surface-border)',
  badgeBackground: 'var(--color-surface-strong)',
  badgeText: 'var(--color-text-secondary)',
  badgeHover: 'var(--color-surface-hover)',
  focusedBorder: 'var(--color-accent)',
  fontFamily: 'inherit',
  interactiveStyle: {
    cursor: 'pointer',
    textDecorationLine: 'none',
    transitionProperty: 'background-color, border-color, color, box-shadow',
  },
  focusStyle: {},
};

function body(values) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      params.append(key, value);
    }
  });
  return params;
}

function readPreviewSections(parsed, node) {
  const root = node.querySelector('[data-tag-preview-root]');
  const script = root?.dataset.propsId ? parsed.getElementById(root.dataset.propsId) : null;
  if (!script) return null;
  try {
    return JSON.parse(script.textContent);
  } catch {
    return null;
  }
}

export function applyPreviewRefresh(html) {
  const parsed = new DOMParser().parseFromString(html, 'text/html');
  parsed.querySelectorAll('[hx-swap-oob="outerHTML"]').forEach((node) => {
    const target = node.id ? document.getElementById(node.id) : null;
    if (!target) return;
    const sections = readPreviewSections(parsed, node);
    const mountedRoot = target.querySelector('[data-tag-preview-root]');
    if (sections && mountedRoot?.dataset.reactMounted === 'true') {
      if (node.dataset.hasPreview) target.dataset.hasPreview = node.dataset.hasPreview;
      window.dispatchEvent(new CustomEvent('tag-preview-update', {
        detail: { id: node.id, sections },
      }));
      return;
    }
    node.removeAttribute('hx-swap-oob');
    target.replaceWith(node);
  });
  return parsed;
}

export function readTags(parsed) {
  return [...parsed.querySelectorAll('[data-tag-row]')].map((row) => ({
    id: Number(row.dataset.tagId),
    name: row.dataset.tagName || '',
    hasTag: row.dataset.hasTag === 'true',
    owned: true,
  }));
}

function TagIndexAdapter({ props }) {
  const [tags, setTags] = useState(props.tags || []);
  const [sort, setSort] = useState(props.sort || 'name');

  const visible = useMemo(() => {
    return [...tags].sort((left, right) => sort === 'count'
      ? right.count - left.count || left.name.toLowerCase().localeCompare(right.name.toLowerCase())
      : left.name.toLowerCase().localeCompare(right.name.toLowerCase()));
  }, [sort, tags]);

  function openType(_tag, type) {
    if (type.url) window.location.assign(type.url);
  }

  function changeSort(next) {
    setSort(next);
    const url = new URL(window.location.href);
    url.searchParams.set('sort', next);
    window.history.replaceState({}, '', url);
  }

  function remove(tag) {
    if (!window.confirm(tag.confirmMessage || `Delete the "${tag.name}" tag from your library? This removes it from every item.`)) return;
    window.fetch(props.urls.delete, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-CSRFToken': props.csrfToken || '' },
      body: body({ tag_id: tag.id }),
    }).then((response) => {
      if (!response.ok) throw new Error('Delete failed');
      setTags((current) => current.filter((entry) => entry.id !== tag.id));
    }).catch(() => {
      window.alert('The tag could not be deleted. Try again.');
    });
  }

  return <TagsPageView
    title={props.title}
    subtitle={props.subtitle}
    tags={visible}
    sort={sort}
    labels={{ ...(props.labels || {}), empty: props.emptyText || props.labels?.empty }}
    palette={palette}
    onSortChange={changeSort}
    onDelete={remove}
    onOpenType={openType} />;
}

function TagAssignmentAdapter({ host, props }) {
  const [tags, setTags] = useState(props.tags || []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  function previewFields() {
    return {
      item_id: props.item.id,
      tag_surface: host.dataset.tagSurface || 'modal',
      preview_genres_json: props.previewGenresJson,
      preview_implied_genres_json: props.previewImpliedGenresJson,
    };
  }

  async function post(url, values) {
    const response = await window.fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-CSRFToken': props.csrfToken || '' },
      body: body({ ...previewFields(), ...values }),
    });
    if (!response.ok) throw new Error('Request failed');
    return applyPreviewRefresh(await response.text());
  }

  function toggle(tag) {
    if (busy) return;
    setBusy(true);
    setError('');
    post(props.urls.toggle, { tag_id: tag.id }).then(() => {
      setTags((current) => current.map((entry) => entry.id === tag.id
        ? { ...entry, hasTag: !entry.hasTag }
        : entry));
    }).catch(() => {
      setError('The tag could not be updated. Try again.');
    }).finally(() => setBusy(false));
  }

  function create(name) {
    if (tags.some((tag) => tag.name.toLowerCase() === name.toLowerCase())) {
      setError(`Tag "${name}" already exists.`);
      return false;
    }
    setBusy(true);
    setError('');
    post(props.urls.create, { name }).then((parsed) => {
      const next = readTags(parsed);
      if (!next.some((tag) => tag.name.toLowerCase() === name.toLowerCase())) {
        setError(`Tag "${name}" already exists.`);
        return;
      }
      setTags(next);
    }).catch(() => {
      setError('The tag could not be created. Try again.');
    }).finally(() => setBusy(false));
    return true;
  }

  function remove(tag) {
    if (busy) return;
    setBusy(true);
    setError('');
    post(props.urls.delete, { tag_id: tag.id }).then((parsed) => {
      setTags(readTags(parsed));
    }).catch(() => {
      setError('The tag could not be deleted. Try again.');
    }).finally(() => setBusy(false));
  }

  function close() {
    setError('');
    host.dispatchEvent(new CustomEvent('tag-assignment-close', { bubbles: true }));
  }

  return <TagAssignmentDialog
    open
    embedded
    showClose={host.dataset.tagSurface !== 'track'}
    item={props.item}
    tags={tags}
    palette={palette}
    busy={busy}
    error={error}
    onToggle={toggle}
    onCreate={create}
    onDelete={remove}
    onClose={close} />;
}

function TagMediaFilterAdapter({ host, props }) {
  const [active, setActive] = useState('all');
  const options = Array.isArray(props) ? props : (props.options || []);

  function select(key) {
    setActive(key);
    host.dispatchEvent(new CustomEvent('tag-media-filter-change', {
      bubbles: true,
      detail: { key },
    }));
  }

  return <TagMediaFilter
    options={options}
    active={active}
    allLabel={host.dataset.allLabel || 'All'}
    prompt={host.dataset.prompt || 'Browse by media type:'}
    summary={host.dataset.summary === 'true'}
    palette={palette}
    onSelect={select} />;
}

function TagPreviewAdapter({ host, props }) {
  const [sections, setSections] = useState(Array.isArray(props) ? props : []);

  useEffect(() => {
    const previewId = host.dataset.previewId || host.id;
    const update = (event) => {
      if (event.detail?.id !== previewId) return;
      setSections(event.detail.sections || []);
    };
    window.addEventListener('tag-preview-update', update);
    return () => window.removeEventListener('tag-preview-update', update);
  }, [host]);

  function openEntry(entry) {
    if (entry.url) window.location.assign(entry.url);
  }

  function openEditor() {
    host.dispatchEvent(new CustomEvent('tag-preview-open', { bubbles: true }));
  }

  return <TagPreview
    sections={sections}
    palette={palette}
    onOpenEntry={openEntry}
    onOpen={openEditor} />;
}

export function mountTagIndex(host, props) {
  return mountRoot(host, <TagIndexAdapter props={props} />);
}
export function mountTagAssignment(host, props) {
  return mountRoot(host, <TagAssignmentAdapter host={host} props={props} />);
}

export function mountTagMediaFilter(host, props) {
  return mountRoot(host, <TagMediaFilterAdapter host={host} props={props} />);
}

export function mountTagPreview(host, props) {
  return mountRoot(host, <TagPreviewAdapter host={host} props={props} />);
}
