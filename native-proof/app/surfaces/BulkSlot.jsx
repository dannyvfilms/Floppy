import React, { useState } from 'react';
import { StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { BulkActionDialog, BulkOptionRow, BulkToolbar } from '../../../frontend/ui/BulkActions';
import { Button } from '../../../frontend/ui/Button';
import { MediaCardView } from '../../../frontend/ui/MediaCardView';
import MediaCardSlot from './MediaCardSlot';
import { mediaCardPalette, palette, radius, spacing } from '../theme';

export const surface = {
  id: 'BULK',
  title: 'Bulk selection and actions',
  where: 'Library, custom lists and smart lists',
  status: 'in_progress',
  note: 'Closing BULK: adopting the shared BulkToolbar/dialog presentation on the web, porting the Add Plays job dock/status to the shared surface, and preserving Alpine selection/HTMX writes as fallbacks.',
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
  const columns = width >= 760 ? 4 : width >= 560 ? 3 : 2;
  const cardWidth = Math.min(180, Math.max(120, (width - 32 - (columns - 1) * spacing.md) / columns));

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
    }
  }

  const count = selectedIds.length;
  const dialogOpen = dialog !== null;
  const title = dialog === 'status' ? labels.updateStatus
    : dialog === 'list' ? labels.addToList
      : dialog === 'collection' ? labels.addToCollection
        : dialog === 'tag' ? labels.applyTag : '';
  const description = dialog === 'status'
    ? `Set ${count} selected item${count === 1 ? '' : 's'} to ${status}. This changes status only; Completed also adds plays dated today.`
    : dialog === 'list'
      ? 'Choose an editable list. Smart lists and read-only lists are not writable.'
      : dialog === 'collection'
        ? `Add ${count} selected item${count === 1 ? '' : 's'} to your collection? Shows and seasons expand to their episodes.`
        : dialog === 'tag'
          ? `Choose a tag and whether to add or remove it across ${count} selected item${count === 1 ? '' : 's'}.`
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
      onApplyTag={() => setDialog('tag')} /> : null}
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
            : 'Apply tag'}
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
