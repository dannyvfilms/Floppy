import React, { useEffect, useState } from 'react';
import { FilePicker, Form, SelectField } from '../ui/controls';
import { mountRoot } from '../settings/root';

// Provider adapters supply field choices and transport; only the file is posted.
export function FileImport({ model, host }) {
  const [mediaType, setMediaType] = useState('');
  const [preferences, setPreferences] = useState(() => {
    const values = host.closest('[x-data]')?.importPreferences || model.values;
    return { ...values, mode: model.allowedModes.includes(values.mode) ? values.mode : model.defaultMode };
  });
  useEffect(() => {
    const parent = host.closest('[x-data]');
    const change = event => setPreferences(event.detail);
    parent?.addEventListener('import-preferences-changed', change);
    return () => parent?.removeEventListener('import-preferences-changed', change);
  }, [host]);
  return <div className="ui-account-action">
    <p>{model.intro} <a href={model.website} target="_blank" rel="noopener">{model.sourceLabel}</a>. {model.description}</p>
    <Form id="file-import-form" action={model.action} csrf={model.csrf} returnTo={model.next} encType="multipart/form-data">
      <input type="hidden" name="frequency" value={model.frequency} />
      {model.postFields.map(field => <input key={field.name} type="hidden" name={field.name} value={preferences[field.key]} />)}
      <SelectField id="file-import-media-type" name={model.mediaField} label={model.fieldLabel}
        value={mediaType} options={model.mediaTypes} onChange={event => setMediaType(event.target.value)} />
      <FilePicker name={model.fileField} accept={model.accept} required label={model.selectLabel}
        onChange={event => { if (event.target.files.length) event.target.form.requestSubmit(); }} />
    </Form>
  </div>;
}

export function mountFileImport(host, model) {
  if (host.querySelector('input[type="file"]')?.files.length) return () => {};
  return mountRoot(host, <FileImport host={host} model={model} />);
}
