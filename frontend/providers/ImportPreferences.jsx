import React, { useEffect, useRef, useState } from 'react';
import { Button, Card, ComboField, Field, SelectField, Tooltip } from '../ui/controls';
import { mountRoot } from '../settings/root';

export function useImportPreferences(initial, draft, onChange) {
  const [values, setValues] = useState(() => {
    const current = { ...initial.values, ...draft };
    if (initial.profile === 'clz' && !['new', 'overwrite'].includes(current.mode)) current.mode = 'new';
    return current;
  });
  const [saveState, setSaveState] = useState('');
  const pending = useRef(Promise.resolve()), version = useRef(0), controller = useRef(new AbortController());
  useEffect(() => () => controller.current.abort(), []);
  function update(next) { setValues(next); onChange?.(next); }
  function save(next) {
    update(next); setSaveState('saving');
    const revision = ++version.current;
    pending.current = pending.current.catch(() => {}).then(async () => {
      if (controller.current.signal.aborted) return;
      const body = new URLSearchParams({ import_frequency: next.frequency, import_time: next.time,
        import_mode: next.mode, watchlist_status: next.watchlistStatus, watchlist_tag: next.watchlistTag,
        csrfmiddlewaretoken: initial.csrf });
      if (initial.profile === 'clz') {
        body.set('clz_wishlist_status', next.clzWishlistStatus);
        body.set('clz_wishlist_tag', next.clzWishlistTag);
      }
      const response = await fetch(initial.saveUrl, {
        method: 'POST', credentials: 'same-origin', signal: controller.current.signal,
        headers: { 'X-CSRFToken': initial.csrf },
        body,
      });
      if (response.status !== 204) throw new Error('Preference save failed');
      if (revision === version.current) setSaveState('saved');
    }).catch(() => { if (!controller.current.signal.aborted && revision === version.current) setSaveState('error'); });
  }
  return { values, save, saveState, update };
}

export function ImportPreferences({ initial, values, save, saveState, update }) {
  const t = text => initial.labels[text] || text;
  const clz = initial.profile === 'clz';
  const history = clz || ['new', 'overwrite'].includes(values.mode);
  const previousOverride = useRef(history ? values.mode : 'new');
  const savedClzTag = useRef(values.clzWishlistTag);
  if (history) previousOverride.current = values.mode;
  const select = (label, id, value, options, change) => <SelectField label={t(label)} id={id} value={value}
    options={options} labelHidden={id === 'import-override'} disabled={!initial.editable} onChange={event => change(event.target.value)} />;
  const opts = rows => rows.map(([value, label]) => ({ value, label: t(label) }));
  return <Card title={t('Import preferences')} tone={initial.fixed ? 'warning' : 'info'} badge={t(initial.fixed || !initial.editable ? 'Read-only' : 'Editable')}>
    {initial.fixed ? <>
      <div><span className="provider-small">{t('Import Mode')}</span><p>{initial.fixed.mode}</p></div>
      <div><span className="provider-small">{t('Import Frequency')}</span><p>{initial.fixed.frequency}</p></div>
      <p className="provider-small">{initial.fixed.explanation}</p>
    </> : <>
      {clz ? <div>
        <div className="ui-import-help"><span>{t('Import Mode')}</span><Tooltip label={t('Import mode help')}
          text={t('CLZ imports owned copies and wishlist entries. It does not import reading or viewing history.')} /></div>
        <SelectField label={t('Import Mode')} labelHidden id="import-mode" value="collection_wishlist" disabled
          options={opts([['collection_wishlist', 'Collection and wishlist']])} />
      </div> : select('Import Mode', 'import-mode', history ? 'history' : values.mode,
        opts([['history', 'History'], ['watchlist', 'Watchlist'], ['update_collection', 'Collection']]),
        value => save({ ...values, mode: value === 'history' ? previousOverride.current : value }))}
      {history && <div>
        <div className="ui-import-help"><span>{t('Override mode')}</span><Tooltip label={t('Override mode help')} text={t('New items leaves existing entries unchanged. Overwrite replaces matching imported entries.')} /></div>
        {select('Override mode', 'import-override', values.mode, opts([['new', 'New Items Only'], ['overwrite', 'Overwrite Existing']]),
          mode => save({ ...values, mode }))}
      </div>}
      {clz && <>
        {select('Wishlist items', 'clz-wishlist-status', values.clzWishlistStatus,
          initial.statuses,
          clzWishlistStatus => save({ ...values, clzWishlistStatus }))}
        <ComboField label={t('Tag for wishlist items')} id="clz-wishlist-tag" value={values.clzWishlistTag}
          options={initial.tagNames} placeholder={t('Optional tag name')} maxLength={50} disabled={!initial.editable}
          createLabel={name => t('Create tag "{name}"').replace('{name}', name)}
          onChange={clzWishlistTag => update({ ...values, clzWishlistTag })}
          onCommit={clzWishlistTag => { if (savedClzTag.current !== clzWishlistTag) { savedClzTag.current = clzWishlistTag; save({ ...values, clzWishlistTag }); } }} />
      </>}
      {values.mode === 'watchlist' && <>
        {select('Watchlist status', 'watchlist-status', values.watchlistStatus, initial.statuses, watchlistStatus => save({ ...values, watchlistStatus }))}
        {select('Watchlist tag', 'watchlist-tag', values.watchlistTag, initial.tags, watchlistTag => save({ ...values, watchlistTag }))}
      </>}
      {initial.fixedFrequency ? <div>
        <div className="ui-import-help"><span>{t('Import Frequency')}</span><Tooltip label={t('Import frequency help')} text={initial.fixedFrequencyHelp} /></div>
        <SelectField label={t('Import Frequency')} labelHidden id="import-frequency" value="once" disabled
          options={opts([['once', 'One Time Import']])} />
      </div> : <>
        {select('Import Frequency', 'import-frequency', values.frequency, opts([['once', 'One Time Import'], ['daily', 'Every Day'], ['2days', 'Every 2 Days']]), frequency => save({ ...values, frequency }))}
        {values.frequency !== 'once' && <Field label={t('Import Time')} id="import-time" type="time" value={values.time} required disabled={!initial.editable} onChange={event => save({ ...values, time: event.target.value })} />}
      </>}
      <div role="status" className="provider-small">{saveState === 'error' && t('Could not save preferences. Try again.')}</div>
      {saveState === 'error' && <Button type="button" secondary onClick={() => save(values)}>{t('Retry')}</Button>}
    </>}
  </Card>;
}

function LegacyPreferences({ host, initial }) {
  const state = useImportPreferences(initial, null, values => {
    const parent = host.closest('[x-data]');
    if (parent) {
      parent.importPreferences = values;
      parent.querySelectorAll('[data-file-import-root]:not([data-react-mounted]) [data-import-preference]').forEach(input => {
        input.value = values[input.dataset.importPreference] ?? '';
      });
    }
    host.dispatchEvent(new CustomEvent('import-preferences-changed', { bubbles: true, detail: values }));
  });
  return <ImportPreferences initial={initial} {...state} />;
}
export function mountImportPreferences(host, props) { return mountRoot(host, <LegacyPreferences host={host} initial={props} />); }
