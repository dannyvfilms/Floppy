import React, { useEffect, useState } from 'react';
import { Button, Chip, Field, FilePicker, Form, SelectField } from '../ui/controls';
import { mountRoot } from '../settings/root';

// Provider adapters supply field choices and transport; only the file is posted.
export function FileImport({ model, host }) {
  const [mediaType, setMediaType] = useState('');
  const [chosen, setChosen] = useState({});
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
  const files = model.files || [{ field: model.fileField, accept: model.accept, selectLabel: model.selectLabel, multiple: model.multiple }];
  const auto = model.autoSubmit !== false;
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
      {model.textFields?.map(field => <Field key={field.name} id={`file-import-${field.name}`} name={field.name} label={field.label}
        type={field.type} placeholder={field.placeholder} required={field.required} disabled={blocked} autoComplete="off" />)}
      {model.note && <p className="provider-small">{model.note}</p>}
      {files.map(file => <div key={file.field} className="ui-file-import-file">
        {file.label && <span className="provider-small">{file.label}</span>}
        <FilePicker name={file.field} accept={file.accept} multiple={file.multiple} required={auto} label={file.selectLabel} disabled={blocked}
          onChange={event => {
            setChosen({ ...chosen, [file.field]: [...event.target.files].map(item => item.name).join(', ') });
            if (auto && event.target.files.length) event.target.form.requestSubmit();
          }} />
        {chosen[file.field] && <span className="provider-small">{chosen[file.field]}</span>}
      </div>)}
      {!auto && <Button type="submit" disabled={blocked}>{model.submitLabel}</Button>}
      {blocked && <p className="provider-small">{model.blockedLabel}</p>}
    </Form>
  </div>;
}

export function mountFileImport(host, model) {
  if (host.querySelector('input[type="file"]')?.files.length) return () => {};
  return mountRoot(host, <FileImport host={host} model={model} />);
}
