import React from 'react';
import { Card, CardGrid, Chip, Tabs } from '../ui/controls';
import { PageContext } from './web';
import { Connection } from './Connection';
import { Import } from './Import';
import { Activity } from './Activity';

export function ProviderPage({ model, draft }) {
  const t = text => model.labels[text] ?? text;
  return <PageContext.Provider value={{ model, t }}>
    <div className="provider-page">
      <div className="ui-heading provider-identity">
        <div><div className="provider-name"><img src={model.provider.logo} alt="" /><h2>{model.provider.label}</h2></div>
          <p>{model.provider.description}</p></div>
        <div className="provider-media" aria-label={t('Media types')}>{model.provider.media.map(media => <Chip key={media} label={media} pill />)}</div>
      </div>
      <Tabs items={model.tabs} selected={model.tab} label={t('Provider sections')} />
      {model.onboardingUrl && <a href={model.onboardingUrl}>{t('Continue Guided Setup')}</a>}
      {model.tab === 'overview' && <Overview model={model} t={t} />}
      {model.tab === 'connection' && <Connection draft={draft} />}
      {model.tab === 'import' && <Import draft={draft} />}
      {model.tab === 'activity' && <Activity />}
    </div>
  </PageContext.Provider>;
}

function Overview({ model, t }) {
  const overview = model.overview;
  const active = overview.connection !== 'none';
  return <CardGrid auto className="provider-overview">
    <Card title={t('Connection')} href={model.urls.connection} tone={active ? 'info' : 'neutral'} badge={t(active ? 'Active' : 'Inactive')}
      tooltip={!active ? t('Public username imports do not require provider credentials.') :
        overview.instanceFallback ? t('Uses instance fallback for fields without a personal value.') : undefined}>
      <p>{t(overview.connection === 'personal' ? 'Personal credentials active' :
        overview.connection === 'instance' ? 'Instance credentials active' : 'No credentials active')}</p>
    </Card>
    <Card title={t('Automatic import')} href={model.urls.import} tone={overview.scheduleCount ? 'info' : 'neutral'}
      badge={t(overview.scheduleCount ? 'Active' : 'Inactive')}>
      {overview.scheduleCount ? <><p>{overview.scheduleSummary}</p>
        {overview.nextImport && <p>{t('Next import')}: {overview.nextImport}</p>}</> : <p>{t('No automatic imports configured')}</p>}
    </Card>
    <Card title={t('Last active import')} href={model.urls.activity}>
      {overview.latestImport ? <><p>{overview.latestImport.status}</p><p>{overview.latestImport.date}</p></> : <p>{t('No imports yet')}</p>}
    </Card>
  </CardGrid>;
}
