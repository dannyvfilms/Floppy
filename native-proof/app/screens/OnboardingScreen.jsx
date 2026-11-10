import React, { useCallback, useEffect, useState } from 'react';
import * as ExpoLinking from 'expo-linking';
import { AppState, Linking, StyleSheet, Text, View } from 'react-native';
import { OnboardingView } from '../../../frontend/pages/OnboardingView';
import {
  OnboardingCompleteStep,
  OnboardingImportStatusStep,
  OnboardingIntegrationStep,
  OnboardingMediaTypesStep,
  OnboardingMetadataStep,
  OnboardingNotice,
  OnboardingServicesStep,
  OnboardingServiceSetupStep,
  OnboardingSummaryStep,
} from '../../../frontend/onboarding/OnboardingWizard';
import { Button } from '../../../frontend/ui/Button';
import { actionIcons } from '../../../frontend/ui/actionIcons';
import { ProviderLinkCard } from '../../../frontend/providers/ProviderLinkCard';
import { Screen } from '../components/Screen';
import { createOnboardingTransport, mediaTypeSelection, sourceSelection } from '../data/onboardingTransport';
import { createProvidersTransport } from '../data/providersTransport';
import { copyText, pickImportFile } from '../data/fileFlows';
import { integrationButtonPalette } from './integrationPalette';
import { absoluteUrl } from '../data/settingsTransport';
import { getActiveAuthSession } from '../data/authSession';
import { palette, radius } from '../theme';

export const surface = {
  id: 'ONBOARDING',
  status: 'ported',
  title: 'First-run setup',
  where: 'Media types, metadata keys, services, summary, scrobbling and import status',
  note: 'Reads and advances the server wizard through /api/v1/user/onboarding/. Inline service forms and uploads delegate to the existing web handlers through connect_service; OAuth and device sign-in use the provider JSON hand-off and reload on return. Media-type order and switches remain local until Continue. Browser comparison is recorded separately; iOS and Android have not been exercised.',
};

// Step titles and explanations follow src/templates/users/onboarding/*.html.
function stepCopy(data) {
  switch (data.step) {
    case 'media_types':
      return {
        title: 'What do you want to track?',
        explanation: "Pick the kinds of media you want Floppy to track. This controls what shows up in your sidebar and search, and which services we'll offer to connect next.\n\nYou can change this anytime from Settings, and nothing you skip here is lost.",
      };
    case 'metadata':
      return {
        title: 'Better artwork and data',
        explanation: "Floppy works without any of these. Each one fills a gap, like logos and backdrops for games, or a higher request limit.\n\nKeys stay private to your account. You can add or change them anytime in Settings > Providers.",
      };
    case 'services': {
      const label = data.services?.mediaTypeLabel || '';
      return {
        title: label,
        explanation: `Do you use any of these apps for ${label.toLowerCase()}?\n\nPick any that apply. We'll walk you through connecting them next. Skip this if you don't use any.`,
      };
    }
    case 'services_summary': {
      const count = data.summary?.mediaTypeCount || 0;
      return {
        title: `Tracking ${count} media ${count === 1 ? 'type' : 'types'}`,
        explanation: "Next we can walk you through connecting the services you picked, one at a time, and kick off an initial import.\n\nYou can always finish this later from Settings > Import.",
      };
    }
    case 'service_setup': {
      const left = data.serviceSetup?.remainingCount || 0;
      const inline = data.serviceSetup?.source?.inlineSupported;
      return {
        title: 'Connect your services',
        explanation: `${left} ${left === 1 ? 'service' : 'services'} left to connect.\n\n${inline
          ? "Connect right here. Once it's done, you'll automatically see the next one."
          : "Connecting opens the normal Import setup for this service in a focused view. Finish there and you'll come right back here for the next one."}\n\nDon't have it handy? Skip it. You can always connect it later from Settings > Import.`,
      };
    }
    case 'integration_setup':
      return {
        title: 'Turn on scrobbling',
        explanation: "To keep tracking automatically going forward, a connected service also needs a webhook set up.\n\nThis depends on where your library actually lives, so it's a separate, optional step.\n\nDon't need it? Skip it. You can always set it up later from Settings > Providers.",
      };
    case 'import_status':
      return {
        title: "You're all set",
        explanation: "Your connected services are queued to import. This can take a few minutes depending on how much history they have.\n\nYou can check progress and history anytime from Settings > Import.",
      };
    default:
      return { title: 'Setup complete', explanation: '' };
  }
}

export default function OnboardingScreen({ params, onFinish, onBack, navigate }) {
  const [transport] = useState(() => createOnboardingTransport());
  const [providersTransport] = useState(() => createProvidersTransport());
  const [data, setData] = useState(null);
  const [loadError, setLoadError] = useState('');
  const [busy, setBusy] = useState(false);
  const [stepError, setStepError] = useState('');
  const [mediaTypes, setMediaTypes] = useState([]);
  const [mediaOrder, setMediaOrder] = useState([]);
  const [metadataValues, setMetadataValues] = useState({});
  const [sources, setSources] = useState([]);
  const [serviceValues, setServiceValues] = useState({});
  const [traktProfile, setTraktProfile] = useState('public');

  const adopt = useCallback(next => {
    const serverUrl = getActiveAuthSession()?.serverUrl;
    const source = value => value ? { ...value, logo: absoluteUrl(serverUrl, value.logo) } : value;
    setData({ ...next,
      ...(next?.services ? { services: { ...next.services, candidates: next.services.candidates.map(source) } } : {}),
      ...(next?.summary ? { summary: { ...next.summary,
        selectedSources: next.summary.selectedSources?.map(source), connectedSourceList: next.summary.connectedSourceList?.map(source) } } : {}),
      ...(next?.serviceSetup ? { serviceSetup: { ...next.serviceSetup, source: source(next.serviceSetup.source) } } : {}),
      ...(next?.integration ? { integration: { ...next.integration, source: source(next.integration.source) } } : {}),
      ...(next?.importStatus ? { importStatus: { ...next.importStatus,
        sources: next.importStatus.sources.map(row => ({ ...row, source: source(row.source) })) } } : {}),
    });
    setStepError('');
    if (next?.mediaTypes) {
      setMediaTypes(next.mediaTypes.selected || []);
      setMediaOrder(next.mediaTypes.options.map(option => option.value));
    }
    if (next?.services) setSources(next.services.selected || []);
    if (next?.step !== 'metadata') setMetadataValues({});
  }, []);

  const load = useCallback(async options => {
    setLoadError('');
    try {
      const next = await transport.load(options);
      if (next?.local) {
        setLoadError(next.reason);
        return;
      }
      adopt(next);
    } catch (error) {
      setLoadError(error?.message || 'Could not load setup.');
    }
  }, [transport, adopt]);

  useEffect(() => {
    if (params?.restart) transport.act('restart').then(adopt).catch(error => setLoadError(error?.message || 'Could not restart setup.'));
    else load();
  }, [load, params?.restart, transport, adopt]);
  useEffect(() => {
    setServiceValues({});
    setTraktProfile(data?.serviceSetup?.traktConfigured ? 'public' : 'csv');
  }, [data?.serviceSetup?.source?.slug, data?.serviceSetup?.traktConfigured]);
  useEffect(() => {
    if (data?.step !== 'service_setup') return undefined;
    const appSubscription = AppState.addEventListener('change', next => { if (next === 'active') load(); });
    const urlSubscription = ExpoLinking.addEventListener('url', event => {
      if (String(event?.url || '').includes('connect/')) load();
    });
    return () => { appSubscription.remove(); urlSubscription.remove(); };
  }, [data?.step, load]);

  async function act(action, payload, { then } = {}) {
    setBusy(true);
    setStepError('');
    try {
      const next = await transport.act(action, payload);
      adopt(next);
      if (then) then(next);
    } catch (error) {
      setStepError(error?.message || 'Could not save this step.');
    } finally {
      setBusy(false);
    }
  }

  const finish = () => (onFinish || onBack)?.();
  const wizardPalette = { ...palette, radius: radius.md, controlRadius: radius.sm, thumb: palette.onAccentStrong,
    accentText: palette.onAccentStrong, focusStyle: {} };
  const serverUrl = getActiveAuthSession()?.serverUrl;

  if (loadError) {
    return <Screen chrome={false} contentStyle={{ paddingTop: 24 }}>
      <OnboardingNotice tone="error" title="Could not load setup" palette={wizardPalette}>{loadError}</OnboardingNotice>
      <View style={styles.retry}><Button label="Retry" onPress={() => load()} palette={integrationButtonPalette()} /></View>
    </Screen>;
  }
  if (!data) {
    return <Screen chrome={false} contentStyle={{ paddingTop: 24 }}><OnboardingView loading palette={wizardPalette} /></Screen>;
  }

  const copy = stepCopy(data);
  const done = data.step === 'done';
  const progress = { steps: data.steps, activeStep: data.activeStep, completedSteps: data.completedSteps };

  let body = null;
  if (data.step === 'media_types') {
    const options = mediaOrder.map(value => data.mediaTypes.options.find(option => option.value === value)).filter(Boolean);
    body = <OnboardingMediaTypesStep options={options} selected={mediaTypes}
      dragIcon={actionIcons.grip} onMove={(from, to) => setMediaOrder(current => {
        const next = [...current]; const [moved] = next.splice(from, 1); next.splice(to, 0, moved); return next;
      })}
      onToggle={value => setMediaTypes(current => mediaTypeSelection(current, value))}
      onContinue={() => act('media_types', {
        mediaTypes,
        order: options.map(option => option.value),
      })}
      onSkip={() => act('skip', {}, { then: finish })}
      error={stepError} busy={busy} palette={wizardPalette} buttonPalette={integrationButtonPalette()} />;
  } else if (data.step === 'metadata') {
    body = <OnboardingMetadataStep suggestions={data.metadata.suggestions} values={metadataValues}
      onChange={(key, text) => setMetadataValues(current => ({ ...current, [key]: text }))}
      onOpenDocs={suggestion => { if (suggestion.docsUrl) Linking.openURL(suggestion.docsUrl).catch(() => {}); }}
      onSkip={() => act('skip_metadata')}
      onContinue={() => act('metadata', { values: metadataValues })}
      error={stepError} busy={busy} palette={wizardPalette} buttonPalette={integrationButtonPalette()} />;
  } else if (data.step === 'services') {
    const services = data.services;
    body = <OnboardingServicesStep mediaTypeLabel={services.mediaTypeLabel}
      stepNumber={services.index + 1} stepTotal={services.total}
      candidates={services.candidates} selected={sources} isLast={services.isLast}
      onToggle={slug => setSources(current => sourceSelection(current, slug))}
      onNext={() => act('services', { index: services.index, sources })}
      busy={busy} palette={wizardPalette} buttonPalette={integrationButtonPalette()} />;
  } else if (data.step === 'services_summary') {
    body = <OnboardingSummaryStep mediaTypeCount={data.summary.mediaTypeCount}
      selectedSources={data.summary.selectedSources} connectedSources={data.summary.connectedSources}
      onLater={() => act('later', {}, { then: finish })}
      onSetupNow={() => act('setup_now')} palette={wizardPalette} buttonPalette={integrationButtonPalette()} />;
  } else if (data.step === 'service_setup') {
    const source = { ...data.serviceSetup.source, logo: absoluteUrl(serverUrl, data.serviceSetup.source.logo) };
    const providerSlug = source.providerSlug || source.slug;
    const returnUrl = ExpoLinking.createURL(`connect/${providerSlug}`);
    const connection = <ProviderLinkCard label={source.name} needsServerUrl={source.slug === 'storyteller'}
      palette={wizardPalette} buttonPalette={integrationButtonPalette()}
      onStart={values => providersTransport.startLink(providerSlug, {
        ...values, ...(/^floppy-native-proof:\/\//.test(returnUrl) ? { returnTo: returnUrl } : {}),
      })}
      onPoll={() => providersTransport.pollLink(providerSlug)}
      onCancel={() => providersTransport.cancelLink(providerSlug)}
      onOpenUrl={url => Linking.openURL(url).catch(() => {})} onCopy={copyText} onConnected={() => load()} />;
    const connect = async () => {
      if (source.uploadFieldName || (source.slug === 'trakt' && traktProfile === 'csv')) {
        setStepError('');
        try {
          const file = await pickImportFile({ accept: source.slug === 'trakt' ? '.zip,.json,.csv' : source.uploadAccept });
          if (!file) return;
          await act('connect_service', { slug: source.slug, profile: traktProfile,
            name: file.name, ...(file.base64 ? { contentBase64: file.base64 } : { content: file.text }) });
        } catch (error) { setStepError(error?.message || 'Could not select the import file.'); }
      } else {
        await act('connect_service', { slug: source.slug, profile: traktProfile, values: serviceValues });
      }
    };
    body = <OnboardingServiceSetupStep source={source} values={serviceValues} showRemainingCount={false}
      onChange={(name, value) => setServiceValues(current => ({ ...current, [name]: value }))}
      onConnect={connect} onSkip={() => act('skip_service', { slug: source.slug })}
      traktConfigured={data.serviceSetup.traktConfigured} traktProfile={traktProfile}
      onTraktProfileChange={setTraktProfile} oauthContent={connection} deviceContent={connection}
      onOpenImport={() => navigate?.('ProviderDetail', { slug: providerSlug, label: source.name, tab: 'import' })}
      busy={busy} error={stepError} palette={wizardPalette} buttonPalette={integrationButtonPalette()} />;
  } else if (data.step === 'integration_setup') {
    const source = data.integration.source;
    body = <OnboardingIntegrationStep source={source}
      onSkip={() => act('skip_integration', { slug: source.slug })}
      onContinue={() => act('integration_done')} busy={busy} palette={wizardPalette} buttonPalette={integrationButtonPalette()} />;
  } else if (data.step === 'import_status') {
    body = <OnboardingImportStatusStep sources={data.importStatus.sources}
      onRefresh={() => load()} onContinue={() => act('finish', {}, { then: finish })}
      palette={wizardPalette} buttonPalette={integrationButtonPalette()} />;
  } else {
    body = <View style={styles.section}>
      <OnboardingCompleteStep mediaTypeCount={data.summary?.mediaTypeCount || 0}
        connectedSources={data.summary?.connectedSourceList || []}
        onRestart={() => act('restart')} palette={wizardPalette} buttonPalette={integrationButtonPalette()} />
      <Button label="Done" onPress={finish} palette={integrationButtonPalette()} />
    </View>;
  }

  return <Screen chrome={false} contentStyle={{ paddingTop: 24 }}>
    <OnboardingView {...progress} title={copy.title} explanation={copy.explanation}
      standalone heroSource={data.heroUrl ? { uri: absoluteUrl(serverUrl, data.heroUrl) } : undefined}
      progressArrowIcon={actionIcons.chevronRight} buttonPalette={integrationButtonPalette()}
      status={done ? 'completed' : 'in_progress'} palette={wizardPalette}
      blocked={Boolean(data.demo)} blockedMessage={data.message}
      notice={stepError && data.step !== 'media_types' && data.step !== 'metadata' && data.step !== 'service_setup'
        ? { tone: 'error', title: 'Could not continue', text: stepError } : null}
      saveLabel="Save & finish later" onSaveAndFinish={done ? undefined : finish}>
      {body}
    </OnboardingView>
  </Screen>;
}

const styles = StyleSheet.create({
  section: { gap: 12, minWidth: 0 },
  sourceName: { fontSize: 16, fontWeight: '600' },
  error: { fontSize: 12, lineHeight: 17 },
  actions: { flexDirection: 'row', justifyContent: 'space-between' },
  retry: { alignSelf: 'flex-start' },
});
