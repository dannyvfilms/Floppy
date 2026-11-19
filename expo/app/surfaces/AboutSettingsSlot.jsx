import React, { useEffect, useRef, useState } from 'react';
import { Linking, Platform, View } from 'react-native';
import { SettingsCard } from '../../../frontend/settings/SettingsCard';
import { Button } from '../../../frontend/ui/Button';
import { AboutSpecificationPreview } from '../../../frontend/settings/AboutSettings';
import { SettingsAboutView } from '../../../frontend/pages/SettingsAboutView';
import { readLocalSetting, writeLocalSetting } from '../data/localSettings';
import { aboutFromPayload } from '../data/settingsTransport';
import SettingsLoadState from './SettingsLoadState';
import { useSettingsPalettes } from './settingsPalettes';
import { useSettingsResource } from './useSettingsResource';
import { copyText, saveTextFile } from '../data/fileFlows';

export const surface = {
  id: 'SET-ABOUT',
  title: 'About',
  where: 'Settings about, release notes, resources, API specifications and licences',
  status: 'in_progress',
  note: 'Version, commit, resources, API specifications, attributions and licences load from /api/v1/user/about/ (the props the web About page renders); release notes come from the same payload, or from /api/v1/user/about/whats-new/ when the server cache is cold. The update notice follows the web rule (a changed release tag since the last one dismissed on this device) and keeps its state in data/localSettings. Spec links use the signed-in server address. The browser install prompt does not exist on native, so the install card shows its guide link only.',
};

const SEEN_KEY = 'seen_release';

function AboutBody({ transport, payload, onNavigate }) {
  const { settingsPalette, buttonPalette } = useSettingsPalettes();
  const about = aboutFromPayload(payload, transport.serverUrl);
  const [releases, setReleases] = useState(about.releases);
  const [loadingReleases, setLoadingReleases] = useState(!about.releasesLoaded && !about.releases.length);
  const [banner, setBanner] = useState(false);
  const [preview, setPreview] = useState(null);
  const previewSequence = useRef(0);

  async function previewSpecification(spec) {
    const request = ++previewSequence.current;
    setPreview({ spec, loading: true, text: '', error: '' });
    try {
      const text = await transport.loadSpecification(spec.path);
      if (request === previewSequence.current) setPreview({ spec, text, loading: false, error: '' });
    } catch (cause) {
      if (request === previewSequence.current) setPreview({ spec, loading: false, error: cause?.message || 'Could not load this specification.' });
    }
  }

  async function downloadSpecification(spec) {
    try {
      const text = preview?.spec.path === spec.path && typeof preview.text === 'string' && !preview.error
        ? preview.text : await transport.loadSpecification(spec.path);
      await saveTextFile({ name: spec.downloadName, text });
    } catch (cause) {
      setPreview({ spec, loading: false, error: cause?.message || 'Could not download this specification.' });
    }
  }

  useEffect(() => {
    let active = true;
    if (!about.releasesLoaded && !about.releases.length) {
      transport.loadWhatsNew()
        .then(result => { if (active) setReleases(result?.releases || []); })
        .catch(() => {})
        .finally(() => { if (active) setLoadingReleases(false); });
    }
    readLocalSetting(SEEN_KEY).then(seen => {
      if (!active || !about.releaseTag) return;
      if (seen === null) writeLocalSetting(SEEN_KEY, about.releaseTag);
      else setBanner(seen !== about.releaseTag);
    });
    return () => { active = false; };
  }, [transport, about.releaseTag, about.releasesLoaded, about.releases.length]);

  const openUrl = url => { if (url) Linking.openURL(url).catch(() => {}); };
  const dismiss = () => {
    setBanner(false);
    writeLocalSetting(SEEN_KEY, about.releaseTag);
  };

  return <View style={{ gap: 16 }}><SettingsAboutView
    heading={false} presentation={payload.presentation || {}}
    banner={banner ? { releaseTag: about.releaseTag, onDismiss: dismiss, onViewWhatsNew: dismiss } : null}
    overview={{ onOpenUrl: openUrl, sponsorUrl: payload.sponsorUrl }}
    whatsNew={{ releases, releasesUrl: about.releasesUrl, loading: loadingReleases, onOpenUrl: openUrl }}
    install={{ platform: Platform.OS === 'web' ? 'desktop' : Platform.OS, installAvailable: false, guideUrl: about.guideUrl || undefined, onOpenUrl: openUrl }}
    resources={{ resources: about.resources, onOpenUrl: openUrl }}
    specs={{
      specs: about.specs, onOpenUrl: openUrl,
      onPreview: previewSpecification,
      onDownload: downloadSpecification,
    }}
    attributions={{ attributions: about.attributions, onOpenUrl: openUrl }}
    licenses={{ licenses: about.licenses, onOpenUrl: openUrl }}
    version={{ version: about.version, commit: about.commit }}
    palette={{ ...settingsPalette, pageCards: true, pageGap: 32 }} buttonPalette={buttonPalette} />
    <SettingsCard title="Clipboard and install" palette={settingsPalette}>
      <Button label="Open Utilities" tone="surface" palette={buttonPalette} onPress={() => onNavigate?.('Utilities')} />
    </SettingsCard>
    <AboutSpecificationPreview model={preview} palette={settingsPalette} buttonPalette={buttonPalette}
      copyLabel={Platform.OS === 'web' ? 'Copy' : 'Share'} copiedLabel={Platform.OS === 'web' ? 'Copied!' : 'Shared'}
      onClose={() => { previewSequence.current += 1; setPreview(null); }}
      onRetry={() => previewSpecification(preview.spec)} onDownload={() => downloadSpecification(preview.spec)}
      onCopy={async () => {
        try {
          if (await copyText(preview.text)) setPreview(current => current ? { ...current, copied: true } : current);
        } catch (cause) { setPreview(current => current ? { ...current, error: cause?.message || 'Could not copy the specification.' } : current); }
      }} />
  </View>;
}

export default function AboutSettingsSlot({ onNavigate }) {
  const resource = useSettingsResource(transport => transport.loadAbout());
  if (resource.state !== 'ready') {
    return <SettingsLoadState state={resource.state} message={resource.message} onRetry={resource.reload} />;
  }
  return <AboutBody transport={resource.transport} payload={resource.data} onNavigate={onNavigate} />;
}
