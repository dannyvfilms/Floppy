import React, { useEffect, useMemo, useState } from 'react';
import { StyleSheet, Text, TextInput, View } from 'react-native';
import { BulkActionBar } from '../../../frontend/ui/BulkActionBar';
import {
  BulkActionDialog,
  BulkJobMessage,
  BulkJobProblems,
  BulkJobProgress,
  BulkJobSummary,
  BulkNote,
  BulkOptionRow,
} from '../../../frontend/ui/BulkActions';
import {
  listOptionsFromPayload,
  STATUS_TRACK_OPTIONS,
  summarizeBulkOutcome,
  tagOptionsFromPayload,
} from '../data/libraryTransportCore';
import { mediaCardPalette, palette, radius, spacing } from '../theme';

export const surface = {
  id: 'BULK',
  title: 'Bulk selection and actions',
  where: 'Library',
  status: 'ported',
  note: 'The shared bulk action bar appears in select mode (entered from the view settings menu, like the web page) over the rows of the grid or table. Update Status, Add to List, Add to Collection, Apply Tag and Add Plays to History each post one request to /api/v1/library/bulk/*, which runs the same server code as the web toolbar and returns its message. Select all matching reads the item ids behind the current filters from /api/v1/media/{type}/item-ids/.',
};

const bulkPalette = {
  ...palette,
  overlay: mediaCardPalette.chipBackground,
  radius: radius.md,
  focusStyle: {},
};

const labels = {
  close: 'Close',
  confirm: 'Confirm',
  cancelAction: 'Cancel',
  working: 'Working…',
};

const PLAY_SCOPES = [
  { value: 'aired', label: 'All aired episodes' },
  { value: 'watched', label: 'Episodes my status says I watched' },
  { value: 'seasons', label: 'A range of seasons' },
];
const PLAY_DATES = [
  { value: 'air_date', label: 'Episode air dates (estimate)' },
  { value: 'one_date', label: 'One date for every play' },
  { value: 'range', label: 'Spread across a date range' },
];
const SCOPE_HELP = {
  aired: 'Every episode that has aired. Specials are left out.',
  watched: 'Completed shows get every aired episode. Other shows get only their completed seasons.',
  seasons: 'Aired episodes in these seasons. Season 0 is specials.',
};
const DATE_HELP = {
  air_date: 'Each play is dated when the episode first aired. This is an estimate of when you watched, not a real watch time.',
  one_date: 'Every play lands on one day. Many plays on one day can distort activity, streaks and Statistics.',
  range: 'Plays are spread evenly in order across the dates. Still an estimate.',
};
const EMPTY_PLAYS = { scope: 'aired', season_from: '1', season_to: '1', existing: 'skip', date_mode: 'air_date', date: '', start_date: '', end_date: '' };
const PLAY_EXISTING = [
  { value: 'skip', label: 'Skip episodes that already have a play' },
  { value: 'add', label: 'Add another play anyway' },
];

const POLL_MS = 1500;
const POLL_LIMIT = 40;

function plural(count) {
  return `${count} selected item${count === 1 ? '' : 's'}`;
}

export default function BulkSlot({
  selectMode = false,
  selectedIds = [],
  transport,
  onLoadAllIds,
  onSelectIds,
  onToggleSelectMode,
  onClearSelection,
  onDone,
}) {
  const isServer = transport?.mode === 'server';
  const [lists, setLists] = useState([]);
  const [tags, setTags] = useState([]);
  const [pending, setPending] = useState(null);
  const [form, setForm] = useState(EMPTY_PLAYS);
  // The web Add Plays dialog previews first: stage is form, checking, review or adding.
  const [plays, setPlays] = useState({ stage: 'form', result: null, error: '' });
  const [busy, setBusy] = useState(false);
  const [selecting, setSelecting] = useState(false);
  const [notice, setNotice] = useState(null);

  // The pickers read real lists and tags; a failed load leaves the menu empty
  // ("No editable lists." / "No tags yet.") instead of listing sample rows.
  useEffect(() => {
    if (!isServer || !selectMode) return undefined;
    let active = true;
    transport.loadLists()
      .then(payload => {
        if (!active) return;
        const editable = (payload?.results || []).filter(list => !list.is_smart);
        setLists(listOptionsFromPayload({ results: editable }));
      })
      .catch(() => { if (active) setLists([]); });
    transport.loadTags()
      .then(payload => { if (active) setTags(tagOptionsFromPayload(payload)); })
      .catch(() => { if (active) setTags([]); });
    return () => { active = false; };
  }, [transport, isServer, selectMode]);

  const count = selectedIds.length;

  async function run(action, success) {
    if (busy || !count) return;
    setBusy(true);
    setNotice(null);
    try {
      const outcome = await action();
      setNotice({ text: success ? success(outcome) : summarizeBulkOutcome(outcome), tone: 'success' });
      onClearSelection?.();
      onToggleSelectMode?.();
      onDone?.();
    } catch (error) {
      setNotice({ text: error?.message || 'The bulk action failed.', tone: 'error' });
    } finally {
      setBusy(false);
      setPending(null);
    }
  }

  function playOptions() {
    const options = {
      scope: form.scope,
      existing: form.existing,
      date_mode: form.date_mode,
      date: form.date,
      start_date: form.start_date,
      end_date: form.end_date,
    };
    if (form.scope === 'seasons') {
      options.season_from = form.season_from;
      options.season_to = form.season_to;
    }
    return options;
  }

  async function pollPlays(operation) {
    for (let attempt = 0; operation && attempt < POLL_LIMIT; attempt += 1) {
      await new Promise(resolve => setTimeout(resolve, POLL_MS));
      const state = await transport.bulkPlaysStatus(operation);
      if (state?.state && state.state !== 'running') return state;
    }
    return null;
  }

  async function previewPlays() {
    setPlays({ stage: 'checking', result: null, error: '' });
    try {
      const started = await transport.bulkAddPlays(selectedIds, { ...playOptions(), dry_run: '1' });
      const state = await pollPlays(started?.operation_id);
      if (!state || state.state === 'error') throw new Error('The preview could not finish.');
      setPlays({ stage: 'review', result: state, error: '' });
    } catch (error) {
      setPlays({ stage: 'form', result: null, error: error?.message || 'The preview failed.' });
    }
  }

  async function runPlays() {
    const started = await transport.bulkAddPlays(selectedIds, playOptions());
    const state = await pollPlays(started?.operation_id);
    if (state?.totals) return { message: `${state.totals.plays} play${state.totals.plays === 1 ? '' : 's'} added across ${state.totals.shows} show${state.totals.shows === 1 ? '' : 's'}.` };
    return { message: state?.error || 'Adding plays to History. It keeps running in the background.' };
  }

  function closePlays() {
    if (busy) return;
    setPending(null);
    setPlays({ stage: 'form', result: null, error: '' });
  }

  async function selectAll() {
    if (selecting || !onLoadAllIds) return;
    setSelecting(true);
    setNotice(null);
    try {
      onSelectIds?.(await onLoadAllIds());
    } catch (error) {
      setNotice({ text: error?.message || 'Could not select the matching items.', tone: 'error' });
    } finally {
      setSelecting(false);
    }
  }

  const actions = useMemo(() => [
    {
      key: 'status',
      icon: 'status',
      label: 'Update Status',
      items: [
        { heading: 'Changes status only. Completed on a show also adds plays dated today.' },
        ...STATUS_TRACK_OPTIONS.map(option => ({
          label: option.label,
          onSelect: () => setPending({ kind: 'status', status: option.value, label: option.label }),
        })),
      ],
    },
    {
      key: 'list',
      icon: 'list',
      label: 'Add to List',
      items: lists.length
        ? lists.map(list => ({ label: list.name, onSelect: () => setPending({ kind: 'list', id: list.id, label: list.name }) }))
        : [{ heading: 'No editable lists.' }],
    },
    {
      key: 'collection',
      icon: 'collection',
      label: 'Add to Collection',
      onSelect: () => setPending({ kind: 'collection' }),
    },
    {
      key: 'tag',
      icon: 'tag',
      label: 'Apply Tag',
      items: tags.length
        ? tags.map(tag => ({
          label: tag.name,
          actions: [
            { label: 'Add', onSelect: () => setPending({ kind: 'tag', id: tag.id, mode: 'add', label: tag.name }) },
            { label: 'Remove', onSelect: () => setPending({ kind: 'tag', id: tag.id, mode: 'remove', label: tag.name }) },
          ],
        }))
        : [{ heading: 'No tags yet.' }],
    },
    {
      key: 'more',
      icon: 'more',
      label: 'More actions',
      items: [{ label: 'Add Plays to History', onSelect: () => setPending({ kind: 'plays' }) }],
    },
  ], [lists, tags]);

  if (!isServer) return null;

  function confirm() {
    if (pending?.kind === 'status') return run(() => transport.bulkStatus(selectedIds, pending.status));
    if (pending?.kind === 'list') return run(() => transport.bulkAddToList(selectedIds, pending.id));
    if (pending?.kind === 'collection') return run(() => transport.bulkAddToCollection(selectedIds));
    if (pending?.kind === 'tag') return run(() => transport.bulkApplyTag(selectedIds, pending.id, pending.mode));
    if (pending?.kind === 'plays') {
      if (plays.stage === 'review') return run(runPlays).then(() => setPlays({ stage: 'form', result: null, error: '' }));
      return previewPlays();
    }
    return undefined;
  }

  const dialog = {
    status: ['Update Status', `Set ${plural(count)} to ${pending?.label}. Only tracked items can be updated.`, 'Update status'],
    list: ['Add to List', `Add ${plural(count)} to ${pending?.label}.`, 'Add to list'],
    collection: ['Add to Collection', `Add ${plural(count)} to your collection? Copies you already own are skipped.`, 'Add to collection'],
    tag: [
      'Apply Tag',
      `${pending?.mode === 'remove' ? 'Remove' : 'Add'} ${pending?.label} ${pending?.mode === 'remove' ? 'from' : 'to'} ${plural(count)}.`,
      pending?.mode === 'remove' ? 'Remove tag' : 'Apply Tag',
    ],
    plays: ['Add Plays to History', `Add plays to History for ${plural(count)}. Only shows are used.`,
      plays.stage === 'review' ? `Add ${plays.result?.totals?.plays || 0} plays` : 'Preview'],
  }[pending?.kind] || ['', '', ''];

  return <View style={styles.root}>
    {selectMode ? <BulkActionBar
      count={count}
      actions={actions}
      disabled={!count || busy}
      deselectDisabled={busy}
      palette={bulkPalette}
      onSelectAll={onLoadAllIds ? selectAll : undefined}
      selectAllDisabled={busy}
      selecting={selecting}
      onDeselect={() => { onClearSelection?.(); onToggleSelectMode?.(); }} /> : null}
    {notice ? <Text role="status" accessibilityLiveRegion="polite"
      style={[styles.notice, { color: notice.tone === 'error' ? palette.danger : palette.success }]}>
      {notice.text}
    </Text> : null}
    <BulkActionDialog
      open={Boolean(pending)}
      title={dialog[0]}
      description={dialog[1]}
      confirmLabel={dialog[2]}
      busy={busy}
      confirmDisabled={busy || count === 0 || plays.stage === 'checking' || (pending?.kind === 'plays' && plays.stage === 'review' && !plays.result?.totals?.plays)}
      palette={bulkPalette}
      labels={labels}
      onConfirm={confirm}
      onClose={pending?.kind === 'plays' ? closePlays : () => { if (!busy) setPending(null); }}>
      {pending?.kind === 'plays' ? <View style={styles.options}>
        {plays.stage === 'checking' ? <BulkJobProgress label="Checking" palette={bulkPalette} /> : null}
        {plays.stage === 'review' && plays.result ? <>
          <BulkJobSummary totals={plays.result.totals} samples={plays.result.samples || []} palette={bulkPalette}
            notes={[
              plays.result.totals.existing && `${plays.result.totals.existing} episode(s) skipped (already have a play)`,
              plays.result.totals.unaired && `${plays.result.totals.unaired} episode(s) skipped (not aired yet)`,
              plays.result.totals.no_date && `${plays.result.totals.no_date} episode(s) skipped (no air date)`,
            ].filter(Boolean)} />
          <BulkJobProblems count={plays.result.problem_count} problems={plays.result.problems || []} palette={bulkPalette} />
          {plays.result.totals.plays === 0 ? <BulkJobMessage palette={bulkPalette}>Nothing to add with these choices.</BulkJobMessage> : null}
        </> : null}
        {plays.stage === 'form' ? <>
          {plays.error ? <BulkJobMessage tone="danger" palette={bulkPalette}>{plays.error}</BulkJobMessage> : null}
          {PLAY_SCOPES.map(option => <BulkOptionRow key={option.value} label={option.label}
            selected={form.scope === option.value} palette={bulkPalette} onPress={() => setForm(current => ({ ...current, scope: option.value }))} />)}
          <BulkNote palette={bulkPalette}>{SCOPE_HELP[form.scope]}</BulkNote>
          {form.scope === 'seasons' ? <View style={styles.fieldRow}>
            <PlayField label="First season" value={form.season_from} keyboardType="numeric"
              onChange={value => setForm(current => ({ ...current, season_from: value }))} />
            <PlayField label="Last season" value={form.season_to} keyboardType="numeric"
              onChange={value => setForm(current => ({ ...current, season_to: value }))} />
          </View> : null}
          {PLAY_EXISTING.map(option => <BulkOptionRow key={option.value} label={option.label}
            selected={form.existing === option.value} palette={bulkPalette} onPress={() => setForm(current => ({ ...current, existing: option.value }))} />)}
          {PLAY_DATES.map(option => <BulkOptionRow key={option.value} label={option.label}
            selected={form.date_mode === option.value} palette={bulkPalette} onPress={() => setForm(current => ({ ...current, date_mode: option.value }))} />)}
          <BulkNote palette={bulkPalette}>{DATE_HELP[form.date_mode]}</BulkNote>
          {form.date_mode === 'one_date' ? <PlayField label="Date (YYYY-MM-DD)" value={form.date}
            onChange={value => setForm(current => ({ ...current, date: value }))} /> : null}
          {form.date_mode === 'range' ? <View style={styles.fieldRow}>
            <PlayField label="From (YYYY-MM-DD)" value={form.start_date}
              onChange={value => setForm(current => ({ ...current, start_date: value }))} />
            <PlayField label="To (YYYY-MM-DD)" value={form.end_date}
              onChange={value => setForm(current => ({ ...current, end_date: value }))} />
          </View> : null}
        </> : null}
      </View> : null}
    </BulkActionDialog>
  </View>;
}

function PlayField({ label, value, onChange, keyboardType }) {
  return <View style={styles.field}>
    <Text style={[styles.fieldLabel, { color: bulkPalette.textSecondary }]}>{label}</Text>
    <TextInput accessibilityLabel={label} value={value} onChangeText={onChange} keyboardType={keyboardType}
      autoCapitalize="none" autoCorrect={false}
      style={[styles.input, { color: bulkPalette.text, borderColor: bulkPalette.border, backgroundColor: bulkPalette.background }]} />
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: spacing.md },
  fieldRow: { flexDirection: 'row', gap: spacing.sm },
  field: { flex: 1, gap: 4 },
  fieldLabel: { fontSize: 13, fontWeight: '600' },
  input: { minHeight: 40, borderWidth: 1, borderRadius: radius.md, paddingHorizontal: 10, fontSize: 14 },
  notice: { fontSize: 12, lineHeight: 17 },
  options: { gap: spacing.sm },
});
