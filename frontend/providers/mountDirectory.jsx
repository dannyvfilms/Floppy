import React from 'react';
import { mountRoot } from '../settings/root';
import { ProviderDirectoryView } from './ProviderDirectoryView';
import { readThemePalette } from './transport.web';

const DEFAULT_FILTERS = { q: '', capability: '', media: '' };

export function mountDirectory(host, model) {
  const initialFilters = { ...DEFAULT_FILTERS, ...(model.filters || {}) };
  for (const key of Object.keys(initialFilters)) {
    const field = host.querySelector(`[name="${key}"]`);
    if (field) initialFilters[key] = field.value;
  }
  const defaults = { ...DEFAULT_FILTERS, ...(model.filters || {}) };
  const unchanged = Object.keys(defaults).every(key => initialFilters[key] === defaults[key]);
  const colors = readThemePalette();

  function onFetch({ filters, signal }) {
    const url = new URL(model.url, location.origin);
    for (const [key, value] of Object.entries(filters)) if (value) url.searchParams.set(key, value);
    const destination = url.pathname + url.search;
    if (location.pathname + location.search !== destination) history.pushState(null, '', destination);
    url.searchParams.set('format', 'json');
    return fetch(url, { signal, credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(response => {
        if (!response.ok) throw new Error('Directory request failed');
        return response.json();
      });
  }

  function subscribeHistory(listener) {
    const onPop = () => {
      const params = new URLSearchParams(location.search);
      listener({
        q: params.get('q') || '',
        capability: params.get('capability') || '',
        media: params.get('media') || '',
      });
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }

  async function onPin(item) {
    const response = await fetch(model.pinUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-CSRFToken': model.csrf, Accept: 'application/json' },
      body: new URLSearchParams({ provider: item.slug, pinned: item.pinned ? '0' : '1' }),
    });
    if (!response.ok) throw new Error('Pin update failed');
    return response.json();
  }

  return mountRoot(host, <ProviderDirectoryView
    model={model}
    palette={colors}
    initialFilters={initialFilters}
    skipInitialLoad={unchanged}
    onFetch={onFetch}
    onPin={onPin}
    subscribeHistory={subscribeHistory}
    onNavigate={url => { if (url) location.assign(url); }}
  />);
}
