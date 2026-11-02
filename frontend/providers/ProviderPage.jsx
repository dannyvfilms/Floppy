import React from 'react';
import { Card, CatalogGrid, Chip, Tabs } from '../ui/controls';
import { PageContext } from './web';
import { Connection } from './Connection';
import { Import } from './Import';
import { Activity } from './Activity';
import { Metadata } from './Metadata';

export function ProviderPage({ model, draft }) {
  const t = text => model.labels[text] ?? text;
  return <PageContext.Provider value={{ model, t }}>
    <div className={model.contentOwner === 'server' ? 'provider-page-content' : 'provider-page'}>
      <div className="provider-identity">
        <div className="provider-title-row">
          <div className="provider-name">{model.provider.logo && <img src={model.provider.logo} alt="" />}<h2>{model.provider.label}</h2></div>
          <div className="provider-media" aria-label={t('Media types')}>{model.provider.media.map(media => <Chip key={media} label={media} pill />)}</div>
        </div>
        <p>{model.provider.description}</p>
      </div>
      <Tabs items={model.tabs} selected={model.tab} label={t('Provider sections')} />
      {model.onboardingUrl && <a href={model.onboardingUrl}>{t('Continue Guided Setup')}</a>}
      {model.tab === 'overview' && <Overview model={model} />}
      {model.contentOwner === 'react' && model.tab === 'connection' && <Connection draft={draft} />}
      {model.contentOwner === 'react' && model.tab === 'import' && <Import draft={draft} />}
      {model.contentOwner === 'react' && model.tab === 'activity' && <Activity />}
      {model.contentOwner === 'react' && model.tab === 'metadata' && <Metadata />}
    </div>
  </PageContext.Provider>;
}

function Overview({ model }) {
  return <CatalogGrid className="provider-overview">
    {model.overviewCards.map(card => <Card key={card.key} title={card.title} href={card.url}
      tone={card.tone} badge={card.badge} tooltip={card.tooltip || undefined}>
      <p>{card.subtitle}</p>
      {card.detail && <p>{card.detail}</p>}
    </Card>)}
  </CatalogGrid>;
}
