import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { SettingsCard } from '../settings/SettingsCard';
import { Button } from '../ui/Button';
import { MetadataMatchResults } from '../ui/MetadataReview';
import { SelectField } from '../ui/SelectField';
import { TextField } from '../ui/TextField';

export const metadataReviewCopy = {
  title: 'Matching review',
  copy: 'These provider identities were not safe to match automatically.',
  savedTitle: 'Saved match decisions',
  savedCopy: 'These decisions are applied to future Plex and Trakt imports.',
  empty: 'Nothing needs a match decision.',
  fix: 'Fix match',
  edit: 'Edit',
  ignore: 'Ignore',
  remove: 'Remove',
  fixTitle: 'Fix match',
  fixIntro: 'Choose the correct title for “{title}”. Your tracking data stays private to your account.',
  provider: 'Provider',
  searchLabel: 'Search titles',
  search: 'Search',
  review: 'Review changes',
  moving: 'Moving to {title}',
  movingCopy: 'Your tracking data for this title moves to the selected one. Provider identities and other users are not changed.',
  plays: 'Plays and watches',
  collection: 'Collection entries',
  lists: 'List entries',
  references: 'Saved source references',
  numbering: 'Episode numbering',
  numberingCopy: 'Pick the episode each of your watched episodes belongs to on the new title. Matches by number and title are filled in for you; check anything marked Suggested or Needs choice.',
  chooseEpisode: 'Choose episode',
  needsChoice: 'Needs choice',
  suggested: 'Suggested',
  matched: 'Matched',
  stillNeeds: 'Still needs a choice:',
  differ: 'Details that differ',
  differCopy: 'You already track the destination. Choose which value to keep.',
  choose: 'Choose',
  keep: 'Keep',
  currentTitle: 'current title',
  newTitle: 'new title',
  note: 'Note (optional)',
  apply: 'Apply correction',
  cancel: 'Cancel',
  applied: 'Match corrected and future imports mapped.',
  loading: 'Loading matching review…',
  retry: 'Retry',
};

const KIND = { matched: 'matched', suggested: 'suggested' };

function ReferenceRow({ row, saved, copy, palette, buttonPalette, busy, onFix, onReference }) {
  const target = row.corrected || row.matched;
  return <View style={[styles.reference, { borderColor: palette.border }]}>
    <View style={styles.referenceCopy}>
      <Text style={[styles.title, { color: palette.text }]} numberOfLines={2}>{row.title} ({row.integration})</Text>
      {saved ? <Text style={[styles.copy, { color: palette.textMuted }]}>{row.review_status_label}</Text> : null}
    </View>
    <View style={styles.row}>
      {target ? <Button label={saved ? copy.edit : copy.fix} tone="surface" disabled={busy}
        onPress={() => onFix(target)} palette={buttonPalette} /> : null}
      <Button label={saved ? copy.remove : copy.ignore} tone="surface" disabled={busy}
        onPress={() => onReference(row, saved ? 'remove' : 'ignored')} palette={buttonPalette} />
    </View>
  </View>;
}

function FixFlow({ item, copy, palette, buttonPalette, onSearch, onPreview, onApply, onDone }) {
  const [provider, setProvider] = useState('');
  const [providers, setProviders] = useState([]);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState(null);
  const [preview, setPreview] = useState(null);
  const [mapping, setMapping] = useState({});
  const [decisions, setDecisions] = useState({});
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const card = { ...palette, background: palette.surface ?? palette.background };

  async function guard(kind, action) {
    if (busy) return;
    setBusy(kind);
    setError('');
    try { await action(); } catch (reason) { setError(reason?.message || 'The request failed. Try again.'); } finally { setBusy(''); }
  }

  const search = () => guard('search', async () => {
    const found = await onSearch(item.id, { q: query, provider });
    setProvider(found.provider);
    setProviders(found.providers);
    setResults(found.results);
  });
  const choose = result => guard(result.id, async () => {
    const next = await onPreview(item.id, { provider, q: query, destinationMediaId: result.id });
    setPreview(next);
    setMapping(next.mapping);
    setDecisions({});
  });
  const conflicts = preview ? Object.entries(preview.scalarConflicts) : [];
  const needs = preview ? preview.rows.filter(row => !mapping[row.id]).length : 0;
  const undecided = conflicts.filter(([field]) => !decisions[field]).length;
  const bySeason = preview ? preview.rows.reduce((groups, row) => {
    (groups[row.season] = groups[row.season] || []).push(row);
    return groups;
  }, {}) : {};

  return <View style={styles.stack} testID="metadata-fix-flow">
    <Text role="heading" aria-level={2} style={[styles.heading, { color: palette.text }]}>{copy.fixTitle}</Text>
    <Text style={[styles.copy, { color: palette.textMuted }]}>{copy.fixIntro.replace('{title}', item.title)}</Text>
    {!preview ? <View style={styles.stack}>
      {providers.length > 1 ? <SelectField id="match-provider" name="provider" label={copy.provider} value={provider}
        options={providers} palette={palette} onChange={event => setProvider(event.target.value)} /> : null}
      <TextField id="match-query" name="q" label={copy.searchLabel} value={query} onChangeText={setQuery} palette={palette} />
      <View style={styles.row}>
        <Button label={copy.search} busy={busy === 'search'} disabled={!query.trim() || !!busy} onPress={search} palette={buttonPalette} />
        <Button label={copy.cancel} tone="surface" onPress={onDone} palette={buttonPalette} />
      </View>
      {results ? <MetadataMatchResults model={{ results: results.map(result => ({ ...result, actionLabel: copy.review })), variant: 'libraryMove', query }}
        busyId={busy} palette={palette} onChoose={choose} /> : null}
    </View> : <View style={styles.stack}>
      <SettingsCard title={copy.moving.replace('{title}', preview.destination.title)} palette={card}>
        <Text style={[styles.copy, { color: palette.textMuted }]}>{copy.movingCopy}</Text>
        {[[copy.plays, (preview.counts.movie_plays || 0) + (preview.counts.episodes || 0)],
          [copy.collection, preview.counts.collections || 0], [copy.lists, preview.counts.lists || 0],
          [copy.references, preview.referenceCount]].map(([label, value]) => <Text key={label}
          style={[styles.copy, { color: palette.textSecondary }]}>{label}: {value}</Text>)}
      </SettingsCard>
      {preview.rows.length ? <SettingsCard title={copy.numbering} palette={card}>
        <Text style={[styles.copy, { color: palette.textMuted }]}>{copy.numberingCopy}</Text>
        {Object.entries(bySeason).map(([season, rows]) => <View key={season} style={styles.stack}>
          <Text style={[styles.title, { color: palette.text }]}>Season {season}</Text>
          {rows.map(row => <SelectField key={row.id} id={`map-${row.id}`} name={row.id}
            label={`${row.code} · ${row.title}`}
            value={mapping[row.id] || ''} placeholder={copy.chooseEpisode} palette={palette}
            help={KIND[row.kind] ? copy[KIND[row.kind]] : copy.needsChoice}
            options={preview.episodes.map(episode => ({ value: episode.id, label: `${episode.code} · ${episode.title}` }))}
            onChange={event => setMapping(current => ({ ...current, [row.id]: event.target.value }))} />)}
        </View>)}
        {needs ? <Text style={[styles.copy, { color: palette.warning }]}>{copy.stillNeeds} {needs}</Text> : null}
      </SettingsCard> : null}
      {conflicts.length ? <SettingsCard title={copy.differ} palette={card}>
        <Text style={[styles.copy, { color: palette.textMuted }]}>{copy.differCopy}</Text>
        {conflicts.map(([field, values]) => <SelectField key={field} id={`decision-${field}`} name={field}
          label={field.charAt(0).toUpperCase() + field.slice(1)} value={decisions[field] || ''} placeholder={copy.choose}
          palette={palette}
          options={[{ value: 'source', label: `${copy.keep} ${values.source} (${copy.currentTitle})` },
            { value: 'destination', label: `${copy.keep} ${values.destination} (${copy.newTitle})` }]}
          onChange={event => setDecisions(current => ({ ...current, [field]: event.target.value }))} />)}
      </SettingsCard> : null}
      <TextField id="match-note" name="note" label={copy.note} value={note} maxLength={500} onChangeText={setNote} palette={palette} />
      <View style={styles.row}>
        <Button label={copy.apply} busy={busy === 'apply'} disabled={!!busy || needs > 0 || undecided > 0} palette={buttonPalette}
          onPress={() => guard('apply', async () => { await onApply(item.id, preview, { mapping, decisions, note }); onDone(true); })} />
        <Button label={copy.cancel} tone="surface" onPress={() => { setPreview(null); setError(''); }} palette={buttonPalette} />
      </View>
    </View>}
    {error ? <Text accessibilityRole="alert" style={[styles.copy, { color: palette.danger }]}>{error}</Text> : null}
  </View>;
}

/**
 * Matching review: references that need a decision, saved decisions, and the
 * search, preview and apply flow for correcting a match. Presentation only.
 */
export function MetadataReviewView({
  queue,
  state = 'ready',
  error = '',
  labels,
  palette = {},
  buttonPalette = {},
  onRetry,
  onReference,
  onSearch,
  onPreview,
  onApply,
  onChanged,
  initialItem = null,
  heading = true,
}) {
  const copy = { ...metadataReviewCopy, ...(labels || {}) };
  const [fixing, setFixing] = useState(initialItem);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState('');
  const [notice, setNotice] = useState('');
  const head = <View style={styles.stack}>
    {heading ? <Text role="heading" aria-level={2} style={[styles.heading, { color: palette.text }]}>{copy.title}</Text> : null}
    <Text style={[styles.copy, { color: palette.textMuted }]}>{copy.copy}</Text>
  </View>;
  if (state === 'loading') {
    return <View style={styles.page}>{head}<Text style={[styles.copy, { color: palette.textMuted }]}>{copy.loading}</Text></View>;
  }
  if (state === 'error') {
    return <View style={styles.page}>{head}
      <Text accessibilityRole="alert" style={[styles.copy, { color: palette.danger }]}>{error}</Text>
      {onRetry ? <View style={styles.row}><Button label={copy.retry} tone="surface" onPress={onRetry} palette={buttonPalette} /></View> : null}
    </View>;
  }
  if (fixing) {
    return <View style={styles.page}>
      <FixFlow item={fixing} copy={copy} palette={palette} buttonPalette={buttonPalette}
        onSearch={onSearch} onPreview={onPreview} onApply={onApply}
        onDone={applied => { setFixing(null); if (applied) { setNotice(copy.applied); onChanged?.(); } }} />
    </View>;
  }
  async function reference(row, action) {
    if (busy) return;
    setBusy(true);
    setActionError('');
    setNotice('');
    try { await onReference(row, action); onChanged?.(); } catch (reason) { setActionError(reason?.message || 'The request failed. Try again.'); } finally { setBusy(false); }
  }
  const { needsReview = [], saved = [] } = queue || {};
  const card = { ...palette, background: palette.surface ?? palette.background };
  return <View style={styles.page} testID="metadata-review-view">
    {head}
    {notice ? <Text accessibilityLiveRegion="polite" style={[styles.copy, { color: palette.success }]}>{notice}</Text> : null}
    {actionError ? <Text accessibilityRole="alert" style={[styles.copy, { color: palette.danger }]}>{actionError}</Text> : null}
    {!needsReview.length && !saved.length ? <Text style={[styles.copy, { color: palette.textMuted }]}>{copy.empty}</Text> : null}
    {needsReview.length ? <SettingsCard title={copy.title} palette={card}>
      {needsReview.map(row => <ReferenceRow key={row.id} row={row} copy={copy} palette={palette} buttonPalette={buttonPalette}
        busy={busy} onFix={setFixing} onReference={reference} />)}
    </SettingsCard> : null}
    {saved.length ? <SettingsCard title={copy.savedTitle} palette={card}>
      <Text style={[styles.copy, { color: palette.textMuted }]}>{copy.savedCopy}</Text>
      {saved.map(row => <ReferenceRow key={row.id} saved row={row} copy={copy} palette={palette} buttonPalette={buttonPalette}
        busy={busy} onFix={setFixing} onReference={reference} />)}
    </SettingsCard> : null}
  </View>;
}

const styles = StyleSheet.create({
  page: { gap: 16, minWidth: 0 },
  stack: { gap: 10 },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  heading: { fontSize: 22, fontWeight: '600', lineHeight: 28 },
  title: { fontSize: 14, fontWeight: '600', lineHeight: 20 },
  copy: { fontSize: 13, lineHeight: 19 },
  reference: { gap: 8, borderBottomWidth: StyleSheet.hairlineWidth, paddingBottom: 10 },
  referenceCopy: { gap: 2 },
});
