import React, { useState } from 'react';
import { Button, Card, CardGrid, Chip, Dialog, Field, Form } from '../ui/controls';
import { mountRoot } from '../settings/root';

// One credentials presentation for every provider; the adapter supplies URLs and
// state labels, never stored values or masked previews.
export function Credentials({ credentials, draft = {} }) {
  const t = text => credentials.labels[text] ?? text;
  const [infoOpen, setInfoOpen] = useState(false);
  const [setupOpen, setSetupOpen] = useState(false);
  const form = { csrf: credentials.csrf, returnTo: credentials.next };
  const key = t('Get a key from {name}').replace('{name}', credentials.label);
  return <>
    <div className="ui-heading"><h3>{t('Provider credentials')}</h3>
      {credentials.setupHint
        ? <Chip tone="info" label={key} hasPopup onPress={() => setSetupOpen(true)} />
        : <Chip tone="info" label={key} href={credentials.getKeyUrl} hrefAttrs={{ target: '_blank', rel: 'noopener' }} />}
    </div>
    <CardGrid>
      <Card title={t('Instance credentials')} tone={credentials.publicAccess ? 'success' : credentials.editable ? 'info' : 'warning'}
        badge={t(credentials.publicAccess ? 'Public API' : credentials.editable ? 'Editable' : 'Read-only')}
        infoLabel={t('Read-only: explain instance credential access')}
        onInfo={credentials.editable ? undefined : () => setInfoOpen(true)}>
        <p>{t('These credentials are shared across the instance.')}</p>
        <Form action={credentials.saveUrl} {...form}>
          {credentials.fields.map(field => <Field key={field.name} id={`${credentials.slug}-${field.name}`} name={field.disabled ? undefined : field.name}
            label={<>{field.label}{!field.required && <> {t('(optional)')}</>}
              {field.environment && <small> ({t('Environment')}: {field.setting})</small>}
              {field.usingDefault && <small> ({t('Bundled default')})</small>}</>}
            type={field.disabled ? 'text' : field.secret ? 'password' : 'text'} disabled={field.disabled} readOnly={field.disabled}
            defaultValue={field.disabled ? t(field.environment ? 'Environment' : field.usingDefault ? 'Bundled default' : field.stored ? 'Stored' : 'Not set') : draft.instance?.[field.name] ?? ''}
            placeholder={field.disabled ? undefined : field.fallback ? t('Leave a field blank to keep the current fallback.') : field.placeholder} autoComplete="off" />)}
          {credentials.editable && <Button type="submit">{t('Save')}</Button>}
        </Form>
        {credentials.canClear && <Form action={credentials.clearUrl} {...form}><Button type="submit" danger>{t('Remove stored credentials')}</Button></Form>}
        {credentials.editable && <p className="provider-small">{t('Leave a field blank to keep the current fallback.')}</p>}
      </Card>
      {credentials.personalFields && <Card title={t('Personal credentials')}>
        <p>{t('Your key may avoid shared instance or bundled rate limits.')}</p>
        <Form action={credentials.personalUrl} {...form}>
          {credentials.personalFields.map(field => <Field key={field.name} id={`${credentials.slug}-personal-${field.name}`} name={field.name}
            label={`${t('Your')} ${field.label}`} type={field.secret ? 'password' : 'text'} autoComplete="off"
            defaultValue={draft.personal?.[field.name] ?? ''} placeholder={field.placeholder} />)}
          <Button type="submit">{t('Save personal key')}</Button>
        </Form>
      </Card>}
    </CardGrid>
    {credentials.defaults.length > 0 && <div className="ui-section">
      <p>{t('Make this the default provider for')}</p>
      {credentials.defaults.map(item => <Form key={item.mediaType} action={item.action} {...form}>
        <input type="hidden" name="source" value={credentials.slug} />
        <Button type="submit" secondary>{item.label}</Button>
      </Form>)}
    </div>}
    <Dialog closeLabel={t('Close')} open={infoOpen} title={t('Instance credential access')} onClose={() => setInfoOpen(false)}>
      {credentials.superuser ? <p>{t('Only superusers can change instance-wide credentials. Values set in the environment are read-only here and take precedence over stored credentials.')}</p> : <>
        <h4>{t('You are not a superuser')}</h4>
        <p>{t('Instance-wide keys can only be changed by a superuser. You can still add your own personal key.')}</p>
        <h4>{t(credentials.hasSuperuser ? 'Ask an administrator, or promote your own account' : 'This instance has no superuser yet')}</h4>
        <p>{t(credentials.inContainer ? 'Run this on the host running the container:' : 'Run this where Floppy is installed:')}</p>
        <pre>{credentials.promoteCommand}</pre><p>{t('Then sign out and back in. Add --list to see accounts first.')}</p>
      </>}
    </Dialog>
    {credentials.setupHint && <Dialog closeLabel={t('Close')} open={setupOpen} title={t('Get a key')} onClose={() => setSetupOpen(false)}>
      <p>{credentials.setupHint}</p>
      <a href={credentials.getKeyUrl} target="_blank" rel="noopener">{key}</a>
    </Dialog>}
  </>;
}

export function mountCredentials(host, credentials) {
  // Keep text typed into the server fallback while this module was loading.
  const draft = { instance: {}, personal: {} };
  for (const input of host.querySelectorAll('input[name]')) {
    if (input.type === 'hidden' || input.disabled || input.value === input.defaultValue) continue;
    draft[input.id.includes('-personal-') ? 'personal' : 'instance'][input.name] = input.value;
  }
  return mountRoot(host, <div className="ui-section-stack"><Credentials credentials={credentials} draft={draft} /></div>);
}
