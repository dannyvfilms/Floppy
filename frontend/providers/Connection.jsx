import React, { useState } from 'react';
import { Button, Card, CardGrid, Dialog, Field, Chip } from '../ui/controls';
import { Form, usePage } from './web';

export function Connection({ draft }) {
  const { model, t } = usePage();
  const credentials = model.credentials;
  const [infoOpen, setInfoOpen] = useState(false);
  return <>
    <div className="ui-heading"><h3>{t('Provider credentials')}</h3>
      <Chip tone="info" label={t('Get a key from AniList')} href={credentials.getKeyUrl}
        hrefAttrs={{ target: '_blank', rel: 'noopener' }} />
    </div>
    <CardGrid>
      <Card title={t('Instance credentials')} tone={credentials.publicAccess ? 'success' : credentials.editable ? 'info' : 'warning'}
        badge={t(credentials.publicAccess ? 'Public API' : credentials.editable ? 'Editable' : 'Read-only')}
        infoLabel={t('Read-only: explain instance credential access')}
        onInfo={credentials.editable ? undefined : () => setInfoOpen(true)}>
        <p>{t('These credentials are shared across the instance.')}</p>
        <Form action={credentials.saveUrl}>
          {credentials.fields.map(field => <Field key={field.name} id={`anilist-${field.name}`} name={field.disabled ? undefined : field.name}
            label={<>{field.label}{field.environment && <small> ({t('Environment')}: {field.setting})</small>}</>}
            type={field.disabled ? 'text' : field.secret ? 'password' : 'text'} disabled={field.disabled} readOnly={field.disabled}
            defaultValue={field.disabled ? t(field.environment ? 'Environment' : field.stored ? 'Stored' : 'Not set') : draft?.instance?.[field.name] ?? ''}
            placeholder={field.stored ? t('Leave a field blank to keep the current fallback.') : ''} autoComplete="off" />)}
          {credentials.editable && <Button type="submit">{t('Save')}</Button>}
        </Form>
        {credentials.canClear && <Form action={credentials.clearUrl}><Button type="submit" danger>{t('Remove stored credentials')}</Button></Form>}
        {credentials.editable && <p className="provider-small">{t('Leave a field blank to keep the current fallback.')}</p>}
      </Card>
      <Card title={t('Personal credentials')}>
        <p>{t('Your key may avoid shared instance or bundled rate limits.')}</p>
        <Form action={credentials.personalUrl}>
          {credentials.fields.map(field => <Field key={field.name} id={`anilist-personal-${field.name}`} name={field.name}
            label={`${t('Your')} ${field.label}`} type={field.secret ? 'password' : 'text'} autoComplete="off"
            defaultValue={draft?.personal?.[field.name] ?? ''}
            placeholder={field.personalStored ? t('Saved — enter a new value to replace') : ''} />)}
          <Button type="submit">{t('Save personal key')}</Button>
        </Form>
      </Card>
    </CardGrid>
    <Dialog closeLabel={t('Close')} open={infoOpen} title={t('Instance credential access')} onClose={() => setInfoOpen(false)}>
      {credentials.superuser ? <p>{t('Only superusers can change instance-wide credentials. Values set in the environment are read-only here and take precedence over stored credentials.')}</p> : <>
        <h4>{t('You are not a superuser')}</h4>
        <p>{t('Instance-wide keys can only be changed by a superuser. You can still add your own personal key.')}</p>
        <h4>{t(credentials.hasSuperuser ? 'Ask an administrator, or promote your own account' : 'This instance has no superuser yet')}</h4>
        <p>{t(credentials.inContainer ? 'Run this on the host running the container:' : 'Run this where Floppy is installed:')}</p>
        <pre>{credentials.promoteCommand}</pre><p>{t('Then sign out and back in. Add --list to see accounts first.')}</p>
      </>}
    </Dialog>
  </>;
}
