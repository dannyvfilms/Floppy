import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { SettingsCard } from '../settings/SettingsCard';
import { Button } from '../ui/Button';
import { Tabs } from '../ui/controls/Navigation';
import { Dialog } from '../ui/controls/Dialog';
import { TextField } from '../ui/TextField';
import { SelectField } from '../ui/SelectField';
import { MetadataMatchResults } from '../ui/MetadataReview';

function MappingDialog({ mapping, actions, onAction, onSearch, onEpisodes, onClose, onSaved, palette, buttonPalette }) {
  const [query, setQuery] = useState(mapping.entry.title || '');
  const [results, setResults] = useState([]);
  const [selected, setSelected] = useState(null);
  const [episodes, setEpisodes] = useState([]);
  const [episode, setEpisode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function run(action) {
    setBusy(true); setError('');
    try { await action(); } catch (reason) { setError(reason?.message || 'The request failed. Try again.'); }
    finally { setBusy(false); }
  }
  return <Dialog open title="Fix mapping" onClose={onClose} palette={palette}>
    <View style={styles.stack}>
      <Text style={[styles.strong, { color: palette.text }]}>{mapping.entry.title}</Text>
      {!selected ? <>
        <TextField label="Search MyAnimeList" value={query} onChangeText={setQuery} palette={palette} />
        <Button label="Search" disabled={busy || query.trim().length < 3} busy={busy} palette={buttonPalette}
          onPress={() => run(async () => setResults((await onSearch(query)).results || []))} />
        <MetadataMatchResults model={{ results: results.map(row => ({ id: String(row.media_id), title: row.title,
          image: row.image, meta: row.year ? `${row.year} · MAL ${row.media_id}` : `MAL ${row.media_id}`, actionLabel: 'Select' })) }}
          palette={palette} onChoose={row => run(async () => {
            const data = await onEpisodes(row.id);
            const span = mapping.scope === 'season' ? Math.max(...mapping.season.episodes) - Math.min(...mapping.season.episodes) + 1 : 1;
            const choices = (data.episodes || []).slice(0, Math.max(0, (data.episodes || []).length - span + 1));
            setSelected(row); setEpisodes(choices); setEpisode(String(choices[0] || ''));
          })} />
      </> : <>
        <Text style={[styles.strong, { color: palette.text }]}>{selected.title}</Text>
        <SelectField label={mapping.scope === 'season' ? 'First MAL episode' : 'MAL episode'} value={episode}
          options={episodes.map(value => ({ value: String(value), label: `Episode ${value}` }))}
          placeholder="Select an episode" onChange={event => setEpisode(event.target.value)} palette={palette} />
        {!episodes.length ? <Text style={[styles.copy, { color: palette.warning }]}>MyAnimeList does not report an episode count for this title, so it cannot be selected for episode mapping.</Text> : null}
        {mapping.scope === 'season' ? <Text style={[styles.copy, { color: palette.textMuted }]}>Episodes are mapped sequentially from the selected first MAL episode.</Text> : null}
        <View style={styles.actions}>
          <Button label="Back" tone="surface" palette={buttonPalette} disabled={busy} onPress={() => setSelected(null)} />
          <Button label="Save mapping" palette={buttonPalette} disabled={busy || !episode} busy={busy}
            onPress={() => run(async () => {
              await onAction(actions.mal_episode_mapping_save, { item_id: mapping.entry.item_id,
                season: mapping.season.season, episode: mapping.episode, scope: mapping.scope,
                mal_id: selected.id, mal_episode: episode });
              onClose();
              onSaved?.();
            })} />
        </View>
      </>}
      {error ? <Text accessibilityRole="alert" style={[styles.copy, { color: palette.danger }]}>{error}</Text> : null}
    </View>
  </Dialog>;
}

function TrackerActivity({ data, onAction, onRefreshMappings, onMappingSearch, onMappingEpisodes, palette, buttonPalette }) {
  const [tab, setTab] = useState('sync');
  const [previewIssues, setPreviewIssues] = useState(null);
  const [mapping, setMapping] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState({});
  const mal = data.mal || {};
  const actions = data.actions || {};
  const report = mal.report;
  const issues = previewIssues || report?.mapping_issues || [];
  const results = (report?.results || []).filter(row => row.outcome !== 'skipped');
  const tabs = [
    { key: 'sync', label: 'Sync' }, { key: 'mapping', label: `Mapping Issues (${issues.length})` },
    { key: 'manual', label: `Manual Mappings (${(mal.manual || []).length})` }, { key: 'ignored', label: `Ignored (${(mal.ignored || []).length})` },
  ];
  async function run(action) {
    if (busy) return;
    setBusy(true); setError('');
    try { await action(); } catch (reason) { setError(reason?.message || 'The request failed. Try again.'); }
    finally { setBusy(false); }
  }
  return <View style={styles.stack}>
    <Text role="heading" aria-level={3} style={[styles.sectionTitle, { color: palette.text }]}>MyAnimeList sync and mapping activity</Text>
    <Tabs label="MyAnimeList sync" selected={tab} onSelect={setTab} palette={palette} items={tabs} />
    <View role="tabpanel" accessibilityLabel={tabs.find(item => item.key === tab)?.label} style={styles.stack}>
    {tab === 'sync' ? <SettingsCard title="Recent MyAnimeList sync" headingLevel={2} palette={palette}>
      {report && report.status !== 'idle' ? <View style={styles.stack}>
        <Text style={[styles.strong, { color: palette.text }]}>Full sync status · {report.status_label}</Text>
        {report.is_active ? <View style={styles.stack}>
          <View accessibilityRole="progressbar" accessibilityLabel="Full sync status"
            accessibilityValue={{ min: 0, max: report.total || 0, now: report.processed || 0 }}
            style={{ height: 8, backgroundColor: palette.surfaceStrong, borderRadius: palette.radius, overflow: 'hidden' }}>
            <View style={{ height: 8, backgroundColor: palette.accent,
              width: `${report.total ? Math.max(0, Math.min(100, report.processed / report.total * 100)) : 0}%` }} />
          </View>
          <Text style={[styles.copy, { color: palette.textMuted }]}>{report.total ? `${report.processed} / ${report.total}` : 'Preparing sync...'}</Text>
        </View> : null}
        {report.processed ? <Text style={[styles.copy, { color: palette.textSecondary }]}>{report.succeeded || 0} succeeded, {report.failed || 0} failed</Text> : null}
        {!report.is_active && report.retryable > 0 ? <Button label="Retry failed" tone="surface" disabled={busy} busy={busy}
          onPress={() => run(() => onAction(actions.mal_full_sync_retry_failed, {}))} palette={buttonPalette} /> : null}
        <Text style={[styles.copy, { color: palette.textMuted }]}>{results.length} results</Text>
        {results.map((row, index) => <View key={index} style={styles.stack}>
          <Text style={[styles.strong, { color: row.outcome === 'succeeded' ? palette.success : palette.danger }]}>{row.title}</Text>
          {row.reason ? <Text style={[styles.copy, { color: palette.textMuted }]}>{row.reason}</Text> : null}
        </View>)}
      </View> : null}
    </SettingsCard> : null}
    {tab === 'mapping' ? <View style={styles.stack}>
      <Text role="heading" aria-level={2} style={[styles.sectionTitle, { color: palette.text }]}>Anime with mapping issues</Text>
      {mal.connected && mal.sync_enabled ? <Button label="Refresh" tone="surface" busy={busy} disabled={busy}
        onPress={() => run(async () => setPreviewIssues(await onRefreshMappings()))} palette={buttonPalette} /> : null}
      {!issues.length ? <Text style={[styles.copy, { color: palette.textMuted }]}>No mapping issues reported.</Text> : null}
      {issues.map((entry, index) => <View key={entry.item_id || index} style={styles.stack}>
        <Text style={[styles.strong, { color: palette.text }]}>{entry.title}</Text>
        <Button label="Ignore" tone="surface" disabled={busy} palette={buttonPalette}
          onPress={() => run(async () => { await onAction(actions.mal_mapping_ignore, { item_id: entry.item_id, ignored: true }); setPreviewIssues(current => (current || issues).filter(row => row.item_id !== entry.item_id)); })} />
        <Text style={[styles.copy, { color: palette.warning }]}>{entry.reason}</Text>
        {(entry.seasons || []).map(season => <View key={season.season} style={styles.stack}>
          <Text style={[styles.copy, { color: palette.text }]}>Season {season.season}</Text>
          {season.all_unmapped ? <Button label="Fix whole season" disabled={busy} palette={buttonPalette}
            onPress={() => setMapping({ entry, season, episode: season.episodes[0], scope: 'season' })} /> : null}
          <View style={styles.actions}>{(season.episodes || []).map(episode => <Button key={episode} label={`E${String(episode).padStart(2, '0')} Fix mapping`}
            tone="surface" disabled={busy} palette={buttonPalette} onPress={() => setMapping({ entry, season, episode, scope: 'episode' })} />)}</View>
        </View>)}
      </View>)}
    </View> : null}
    {tab === 'manual' ? <View style={styles.stack}>
      <Text role="heading" aria-level={2} style={[styles.sectionTitle, { color: palette.text }]}>Manual episode mappings</Text>
      {!(mal.manual || []).length ? <Text style={[styles.copy, { color: palette.textMuted }]}>No manual mappings have been saved.</Text> : null}
      {(mal.manual || []).map(entry => <View key={entry.key} style={styles.stack}>
        <Text style={[styles.strong, { color: palette.text }]}>{entry.title}</Text>
        <Text style={[styles.copy, { color: palette.textMuted }]}>{`S${entry.season} E${entry.episodes.join(', ')} → MAL ${entry.mal_id} E${entry.mal_episodes.join(', ')}`}</Text>
        <Button label="Revert" tone="surface" disabled={busy} palette={buttonPalette}
          onPress={() => run(() => onAction(actions.mal_episode_mapping_revert, { reference_id: entry.reference_ids }))} />
      </View>)}
    </View> : null}
    {tab === 'ignored' ? <View style={styles.stack}>
      <Text role="heading" aria-level={2} style={[styles.sectionTitle, { color: palette.text }]}>Ignored anime</Text>
      {!(mal.ignored || []).length ? <Text style={[styles.copy, { color: palette.textMuted }]}>No anime has been ignored.</Text> : null}
      {(mal.ignored || []).map(entry => <View key={entry.item_id} style={styles.stack}>
        <Text style={[styles.strong, { color: palette.text }]}>{entry.title}</Text>
        <Button label="Move back" disabled={busy} palette={buttonPalette}
          onPress={() => run(() => onAction(actions.mal_mapping_ignore, { item_id: entry.item_id, ignored: false }))} />
      </View>)}
    </View> : null}
    </View>
    {error ? <Text accessibilityRole="alert" style={[styles.copy, { color: palette.danger }]}>{error}</Text> : null}
    {(data.services || []).map(service => <SettingsCard key={service.slug} title={service.slug === 'tmdb' ? 'TMDB' : 'WeTrakr'}
      badge={service.state === 'connected' ? 'Connected' : service.state === 'attention' ? 'Needs attention' : service.state === 'waiting' ? 'Waiting for approval' : 'Not connected'} palette={palette}>
      <Text style={[styles.copy, { color: palette.textMuted }]}>{service.slug === 'tmdb'
        ? 'Send your movie, show and episode ratings to your TMDb account. Season ratings stay in Floppy.'
        : 'Send the movies and episodes you watch, your statuses and your ratings to WeTrakr. Each play keeps the date you watched it. Imports are never sent on their own.'}</Text>
      {service.slug === 'tmdb' ? <Text style={[styles.copy, { color: palette.textMuted }]}>Scores are rounded to the nearest half-point (minimum 0.5). Your Floppy score is unchanged. Clearing a rating removes it from TMDb. TMDb may remove rated titles from its watchlist, depending on your TMDb account settings.</Text> : null}
      <Text role="heading" aria-level={4} style={[styles.strong, { color: palette.text }]}>Activity</Text>
      <View style={styles.actions}>{[['pending', 'Waiting'], ['in_flight', 'Sending'], ['delivered', 'Sent'], ['failed', 'Failed'], ['skipped', 'Skipped']].map(([key, label]) =>
        <Text key={key} style={[styles.copy, { color: service.counts?.failed && key === 'failed' ? palette.warning : palette.textMuted }]}>{label} {service.counts?.[key] || 0}</Text>)}</View>
      {service.last_sent_label ? <Text style={[styles.copy, { color: palette.textMuted }]}>Last sent: {service.last_sent_label}</Text> : null}
      {service.recent?.length ? <>
        <Button label="Recent results" tone="surface" palette={buttonPalette} onPress={() => setExpanded(current => ({ ...current, [service.slug]: !current[service.slug] }))} />
        {expanded[service.slug] ? service.recent.map(row => <Text key={row.id} style={[styles.copy, { color: palette.textMuted }]}>{row.title}{row.operation ? ` (${row.operation})` : ''}: {row.status}{row.error ? ` (${row.error})` : ''}</Text>) : null}
      </> : null}
    </SettingsCard>)}
    {mapping ? <MappingDialog mapping={mapping} actions={actions} onAction={onAction} onSearch={onMappingSearch}
      onEpisodes={onMappingEpisodes} onClose={() => setMapping(null)}
      onSaved={() => run(async () => setPreviewIssues(await onRefreshMappings()))}
      palette={palette} buttonPalette={buttonPalette} /> : null}
  </View>;
}

export const activityCopy = {
  title: 'Activity',
  periodicTitle: 'Active Periodic Imports',
  periodicCopy: 'Automated imports that run on a schedule. These will continue to sync your media until disabled.',
  periodicEmpty: 'No periodic imports configured',
  periodicEmptyHint: 'Enable a recurring import or Plex watchlist sync to see it here',
  historyTitle: 'Import History',
  historyCopy: 'Showing import activity from the last 7 days.',
  historyEmpty: 'No imports in the last 7 days',
  historyEmptyHint: 'Import your media from any source to see the history here',
  username: 'Username',
  mode: 'Mode',
  lastImport: 'Last Import',
  nextImport: 'Next Import',
  syncTitle: 'Sync and mapping activity',
  syncCopy: 'Watched-state sync between your media servers, and titles that were not safe to match automatically.',
  connections: 'Connections',
  review: 'Matching review',
};

const STATUS = {
  SUCCESS: 'Success', STARTED: 'Started', FAILURE: 'Failed', REVOKED: 'Cancelled',
};

function Block({ children, palette }) {
  return <View style={[styles.block, { backgroundColor: palette.surfaceStrong, borderRadius: palette.radius ?? 8 }]}>{children}</View>;
}

/** Settings > Activity: periodic imports, import history and sync/mapping entry points. Props only. */
export function SettingsActivityView({
  schedules = [], results = [], formatDate = value => value, onOpenConnections, onOpenReview,
  labels = {}, palette = {}, buttonPalette = {},
  importsContent,
  trackerActivity,
  onTrackerAction,
  onRefreshMappings,
  onMappingSearch,
  onMappingEpisodes,
}) {
  const copy = { ...activityCopy, ...labels };
  const color = status => (status === 'SUCCESS' ? palette.success : status === 'FAILURE' ? palette.danger
    : status === 'REVOKED' ? palette.textMuted : palette.warning);
  return <View style={[styles.stack, palette.pageCards && { gap: 24 }]}>
    <Text role="heading" aria-level={2} style={[styles.title, { color: palette.text }]}>{copy.title}</Text>
    {importsContent || <><SettingsCard title={copy.periodicTitle} palette={palette}>
      <Text style={[styles.copy, { color: palette.textMuted }]}>{copy.periodicCopy}</Text>
      {schedules.length ? schedules.map((entry, index) => <Block key={`${entry.source}-${index}`} palette={palette}>
        <View style={styles.line}>
          <Text style={[styles.strong, { color: palette.text }]}>{entry.source}</Text>
          <Text style={[styles.copy, { color: palette.textMuted }]}>{entry.schedule}</Text>
        </View>
        {entry.username ? <Text style={[styles.copy, { color: palette.textMuted }]}>{`${copy.username}: ${entry.username}`}</Text> : null}
        <Text style={[styles.copy, { color: palette.textMuted }]}>{`${copy.mode}: ${entry.mode}`}</Text>
        <Text style={[styles.copy, { color: palette.textMuted }]}>{`${copy.lastImport}: ${formatDate(entry.last_run)}`}</Text>
        <Text style={[styles.copy, { color: palette.textMuted }]}>{`${copy.nextImport}: ${formatDate(entry.next_run)}`}</Text>
      </Block>) : <Block palette={palette}>
        <Text style={[styles.center, { color: palette.textMuted }]}>{copy.periodicEmpty}</Text>
        <Text style={[styles.hint, { color: palette.textMuted }]}>{copy.periodicEmptyHint}</Text>
      </Block>}
    </SettingsCard>
    <SettingsCard title={copy.historyTitle} palette={palette}>
      <Text style={[styles.copy, { color: palette.textMuted }]}>{copy.historyCopy}</Text>
      {results.length ? results.map((entry, index) => <Block key={`${entry.source}-${entry.date}-${index}`} palette={palette}>
        <View style={styles.line}>
          <Text style={[styles.strong, { color: color(entry.status) }]}>
            {entry.status === 'SUCCESS' && entry.errors ? 'Finished' : (STATUS[entry.status] || 'Pending')}
          </Text>
          <Text style={[styles.strong, { color: palette.text }]}>{entry.source}</Text>
          <Text style={[styles.copy, { color: palette.textMuted }]}>{formatDate(entry.date)}</Text>
        </View>
        {entry.summary ? <Text style={[styles.copy, { color: palette.textSecondary }]}>{entry.summary}</Text> : null}
      </Block>) : <Block palette={palette}>
        <Text style={[styles.center, { color: palette.textMuted }]}>{copy.historyEmpty}</Text>
        <Text style={[styles.hint, { color: palette.textMuted }]}>{copy.historyEmptyHint}</Text>
      </Block>}
    </SettingsCard>
    </>}
    {trackerActivity ? <TrackerActivity data={trackerActivity} onAction={onTrackerAction} onRefreshMappings={onRefreshMappings}
      onMappingSearch={onMappingSearch} onMappingEpisodes={onMappingEpisodes} palette={palette} buttonPalette={buttonPalette} />
      : <SettingsCard title={copy.syncTitle} palette={palette}>
      <Text style={[styles.copy, { color: palette.textMuted }]}>{copy.syncCopy}</Text>
      <View style={styles.actions}>
        <Button label={copy.connections} tone="surface" onPress={onOpenConnections} palette={buttonPalette} />
        <Button label={copy.review} tone="surface" onPress={onOpenReview} palette={buttonPalette} />
      </View>
    </SettingsCard>}
  </View>;
}

const styles = StyleSheet.create({
  stack: { gap: 16 },
  title: { fontSize: 20, fontWeight: '600' },
  sectionTitle: { fontSize: 18, lineHeight: 28, fontWeight: '600' },
  block: { padding: 12, gap: 4 },
  line: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 },
  strong: { fontSize: 14, fontWeight: '600' },
  copy: { fontSize: 13, lineHeight: 19 },
  center: { fontSize: 14, textAlign: 'center' },
  hint: { fontSize: 12, textAlign: 'center' },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
});
