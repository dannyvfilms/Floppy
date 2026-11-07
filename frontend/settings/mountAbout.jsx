import React, { useEffect, useState } from 'react';
import { mountRoot } from './root';
import {
  AboutOverviewCard,
  AboutVersionFooter,
  AttributionsCard,
  DeveloperSpecsCard,
  LicenseCard,
  ProjectResourcesCard,
  InstallCard,
  ReleaseUpdateBanner,
  WhatsNewCard,
} from './AboutSettings';
import { systemPalette } from './mountAdvanced';
import { getInstallState, openInstallGuide, requestInstall, subscribeInstallState } from '../ui/installPrompt';

const systemButtonPalette = {
  primary: {
    background: 'var(--color-accent)',
    pressed: 'var(--color-accent-strong)',
    hovered: 'var(--color-accent-strong)',
    text: '#ffffff',
    border: 'transparent',
  },
  surface: {
    background: 'var(--color-surface-strong)',
    pressed: 'var(--color-surface-muted)',
    hovered: 'var(--color-surface-muted)',
    text: 'var(--color-text)',
    border: 'var(--color-surface-border)',
  },
  radius: 6,
  focusStyle: {},
};

function openUrl(url) {
  if (url) window.open(url, '_blank', 'noopener,noreferrer');
}

const SEEN_RELEASE_KEY = 'floppy_seen_release';

function rememberRelease(tag) {
  try {
    localStorage.setItem(SEEN_RELEASE_KEY, tag || '');
  } catch (error) {
    // Storage can be unavailable in private windows; the banner still hides.
  }
}

function initialBannerVisible(tag) {
  try {
    const seen = localStorage.getItem(SEEN_RELEASE_KEY);
    if (seen === null) {
      localStorage.setItem(SEEN_RELEASE_KEY, tag || '');
      return false;
    }
    return seen !== tag;
  } catch (error) {
    return false;
  }
}

function BannerAdapter({ props }) {
  const [visible, setVisible] = useState(() => initialBannerVisible(props.releaseTag));
  function dismiss() {
    rememberRelease(props.releaseTag);
    setVisible(false);
  }
  function viewWhatsNew() {
    dismiss();
    if (props.whatsNewUrl) window.location.assign(props.whatsNewUrl);
  }
  if (!visible) return null;
  return <ReleaseUpdateBanner releaseTag={props.releaseTag}
    onDismiss={dismiss} onViewWhatsNew={viewWhatsNew}
    palette={systemPalette} labels={props.labels} />;
}

function OverviewAdapter({ props }) {
  return <AboutOverviewCard description={props.description || props.labels.description}
    sponsorUrl={props.sponsorUrl} onOpenUrl={openUrl}
    palette={systemPalette} labels={props.labels} icons={props.icons} />;
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
    palette={systemPalette} labels={props.labels} icons={props.icons} />;
}

function InstallAdapter({ props }) {
  const labels = props.labels || {};
  const [state, setState] = useState(getInstallState);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  const [attempted, setAttempted] = useState(false);

  useEffect(() => subscribeInstallState(setState), []);

  async function install() {
    setBusy(true);
    setStatus('');
    setAttempted(true);
    try {
      const result = await requestInstall();
      setStatus(labels[{
        accepted: 'installedStatus',
        dismissed: 'dismissedStatus',
        failed: 'failedStatus',
        unavailable: 'unavailableStatus',
      }[result?.outcome]] || '');
    } catch (error) {
      setStatus(labels.failedStatus || '');
    } finally {
      setBusy(false);
    }
  }

  return <InstallCard installAvailable={state.canInstall && !attempted} installBusy={busy}
    installStatus={status} platform={state.platform}
    guideUrl={props.guideUrl} onInstall={install}
    onOpenUrl={openInstallGuide} labels={labels}
    palette={systemPalette} buttonPalette={systemButtonPalette}
    icons={props.icons} />;
}

function SpecsAdapter({ props }) {
  function preview(spec) {
    window.dispatchEvent(new CustomEvent('about:schema-preview', {
      bubbles: true,
      detail: {
        url: spec.url,
        title: spec.previewTitle || spec.label,
        badge: spec.badge || spec.format || '',
        downloadName: spec.downloadName || '',
      },
    }));
  }
  function download(spec) {
    if (!spec.downloadName) {
      openUrl(spec.url);
      return;
    }
    const separator = spec.url.includes('?') ? '&' : '?';
    window.location.assign(`${spec.url}${separator}download=1`);
  }
  return <DeveloperSpecsCard specs={props.items}
    onOpenUrl={openUrl} onPreview={preview} onDownload={download}
    palette={systemPalette} labels={props.labels} icons={props.icons} />;
}

function ResourcesAdapter({ props }) {
  return <ProjectResourcesCard resources={props.items}
    onOpenUrl={openUrl} palette={systemPalette} labels={props.labels} icons={props.icons} />;
}

function AttributionsAdapter({ props }) {
  return <AttributionsCard attributions={props.items}
    onOpenUrl={openUrl} palette={systemPalette} labels={props.labels} icons={props.icons} />;
}

function LicensesAdapter({ props }) {
  return <LicenseCard licenses={props.items}
    onOpenUrl={openUrl} palette={systemPalette} labels={props.labels} icons={props.icons} />;
}

function VersionAdapter({ props }) {
  return <AboutVersionFooter version={props.version} commit={props.commit}
    palette={systemPalette} labels={props.labels} />;
}

const adapters = {
  banner: BannerAdapter,
  overview: OverviewAdapter,
  whatsNew: WhatsNewAdapter,
  install: InstallAdapter,
  resources: ResourcesAdapter,
  specs: SpecsAdapter,
  attributions: AttributionsAdapter,
  licenses: LicensesAdapter,
  version: VersionAdapter,
};

export function mountAboutCard(host, props) {
  const Adapter = adapters[props.kind];
  if (!Adapter) throw new Error(`Unknown About card: ${props.kind}`);
  return mountRoot(host, <Adapter props={props} />);
}
