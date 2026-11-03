import React, { useState } from 'react';
import { Button, Card, CardGrid, Chip, FeatureList, Field, MediaIcon, SelectField } from '../ui/controls';
import { Form, usePage } from './web';

export function Metadata() {
  const { model, t } = usePage();
  const metadata = model.metadata;
  return <>
    <h3>{t('Metadata settings')}</h3>
    <CardGrid alignStart>
      <Card title={t('Metadata sources')} tone={metadata.status.active ? 'info' : 'neutral'} badge={t(metadata.status.active ? 'Active' : 'Inactive')}>
        <p>{metadata.status.summary}</p>
        {metadata.imported && <p>{t('This provider supplies metadata for its imported items; library defaults apply to new searches.')}</p>}
        <FeatureList items={metadata.contributions} />
      </Card>
      <Card title={t('Provider settings')}>
        {metadata.proxy ? <>
          <div className="ui-heading"><h4>{t('TMDB Proxy')}</h4><Chip label={t(metadata.proxy.configured ? 'Configured' : 'Not configured')} /></div>
          <p>{t('Route TMDB requests through an HTTP or SOCKS5 proxy. Leave blank and save to remove it.')}</p>
          <Form action={metadata.proxy.action}>
            <Field id="tmdb-proxy-url" name="tmdb_proxy_url" label={t('Proxy URL')} placeholder="socks5://user:pass@host:port" autoComplete="off" />
            <Button type="submit">{t('Save')}</Button>
          </Form>
        </> : <p>{t('This provider has no additional settings.')}</p>}
      </Card>
    </CardGrid>
    {metadata.sources.length > 0 && <section className="ui-library-section">
      <h3>{t('Library sources')}</h3>
      <p>{t('Choose where new titles come from. Existing titles keep their original provider.')}</p>
      <div className="ui-library-sources">
        {metadata.sources.map(source => <SourceSettings key={source.key} source={source} />)}
      </div>
    </section>}
  </>;
}

function SourceSettings({ source }) {
  const { t } = usePage();
  const [value, setValue] = useState(source.current);
  const [animeMode, setAnimeMode] = useState(source.animeMode);
  const configured = source.choices.find(choice => choice.value === value)?.configured;
  const [open, setOpen] = useState(false);
  const detailsId = `metadata-source-details-${source.key}`;
  return <section className="ui-library-row">
    <div className="ui-library-row-header">
      <div className="ui-library-row-name"><MediaIcon type={source.key} /><h4>{source.title}</h4></div>
      <div className="ui-library-row-actions"><Chip label={source.currentLabel} tone="warning" pill />
        <div className="ui-library-configure"><Button type="button" secondary aria-expanded={open} aria-controls={detailsId}
          aria-label={`${t(open ? 'Close' : 'Configure')} ${source.title}`} onClick={() => setOpen(!open)}>{t(open ? 'Close' : 'Configure')}</Button></div>
      </div>
    </div>
    <div id={detailsId} hidden={!open} className="ui-section ui-library-details">
      {source.action ? <>
        <p>{t('Used for new titles. Existing entries keep their provider until you move them.')}</p>
        <Form action={source.action}>
          <SelectField id={`metadata-source-${source.key}`} name="source" label={t('Provider for new titles')}
            value={value} disabled={!source.editable} onChange={event => setValue(event.target.value)}
            options={source.choices.map(choice => ({ value: choice.value, label: choice.label, disabled: !choice.configured }))} />
          {source.animeMode !== null && <SelectField id="metadata-anime-mode" name="anime_library_mode" label={t('Anime Library')}
            value={animeMode} disabled={!source.editable} onChange={event => setAnimeMode(event.target.value)} options={source.animeModes} />}
          {source.editable && <Button type="submit" disabled={!configured}>{t('Save')}</Button>}
        </Form>
      </> : <><p>{t('Default for new titles')}: {source.currentLabel}</p><p>{t('The default cannot be changed. Imported titles keep their original source.')}</p></>}
      <div className="ui-option-list">{source.choices.map(choice => <div key={choice.value} className="ui-option-row">
        <span>{choice.label}</span>
        {!choice.configured && choice.connectionUrl ? <Chip label={t('Not configured')} href={choice.connectionUrl} /> :
          <Chip label={t(!choice.configured ? 'Not configured' : choice.value === source.current ? 'Default' : choice.imported ? 'Imported items' : source.action ? 'Ready' : 'Available')}
            tone={choice.configured && choice.value === source.current ? 'info' : 'neutral'} />}
      </div>)}</div>
    </div>
    {source.existingCount > 0 && <div className="ui-section ui-library-details">
      <p>{t('Existing entries on another provider or format')}: {source.existingCount}</p>
      <p>{t(source.key === 'tv' ? 'Moving preserves history when supported; entries that cannot be moved safely are left unchanged.' :
        'Converting rebuilds entries. Moving to MyAnimeList drops per-episode history; unsafe conversions are left unchanged.')}</p>
      {source.moveAction && <Form action={source.moveAction}><Button secondary type="submit">{t(source.key === 'tv' ? 'Move existing shows' : 'Convert existing anime')}</Button></Form>}
    </div>}
  </section>;
}
