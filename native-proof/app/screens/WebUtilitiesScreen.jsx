import React, { useEffect, useState } from 'react';
import { Screen } from '../components/Screen';
import { UtilitiesView } from '../../../frontend/pages/UtilitiesView';
import { copyText } from '../../../frontend/ui/clipboard';
import { getInstallState, openInstallGuide, requestInstall, subscribeInstallState } from '../../../frontend/ui/installPrompt';
import { getCacheStatus } from '../../../frontend/ui/serviceWorkerStatus';
import { palette, radius } from '../theme';

export const surface = {
  id: 'WEB-UTILITIES',
  title: 'Clipboard and install',
  where: 'Copy controls, install feedback and static cache',
  status: 'ported',
  note: 'Copy fields, install/launch feedback and web-only service-worker status render here. The browser mounts the same copy, install and cache cards over its server fallback; the native app uses its clipboard and reports the browser cache as not applicable.',
};

const uiPalette = {
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  background: palette.surface,
  surface: palette.surface,
  surfaceStrong: palette.surfaceStrong,
  surfaceMuted: palette.surfaceMuted,
  border: palette.border,
  success: palette.success,
  danger: palette.danger,
  accent: palette.accent,
  badgeBorder: palette.surfaceMuted,
  badgeBackground: palette.surfaceStrong,
  badgeText: palette.textSecondary,
  badgeHover: palette.surfaceMuted,
  radius: radius.md,
  focusStyle: { outlineStyle: 'solid', outlineWidth: 2, outlineColor: palette.accent, outlineOffset: 2 },
};

const buttonPalette = {
  primary: { background: palette.accentStrong, pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: palette.surfaceStrong, pressed: palette.surfaceMuted, hovered: palette.surfaceMuted, text: palette.text, border: palette.border },
  'danger-solid': { background: palette.danger, pressed: '#b91c1c', hovered: '#b91c1c', text: '#ffffff', border: 'transparent' },
  radius: radius.sm,
  focusStyle: uiPalette.focusStyle,
};

export default function WebUtilitiesScreen({ onBack }) {
  const [installState, setInstallState] = useState(() => getInstallState());
  const [cache, setCache] = useState({ loading: true, supported: true });

  useEffect(() => subscribeInstallState(setInstallState), []);

  const refreshCache = async () => {
    setCache(current => ({ ...current, loading: true }));
    const status = await getCacheStatus();
    setCache({ ...status, loading: false });
  };

  useEffect(() => {
    let live = true;
    getCacheStatus().then(status => { if (live) setCache({ ...status, loading: false }); });
    return () => { live = false; };
  }, []);

  const cacheLine = cache.supported === false
    ? 'not applicable'
    : cache.registered ? 'registered' : 'not registered';
  const report = [
    'Floppy diagnostics',
    `Platform: ${installState.platform}`,
    `Install prompt: ${installState.canInstall ? 'available' : 'not available'}`,
    `Installed: ${installState.installed ? 'yes' : 'no'}`,
    `Static cache: ${cacheLine}`,
  ].join('\n');

  return <Screen title="Clipboard" subtitle="Clipboard and install" onBack={onBack}>
    <UtilitiesView
      onCopy={copyText}
      copyFields={[
        {
          id: 'server-url', label: 'Server URL', value: 'https://floppy.example.com',
          help: 'Used by clients and webhooks that connect to this instance.',
        },
        {
          id: 'webhook-url', label: 'Webhook URL',
          value: 'https://floppy.example.com/hooks/library/demo-01',
          help: 'Paste this into a media server to report plays.',
        },
        {
          id: 'diagnostics', label: 'Diagnostic report', value: report,
          help: 'If a copy or install step fails, paste this report into your issue.',
          copyLabel: 'Copy report',
        },
      ]}
      installState={installState}
      install={{ onInstall: requestInstall, onOpenGuide: openInstallGuide }}
      cacheStatus={cache}
      cache={{ onRefresh: refreshCache, busy: cache.loading }}
      palette={uiPalette} buttonPalette={buttonPalette} />
  </Screen>;
}
