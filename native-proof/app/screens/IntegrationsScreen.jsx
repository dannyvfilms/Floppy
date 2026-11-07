import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Screen } from '../components/Screen';
import {
  ArrLibraryPanels,
  SeerrRequestDialog,
} from '../../../frontend/ui/IntegrationPanels';
import { palette, spacing } from '../theme';

export const surface = {
  id: 'INTEGRATION-PANELS',
  status: 'ported',
  title: 'Library and request panels',
  where: 'Detail Arr/Seerr status and request actions',
  note: 'Arr library availability, download queue, activity, per-instance errors and copy feedback plus Seerr request state, per-season controls and request dialog use shared React Native cards, badges, buttons and dialogs. The web detail pages keep the server-rendered htmx panels, permissions and progressive fallback; credential, transport and system-browser handoff remain adapters.',
};

const SHOW_PANELS = [
  {
    app: 'Sonarr',
    name: 'Main',
    instance_id: 'sonarr-main-show',
    status: 'has_file',
    monitored: true,
    summary: [9, 10],
    path: '/data/tv/Severance',
    quality: 'WEBDL-1080p',
    size: 32_000_000_000,
    added: '2026-09-29T08:12:00Z',
    queue: [],
    history: [
      { when: '2026-09-29T08:12:00Z', label: 'Imported', tone: 'ok', quality: 'WEBDL-1080p', detail: 'SABnzbd' },
      { when: '2026-09-28T22:00:00Z', label: 'Grabbed', tone: 'info', quality: 'WEBDL-1080p', detail: 'NZBGeek' },
      { when: '2026-09-27T19:30:00Z', label: 'Failed', tone: 'bad', quality: '', detail: 'No space left' },
    ],
    search: { kind: 'series', arr_id: 5 },
  },
  {
    app: 'Sonarr',
    name: '4K',
    instance_id: 'sonarr-4k-show',
    status: 'downloading',
    monitored: true,
    summary: [7, 10],
    path: '/data/tv-4k/Severance',
    quality: 'Bluray-2160p',
    size: 96_000_000_000,
    added: '2026-09-20T11:15:00Z',
    queue: [
      { title: 'Severance.S02E03.2160p.WEB-DL', percent: 72, timeleft: '00:12:18' },
    ],
    history: [
      { when: '2026-09-29T10:02:00Z', label: 'Grabbed', tone: 'info', quality: 'Bluray-2160p', detail: 'NZBGeek' },
    ],
    search: { kind: 'series', arr_id: 9 },
  },
  {
    app: 'Sonarr',
    name: 'Archive',
    instance_id: 'sonarr-archive-show',
    status: 'missing',
    error: 'Sonarr rejected the API key.',
    monitored: false,
    queue: [],
    history: [],
    search: null,
  },
];

const SHOW_REQUESTS = [
  { by: 'Sam', when: '2026-09-22T10:00:00Z', status: 'Approved' },
  { by: 'maya', when: '2026-09-20T10:00:00Z', status: 'Pending approval' },
];

const SEASON_PANELS = [
  {
    app: 'Sonarr',
    name: 'Main',
    instance_id: 'sonarr-main-season-2',
    status: 'downloading',
    monitored: true,
    summary: [6, 8],
    path: '/data/tv/Severance/Season 2',
    quality: 'WEBDL-1080p',
    size: 18_000_000_000,
    added: '2026-09-29T08:12:00Z',
    queue: [
      { title: 'Severance.S02E02.1080p.WEB-DL', percent: 48, timeleft: '00:21:05' },
    ],
    history: [
      { when: '2026-09-29T08:12:00Z', label: 'Imported', tone: 'ok', quality: 'WEBDL-1080p', detail: 'SABnzbd' },
    ],
    search: { kind: 'season', arr_id: 5, season: 2 },
  },
];

const EPISODE_PANELS = [
  {
    app: 'Sonarr',
    name: 'Main',
    instance_id: 'sonarr-main-s02e02',
    status: 'missing',
    monitored: true,
    queue: [],
    history: [
      { when: '2026-09-28T08:00:00Z', label: 'Failed', tone: 'bad', quality: '', detail: 'Download stalled' },
    ],
    search: { kind: 'episode', arr_id: 102 },
  },
];

const INITIAL_SEASON_SUMMARY = {
  status: 'partially_available',
  requestable: true,
  seasons: [
    { number: 1, name: 'Season 1', status: 'available', requestable: false },
    { number: 2, name: 'Season 2', status: 'unknown', requestable: true },
    { number: 3, name: 'Season 3', status: 'unknown', requestable: true },
  ],
};

function Context({ title, meta, children }) {
  return <View style={styles.context}>
    <View style={styles.contextHeading}>
      <Text role="heading" aria-level={2} style={styles.contextTitle}>{title}</Text>
      {meta ? <Text style={styles.contextMeta}>{meta}</Text> : null}
    </View>
    {children}
  </View>;
}

function markRequested(summary, numbers) {
  const seasons = summary.seasons.map(season => numbers.includes(season.number)
    ? { ...season, status: 'pending', requestable: false }
    : season);
  return { ...summary, seasons, requestable: seasons.some(season => season.requestable) };
}

export default function IntegrationsScreen({ onBack }) {
  const [requestOpen, setRequestOpen] = useState(false);
  const [summary, setSummary] = useState(INITIAL_SEASON_SUMMARY);
  const [busySeason, setBusySeason] = useState(null);
  const [busyAll, setBusyAll] = useState(false);
  const [searchFeedback, setSearchFeedback] = useState({ context: '', message: '', error: '' });
  const [notice, setNotice] = useState('');

  function search(panel, context) {
    setSearchFeedback({ context, message: `Search started in ${panel.app}.`, error: '' });
  }

  function requestSeason(number) {
    if (busyAll || busySeason !== null) return;
    setBusySeason(number);
    setTimeout(() => {
      setSummary(current => markRequested(current, [number]));
      setBusySeason(null);
    }, 450);
  }

  function requestAll() {
    if (busyAll || busySeason !== null) return;
    setBusyAll(true);
    setTimeout(() => {
      setSummary(current => markRequested(
        current,
        current.seasons.filter(season => season.requestable).map(season => season.number),
      ));
      setBusyAll(false);
    }, 600);
  }

  function messageFor(context) {
    return searchFeedback.context === context ? searchFeedback.message : '';
  }

  return <Screen title="Library" subtitle="Library and request panels" onBack={onBack}>
    <View style={styles.media}>
      <Text style={styles.eyebrow}>TV SHOW · TMDB 95396</Text>
      <Text role="heading" aria-level={1} style={styles.mediaTitle}>Severance</Text>
      <Text style={styles.mediaMeta}>2022 · Drama, Mystery · 10 episodes</Text>
    </View>

    <Context title="Show" meta="Severance · all seasons">
      <ArrLibraryPanels panels={SHOW_PANELS} seerrRequests={SHOW_REQUESTS}
        message={messageFor('show')} palette={palette}
        onSearch={panel => search(panel, 'show')} onCopy={() => {}}
        onOpenRequest={() => setRequestOpen(true)} />
    </Context>

    <Context title="Season 2" meta="8 aired episodes · 6 have files">
      <ArrLibraryPanels panels={SEASON_PANELS} message={messageFor('season')}
        palette={palette} onSearch={panel => search(panel, 'season')} onCopy={() => {}} />
    </Context>

    <Context title="S02E02 · The Outer Ring" meta="Episode 2 · aired Sep 30, 2026">
      <ArrLibraryPanels panels={EPISODE_PANELS} message={messageFor('episode')}
        palette={palette} onSearch={panel => search(panel, 'episode')} onCopy={() => {}} />
    </Context>

    {notice ? <Text accessibilityLiveRegion="polite" style={styles.notice}>{notice}</Text> : null}

    <SeerrRequestDialog open={requestOpen} summary={summary} palette={palette}
      busy={busyAll} busySeason={busySeason}
      onRequestSeason={requestSeason} onRequestAll={requestAll}
      onOpenSeerr={() => { setRequestOpen(false); setNotice('Opened Seerr for Severance.'); }}
      onClose={() => setRequestOpen(false)} />
  </Screen>;
}

const styles = StyleSheet.create({
  media: { gap: 2, paddingBottom: spacing.sm },
  eyebrow: { color: palette.textMuted, fontSize: 11, fontWeight: '700', letterSpacing: 0.8 },
  mediaTitle: { color: palette.text, fontSize: 24, fontWeight: '700' },
  mediaMeta: { color: palette.textSecondary, fontSize: 13 },
  context: { gap: spacing.sm },
  contextHeading: { gap: 1 },
  contextTitle: { color: palette.text, fontSize: 17, fontWeight: '600' },
  contextMeta: { color: palette.textMuted, fontSize: 12 },
  notice: { color: palette.textMuted, fontSize: 12 },
});
