import React, { useEffect, useState } from 'react';
import { mountRoot } from './root';
import {
  AboutOverviewCard,
  AboutVersionFooter,
  AttributionsCard,
  InstallCard,
  LicenseCard,
  ProjectResourcesCard,
  WhatsNewCard,
} from './AboutSettings';
import { systemPalette } from './mountAdvanced';

function openUrl(url) {
  if (url) window.open(url, '_blank', 'noopener,noreferrer');
}

function detectPlatform() {
  const ua = navigator.userAgent || '';
  if (/Android/i.test(ua)) return 'android';
  const iosDevice = /iPad|iPhone|iPod/.test(ua);
  // iPadOS 13+ reports a Mac user agent; touch points betray it.
  const iPadDesktopUA = /Macintosh/.test(ua) && navigator.maxTouchPoints > 1;
  return iosDevice || iPadDesktopUA ? 'ios' : 'desktop';
}

function installAvailable() {
  const pwa = window.floppyPwa;
  return Boolean(pwa?.deferredPrompt) && !pwa.isStandalone();
}

function OverviewAdapter({ props }) {
  return <AboutOverviewCard description={props.labels.description}
    sponsorUrl={props.sponsorUrl} onOpenUrl={openUrl}
    palette={systemPalette} labels={props.labels} />;
}

function WhatsNewAdapter({ props }) {
  const [releases, setReleases] = useState(props.releases || []);
  const [loading, setLoading] = useState(!props.releasesLoaded);
  useEffect(() => {
    if (props.releasesLoaded) return undefined;
    let active = true;
    fetch(props.url, { headers: { Accept: 'application/json' } })
      .then(response => response.ok ? response.json() : Promise.reject(response))
      .then(data => {
        if (!active) return;
        setReleases(data.releases || []);
        setLoading(false);
      })
      .catch(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [props.releasesLoaded, props.url]);
  return <WhatsNewCard releases={releases} loading={loading}
    releasesUrl={props.releasesUrl} onOpenUrl={openUrl}
    palette={systemPalette} labels={props.labels} />;
}

function InstallAdapter({ props }) {
  const labels = props.labels || {};
  const [platform] = useState(detectPlatform);
  const [available, setAvailable] = useState(installAvailable);
  const [status, setStatus] = useState('');

  useEffect(() => {
    const sync = () => setAvailable(installAvailable());
    window.addEventListener('floppy:install-availability', sync);
    return () => window.removeEventListener('floppy:install-availability', sync);
  }, []);

  async function install() {
    const pwa = window.floppyPwa;
    const prompt = pwa?.deferredPrompt;
    if (!prompt) {
      setAvailable(false);
      return;
    }
    // Consume the event either way: it is single-use.
    pwa.deferredPrompt = null;
    setAvailable(false);
    try {
      await prompt.prompt();
      const choice = await prompt.userChoice;
      setStatus(
        choice.outcome === 'accepted'
          ? labels.installedStatus
          : labels.dismissedStatus,
      );
    } catch (error) {
      setStatus(labels.failedStatus);
    }
  }

  return <InstallCard platform={platform} installAvailable={available}
    installStatus={status} guideUrl={props.guideUrl} onInstall={install}
    onOpenUrl={openUrl} palette={systemPalette} labels={labels} />;
}

function ResourcesAdapter({ props }) {
  return <ProjectResourcesCard resources={props.items}
    onOpenUrl={openUrl} palette={systemPalette} labels={props.labels} />;
}

function AttributionsAdapter({ props }) {
  return <AttributionsCard attributions={props.items}
    onOpenUrl={openUrl} palette={systemPalette} labels={props.labels} />;
}

function LicensesAdapter({ props }) {
  return <LicenseCard licenses={props.items}
    onOpenUrl={openUrl} palette={systemPalette} labels={props.labels} />;
}

function VersionAdapter({ props }) {
  return <AboutVersionFooter version={props.version} commit={props.commit}
    palette={systemPalette} labels={props.labels} />;
}

const adapters = {
  overview: OverviewAdapter,
  whatsNew: WhatsNewAdapter,
  install: InstallAdapter,
  resources: ResourcesAdapter,
  attributions: AttributionsAdapter,
  licenses: LicensesAdapter,
  version: VersionAdapter,
};

export function mountAboutCard(host, props) {
  const Adapter = adapters[props.kind];
  if (!Adapter) throw new Error(`Unknown About card: ${props.kind}`);
  return mountRoot(host, <Adapter props={props} />);
}
