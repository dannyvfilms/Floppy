import React, { useEffect, useState } from 'react';
import { Chip, FilePicker, Form, SelectField } from '../ui/controls';
import { mountRoot } from '../settings/root';

// Provider adapters supply field choices and transport; only the file is posted.
export function FileImport({ model, host }) {
  const [mediaType, setMediaType] = useState('');
  const [preferences, setPreferences] = useState(() => {
    const values = host.closest('[x-data]')?.importPreferences || model.values;
    return model.allowedModes ? { ...values, mode: model.allowedModes.includes(values.mode) ? values.mode : model.defaultMode } : values;
  });
  useEffect(() => {
    const parent = host.closest('[x-data]');
    const change = event => setPreferences(event.detail);
    parent?.addEventListener('import-preferences-changed', change);
    return () => parent?.removeEventListener('import-preferences-changed', change);
  }, [host]);
  const blocked = !model.allowedModes && ['update_collection', 'watchlist'].includes(preferences.mode);
  return <div className="ui-account-action">
    {model.oneTime && preferences.frequency !== 'once' && <div title={model.oneTime.title}><Chip label={model.oneTime.label} pill /></div>}
    {model.sourceLabel ? <p>{model.intro} <a href={model.website} target="_blank" rel="noopener">{model.sourceLabel}</a>. {model.description}</p>
      : <p>{model.description}{model.docs && <> <a href={model.docs.url} target="_blank" rel="noopener">{model.docs.label}</a></>}</p>}
    <Form id="file-import-form" action={model.action} csrf={model.csrf} returnTo={model.next} encType="multipart/form-data">
      {model.frequency && <input type="hidden" name="frequency" value={model.frequency} />}
      {model.postFields.map(field => <input key={field.name} type="hidden" name={field.name} value={preferences[field.key]} />)}
      {model.mediaTypes?.length > 0 && <SelectField id="file-import-media-type" name={model.mediaField} label={model.fieldLabel}
        value={mediaType} options={model.mediaTypes} onChange={event => setMediaType(event.target.value)} />}
      <FilePicker name={model.fileField} accept={model.accept} multiple={model.multiple} required label={model.selectLabel} disabled={blocked}
        onChange={event => { if (event.target.files.length) event.target.form.requestSubmit(); }} />
      {blocked && <p className="provider-small">{model.blockedLabel}</p>}
    </Form>
  </div>;
}

export function mountFileImport(host, model) {
  if (host.querySelector('input[type="file"]')?.files.length) return () => {};
  return mountRoot(host, <FileImport host={host} model={model} />);
}
