import React, { useEffect, useRef, useState } from 'react';
import { StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { BulkActionDialog, BulkActionRow, BulkJobCard, BulkJobMessage, BulkJobProblems, BulkJobProgress, BulkJobSummary, BulkOptionRow, BulkToolbar } from '../../../frontend/ui/BulkActions';
import { BulkJobDock } from '../../../frontend/ui/BulkJobDock';
import { Button } from '../../../frontend/ui/Button';
import { MediaCardView } from '../../../frontend/ui/MediaCardView';
import MediaCardSlot from './MediaCardSlot';
import { emitMediaCardChange } from './mediaCardEvents';
import { mediaCardPalette, palette, radius, spacing } from '../theme';

export const surface = {
  id: 'BULK',
  title: 'Bulk selection and actions',
  where: 'Library, custom lists and smart lists',
  status: 'ported',
  note: 'Library select mode, card selection, selected count, Update Status, Add to List, Add to Collection, Apply Tag, Add Plays, confirmation dialogs, job progress, skipped-item results and clear/reset use shared bulk presentation. Finished status and plays actions publish a card-change event so the card grid reflects them. The demo writes stay local; the browser keeps its authenticated transport.',
};

const STATUS_OPTIONS = [
  { value: 'Completed', label: 'Completed' },
  { value: 'In progress', label: 'In progress' },
  { value: 'Planning', label: 'Planning' },
  { value: 'Paused', label: 'Paused' },
  { value: 'Dropped', label: 'Dropped' },
];

const LIST_OPTIONS = [
  { value: 'weekend', label: 'Weekend Watchlist', detail: '8 items · private' },
  { value: 'comfort', label: 'Comfort watches', detail: '12 items · private' },
  { value: 'friends', label: 'With friends', detail: '5 items · shared' },
];

const TAG_OPTIONS = [
  { value: 'Favorite', label: 'Favorite' },
  { value: 'Comfort', label: 'Comfort' },
  { value: 'Sci-fi', label: 'Sci-fi' },
];

const CARDS = [
  {
    id: 'quiet-orbit',
    model: {
      mediaType: 'tv',
      identity: { mediaType: 'tv', source: 'tmdb', mediaId: '76479' },
      shape: 'poster',
      video: false,
      image: { src: 'https://picsum.photos/seed/floppy-orbit/400/600', fallback: '', source: 'primary' },
      title: 'The Quiet Orbit',
      altTitle: null,
      statusChip: { kind: 'status', status: 'In progress', hideOnMobile: false },
      cornerChips: [{ kind: 'next-episode', text: 'Next ep' }],
      titleLinks: [],
      progressBar: { percent: 62, paused: false },
      lines: [{ join: 'plain', parts: [{ text: '2024' }, { text: '• 6 / 10 episodes', muted: true }] }],
      rating: { label: '8.0', value: 8, scaleMax: 10, rateLabel: 'Rate' },
      ratingEditable: true,
      actions: null,
    },
  },
  {
    id: 'signal-static',
    model: {
      mediaType: 'podcast',
      identity: { mediaType: 'podcast', source: 'pocketcasts', mediaId: 'signal-carrier-wave', episodeNumber: 3 },
      shape: 'square',
      video: false,
      image: { src: 'https://picsum.photos/seed/floppy-signal/400/400', fallback: '', source: 'primary' },
      title: 'Signal & Static',
      altTitle: 'Signal and Static',
      statusChip: { kind: 'status', status: 'In progress', hideOnMobile: false },
      cornerChips: [],
      titleLinks: [],
      progressBar: { percent: 38, paused: true },
      lines: [{ join: 'plain', parts: [{ text: '2023' }, { text: '• 3 / 8 episodes', muted: true }] }],
      rating: { label: '4.5', value: 4.5, scaleMax: 5, rateLabel: 'Rate' },
      ratingEditable: true,
      actions: null,
    },
  },
  {
    id: 'home-studio',
    model: {
      mediaType: 'video',
      identity: { mediaType: 'movie', source: 'tmdb', mediaId: '603' },
      shape: 'landscape',
      video: true,
      image: { src: 'https://picsum.photos/seed/floppy-studio/800/450', fallback: '', source: 'primary' },
      title: 'Building a Home Studio',
      altTitle: null,
      statusChip: { kind: 'status', status: 'Completed', hideOnMobile: false },
      cornerChips: [{ kind: 'runtime', text: '12:40' }],
      titleLinks: [],
      progressBar: null,
      lines: [{ join: 'plain', parts: [{ text: '2024' }, { text: '• Watched', muted: true }] }],
      rating: null,
      ratingEditable: true,
      actions: null,
    },
  },
  {
    id: 'paper-lanterns',
    model: {
      mediaType: 'book',
      identity: { mediaType: 'book', source: 'openlibrary', mediaId: 'OL27448W' },
      shape: 'poster',
      video: false,
      publicView: true,
      image: { src: null, fallback: '', source: 'primary' },
      title: 'Paper Lanterns',
      altTitle: null,
      statusChip: {
        kind: 'media-type',
        type: 'book',
        style: 'soft',
        color: '#D946EF',
        contrast: '#FFFFFF',
        label: 'Book',
      },
      cornerChips: [],
      titleLinks: [],
      progressBar: null,
      lines: [{ join: 'plain', parts: [{ text: '2022' }, { text: '• 0 / 320 pages', muted: true }] }],
      rating: { label: '6.5', value: 6.5, scaleMax: 10, rateLabel: 'Rate' },
      ratingEditable: false,
      actions: null,
    },
  },
];

const bulkPalette = {
  ...palette,
  textSecondary: palette.textSecondary,
  overlay: 'rgba(0, 0, 0, 0.6)',
  radius: radius.md,
  focusStyle: {},
};

const labels = {
  selectItems: 'Select Items',
  cancelSelect: 'Cancel Select',
  updateStatus: 'Update Status',
  addToList: 'Add to List',
  addToCollection: 'Add to Collection',
  applyTag: 'Apply Tag',
  clear: 'Clear',
  hint: 'Pick items to use these actions.',
  selected: 'selected',
  working: 'Working…',
  close: 'Close',
  confirm: 'Confirm',
  cancelAction: 'Cancel',
  addPlays: 'Add Plays to History',
  checking: 'Checking',
  addingPlays: 'Adding plays',
  nothingToAdd: 'Nothing to add with these choices.',
  discard: 'Discard',
};

export default function BulkSlot({ onOpenDetail }) {
  const { width } = useWindowDimensions();
  const [selectMode, setSelectMode] = useState(true);
  const [selectedIds, setSelectedIds] = useState(['quiet-orbit', 'signal-static']);
  const [dialog, setDialog] = useState(null);
  const [status, setStatus] = useState('In progress');
  const [listId, setListId] = useState('weekend');
  const [tagMode, setTagMode] = useState('add');
  const [tagName, setTagName] = useState('Favorite');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);
  const [playsJob, setPlaysJob] = useState(null);
  const playsTimer = useRef(null);
  const columns = width >= 760 ? 4 : width >= 560 ? 3 : 2;
  const cardWidth = Math.min(180, Math.max(120, (width - 32 - (columns - 1) * spacing.md) / columns));

  useEffect(() => () => clearTimeout(playsTimer.current), []);

  function toggleSelectMode() {
    if (selectMode) {
      setSelectedIds([]);
      setDialog(null);
    }
    setSelectMode(!selectMode);
    setNotice(null);
  }

  function toggleItem(id) {
    setSelectedIds(current => current.includes(id)
      ? current.filter(value => value !== id)
      : [...current, id]);
    setNotice(null);
  }

  function clearSelection() {
    setSelectedIds([]);
    setNotice(null);
  }

  function finish(text, tone = 'success') {
    const identities = CARDS
      .filter(card => selectedIds.includes(card.id))
      .map(card => card.model.identity)
      .filter(Boolean);
    emitMediaCardChange({
      source: 'bulk',
      identities,
      ...(dialog === 'status' ? { status } : {}),
    });
    setBusy(false);
    setDialog(null);
    setSelectedIds([]);
    setSelectMode(false);
    setNotice({ text, tone });
  }

  function runAction(simulate) {
    if (busy) return;
    setBusy(true);
    setTimeout(() => {
      const outcome = simulate();
      finish(outcome.text, outcome.tone);
    }, 700);
  }

  function confirmDialog() {
    const count = selectedIds.length;
    if (dialog === 'status') {
      const skipped = selectedIds.includes('paper-lanterns') ? 1 : 0;
      runAction(() => ({
        text: `Set ${count - skipped} item${count - skipped === 1 ? '' : 's'} to ${status}.${skipped ? ` ${skipped} skipped: metadata only.` : ''}`,
        tone: skipped ? 'warning' : 'success',
      }));
    } else if (dialog === 'list') {
      const list = LIST_OPTIONS.find(option => option.value === listId);
      runAction(() => ({
        text: `Added ${count} item${count === 1 ? '' : 's'} to ${list.label}.`,
        tone: 'success',
      }));
    } else if (dialog === 'collection') {
      const already = selectedIds.includes('home-studio') ? 1 : 0;
      runAction(() => ({
        text: `Added ${count - already} item${count - already === 1 ? '' : 's'} to collection.${already ? ` ${already} already present.` : ''}`,
        tone: already ? 'warning' : 'success',
      }));
    } else if (dialog === 'tag') {
      runAction(() => ({
        text: `${tagMode === 'add' ? 'Added' : 'Removed'} ${tagName} ${tagMode === 'add' ? 'to' : 'from'} ${count} item${count === 1 ? '' : 's'}.`,
        tone: 'success',
      }));
    } else if (dialog === 'plays') {
      startPlaysReview(count);
    }
  }

  function startPlaysReview(count) {
    const ids = [...selectedIds];
    const adds = { 'quiet-orbit': 6, 'signal-static': 3, 'home-studio': 1 };
    const samples = CARDS.filter(card => ids.includes(card.id))
      .map(card => ({ title: card.model.title, add: adds[card.id] || 0 }));
    const plays = samples.reduce((sum, sample) => sum + sample.add, 0);
    const problems = ids.includes('paper-lanterns')
      ? [{ title: 'Paper Lanterns', reason: 'Books have no aired episodes to add.' }]
      : [];
    setDialog(null);
    setNotice(null);
    setPlaysJob({ phase: 'previewing', total: count, done: 0, ids, result: null });
    clearTimeout(playsTimer.current);
    playsTimer.current = setTimeout(() => {
      setPlaysJob({
        phase: 'review',
        total: count,
        done: count,
        ids,
        result: { totals: { plays, shows: count }, samples, problem_count: problems.length, problems },
      });
    }, 700);
  }

  function completePlays() {
    if (!playsJob || playsJob.phase !== 'review') return;
    const job = playsJob;
    setPlaysJob({ ...job, phase: 'running', done: 0 });
    clearTimeout(playsTimer.current);
    playsTimer.current = setTimeout(() => {
      const identities = CARDS.filter(card => job.ids.includes(card.id))
        .map(card => card.model.identity).filter(Boolean);
      emitMediaCardChange({ source: 'bulk', identities });
      setSelectedIds([]);
      setSelectMode(false);
      setPlaysJob({
        ...job,
        phase: 'done',
        done: job.total,
        doneText: `${job.result.totals.plays} play${job.result.totals.plays === 1 ? '' : 's'} added across ${job.result.totals.shows} show${job.result.totals.shows === 1 ? '' : 's'}.`,
      });
    }, 700);
  }

  const count = selectedIds.length;
  const dialogOpen = dialog !== null;
  const title = dialog === 'status' ? labels.updateStatus
    : dialog === 'list' ? labels.addToList
      : dialog === 'collection' ? labels.addToCollection
        : dialog === 'tag' ? labels.applyTag
          : dialog === 'plays' ? labels.addPlays : '';
  const description = dialog === 'status'
    ? `Set ${count} selected item${count === 1 ? '' : 's'} to ${status}. This changes status only; Completed also adds plays dated today.`
    : dialog === 'list'
      ? 'Choose an editable list. Smart lists and read-only lists are not writable.'
      : dialog === 'collection'
        ? `Add ${count} selected item${count === 1 ? '' : 's'} to your collection? Shows and seasons expand to their episodes.`
        : dialog === 'tag'
          ? `Choose a tag and whether to add or remove it across ${count} selected item${count === 1 ? '' : 's'}.`
          : dialog === 'plays'
            ? `Adds viewing records for ${count} selected item${count === 1 ? '' : 's'}. Review checks every show before anything is added.`
            : '';

  return <View style={styles.root}>
    <View style={styles.selectRow}>
      <Button label={selectMode ? labels.cancelSelect : labels.selectItems}
        tone={selectMode ? 'surface' : 'primary'} onPress={toggleSelectMode}
        palette={{
          primary: { background: palette.accentStrong, pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
          surface: { background: palette.surfaceStrong, pressed: palette.surfaceMuted, hovered: palette.surfaceMuted, text: palette.text, border: palette.border },
          radius: radius.sm,
          focusStyle: {},
        }} />
    </View>
    {selectMode
      ? <View style={styles.grid}>
          {CARDS.map(item => <MediaCardView key={item.id} model={item.model} labels={labels}
            palette={mediaCardPalette} width={cardWidth}
            selection={{
              active: true,
              selected: selectedIds.includes(item.id),
              label: `Select ${item.model.title}`,
              toggle: () => toggleItem(item.id),
            }}
            onOpen={() => toggleItem(item.id)} />)}
        </View>
      : <MediaCardSlot onOpenDetail={onOpenDetail} />}
    {selectMode ? <BulkToolbar
      count={count}
      palette={bulkPalette}
      labels={labels}
      busy={busy}
      onClear={clearSelection}
      onCancel={toggleSelectMode}
      onUpdateStatus={() => setDialog('status')}
      onAddToList={() => setDialog('list')}
      onAddToCollection={() => setDialog('collection')}
      onApplyTag={() => setDialog('tag')}
      onAddPlays={() => setDialog('plays')} /> : null}
    {notice ? <Text role="status"
      style={[styles.notice, { color: notice.tone === 'warning' ? palette.warning : palette.success }]}>
      {notice.text}
    </Text> : null}
    <BulkActionDialog
      open={dialogOpen}
      title={title}
      description={description}
      confirmLabel={dialog === 'status' ? 'Update status'
        : dialog === 'list' ? 'Add to list'
          : dialog === 'collection' ? 'Add to collection'
            : dialog === 'plays' ? 'Review' : 'Apply tag'}
      busy={busy}
      confirmDisabled={busy || count === 0}
      palette={bulkPalette}
      labels={labels}
      onConfirm={confirmDialog}
      onClose={() => { if (!busy) setDialog(null); }}>
      {dialog === 'status' ? STATUS_OPTIONS.map(option => <BulkOptionRow key={option.value}
        label={option.label} selected={status === option.value}
        palette={bulkPalette} onPress={() => setStatus(option.value)} />) : null}
      {dialog === 'list' ? LIST_OPTIONS.map(option => <BulkOptionRow key={option.value}
        label={option.label} detail={option.detail} selected={listId === option.value}
        palette={bulkPalette} onPress={() => setListId(option.value)} />) : null}
      {dialog === 'tag' ? <View style={styles.tagBody}>
        <View style={styles.tagModes}>
          <BulkOptionRow label="Add tag" selected={tagMode === 'add'}
            palette={bulkPalette} onPress={() => setTagMode('add')} />
          <BulkOptionRow label="Remove tag" selected={tagMode === 'remove'}
            palette={bulkPalette} onPress={() => setTagMode('remove')} />
        </View>
        {TAG_OPTIONS.map(option => <BulkOptionRow key={option.value}
          label={option.label} selected={tagName === option.value}
          palette={bulkPalette} onPress={() => setTagName(option.value)} />)}
      </View> : null}
    </BulkActionDialog>
    {playsJob ? <BulkJobDock palette={bulkPalette} label="Bulk jobs">
      <BulkJobCard title={labels.addPlays} palette={bulkPalette}
        onHide={() => setPlaysJob(null)}
        footer={playsJob.phase === 'review' ? <BulkActionRow>
          {playsJob.result.totals.plays > 0 ? <Button
            label={`${labels.addPlays} (${playsJob.result.totals.plays})`}
            onPress={completePlays} palette={{
              primary: { background: palette.accentStrong, pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
              radius: radius.sm,
              focusStyle: {},
            }} /> : null}
          <Button label={labels.discard} tone="surface" onPress={() => setPlaysJob(null)}
            palette={{
              surface: { background: palette.surfaceStrong, pressed: palette.surfaceMuted, hovered: palette.surfaceMuted, text: palette.text, border: palette.border },
              radius: radius.sm,
              focusStyle: {},
            }} />
        </BulkActionRow> : null}>
        {playsJob.phase === 'previewing' ? <BulkJobProgress label={labels.checking}
          done={playsJob.done} total={playsJob.total} palette={bulkPalette} /> : null}
        {playsJob.phase === 'running' ? <BulkJobProgress label={labels.addingPlays}
          done={Math.round(playsJob.total / 2)} total={playsJob.total} palette={bulkPalette} /> : null}
        {playsJob.phase === 'review' ? <>
          <BulkJobSummary totals={playsJob.result.totals} samples={playsJob.result.samples}
            palette={bulkPalette} />
          <BulkJobProblems count={playsJob.result.problem_count}
            problems={playsJob.result.problems} palette={bulkPalette} />
          {playsJob.result.totals.plays === 0
            ? <BulkJobMessage palette={bulkPalette}>{labels.nothingToAdd}</BulkJobMessage>
            : null}
        </> : null}
        {playsJob.phase === 'done' ? <BulkJobMessage palette={bulkPalette}>
          {playsJob.doneText}
        </BulkJobMessage> : null}
      </BulkJobCard>
    </BulkJobDock> : null}
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: spacing.md },
  selectRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md },
  notice: { fontSize: 12, lineHeight: 17 },
  tagBody: { gap: spacing.sm },
  tagModes: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
});
