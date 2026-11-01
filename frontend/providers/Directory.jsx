import React, { useEffect, useRef, useState } from 'react';
import { Button, CatalogCard, CatalogGrid, Field, FilterDropdown, FilterToolbar } from '../ui/controls';
import { mountRoot } from '../settings/root';

export function mountDirectory(host, model) {
  const filters = { ...model.filters };
  for (const key of Object.keys(filters)) {
    const field = host.querySelector(`[name="${key}"]`);
    if (field) filters[key] = field.value;
  }
  return mountRoot(host, <Directory model={model} draft={filters} />);
}

function Directory({ model, draft }) {
  const [filters, setFilters] = useState(draft);
  const [items, setItems] = useState(model.items);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [pinPending, setPinPending] = useState('');
  const [pinError, setPinError] = useState(false);
  const pinOverrides = useRef(new Map());
  const initial = useRef(true);
  const t = text => model.labels[text] ?? text;
  useEffect(() => {
    const onBack = () => {
      const params = new URLSearchParams(location.search);
      setFilters({ q: params.get('q') || '', capability: params.get('capability') || '', media: params.get('media') || '' });
    };
    window.addEventListener('popstate', onBack);
    return () => window.removeEventListener('popstate', onBack);
  }, []);
  useEffect(() => {
    if (initial.current) {
      initial.current = false;
      if (Object.keys(filters).every(key => filters[key] === model.filters[key])) return;
    }
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setLoading(true);
      setError(false);
      const url = new URL(model.url, location.origin);
      for (const [key, value] of Object.entries(filters)) if (value) url.searchParams.set(key, value);
      const destination = url.pathname + url.search;
      if (location.pathname + location.search !== destination) history.pushState(null, '', destination);
      url.searchParams.set('format', 'json');
      try {
        const response = await fetch(url, { signal: controller.signal, credentials: 'same-origin' });
        if (!response.ok) throw new Error('Directory request failed');
        const result = await response.json();
        if (!controller.signal.aborted) setItems(result.items.map(item => ({ ...item,
          pinned: pinOverrides.current.has(item.slug) ? pinOverrides.current.get(item.slug) : item.pinned,
        })).sort((a, b) => Number(b.pinned) - Number(a.pinned)));
      } catch (failure) {
        if (!controller.signal.aborted) setError(true);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }, 300);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [filters, retry]);
  const update = key => event => setFilters(current => ({ ...current, [key]: event.target.value }));
  async function setPin(item) {
    if (pinPending) return;
    setPinPending(item.slug); setPinError(false);
    try {
      const response = await fetch(model.pinUrl, { method: 'POST', credentials: 'same-origin',
        headers: { 'X-CSRFToken': model.csrf, Accept: 'application/json' },
        body: new URLSearchParams({ provider: item.slug, pinned: item.pinned ? '0' : '1' }),
      });
      if (!response.ok) throw new Error('Pin update failed');
      const result = await response.json();
      pinOverrides.current.set(item.slug, result.pinned);
      setItems(current => current.map(row => row.slug === item.slug ? { ...row, pinned: result.pinned } : row)
        .sort((a, b) => Number(b.pinned) - Number(a.pinned)));
    } catch { setPinError(true); }
    finally { setPinPending(''); }
  }
  return <section className="provider-directory">
    <header>
      <div className="ui-heading"><h2><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><ellipse cx="12" cy="5" rx="9" ry="3" /><path d="M3 5v14a9 3 0 0 0 18 0V5M3 12a9 3 0 0 0 18 0" /></svg>{t('Providers')}</h2>
        <a href={model.setupUrl}>{t('Run guided setup')}</a></div>
      <p>{t('Find services and their available settings.')}</p>
    </header>
    <FilterToolbar action={model.url} method="get" onSubmit={event => event.preventDefault()}>
      <Field label={t('Search providers')} labelHidden id="provider-search" name="q" type="search"
        icon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="10.5" cy="10.5" r="7.5" /><path d="m16 16 5 5" /></svg>}
        autoComplete="off" placeholder={t('Search providers...')} value={filters.q} onChange={update('q')} />
      <FilterDropdown label={t('Filter by capability')} id="provider-capability" name="capability"
        options={model.capabilities} value={filters.capability} onChange={update('capability')} />
      <FilterDropdown label={t('Filter by media type')} id="provider-media" name="media"
        options={model.media} value={filters.media} onChange={update('media')} />
    </FilterToolbar>
    {error && <div role="alert">{t('Could not load providers. Try again.')}<Button secondary onClick={() => setRetry(value => value + 1)}>{t('Retry')}</Button></div>}
    {pinError && <p role="alert">{t('Could not update the pinned provider. Try again.')}</p>}
    <CatalogGrid id="provider-results" aria-busy={loading}>
      {items.map(item => <CatalogCard key={item.slug} title={item.title} description={item.description}
        logo={item.logo} href={item.url} label={item.openLabel} attention={item.attention} status={item.status}
        pinned={item.pinned} pinLabel={item.pinned ? item.unpinLabel : item.pinLabel} pinDisabled={!!pinPending}
        onPin={model.canPin ? () => setPin(item) : undefined} />)}
      {!items.length && <p className="ui-catalog-empty" role="status">{t('No providers match these filters.')}</p>}
    </CatalogGrid>
  </section>;
}
