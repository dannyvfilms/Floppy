import React, { useState } from 'react';
import { Linking } from 'react-native';
import { Screen } from '../components/Screen';
import { SettingsAboutView } from '../../../frontend/pages/SettingsAboutView';
import { SettingsAdvancedView } from '../../../frontend/pages/SettingsAdvancedView';
import { palette, radius } from '../theme';

export const surface = {
  id: 'SET-SYSTEM',
  title: 'Advanced and About',
  where: 'System, updates, logs, install and API links',
  status: 'ported',
  note: 'Shared cache, image, log, server-port and About cards render with realistic demo data. Cache/port writes, log download, release and update links, install guidance and API preview/download intents are represented; authenticated native transport and iOS/Android runtime remain unverified.',
};

const settingsPalette = {
  ...palette,
  badgeBorder: palette.surfaceMuted,
  badgeBackground: palette.surfaceStrong,
  badgeText: palette.textSecondary,
  badgeHover: palette.surfaceMuted,
  radius: radius.md,
};

const buttonPalette = {
  primary: { background: palette.accentStrong, pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: palette.surfaceStrong, pressed: palette.surfaceMuted, hovered: palette.surfaceMuted, text: palette.text, border: palette.border },
  'danger-solid': { background: palette.danger, pressed: '#b91c1c', hovered: '#b91c1c', text: '#ffffff', border: 'transparent' },
  'ghost-danger': { background: 'transparent', pressed: 'rgba(239, 68, 68, 0.18)', hovered: 'rgba(239, 68, 68, 0.18)', text: '#f87171', border: 'transparent' },
  radius: radius.sm,
  focusStyle: {},
};

const serverUrl = 'https://floppy.example.com';
const releasesUrl = 'https://github.com/dannyvfilms/Floppy/releases';
const releaseTag = 'v0.3.0';

const releases = [
  {
    tag: releaseTag,
    published: 'Nov 1, 2026',
    installed: true,
    newer: false,
    url: 'https://github.com/dannyvfilms/Floppy/releases',
    highlights: [
      { title: 'Faster History', text: 'Cached day groups now rebuild only when their data changes.' },
      { title: 'Calendar', text: 'Episode and chapter release dates use the same local date rules as the app.' },
      { title: 'Settings', text: 'Data, access and notification controls moved to shared components.' },
    ],
  },
  {
    tag: 'v0.2.0',
    published: 'Oct 12, 2026',
    installed: false,
    newer: false,
    url: 'https://github.com/dannyvfilms/Floppy/releases',
    highlights: [
      { title: 'Discover', text: 'Recommendation rows and taste profiles refresh independently.' },
      { title: 'Lists', text: 'Smart rules can compare progress, ratings and release windows.' },
    ],
  },
  {
    tag: 'v0.4.0-rc1',
    published: 'Nov 3, 2026',
    installed: false,
    newer: true,
    url: 'https://github.com/dannyvfilms/Floppy/releases',
    highlights: [
      { title: 'Native shell', text: 'Settings screens now exercise shared cards with realistic demo data.' },
    ],
  },
];

const resources = [
  { label: 'Project Website', description: 'Official documentation, guides, and live release announcements', url: 'https://dannyvfilms.github.io/floppy/' },
  { label: 'Source Code', description: 'GitHub repository, issue tracker, pull requests, and releases', url: 'https://github.com/dannyvfilms/Floppy' },
  { label: 'Documentation', description: 'Community wiki, container deployment, reverse proxy setup, and guides', url: 'https://github.com/dannyvfilms/Floppy/wiki' },
  { label: 'Bug Reports', description: 'Report bugs, submit sanitized logs, and request new features', url: 'https://github.com/dannyvfilms/Floppy/issues' },
  { label: 'Community Discord', description: 'Connect with other Floppy users, share setups, and help each other out', url: 'https://discord.gg/uFgha7Kb6n' },
  { label: 'Support Floppy', description: 'Floppy is free and open source, with no paid features. If it has earned a place in your routine, sponsoring helps it keep improving for everyone.', url: 'https://github.com/sponsors/dannyvfilms?metadata_source=app-about' },
];

const specs = [
  { label: 'API Reference', format: 'HTML Docs', description: 'Interactive index, tasks, authentication recipes, and curl cheat sheets', url: `${serverUrl}/api/docs/` },
  { label: 'Verified API Schema', format: 'OpenAPI 3.0.3 (YAML)', badge: 'YAML', previewTitle: 'Verified API Schema (OpenAPI 3.0.3)', downloadName: 'openapi.yaml', description: 'Reviewed subset for stable integrations and MCP grounding', url: `${serverUrl}/api/openapi.yaml` },
  { label: 'Domain Context (JSON-LD)', format: 'JSON-LD 1.1', badge: 'JSON-LD', previewTitle: 'Domain Context (JSON-LD 1.1)', downloadName: 'context.jsonld', description: 'Semantic RDF / schema.org vocabulary mapping for Floppy entities', url: `${serverUrl}/api/context.jsonld` },
  { label: 'Full Diagnostic API Schema', format: 'Live OpenAPI (YAML)', badge: 'Live', previewTitle: 'Full Diagnostic API Schema (Live OpenAPI)', downloadName: 'openapi-live.yaml', description: 'Dynamically generated schema covering all active routes on this instance', url: `${serverUrl}/api/schema/` },
  { label: 'Asynchronous Channels (AsyncAPI)', format: 'AsyncAPI 3.0.0 (JSON)', badge: 'AsyncAPI', previewTitle: 'Asynchronous Channels (AsyncAPI 3.0.0)', downloadName: 'asyncapi.json', description: 'Inbound webhook routes, Celery queues, and worker concurrency profiles', url: `${serverUrl}/api/asyncapi.json` },
];

const attributions = [
  { provider: 'The Movie Database (TMDB)', media: 'Movies, TV Shows, Seasons, Episodes & Cast/Crew Credits', url: 'https://www.themoviedb.org/' },
  { provider: 'IGDB', media: 'Video Games, Platforms, Developers & Publishers', url: 'https://www.igdb.com/' },
  { provider: 'MusicBrainz', media: 'Music Releases, Artists, Discographies & Tracklists', url: 'https://musicbrainz.org/' },
  { provider: 'Hardcover & Open Library', media: 'Books, Authors, Editions & Page Counts', url: 'https://hardcover.app/' },
  { provider: 'JustWatch', media: 'Streaming, Rent & Buy Availability Across Regions', url: 'https://www.justwatch.com/' },
  { provider: 'OpenSubtitles', media: 'Multilingual Subtitles Synchronization', url: 'https://www.opensubtitles.com/' },
  { provider: 'Pocket Casts', media: 'Podcast RSS Directories, Episode Feeds & Artwork', url: 'https://pocketcasts.com/' },
];

const licenses = [
  { subject: 'Floppy Application', terms: 'GNU Affero General Public License v3.0 (AGPL-3.0)', url: 'https://github.com/dannyvfilms/Floppy/blob/release/LICENSE' },
  { subject: 'Upstream Heritage', terms: 'Yamtrack (Original codebase fork; CSV exports supported)', url: 'https://github.com/FuzzyGrim/Yamtrack' },
];

function wait(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

export default function SettingsAdvancedScreen({ onBack, params }) {
  const [updateVisible, setUpdateVisible] = useState(true);
  const [logsBusy, setLogsBusy] = useState(false);
  const [logsSuccess, setLogsSuccess] = useState('');
  const [imageEnabled, setImageEnabled] = useState(true);
  const [imageBusy, setImageBusy] = useState(false);
  const [imageSuccess, setImageSuccess] = useState('');
  const [cacheBusyKind, setCacheBusyKind] = useState('');
  const [cacheSuccess, setCacheSuccess] = useState('');
  const [port, setPort] = useState({
    runtimePort: 8000,
    configuredPort: 8000,
    configuredSource: 'default',
    savedPort: null,
    defaultPort: 8000,
    savedFallbackUnreadable: false,
    environmentOverride: false,
    environmentName: 'FLOPPY_PORT',
    configError: '',
    configErrorSource: '',
    showReset: false,
  });
  const [portBusy, setPortBusy] = useState(false);
  const [portSuccess, setPortSuccess] = useState('');
  const [installBusy, setInstallBusy] = useState(false);
  const [installStatus, setInstallStatus] = useState('');

  const openUrl = url => {
    if (url) Linking.openURL(url).catch(() => {});
  };

  async function downloadLogs() {
    setLogsBusy(true);
    setLogsSuccess('');
    await wait(450);
    setLogsBusy(false);
    setLogsSuccess('Sanitized logs prepared. The server sends the redacted file.');
  }

  async function saveImageCache(enabled) {
    setImageBusy(true);
    setImageSuccess('');
    await wait(400);
    setImageEnabled(enabled);
    setImageBusy(false);
    setImageSuccess(`External image caching ${enabled ? 'enabled' : 'disabled'}.`);
  }

  async function clearImageCache() {
    setImageBusy(true);
    setImageSuccess('');
    await wait(500);
    setImageBusy(false);
    setImageSuccess('Cleared 1,284 cached images (412 MB).');
  }

  async function clearCache(kind) {
    setCacheBusyKind(kind);
    setCacheSuccess('');
    await wait(450);
    setCacheBusyKind('');
    setCacheSuccess(kind === 'all'
      ? 'All caches cleared. History and Discover rebuild as you browse; Statistics rebuilds in the background.'
      : `${kind.charAt(0).toUpperCase()}${kind.slice(1)} cache cleared.`);
  }

  async function savePort(value) {
    setPortBusy(true);
    setPortSuccess('');
    await wait(400);
    setPort(current => ({ ...current, savedPort: value, configuredPort: value, configuredSource: 'saved', showReset: true }));
    setPortBusy(false);
    setPortSuccess(`Server port ${value} saved. Update the container target to ${value}, then restart Floppy.`);
  }

  async function resetPort() {
    setPortBusy(true);
    setPortSuccess('');
    await wait(350);
    setPort(current => ({ ...current, savedPort: null, configuredPort: current.defaultPort, configuredSource: 'default', showReset: false }));
    setPortBusy(false);
    setPortSuccess('Saved server port removed. Floppy falls back to 8000 on the next restart.');
  }

  async function install() {
    setInstallBusy(true);
    setInstallStatus('');
    await wait(400);
    setInstallBusy(false);
    setInstallStatus('Installing Floppy. Look for it alongside your other apps.');
  }

  const page = params?.page === 'about' ? 'about' : 'advanced';
  return <Screen onBack={onBack}>
    {page === 'advanced' ? <SettingsAdvancedView
      logs={{
        isSuperuser: true, logsSince: 'Oct 2, 2026 13:39', lastUncleanExit: 'Oct 28, 2026 22:14',
        bugReportUrl: 'https://github.com/dannyvfilms/Floppy/issues/new?title=%5BBUG%5D%20',
        busy: logsBusy, success: logsSuccess,
        onDownloadLogs: downloadLogs, onOpenUrl: openUrl,
      }}
      imageCache={{
        isSuperuser: true, enabled: imageEnabled, count: 1284, size: '412 MB',
        busy: imageBusy, success: imageSuccess,
        onSave: saveImageCache, onClear: clearImageCache,
      }}
      cacheManagement={{
        busyKind: cacheBusyKind, success: cacheSuccess, onClear: clearCache,
      }}
      serverPort={{
        canManage: true, ...port, busy: portBusy, success: portSuccess,
        onSave: savePort, onReset: resetPort,
      }}
      palette={settingsPalette} buttonPalette={buttonPalette} />
      : <SettingsAboutView
        banner={updateVisible ? {
          releaseTag,
          onDismiss: () => setUpdateVisible(false),
          onViewWhatsNew: () => {
            setUpdateVisible(false);
            openUrl(releasesUrl);
          },
        } : null}
        overview={{ onOpenUrl: openUrl }}
        whatsNew={{ releases, releasesUrl, onOpenUrl: openUrl }}
        install={{
          installAvailable: false, installBusy, installStatus,
          onInstall: install, onOpenUrl: openUrl,
        }}
        resources={{ resources, onOpenUrl: openUrl }}
        specs={{
          specs, onOpenUrl: openUrl,
          onPreview: spec => openUrl(spec.url),
          onDownload: spec => openUrl(`${spec.url}${spec.url.includes('?') ? '&' : '?'}download=1`),
        }}
        attributions={{ attributions, onOpenUrl: openUrl }}
        licenses={{ licenses, onOpenUrl: openUrl }}
        version={{ version: 'v0.3.0', commit: 'a1b2c3d' }}
        palette={settingsPalette} buttonPalette={buttonPalette} />}
  </Screen>;
}
