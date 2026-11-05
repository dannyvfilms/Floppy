import React, { useEffect, useRef, useState } from 'react';
import { StyleSheet, Text } from 'react-native';
import {
  OnboardingCompleteStep,
  OnboardingImportStatusStep,
  OnboardingIntegrationStep,
  OnboardingMediaTypesStep,
  OnboardingMetadataStep,
  OnboardingServiceSetupStep,
  OnboardingServicesStep,
  OnboardingSummaryStep,
  OnboardingWizard,
} from '../../../frontend/onboarding/OnboardingWizard';
import { ConfirmDialog } from '../../../frontend/settings/ConfirmDialog';
import { Screen } from '../components/Screen';
import { readOnboardingState, writeOnboardingState } from '../data/onboardingState';
import { palette, spacing } from '../theme';

export const surface = {
  id: 'ONBOARDING',
  status: 'ported',
  title: 'Onboarding',
  where: 'First-run media, metadata, services and connection steps',
  note: 'Resumable media, metadata and services steps, next/skip/restart, credential/host/API-key/upload/OAuth/Trakt/device variants, Plex webhook instructions, import status and persisted demo resume state use the shared React Native wizard. Server transport, real OAuth handoff, live source permissions and iOS/Android runtime remain unverified.',
};

const STEPS = [
  { slug: 'media_types', label: 'Media Types' },
  { slug: 'metadata', label: 'Metadata' },
  { slug: 'services', label: 'Services' },
  { slug: 'services_summary', label: 'Summary' },
  { slug: 'service_setup', label: 'Connect' },
  { slug: 'integration_setup', label: 'Scrobbling' },
  { slug: 'import_status', label: 'Import' },
];

const MEDIA_TYPES = [
  { value: 'tv', label: 'TV Shows' },
  { value: 'movie', label: 'Movies' },
  { value: 'anime', label: 'Anime' },
  { value: 'manga', label: 'Manga' },
  { value: 'game', label: 'Games' },
  { value: 'book', label: 'Books' },
  { value: 'comic', label: 'Comics' },
  { value: 'boardgame', label: 'Board Games' },
  { value: 'music', label: 'Music' },
  { value: 'podcast', label: 'Podcasts' },
  { value: 'video', label: 'Videos' },
];

const SOURCE_CATALOG = [
  { slug: 'plex', name: 'Plex', mediaTypes: ['movie', 'tv', 'music'], setupKind: 'oauth', isOauth: true, integrationTag: 'plex', description: 'Your Plex library and watch history.' },
  { slug: 'radarr', name: 'Radarr', mediaTypes: ['movie'], setupKind: 'host_url', description: 'Movies from your Radarr library.', connectFields: [
    { name: 'base_url', label: 'Base URL', type: 'url' }, { name: 'api_key', label: 'API Key', type: 'password' },
  ] },
  { slug: 'sonarr', name: 'Sonarr', mediaTypes: ['tv'], setupKind: 'host_url', description: 'TV shows from your Sonarr library.', connectFields: [
    { name: 'base_url', label: 'Base URL', type: 'url' }, { name: 'api_key', label: 'API Key', type: 'password' },
  ] },
  { slug: 'mylar', name: 'Mylar3', mediaTypes: ['comic'], setupKind: 'host_url', description: 'Comics from your Mylar3 library.', connectFields: [
    { name: 'base_url', label: 'Base URL', type: 'url' }, { name: 'api_key', label: 'API Key', type: 'password' },
  ] },
  { slug: 'kapowarr', name: 'Kapowarr', mediaTypes: ['comic'], setupKind: 'host_url', description: 'Comics from your Kapowarr library.', connectFields: [
    { name: 'base_url', label: 'Base URL', type: 'url' }, { name: 'api_key', label: 'API Key', type: 'password' },
  ] },
  { slug: 'stremio', name: 'Stremio', mediaTypes: ['movie', 'tv'], setupKind: 'credentials', description: 'Your Stremio account.', connectFields: [
    { name: 'email', label: 'Email', type: 'email' }, { name: 'password', label: 'Password', type: 'password' },
  ] },
  { slug: 'audiobookshelf', name: 'Audiobookshelf', mediaTypes: ['book', 'podcast'], setupKind: 'host_url', description: 'Audiobooks and podcasts from Audiobookshelf.', connectFields: [
    { name: 'base_url', label: 'Server URL', type: 'url' }, { name: 'api_token', label: 'API Token', type: 'password' },
  ] },
  { slug: 'kavita', name: 'Kavita', mediaTypes: ['book', 'comic', 'manga'], setupKind: 'host_url', description: 'Books, comics and manga from Kavita.', connectFields: [
    { name: 'base_url', label: 'Server URL', type: 'url' }, { name: 'api_key', label: 'API Key', type: 'password' },
  ] },
  { slug: 'komga', name: 'Komga', mediaTypes: ['book', 'comic'], setupKind: 'host_url', description: 'Books and comics from Komga.', connectFields: [
    { name: 'base_url', label: 'Server URL', type: 'url' }, { name: 'api_key', label: 'API Key', type: 'password' },
  ] },
  { slug: 'storyteller', name: 'Storyteller', mediaTypes: ['book'], setupKind: 'host_url', inlineSupported: false, description: 'Audiobooks from your Storyteller server.' },
  { slug: 'pocketcasts', name: 'Pocket Casts', mediaTypes: ['podcast'], setupKind: 'credentials', description: 'Podcast listening history from Pocket Casts.', connectFields: [
    { name: 'email', label: 'Email', type: 'email' }, { name: 'password', label: 'Password', type: 'password' },
  ] },
  { slug: 'gpodder', name: 'GPodder', mediaTypes: ['podcast'], setupKind: 'credentials', description: 'Podcast subscriptions from a GPodder server.', connectFields: [
    { name: 'server_url', label: 'Server URL', type: 'url' }, { name: 'username', label: 'Username', type: 'text' }, { name: 'password', label: 'Password', type: 'password' },
  ] },
  { slug: 'lastfm', name: 'Last.fm', mediaTypes: ['music'], setupKind: 'api_key', description: 'Music scrobbles from Last.fm.', connectFields: [
    { name: 'lastfm_username', label: 'Last.fm Username', type: 'text' },
  ] },
  { slug: 'koito', name: 'Koito', mediaTypes: ['music'], setupKind: 'host_url', description: 'Music listening history from Koito.', connectFields: [
    { name: 'base_url', label: 'Server URL', type: 'url' }, { name: 'api_key', label: 'API Key', type: 'password' },
  ] },
  { slug: 'trakt', name: 'Trakt', mediaTypes: ['movie', 'tv'], setupKind: 'oauth', isOauth: true, description: 'Movies and TV history from Trakt.' },
  { slug: 'mdblist', name: 'MDBList', mediaTypes: ['movie', 'tv'], setupKind: 'api_key', description: 'Lists and watch history from MDBList.', connectFields: [
    { name: 'api_key', label: 'API Key', type: 'password' },
  ] },
  { slug: 'simkl', name: 'SIMKL', mediaTypes: ['movie', 'tv', 'anime'], setupKind: 'oauth', isOauth: true, description: 'Movies, TV and anime history from SIMKL.' },
  { slug: 'myanimelist', name: 'MyAnimeList', mediaTypes: ['anime', 'manga'], setupKind: 'oauth', description: 'Anime and manga lists from MyAnimeList.', connectFields: [
    { name: 'user', label: 'MyAnimeList Username', type: 'text' },
  ] },
  { slug: 'anilist', name: 'AniList', mediaTypes: ['anime', 'manga'], setupKind: 'oauth', isOauth: true, description: 'Anime and manga lists from AniList.' },
  { slug: 'kitsu', name: 'Kitsu', mediaTypes: ['anime', 'manga'], setupKind: 'credentials', description: 'Anime and manga lists from Kitsu.', connectFields: [
    { name: 'user', label: 'Kitsu User ID', type: 'text' },
  ] },
  { slug: 'mangabaka', name: 'MangaBaka', mediaTypes: ['manga'], setupKind: 'api_key', description: 'Manga lists from MangaBaka.', connectFields: [
    { name: 'token', label: 'MangaBaka API Token', type: 'password' },
  ] },
  { slug: 'hltb', name: 'HowLongToBeat', mediaTypes: ['game'], setupKind: 'upload', description: 'Game playtimes from a HowLongToBeat export.', uploadFieldName: 'hltb_csv', uploadAccept: '.csv' },
  { slug: 'playnite', name: 'Playnite', mediaTypes: ['game'], setupKind: 'upload', description: 'Your Playnite library.', uploadFieldName: 'playnite_csv', uploadAccept: '.csv' },
  { slug: 'grouvee', name: 'Grouvee', mediaTypes: ['game'], setupKind: 'upload', description: 'Your Grouvee collection.', uploadFieldName: 'grouvee_json', uploadAccept: '.json,.zip' },
  { slug: 'steam', name: 'Steam', mediaTypes: ['game'], setupKind: 'credentials', description: 'Your Steam library and playtime.', connectFields: [
    { name: 'user', label: 'Steam ID', type: 'text' },
  ] },
  { slug: 'imdb', name: 'IMDb', mediaTypes: ['movie', 'tv'], setupKind: 'upload', description: 'Watch history from an IMDb export.', uploadFieldName: 'imdb_csv', uploadAccept: '.csv' },
  { slug: 'goodreads', name: 'Goodreads', mediaTypes: ['book'], setupKind: 'upload', description: 'Reading history from a Goodreads export.', uploadFieldName: 'goodreads_csv', uploadAccept: '.csv' },
  { slug: 'hardcover', name: 'Hardcover', mediaTypes: ['book'], setupKind: 'upload', description: 'Reading history from a Hardcover export.', uploadFieldName: 'hardcover_csv', uploadAccept: '.csv' },
  { slug: 'storygraph', name: 'StoryGraph', mediaTypes: ['book'], setupKind: 'upload', description: 'Reading history from a StoryGraph export.', uploadFieldName: 'storygraph_csv', uploadAccept: '.csv' },
];

const SOURCE_BY_SLUG = Object.fromEntries(SOURCE_CATALOG.map(source => [source.slug, source]));
const MEDIA_TYPE_BY_VALUE = Object.fromEntries(MEDIA_TYPES.map(mediaType => [mediaType.value, mediaType]));

const METADATA_SUGGESTIONS = [
  {
    slug: 'steamgriddb', label: 'SteamGridDB', badge: 'Recommended', mediaTypes: ['game'],
    why: 'Adds logos and widescreen backdrops to game pages, so Hollow Knight gets its logo over a proper hero image instead of a plain screenshot.',
    docsUrl: 'https://www.steamgriddb.com/profile/preferences/api',
    fields: [{ name: 'api_key', label: 'API key', secret: true }],
  },
  {
    slug: 'thegamesdb', label: 'TheGamesDB', badge: 'Extra coverage', mediaTypes: ['game'],
    why: 'Fills in logos and backdrops for older and obscure games other sources miss.',
    docsUrl: 'https://api.thegamesdb.net/key.php',
    fields: [{ name: 'api_key', label: 'API key', secret: true }],
  },
  {
    slug: 'screenscraper', label: 'ScreenScraper', badge: 'Retro', mediaTypes: ['game'],
    why: 'Matches classic console games by system and name. An account is optional and raises your limits.',
    docsUrl: 'https://www.screenscraper.fr/membreinscription.php',
    fields: [{ name: 'ssid', label: 'Username', secret: false }, { name: 'sspassword', label: 'Password', secret: true }],
  },
  {
    slug: 'tmdb', label: 'TMDB', badge: 'Your own key', mediaTypes: ['movie', 'tv'],
    why: 'The built-in key is shared by every Floppy install and can hit its limit during big imports. A free key of your own avoids that.',
    docsUrl: 'https://www.themoviedb.org/settings/api',
    fields: [{ name: 'api_key', label: 'API key', secret: true }],
  },
];

const DEFAULT_STATE = {
  status: 'in_progress',
  step: 'media_types',
  selectedMediaTypes: [],
  selectedSources: [],
  skippedSources: [],
  connectedSources: [],
  skippedIntegrations: [],
  integrationConfigured: [],
  savedMetadata: [],
  importRuns: {},
};

const STEP_SLUGS = STEPS.map(step => step.slug);

function unique(values) {
  return Array.from(new Set(values));
}

function wait(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function stringList(value) {
  return Array.isArray(value) ? value.filter(item => typeof item === 'string') : [];
}

function normalizeState(stored) {
  const base = { ...DEFAULT_STATE, ...(stored || {}) };
  const state = {
    ...base,
    status: ['not_started', 'in_progress', 'completed'].includes(base.status) ? base.status : 'in_progress',
    step: STEP_SLUGS.includes(base.step) || base.step === 'done' ? base.step : 'media_types',
    selectedMediaTypes: stringList(base.selectedMediaTypes),
    selectedSources: stringList(base.selectedSources),
    skippedSources: stringList(base.skippedSources),
    connectedSources: stringList(base.connectedSources),
    skippedIntegrations: stringList(base.skippedIntegrations),
    integrationConfigured: stringList(base.integrationConfigured),
    savedMetadata: stringList(base.savedMetadata),
    importRuns: base.importRuns && typeof base.importRuns === 'object' ? base.importRuns : {},
  };
  if (state.status === 'completed') {
    state.step = 'done';
  } else if (state.step === 'done') {
    state.step = 'media_types';
  } else if (state.status === 'in_progress' && state.step === 'import_status') {
    state.step = 'integration_setup';
  }
  return state;
}

function metadataSuggestionsFor(selectedMediaTypes, savedMetadata) {
  const enabled = new Set(selectedMediaTypes);
  return METADATA_SUGGESTIONS.filter(suggestion => suggestion.mediaTypes.some(mediaType => enabled.has(mediaType))
    && !savedMetadata.includes(suggestion.slug));
}

function setupCopy(source) {
  if (source.slug === 'trakt') {
    return 'Public profile, private profile (OAuth), or a data export file.';
  }
  if (!source.inlineSupported) {
    return 'Connecting opens the normal Import setup for this service in a focused view. Finish there and you will come right back here.';
  }
  if (source.uploadFieldName) {
    return 'Requires uploading an export file.';
  }
  if (source.setupKind === 'api_key') {
    return 'Requires an API key.';
  }
  if (source.setupKind === 'host_url') {
    return 'Requires your server URL and an API key.';
  }
  return 'Requires your account credentials.';
}

function currentSourceWithCopy(source) {
  return source ? { ...source, setupCopy: setupCopy(source) } : null;
}

export default function OnboardingScreen({ onBack }) {
  const [state, setState] = useState(DEFAULT_STATE);
  const stateRef = useRef(DEFAULT_STATE);
  const [hydrated, setHydrated] = useState(false);
  const [servicesIndex, setServicesIndex] = useState(0);
  const [metadataValues, setMetadataValues] = useState({});
  const [connectionValues, setConnectionValues] = useState({});
  const [traktProfile, setTraktProfile] = useState('public');
  const [uploadNames, setUploadNames] = useState({});
  const [device, setDevice] = useState({ started: false });
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState(null);
  const [error, setError] = useState('');
  const [restartOpen, setRestartOpen] = useState(false);

  useEffect(() => {
    let active = true;
    readOnboardingState().then(stored => {
      if (!active) return;
      const next = normalizeState(stored);
      stateRef.current = next;
      setState(next);
      setServicesIndex(0);
      setHydrated(true);
    });
    return () => {
      active = false;
    };
  }, []);

  function updateState(patch) {
    setState(current => {
      const next = typeof patch === 'function' ? patch(current) : { ...current, ...patch };
      stateRef.current = next;
      writeOnboardingState(next);
      return next;
    });
  }

  const selectedMediaTypes = state.selectedMediaTypes;
  const enabledMediaTypes = MEDIA_TYPES.filter(mediaType => selectedMediaTypes.includes(mediaType.value));
  const walk = enabledMediaTypes.map(mediaType => mediaType.value);
  const metadataSuggestions = metadataSuggestionsFor(selectedMediaTypes, state.savedMetadata);
  const selectedSources = state.selectedSources.map(slug => SOURCE_BY_SLUG[slug]).filter(Boolean);
  const connectedSelectedSources = selectedSources.filter(source => state.connectedSources.includes(source.slug));
  const connectedSourceObjects = unique([...state.connectedSources, ...connectedSelectedSources.map(source => source.slug)])
    .map(slug => SOURCE_BY_SLUG[slug])
    .filter(Boolean);
  const walkIndex = walk.length ? Math.min(servicesIndex, walk.length - 1) : 0;
  const currentMediaTypeValue = walk[walkIndex];
  const currentMediaType = MEDIA_TYPE_BY_VALUE[currentMediaTypeValue];
  const candidates = currentMediaTypeValue
    ? SOURCE_CATALOG.filter(source => source.mediaTypes.includes(currentMediaTypeValue))
    : [];
  const remainingSources = selectedSources.filter(source => !state.skippedSources.includes(source.slug)
    && !state.connectedSources.includes(source.slug));
  const currentSource = currentSourceWithCopy(remainingSources[0] || null);
  const remainingIntegrations = selectedSources.filter(source => source.integrationTag
    && state.connectedSources.includes(source.slug)
    && !state.integrationConfigured.includes(source.slug)
    && !state.skippedIntegrations.includes(source.slug));
  const currentIntegration = remainingIntegrations[0] || null;
  const importStatusSources = connectedSelectedSources.map(source => ({
    source,
    run: state.importRuns[source.slug],
  }));

  useEffect(() => {
    if (!hydrated) return;
    if (state.step === 'metadata' && metadataSuggestions.length === 0) {
      updateState({ step: 'services', status: 'in_progress' });
      setServicesIndex(0);
      return;
    }
    if (state.step === 'services' && walk.length === 0) {
      updateState({ step: 'services_summary', status: 'in_progress' });
      return;
    }
    if (state.step === 'service_setup' && remainingSources.length === 0) {
      updateState({ step: 'integration_setup', status: 'in_progress' });
      return;
    }
    if (state.step === 'integration_setup' && remainingIntegrations.length === 0) {
      updateState({ step: 'import_status', status: 'in_progress' });
    }
  }, [hydrated, state.step, metadataSuggestions.length, walk.length, remainingSources.length, remainingIntegrations.length]);

  function finishSetup() {
    const next = { ...stateRef.current, status: 'completed', step: 'done' };
    stateRef.current = next;
    setState(next);
    writeOnboardingState(next);
    setError('');
    setNotice(null);
    setBusy('');
  }

  function handleSaveAndFinish() {
    const current = stateRef.current;
    const next = { ...current, status: current.status === 'completed' ? 'completed' : 'in_progress' };
    stateRef.current = next;
    setState(next);
    writeOnboardingState(next).finally(() => {
      if (onBack) onBack();
    });
  }

  function restartSetup() {
    setRestartOpen(false);
    setServicesIndex(0);
    setMetadataValues({});
    setConnectionValues({});
    setDevice({ started: false });
    setUploadNames({});
    setError('');
    updateState(current => ({ ...current, status: 'in_progress', step: 'media_types' }));
    setNotice({ tone: 'info', title: 'Guided setup restarted', text: 'Your existing media types and connected services are kept.' });
  }

  function toggleMediaType(value) {
    setError('');
    updateState(current => {
      const selected = new Set(current.selectedMediaTypes);
      if (selected.has(value)) {
        selected.delete(value);
      } else {
        selected.add(value);
      }
      return {
        ...current,
        selectedMediaTypes: MEDIA_TYPES.map(mediaType => mediaType.value).filter(mediaType => selected.has(mediaType)),
      };
    });
  }

  function continueFromMediaTypes() {
    if (!state.selectedMediaTypes.length) {
      setError('Choose at least one media type to continue.');
      return;
    }
    setError('');
    setNotice(null);
    const suggestions = metadataSuggestionsFor(state.selectedMediaTypes, state.savedMetadata);
    updateState({ step: suggestions.length ? 'metadata' : 'services', status: 'in_progress' });
    setServicesIndex(0);
  }

  function changeMetadataValue(key, value) {
    setMetadataValues(current => ({ ...current, [key]: value }));
    setError('');
  }

  function continueFromMetadata() {
    let failure = '';
    const saved = [];
    metadataSuggestions.forEach(suggestion => {
      const values = (suggestion.fields || []).map(field => String(metadataValues[`${suggestion.slug}-${field.name}`] || '').trim());
      if (!values.some(Boolean)) return;
      if (values.some(value => !value)) {
        failure = failure || `${suggestion.label}: fill in every field.`;
        return;
      }
      saved.push(suggestion.slug);
    });
    if (failure) {
      setError(failure);
      if (saved.length) {
        updateState(current => ({ ...current, savedMetadata: unique([...current.savedMetadata, ...saved]) }));
      }
      return;
    }
    setError('');
    setNotice(null);
    setMetadataValues({});
    setServicesIndex(0);
    updateState(current => ({
      ...current,
      savedMetadata: unique([...current.savedMetadata, ...saved]),
      step: 'services',
      status: 'in_progress',
    }));
  }

  function skipMetadata() {
    setError('');
    setNotice(null);
    setMetadataValues({});
    setServicesIndex(0);
    updateState({ step: 'services', status: 'in_progress' });
  }

  function toggleSource(slug) {
    updateState(current => {
      const selected = new Set(current.selectedSources);
      if (selected.has(slug)) {
        selected.delete(slug);
      } else {
        selected.add(slug);
      }
      return {
        ...current,
        selectedSources: SOURCE_CATALOG.map(source => source.slug).filter(sourceSlug => selected.has(sourceSlug)),
      };
    });
  }

  function nextServiceMediaType() {
    setError('');
    setNotice(null);
    if (servicesIndex + 1 < walk.length) {
      setServicesIndex(servicesIndex + 1);
      return;
    }
    updateState({ step: 'services_summary', status: 'in_progress' });
  }

  function startServiceSetup() {
    setError('');
    setNotice(null);
    setConnectionValues({});
    setDevice({ started: false });
    updateState({ step: 'service_setup', status: 'in_progress' });
  }

  function markSourceConnected(source, message) {
    const next = { ...stateRef.current };
    if (!next.connectedSources.includes(source.slug)) {
      next.connectedSources = unique([...next.connectedSources, source.slug]);
    }
    next.importRuns = { ...next.importRuns, [source.slug]: { status: 'running', error: '' } };
    stateRef.current = next;
    setState(next);
    writeOnboardingState(next);
    setBusy('');
    setError('');
    setNotice({ tone: 'success', title: 'Service connected', text: message });
    setConnectionValues({});
    setUploadNames(current => {
      const copy = { ...current };
      delete copy[source.slug];
      return copy;
    });
    setDevice({ started: false });
  }

  async function connectCurrentSource() {
    if (!currentSource || busy) return;
    setError('');
    setNotice(null);
    const variant = !currentSource.inlineSupported ? 'device'
      : currentSource.slug === 'trakt' ? 'trakt'
        : currentSource.isOauth ? 'oauth'
          : currentSource.uploadFieldName ? 'upload'
            : 'form';
    if (variant === 'form') {
      const missing = (currentSource.connectFields || []).some(field => !String(connectionValues[field.name] || '').trim());
      if (missing) {
        setError('Fill in every field to connect.');
        return;
      }
    }
    if (variant === 'trakt') {
      if (traktProfile === 'public' && !String(connectionValues.user || '').trim()) {
        setError('Enter your public Trakt username.');
        return;
      }
      if (traktProfile === 'private' && !traktConfigured) {
        setError('Private Trakt sign-in needs TRAKT_API configured. Use a data export instead.');
        return;
      }
    }
    if (variant === 'upload' || (variant === 'trakt' && traktProfile === 'csv')) {
      const extension = String(currentSource.uploadAccept || '.csv').includes('json') ? '.json' : '.csv';
      const fileName = `${currentSource.slug}-export${extension}`;
      setUploadNames(current => ({ ...current, [currentSource.slug]: fileName }));
    }
    setBusy('connect');
    if (variant === 'oauth' || variant === 'trakt') {
      await wait(650);
    } else {
      await wait(450);
    }
    markSourceConnected(currentSource, `${currentSource.name} is connected and an initial import is queued.`);
  }

  function skipCurrentSource() {
    if (!currentSource || busy) return;
    const source = currentSource;
    setConnectionValues({});
    setDevice({ started: false });
    setError('');
    updateState(current => ({ ...current, skippedSources: unique([...current.skippedSources, source.slug]) }));
    setNotice({ tone: 'info', title: 'Service skipped', text: `${source.name} will stay available in Settings > Import.` });
  }

  async function startDeviceLogin() {
    if (busy) return;
    if (!String(connectionValues.server_url || '').trim()) {
      setError('Storyteller server URL is required.');
      return;
    }
    setError('');
    setNotice(null);
    setBusy('device-start');
    await wait(500);
    setBusy('');
    setDevice({
      started: true,
      code: 'K7QP-2M4R',
      verificationUri: 'https://storyteller.example.com/activate',
      status: 'Waiting for approval…',
    });
  }

  async function checkDeviceLogin() {
    if (busy || !currentSource) return;
    setBusy('device-check');
    await wait(600);
    markSourceConnected(currentSource, 'Storyteller approved the device login and an initial import is queued.');
  }

  function openImportFallback() {
    setNotice({
      tone: 'info',
      title: 'Import setup fallback',
      text: 'This preview keeps the device login here. In the web app this opens the focused Import setup for this service.',
    });
  }

  function continueIntegration() {
    if (!currentIntegration || busy) return;
    const source = currentIntegration;
    setError('');
    updateState(current => ({ ...current, integrationConfigured: unique([...current.integrationConfigured, source.slug]) }));
    setNotice({ tone: 'success', title: 'Scrobbling ready', text: `${source.name} webhook activity is now recognised.` });
  }

  function skipIntegration() {
    if (!currentIntegration || busy) return;
    const source = currentIntegration;
    updateState(current => ({ ...current, skippedIntegrations: unique([...current.skippedIntegrations, source.slug]) }));
    setNotice({ tone: 'info', title: 'Scrobbling skipped', text: `${source.name} webhooks stay available in Settings > Providers.` });
  }

  async function refreshImportProgress() {
    if (busy) return;
    setBusy('refresh');
    await wait(550);
    const current = stateRef.current;
    const importRuns = { ...current.importRuns };
    const connected = selectedSources.filter(source => current.connectedSources.includes(source.slug));
    connected.forEach(source => {
      const run = importRuns[source.slug] || { status: 'queued' };
      if (run.status === 'queued') {
        importRuns[source.slug] = { ...run, status: 'running' };
      } else if (run.status === 'running') {
        importRuns[source.slug] = { ...run, status: 'completed' };
      }
    });
    const next = { ...current, importRuns };
    stateRef.current = next;
    setState(next);
    writeOnboardingState(next);
    setBusy('');
    setNotice({ tone: 'info', title: 'Import progress refreshed', text: 'Statuses come from the server import queue in the web app.' });
  }

  function openMetadataDocs(suggestion) {
    setNotice({
      tone: 'info',
      title: `${suggestion.label} key`,
      text: `Open ${suggestion.docsUrl} in a browser to create a key, then enter it here or in Settings > Providers.`,
    });
  }

  function openExternalLink(url, label) {
    setNotice({ tone: 'info', title: 'Open in a browser', text: `${label || url} opens in a browser on the web app.` });
  }

  async function copyWebhook() {
    setNotice({ tone: 'success', title: 'Copied', text: 'The demo webhook URL is ready to paste into Plex.' });
  }

  const traktConfigured = true;
  const plexWebhookCopy = {
    webhook: 'https://your-floppy.example.com/webhook/plex/…',
  };
  const plexGuide = currentIntegration?.integrationTag === 'plex' ? {
    bare: true,
    primary: { key: 'webhook', label: 'Webhook URL' },
    steps: [
      { parts: [['text', 'You will need a Plex Pass subscription to use webhooks.']] },
      { parts: [['text', 'In Plex, go to '], ['b', 'Settings > Server > Network'], ['text', ' and enable Webhooks.']] },
      { parts: [['text', 'Go to '], ['a', 'Settings > Webhooks', 'https://app.plex.tv/desktop/#!/settings/webhooks'], ['text', ' and click '], ['b', 'Add Webhook'], ['text', ', then enter the URL above.']] },
    ],
  } : null;

  const stepOrder = STEP_SLUGS;
  const activeIndex = stepOrder.indexOf(state.step);
  const completedSteps = state.status === 'completed' ? stepOrder : stepOrder.slice(0, Math.max(activeIndex, 0));
  const mediaTypeCount = enabledMediaTypes.length;

  let title = 'Onboarding';
  let explanation = '';
  let body = null;

  if (state.step === 'media_types') {
    title = 'What do you want to track?';
    explanation = 'Pick the kinds of media you want Floppy to track. This controls what shows up in your sidebar and search, and which services we will offer to connect next.\n\nYou can change this anytime from Settings, and nothing you skip here is lost.';
    body = <OnboardingMediaTypesStep
      options={MEDIA_TYPES}
      selected={state.selectedMediaTypes}
      onToggle={toggleMediaType}
      onContinue={continueFromMediaTypes}
      onSkip={finishSetup}
      error={error}
      busy={Boolean(busy)}
      palette={palette}
    />;
  } else if (state.step === 'metadata') {
    title = 'Better artwork and data';
    explanation = 'Floppy works without any of these. Each one fills a gap, like logos and backdrops for games, or a higher request limit.\n\nKeys stay private to your account. You can add or change them anytime in Settings > Providers.';
    body = <OnboardingMetadataStep
      suggestions={metadataSuggestions}
      values={metadataValues}
      onChange={changeMetadataValue}
      onSkip={skipMetadata}
      onContinue={continueFromMetadata}
      onOpenDocs={openMetadataDocs}
      error={error}
      busy={Boolean(busy)}
      palette={palette}
    />;
  } else if (state.step === 'services') {
    title = currentMediaType ? currentMediaType.label : 'Services';
    explanation = `Do you use any of these apps for ${currentMediaType ? currentMediaType.label.toLowerCase() : 'this media type'}?\n\nPick any that apply — we will walk you through connecting them next. Skip this if you do not use any.`;
    body = <OnboardingServicesStep
      mediaTypeLabel={currentMediaType ? currentMediaType.label : ''}
      stepNumber={walkIndex + 1}
      stepTotal={walk.length}
      candidates={candidates}
      selected={state.selectedSources}
      onToggle={toggleSource}
      onNext={nextServiceMediaType}
      isLast={walkIndex + 1 === walk.length}
      busy={Boolean(busy)}
      palette={palette}
    />;
  } else if (state.step === 'services_summary') {
    title = `Tracking ${mediaTypeCount} media ${mediaTypeCount === 1 ? 'type' : 'types'}`;
    explanation = 'Next we can walk you through connecting the services you picked, one at a time, and kick off an initial import.\n\nYou can always finish this later from Settings > Import.';
    body = <OnboardingSummaryStep
      mediaTypeCount={mediaTypeCount}
      selectedSources={selectedSources}
      connectedSources={state.connectedSources}
      onLater={finishSetup}
      onSetupNow={startServiceSetup}
      palette={palette}
    />;
  } else if (state.step === 'service_setup') {
    title = 'Connect your services';
    explanation = 'Connect right here — once it is done, you will automatically see the next one.\n\nDo not have it handy? Skip it — you can always connect it later from Settings > Import.';
    body = currentSource ? <OnboardingServiceSetupStep
      source={currentSource}
      remainingCount={remainingSources.length}
      values={connectionValues}
      onChange={(name, value) => {
        setConnectionValues(current => ({ ...current, [name]: value }));
        setError('');
      }}
      onConnect={connectCurrentSource}
      onSkip={skipCurrentSource}
      busy={Boolean(busy)}
      error={error}
      traktConfigured={traktConfigured}
      traktProfile={traktProfile}
      onTraktProfileChange={value => {
        setTraktProfile(value);
        setError('');
      }}
      uploadName={currentSource ? uploadNames[currentSource.slug] : ''}
      device={device}
      onStartDevice={startDeviceLogin}
      onCheckDevice={checkDeviceLogin}
      onOpenImport={openImportFallback}
      palette={palette}
    /> : null;
  } else if (state.step === 'integration_setup') {
    title = 'Turn on scrobbling';
    explanation = 'The import only covers what already happened. To keep tracking automatically going forward, the service also needs a webhook set up.\n\nThis depends on where your library lives, so it is a separate, optional step.';
    body = currentIntegration ? <OnboardingIntegrationStep
      source={currentIntegration}
      guide={plexGuide}
      copy={plexWebhookCopy}
      onCopy={copyWebhook}
      onOpenLink={openExternalLink}
      onSkip={skipIntegration}
      onContinue={continueIntegration}
      busy={Boolean(busy)}
      palette={palette}
    /> : null;
  } else if (state.step === 'import_status') {
    title = 'You’re all set';
    explanation = 'Your connected services are queued to import. This can take a few minutes depending on how much history they have.\n\nYou can check progress and history anytime from Settings > Import.';
    body = <OnboardingImportStatusStep
      sources={importStatusSources}
      onRefresh={refreshImportProgress}
      onContinue={finishSetup}
      refreshing={busy === 'refresh'}
      palette={palette}
    />;
  } else {
    title = 'Setup complete';
    explanation = 'Guided setup is complete. Resume it anytime from Settings.';
    body = <OnboardingCompleteStep
      mediaTypeCount={mediaTypeCount}
      connectedSources={connectedSourceObjects}
      onRestart={() => setRestartOpen(true)}
      palette={palette}
    />;
  }

  if (!hydrated) {
    return <Screen title="Onboarding" subtitle="First-run media, metadata, services and connection steps" onBack={onBack}>
      <Text style={styles.loading}>Loading setup…</Text>
    </Screen>;
  }

  return <Screen title="Onboarding" subtitle="First-run media, metadata, services and connection steps" onBack={onBack}>
    <OnboardingWizard
      steps={STEPS}
      activeStep={state.status === 'completed' ? '' : state.step}
      completedSteps={completedSteps}
      title={title}
      explanation={explanation}
      status={state.status}
      notice={notice}
      onSaveAndFinish={state.status === 'completed' ? undefined : handleSaveAndFinish}
      palette={palette}
    >
      {body}
    </OnboardingWizard>
    <ConfirmDialog
      visible={restartOpen}
      title="Restart guided setup?"
      message="This reopens the wizard from the media types step. Your existing media types, selected services and connections are kept."
      confirmLabel="Restart setup"
      cancelLabel="Keep setup"
      palette={palette}
      onCancel={() => setRestartOpen(false)}
      onConfirm={restartSetup}
    />
  </Screen>;
}

const styles = StyleSheet.create({
  loading: { color: palette.textMuted, fontSize: 13, paddingHorizontal: spacing.xs },
});
