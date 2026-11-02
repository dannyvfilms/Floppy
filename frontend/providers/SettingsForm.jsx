import React, { useState } from 'react';
import { Button, Field, Form, SelectField, ToggleRow } from '../ui/controls';
import { mountRoot } from '../settings/root';

function FormField({ field, form }) {
  const [value, setValue] = useState(field.value ?? '');
  const id = `${form.id}-${field.name}`;
  if (field.type === 'toggle') {
    return <ToggleRow id={id} name={field.name} label={field.label} help={field.help} tone={field.tone} defaultChecked={field.value} />;
  }
  if (field.type === 'select') {
    return <><SelectField id={id} name={field.name} label={field.label} value={value} options={field.options}
      onChange={event => setValue(event.target.value)} />{field.help && <p className="ui-field-help">{field.help}</p>}</>;
  }
  return <><Field id={id} name={field.name} label={field.label} type={field.type} placeholder={field.placeholder}
    autoComplete={field.autoComplete || 'off'} required={field.required} defaultValue={field.value ?? ''} {...field.attrs} />{field.help && <p className="ui-field-help">{field.help}</p>}</>;
}

export function SettingsForm({ form }) {
  return <Form action={form.action} csrf={form.csrf} returnTo={form.next}>
    {form.intro && <p>{form.intro}</p>}
    {Object.entries(form.hidden || {}).map(([name, value]) => <input key={name} type="hidden" name={name} value={value} />)}
    {form.fields.map(field => <FormField key={field.name} field={field} form={form} />)}
    <Button type="submit">{form.submit}</Button>
  </Form>;
}

export function mountSettingsForm(host, form) {
  return mountRoot(host, <SettingsForm form={form} />);
}
