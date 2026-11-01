import React, { useEffect, useRef, useState } from 'react';
import { Button, Card, Field, SelectField, Tooltip } from '../ui/controls';
import { mountRoot } from '../settings/root';

export function useImportPreferences(initial, draft, onChange) {
  const [values, setValues] = useState({ ...initial.values, ...draft });
  const [saveState, setSaveState] = useState('');
  const pending = useRef(Promise.resolve()), version = useRef(0), controller = useRef(new AbortController());
  useEffect(() => () => controller.current.abort(), []);
  function save(next) {
    setValues(next); onChange?.(next); setSaveState('saving');
    const revision = ++version.current;
    pending.current = pending.current.catch(() => {}).then(async () => {
      if (controller.current.signal.aborted) return;
      const response = await fetch(initial.saveUrl, {
        method: 'POST', credentials: 'same-origin', signal: controller.current.signal,
        headers: { 'X-CSRFToken': initial.csrf },
        body: new URLSearchParams({ import_frequency: next.frequency, import_time: next.time,
          import_mode: next.mode, watchlist_status: next.watchlistStatus, watchlist_tag: next.watchlistTag,
          csrfmiddlewaretoken: initial.csrf }),
      });
      if (response.status !== 204) throw new Error('Preference save failed');
      if (revision === version.current) setSaveState('saved');
    }).catch(() => { if (!controller.current.signal.aborted && revision === version.current) setSaveState('error'); });
  }
  return { values, save, saveState };
}

export function ImportPreferences({ initial, values, save, saveState }) {
  const t = text => initial.labels[text] || text;
  const history = ['new', 'overwrite'].includes(values.mode);
  const previousOverride = useRef(history ? values.mode : 'new');
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
      {select('Import Mode', 'import-mode', history ? 'history' : values.mode,
        opts([['history', 'History'], ['watchlist', 'Watchlist'], ['update_collection', 'Collection']]),
        value => save({ ...values, mode: value === 'history' ? previousOverride.current : value }))}
      {history && <div>
        <div className="ui-import-help"><span>{t('Override mode')}</span><Tooltip label={t('Override mode help')} text={t('New items leaves existing entries unchanged. Overwrite replaces matching imported entries.')} /></div>
        {select('Override mode', 'import-override', values.mode, opts([['new', 'New Items Only'], ['overwrite', 'Overwrite Existing']]),
          mode => save({ ...values, mode }))}
      </div>}
      {values.mode === 'watchlist' && <>
        {select('Watchlist status', 'watchlist-status', values.watchlistStatus, initial.statuses, watchlistStatus => save({ ...values, watchlistStatus }))}
        {select('Watchlist tag', 'watchlist-tag', values.watchlistTag, initial.tags, watchlistTag => save({ ...values, watchlistTag }))}
      </>}
      {initial.fixedFrequency ? <div><span className="provider-small">{t('Import Frequency')}</span><p>{t('One-time import')}</p><p className="provider-small">{t('Files are imported once when uploaded.')}</p></div> : <>
        {select('Import Frequency', 'import-frequency', values.frequency, opts([['once', 'One Time Import'], ['daily', 'Every Day'], ['2days', 'Every 2 Days']]), frequency => save({ ...values, frequency }))}
        {values.frequency !== 'once' && <Field label={t('Import Time')} id="import-time" type="time" value={values.time} required disabled={!initial.editable} onChange={event => save({ ...values, time: event.target.value })} />}
      </>}
      <div role="status" className="provider-small">{saveState && t(saveState === 'saving' ? 'Saving…' : saveState === 'saved' ? 'Saved' : 'Could not save preferences. Try again.')}</div>
      {saveState === 'error' && <Button type="button" secondary onClick={() => save(values)}>{t('Retry')}</Button>}
    </>}
  </Card>;
}

function LegacyPreferences({ host, initial }) {
  const state = useImportPreferences(initial, null, values => host.dispatchEvent(new CustomEvent('import-preferences-changed', { bubbles: true, detail: values })));
  return <ImportPreferences initial={initial} {...state} />;
}
export function mountImportPreferences(host, props) { return mountRoot(host, <LegacyPreferences host={host} initial={props} />); }
