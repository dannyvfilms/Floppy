import React, { useState } from 'react';
import { Button, Card, CardGrid, Chip, Field, Form, SelectField } from '../ui/controls';
import { mountRoot } from '../settings/root';

// Presentation and actions are supplied by the provider adapter, never stored secrets.
function AccountField({ field, draft }) {
  const [value, setValue] = useState(draft[field.name] || field.value || field.options?.[0]?.value || '');
  if (field.type === 'select') {
    return <SelectField id={`account-${field.name}`} name={field.name} label={field.label} value={value}
      options={field.options} onChange={event => setValue(event.target.value)} />;
  }
  return <Field id={`account-${field.name}`} name={field.name} label={field.label} type={field.type} placeholder={field.placeholder}
    required={field.required !== false} autoComplete="off" defaultValue={draft[field.name] || ''} />;
}

export function AccountConnection({ model, draft = {} }) {
  const t = text => model.labels[text] || text;
  const status = model.connected ? 'Connected' : model.attention ? 'Needs attention' : 'Not connected';
  const form = { csrf: model.csrf, returnTo: model.next };
  const fields = model.fields.map(field => <AccountField key={field.name} field={field} draft={draft} />);
  return <div className="ui-section-stack">
    <h3>{t('Connection settings')}</h3>
    <CardGrid alignStart><Card title={model.title || t('Account connection')} tone={model.connected ? 'success' : model.attention ? 'warning' : 'neutral'} badge={t(status)}>
      {model.description && <p>{model.description}</p>}
      {model.summary && <div className="ui-account-summary">
        {model.summary.url && <p className="provider-small">{model.summary.url}{model.summary.lastSync && ` • ${model.summary.lastSync}`}</p>}
        {model.summary.error && <p className="provider-small" role="alert">{model.summary.error}</p>}
      </div>}
      {model.instances ? <>
        {model.instances.map(instance => <div className="ui-instance-row" key={instance.id}>
          <div className="ui-heading"><strong>{instance.name}</strong>
            <Chip tone={instance.connected ? 'success' : 'neutral'} label={t(instance.connected ? 'Connected' : 'Disconnected')} /></div>
          <p className="provider-small">{instance.url}</p>
          {instance.error && <p className="provider-small">{instance.error}</p>}
          <Form action={model.disconnectUrl} {...form}>
            <input type="hidden" name="instance_id" value={instance.id} />
            <Button type="submit" danger>{t('Disconnect')}</Button>
          </Form>
        </div>)}
        <p>{model.messages[model.instances.length ? 'connected' : 'disconnected']}</p>
        <Form action={model.connectUrl} {...form}>{fields}<Button type="submit">{model.submitLabel}</Button></Form>
      </> : <>
        <p>{model.messages[model.connected ? 'connected' : model.attention ? 'attention' : 'disconnected']}</p>
        {!model.connected && model.connectUrl && <Form action={model.connectUrl} {...form}>{fields}
          <Button type="submit">{model.submitLabel || t(model.saved ? 'Reconnect' : 'Connect')}</Button></Form>}
        {model.saved && <Form action={model.disconnectUrl} {...form}><Button type="submit" danger>{t('Disconnect')}</Button></Form>}
      </>}
    </Card>
      {model.followUp && <Card title={model.followUp.title}>
        <p>{model.followUp.description}</p>
        <Button href={model.followUp.url}>{model.followUp.label}</Button>
      </Card>}
    </CardGrid>
  </div>;
}

export function mountAccountConnection(host, model) {
  const draft = Object.fromEntries(model.fields.map(field => [field.name, host.querySelector(`[name="${field.name}"]`)?.value || '']));
  return mountRoot(host, <AccountConnection model={model} draft={draft} />);
}

// Use the same action presentation for account-backed manual imports.
export function AccountImportAction({ model }) {
  return <div className="ui-account-action"><p>{model.description}</p>
    {model.href ? <Button href={model.href}>{model.label}</Button> :
      <Form action={model.action} csrf={model.csrf} returnTo={model.next}>
        <Button type="submit">{model.label}</Button>
      </Form>}
  </div>;
}
export function mountAccountImportAction(host, model) {
  return mountRoot(host, <AccountImportAction model={model} />);
}
