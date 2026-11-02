import React, { useState } from 'react';
import { Button, Card, CardGrid, Field, ToggleChip } from '../ui/controls';
import { ImportPreferences, useImportPreferences } from './ImportPreferences';
import { Form, usePage } from './web';

export function Import({ draft }) {
  const { model, t } = usePage();
  const initial = model.imports;
  const { values, save, saveState } = useImportPreferences(initial, draft?.preferences);
  const [privateImport, setPrivateImport] = useState(draft?.privateImport ?? false);
  const [username, setUsername] = useState(draft?.username ?? '');
  const disabled = !['new', 'overwrite'].includes(values.mode);
  return <>
    <h3>{t('Import settings')}</h3>
    <CardGrid alignStart>
      <ImportPreferences initial={initial} values={values} save={save} saveState={saveState} />
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
