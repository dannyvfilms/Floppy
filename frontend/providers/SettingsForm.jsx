import React, { useEffect, useState } from 'react';
import { Button, Field, Form, SelectField, ToggleRow } from '../ui/controls';
import { mountRoot } from '../settings/root';

const BLOCKED_MODES = ['update_collection', 'watchlist'];

function FormField({ field, form, values, setValue }) {
  const id = `${form.id}-${field.name}`;
  if (field.showWhen && values[field.showWhen.name] === field.showWhen.not) return null;
  if (field.type === 'toggle') {
    return <ToggleRow id={id} name={field.name} label={field.label} help={field.help} tone={field.tone} defaultChecked={field.value} />;
  }
  if (field.type === 'select') {
    return <><SelectField id={id} name={field.name} label={field.label} value={values[field.name]} options={field.options}
      onChange={event => setValue(field.name, event.target.value)} />{field.help && <p className="ui-field-help">{field.help}</p>}</>;
  }
  return <><Field id={id} name={field.name} label={field.label} type={field.type} placeholder={field.placeholder}
    autoComplete={field.autoComplete || 'off'} required={field.required} defaultValue={field.value ?? ''} {...field.attrs} />
    {field.help && <p className="ui-field-help">{field.help}</p>}</>;
}

export function SettingsForm({ form, host }) {
  const [values, setValues] = useState(() => Object.fromEntries(form.fields.filter(field => field.type === 'select').map(field => [field.name, field.value ?? ''])));
  const [mode, setMode] = useState(form.hidden?.mode);
  const setValue = (name, value) => setValues(current => ({ ...current, [name]: value }));
  // Forms that follow the page's import preferences post the live mode and stop when it cannot apply.
  useEffect(() => {
    if (!form.followPreferences || !host) return undefined;
    const parent = host.closest('[x-data]');
    const change = event => setMode(event.detail.mode);
    parent?.addEventListener('import-preferences-changed', change);
    return () => parent?.removeEventListener('import-preferences-changed', change);
  }, [form.followPreferences, host]);
  const blocked = form.followPreferences && BLOCKED_MODES.includes(mode);
  return <Form action={form.action} csrf={form.csrf} returnTo={form.next}>
    {form.intro && <p>{form.intro}</p>}
    {Object.entries(form.hidden || {}).map(([name, value]) => <input key={name} type="hidden" name={name} value={name === 'mode' ? mode : value} />)}
    {form.fields.map(field => <FormField key={field.name} field={field} form={form} values={values} setValue={setValue} />)}
    <Button type="submit" disabled={blocked}>{form.submit}</Button>
    {blocked && <p className="provider-small">{form.blockedLabel}</p>}
  </Form>;
}

export function mountSettingsForm(host, form) {
  return mountRoot(host, <SettingsForm form={form} host={host} />);
}
