import React, { useEffect, useRef, useState } from 'react';
import { Button, Card, CardGrid, Field, SelectField, ToggleChip } from '../ui/controls';
import { Form, usePage } from './web';

export function Import({ draft }) {
  const { model, t } = usePage();
  const initial = model.imports;
  const [values, setValues] = useState({ frequency: initial.frequency, time: initial.time, mode: initial.mode, ...draft?.preferences });
  const [saveState, setSaveState] = useState('');
  const [privateImport, setPrivateImport] = useState(draft?.privateImport ?? false);
  const [username, setUsername] = useState(draft?.username ?? '');
  const pending = useRef(Promise.resolve());
  const version = useRef(0);
  const controller = useRef(new AbortController());
  useEffect(() => () => controller.current.abort(), []);

  function save(next) {
    setValues(next);
    setSaveState('saving');
    const revision = ++version.current;
    pending.current = pending.current.catch(() => {}).then(async () => {
      if (controller.current.signal.aborted) return;
      const response = await fetch(initial.saveUrl, {
        method: 'POST', credentials: 'same-origin', signal: controller.current.signal,
        headers: { 'X-CSRFToken': model.csrf },
        body: new URLSearchParams({ import_frequency: next.frequency, import_time: next.time,
          import_mode: next.mode, csrfmiddlewaretoken: model.csrf }),
      });
      if (response.status !== 204) throw new Error('Preference save failed');
      if (revision === version.current) setSaveState('saved');
    }).catch(() => {
      if (!controller.current.signal.aborted && revision === version.current) setSaveState('error');
    });
  }
  const disabled = !['new', 'overwrite'].includes(values.mode);
  const frequencyOptions = [['once', 'One Time Import'], ['daily', 'Every Day'], ['2days', 'Every 2 Days']];
  const modeOptions = [['new', 'Only Sync New Items'], ['overwrite', 'Sync New Items and Overwrite Existing'],
    ['watchlist', 'Import Watchlist Data Only'], ['update_collection', 'Update Collection Metadata Only']];
  return <>
    <h3>{t('Import settings')}</h3>
    <CardGrid alignStart>
      <Card title={t('Import preferences')} tone="info" badge={t('Editable')}>
        <SelectField label={t('Import Frequency')} id="import-frequency" name="import_frequency" value={values.frequency}
          onChange={event => save({ ...values, frequency: event.target.value })}
          options={frequencyOptions.map(([value, label]) => ({ value, label: t(label) }))} />
        {values.frequency !== 'once' && <Field label={t('Import Time')} id="import-time" name="import_time"
          type="time" value={values.time} required onChange={event => save({ ...values, time: event.target.value })} />}
        <SelectField label={t('Import Mode')} id="import-mode" name="import_mode" value={values.mode}
          onChange={event => save({ ...values, mode: event.target.value })}
          options={modeOptions.map(([value, label]) => ({ value, label: t(label) }))} />
        <div role="status" className="provider-small">{saveState && t(saveState === 'saving' ? 'Saving…' : saveState === 'saved' ? 'Saved' : 'Could not save preferences. Try again.')}</div>
        {saveState === 'error' && <Button type="button" secondary onClick={() => save(values)}>{t('Retry')}</Button>}
      </Card>
      <Card title={t('Import options')} headerAction={
        <ToggleChip value={privateImport} onChange={setPrivateImport} offLabel={t('Public')} onLabel={t('Private')} />
      }>
        <p>{t('Import anime and manga from your AniList profile.')}</p>
        {privateImport && !initial.configured ? <div className="provider-disabled"><p>{t('Private imports require provider credentials.')}</p>
          <a href={model.urls.connection}>{t('Configure Connection')}</a></div> :
          <Form action={privateImport ? initial.privateUrl : initial.publicUrl}>
            <input type="hidden" name="frequency" value={values.frequency} />
            <input type="hidden" name="time" value={values.time} />
            <input type="hidden" name="mode" value={values.mode} />
            {!privateImport && <Field label={t('Public username')} id="anilist-username" name="user" required
              placeholder={t('Public AniList username')} value={username} onChange={event => setUsername(event.target.value)} />}
            <Button type="submit" disabled={disabled}>{t(privateImport ? 'Connect with AniList & Import' : 'Import')}</Button>
          </Form>}
        {disabled && <p className="provider-small">{t('This import mode is not supported by AniList.')}</p>}
      </Card>
    </CardGrid>
  </>;
}
