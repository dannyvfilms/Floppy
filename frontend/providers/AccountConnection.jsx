import React from 'react';
import { Button, Card, CardGrid, Field, Form } from '../ui/controls';
import { mountRoot } from '../settings/root';

// Presentation and actions are supplied by the provider adapter, never stored secrets.
export function AccountConnection({ model, draft = {} }) {
  const t = text => model.labels[text] || text;
  const status = model.connected ? 'Connected' : model.attention ? 'Needs attention' : 'Not connected';
  return <div className="ui-section-stack">
    <h3>{t('Connection settings')}</h3>
    <CardGrid alignStart><Card title={t('Account connection')} tone={model.connected ? 'success' : model.attention ? 'warning' : 'neutral'} badge={t(status)}>
      <p>{model.messages[model.connected ? 'connected' : model.attention ? 'attention' : 'disconnected']}</p>
      {!model.connected && <Form action={model.connectUrl} csrf={model.csrf} returnTo={model.next}>
          {model.fields.map(field => <Field key={field.name} id={`account-${field.name}`} name={field.name}
            label={field.label} type={field.type} placeholder={field.placeholder} required autoComplete="off" defaultValue={draft[field.name] || ''} />)}
          <Button type="submit">{t(model.saved ? 'Reconnect' : 'Connect')}</Button>
        </Form>}
      {model.saved && <Form action={model.disconnectUrl} csrf={model.csrf} returnTo={model.next}>
        <Button type="submit" danger>{t('Disconnect')}</Button>
      </Form>}
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
