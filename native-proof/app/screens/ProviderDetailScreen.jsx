import React, { useCallback, useEffect, useState } from 'react';
import * as ExpoLinking from 'expo-linking';
import { AppState, Linking, Text } from 'react-native';
import { ProviderDetailView } from '../../../frontend/pages/ProviderDetailView';
import { Button } from '../../../frontend/ui/Button';
import { copyText, pickImportFile } from '../data/fileFlows';
import { createProvidersTransport, detailFromPayload } from '../data/providersTransport';
import { createSettingsTransport } from '../data/settingsTransport';
import { integrationButtonPalette, integrationPalette } from './integrationPalette';
import { palette } from '../theme';
import CatalogGrantsSlot from '../surfaces/CatalogGrantsSlot';
import { SettingsSurface } from './SettingsScreen';

export const surface = {
  id: 'PROVIDER_DETAIL',
  status: 'ported',
  title: 'Provider detail: connect, credentials, webhooks, import, schedules',
  where: 'Providers, one provider (web: /settings/providers/<slug>)',
  note: 'Renders the shared ProviderPageView with ProviderSettingsView bodies from GET /api/v1/providers/<slug>/. Credentials are write-only. Trakt, Storyteller and WeTrakr connect with an in-app device code (start/poll JSON); Trakt, Simkl, Plex, MAL, AniList and TMDB open the provider sign-in in the browser and return through the app scheme (floppy-native-proof://connect/<slug>). The screen refetches on return and when the app comes to the foreground.',
};

const SIGNED_OUT = 'Sign in to your Floppy server to manage providers.';

export default function ProviderDetailScreen({ params, onBack, navigate }) {
  const slug = params?.slug || '';
  const [transport] = useState(() => createProvidersTransport());
  const [tab, setTab] = useState(params?.tab || 'overview');
  const [detail, setDetail] = useState(null);
  const [state, setState] = useState(transport.mode === 'server' ? 'loading' : 'signedOut');
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);

  useEffect(() => {
    if (transport.mode !== 'server') return undefined;
    let active = true;
    if (!detail) setState('loading');
    transport.detail(slug, tab)
      .then(payload => { if (active) { setDetail(detailFromPayload(payload)); setState('ready'); } })
      .catch(cause => { if (active) { setError(cause?.message || 'This provider could not be loaded.'); setState('error'); } });
    return () => { active = false; };
    // The detail is refetched per tab and after every write.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [transport, slug, tab, reload]);

  const refresh = useCallback(() => setReload(value => value + 1), []);

  // Returning from the browser hand-off (Trakt, Plex and the like) reloads the
  // provider so the new connection state shows without a manual refresh.
  useEffect(() => {
    const subscription = AppState.addEventListener('change', next => { if (next === 'active') refresh(); });
    return () => subscription.remove();
  }, [refresh]);
  // The server may only send the browser back to the app's own scheme, so the
  // return address is offered only when this build has that scheme (a dev
  // client or a store build; Expo Go and the web preview use another).
  const returnTo = (() => {
    const url = ExpoLinking.createURL(`connect/${slug}`);
    return /^floppy-native-proof:\/\//.test(url) ? url : undefined;
  })();
  useEffect(() => {
    const subscription = ExpoLinking.addEventListener('url', event => {
      if (String(event?.url || '').includes(`connect/${slug}`)) refresh();
    });
    return () => subscription.remove();
  }, [slug, refresh]);
  const write = useCallback(action => async (...args) => {
    const result = await action(...args);
    refresh();
    return result;
  }, [refresh]);

  const colors = integrationPalette();
  const buttons = integrationButtonPalette();

  if (state !== 'ready') {
    const signedOut = state === 'signedOut';
    return <SettingsSurface navigate={navigate}>
      {state === 'loading' ? <Text style={{ color: palette.textMuted }}>Loading provider…</Text> : <>
        <Text accessibilityRole="alert" style={{ color: palette.danger }}>{signedOut ? SIGNED_OUT : error}</Text>
        <Button label={signedOut ? 'Sign In' : 'Retry'} tone="surface" palette={buttons}
          onPress={signedOut ? () => navigate?.('Auth') : refresh} />
      </>}
    </SettingsSurface>;
  }

  return <SettingsSurface navigate={navigate}>
    <ProviderDetailView detail={detail} tab={tab} palette={colors} buttonPalette={buttons}
      stremioInstallContent={slug === 'stremio' && tab === 'tracking'
        ? <CatalogGrantsSlot palette={colors} buttonPalette={buttons} /> : null}
      onTab={setTab}
      onOpenUrl={url => { if (url) Linking.openURL(url).catch(() => {}); }}
      onCopy={text => copyText(text)}
      onOpenConnections={() => navigate?.('Connections')}
      onStartLink={values => transport.startLink(slug, { ...values, ...(returnTo ? { returnTo } : {}) })}
      onPollLink={() => transport.pollLink(slug)}
      onCancelLink={() => transport.cancelLink(slug)}
      onLinked={refresh}
      onConnect={write(values => transport.connect(slug, values))}
      onDisconnect={write(instanceId => transport.disconnect(slug, instanceId ? { instance_id: instanceId } : {}))}
      onSaveCredentials={write((kind, values) => transport.saveCredentials(slug, kind, values))}
      onClearCredentials={write(() => transport.clearCredentials(slug))}
      pickFiles={async ({ accept }) => { const picked = await pickImportFile({ accept }); return picked ? [picked] : []; }}
      onOpenActivity={setTab}
      onSavePreferences={values => createSettingsTransport().saveImportSettings(Object.fromEntries(Object.entries({
        frequency: values.frequency, time: values.time, mode: values.mode,
        watchlist_status: values.watchlistStatus, clz_wishlist_status: values.clzWishlistStatus,
      }).filter(([, value]) => value)))}
      onImportFile={write(({ name, content, contentBase64, mode }) => transport.importFile(slug, { name, content, contentBase64, mode }))}
      onSaveForm={write((key, values) => transport.saveForm(slug, key, values, tab))}
      onSaveSource={write(({ key, source, animeMode }) => transport.metadataAction(slug, { action: 'source', key, source, ...(animeMode ? { animeMode } : {}) }))}
      onMove={write(({ key }) => transport.metadataAction(slug, { action: 'move', key }))}
      onSaveProxy={write(proxyUrl => transport.metadataAction(slug, { action: 'proxy', proxyUrl }))}
      onTest={write(() => transport.test(slug))}
      onSync={write(() => transport.sync(slug))}
      onImport={write(form => transport.importNow(slug, form))}
      onDeleteSchedule={write(taskName => transport.deleteSchedule(slug, taskName))} />
  </SettingsSurface>;
}
