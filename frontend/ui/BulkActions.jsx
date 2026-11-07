import React from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Button } from './Button';

const FALLBACK_PALETTE = {
  background: '#18181b',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#3f3f46',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  success: '#10b981',
  warning: '#f59e0b',
  danger: '#ef4444',
  overlay: 'rgba(0, 0, 0, 0.6)',
  radius: 10,
  focusStyle: {},
};

const defaultLabels = {
  selected: 'selected',
  clear: 'Clear',
  cancel: 'Cancel Select',
  hint: 'Pick items to use these actions.',
  updateStatus: 'Update Status',
  addToList: 'Add to List',
  addToCollection: 'Add to Collection',
  applyTag: 'Apply Tag',
  addPlays: 'Add Plays to History',
  working: 'Working…',
  close: 'Close',
  cancelAction: 'Cancel',
  confirm: 'Confirm',
  hide: 'Hide',
  hideHint: 'A running job keeps going.',
  checking: 'Checking',
  starting: 'Starting',
  addingPlays: 'Adding plays',
  play: 'play',
  show: 'show',
  episode: 'episode',
  playsAdded: 'plays added',
  nothingToAdd: 'Nothing to add with these choices.',
  discard: 'Discard',
  more: 'more',
  couldNotUse: 'could not be used',
};

const pluralize = (count, word) => `${Number(count || 0).toLocaleString()} ${word}${Number(count) === 1 ? '' : 's'}`;

function mergePalette(palette) {
  return { ...FALLBACK_PALETTE, ...(palette || {}) };
}

function mergeLabels(labels) {
  return { ...defaultLabels, ...(labels || {}) };
}

function buttonPalette(colors) {
  return {
    primary: {
      background: colors.accentStrong,
      pressed: '#4338ca',
      hovered: '#4338ca',
      text: '#ffffff',
      border: 'transparent',
    },
    surface: {
      background: colors.surfaceStrong,
      pressed: colors.surfaceMuted,
      hovered: colors.surfaceMuted,
      text: colors.text,
      border: colors.border,
    },
    'danger-solid': {
      background: colors.danger,
      pressed: '#b91c1c',
      hovered: '#b91c1c',
      text: '#ffffff',
      border: 'transparent',
    },
    radius: colors.radius,
    focusStyle: colors.focusStyle,
  };
}

export function BulkToolbar({
  count = 0,
  palette,
  labels,
  busy = false,
  onClear,
  onCancel,
  onUpdateStatus,
  onAddToList,
  onAddToCollection,
  onApplyTag,
  onAddPlays,
}) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(labels);
  const locked = count === 0 || busy;
  const actions = [
    { key: 'status', label: copy.updateStatus, onPress: onUpdateStatus },
    { key: 'list', label: copy.addToList, onPress: onAddToList },
    { key: 'collection', label: copy.addToCollection, onPress: onAddToCollection },
    { key: 'tag', label: copy.applyTag, onPress: onApplyTag },
    { key: 'plays', label: copy.addPlays, onPress: onAddPlays },
  ].filter(action => typeof action.onPress === 'function');
  return <View style={[styles.toolbar, { backgroundColor: colors.surface, borderColor: colors.border }]}>
    <View style={styles.countRow}>
      <Text style={[styles.count, { color: colors.text }]}>
        <Text style={styles.countValue}>{count}</Text> {copy.selected}
      </Text>
      <View style={styles.countActions}>
        <Button label={copy.clear} tone="surface" disabled={busy || count === 0}
          onPress={onClear} palette={buttonPalette(colors)} />
        {onCancel ? <Button label={copy.cancel} tone="surface" disabled={busy}
          onPress={onCancel} palette={buttonPalette(colors)} /> : null}
      </View>
    </View>
    {count === 0 ? <Text style={[styles.hint, { color: colors.textMuted }]}>{copy.hint}</Text> : null}
    {busy ? <Text style={[styles.hint, { color: colors.accent }]}>{copy.working}</Text> : null}
    {actions.length > 0 ? <View style={styles.actionRow}>
      {actions.map(action => <Button key={action.key} label={action.label}
        tone={action.key === 'status' ? 'primary' : 'surface'} disabled={locked}
        onPress={action.onPress} palette={buttonPalette(colors)} />)}
    </View> : null}
  </View>;
}

export function BulkOptionRow({
  label,
  detail,
  selected = false,
  disabled = false,
  palette,
  onPress,
}) {
  const colors = mergePalette(palette);
  return <Pressable accessibilityRole="radio" accessibilityLabel={detail ? `${label}. ${detail}` : label}
    accessibilityState={{ checked: selected, disabled }}
    disabled={disabled}
    onPress={disabled ? undefined : onPress}
    style={({ pressed }) => [styles.option, {
      backgroundColor: selected ? colors.surfaceStrong : colors.background,
      borderColor: selected ? colors.accent : colors.border,
      opacity: disabled ? 0.55 : 1,
    }, pressed && !disabled && { backgroundColor: colors.surfaceMuted }]}>
    <View style={[styles.radio, { borderColor: selected ? colors.accent : colors.surfaceMuted }]}>
      {selected ? <View style={[styles.radioDot, { backgroundColor: colors.accent }]} /> : null}
    </View>
    <View style={styles.optionBody}>
      <Text style={[styles.optionLabel, { color: colors.text }]}>{label}</Text>
      {detail ? <Text style={[styles.optionDetail, { color: colors.textMuted }]}>{detail}</Text> : null}
    </View>
  </Pressable>;
}

export function BulkActionDialog({
  open = false,
  title,
  description,
  children,
  confirmLabel,
  cancelLabel,
  busy = false,
  confirmDisabled = false,
  palette,
  labels,
  onConfirm,
  onClose,
}) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(labels);
  return <Modal visible={open} transparent animationType="none" onRequestClose={onClose}>
    <View style={[styles.modalRoot, { backgroundColor: colors.overlay }]}>
      <Pressable accessible={false} style={StyleSheet.absoluteFill} onPress={busy ? undefined : onClose} />
      <View style={[styles.dialog, {
        backgroundColor: colors.surface,
        borderColor: colors.border,
        borderRadius: colors.radius,
      }]}>
        <View style={styles.dialogHead}>
          <Text role="heading" style={[styles.dialogTitle, { color: colors.text }]}>{title}</Text>
          <Button label={copy.close} tone="surface" disabled={busy}
            onPress={onClose} palette={buttonPalette(colors)} />
        </View>
        {description ? <Text style={[styles.dialogText, { color: colors.textSecondary }]}>
          {description}
        </Text> : null}
        {children ? <ScrollView style={styles.options} contentContainerStyle={styles.optionsContent}>
          {children}
        </ScrollView> : null}
        <View style={styles.dialogActions}>
          <Button label={confirmLabel || copy.confirm} disabled={busy || confirmDisabled}
            busy={busy} onPress={onConfirm} palette={buttonPalette(colors)} />
          <Button label={cancelLabel || copy.cancelAction} tone="surface" disabled={busy}
            onPress={onClose} palette={buttonPalette(colors)} />
        </View>
      </View>
    </View>
  </Modal>;
}

export function BulkJobProgress({ label, done, total = 0, palette, labels }) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(labels);
  const known = total > 0 && Number.isFinite(done);
  const percent = known ? Math.max(0, Math.min(100, Math.round((done / total) * 100))) : 0;
  const text = known ? `${label} ${done.toLocaleString()} of ${pluralize(total, copy.show)}` : label;
  return <View accessibilityRole="progressbar" accessibilityLabel={text}
    accessibilityValue={known ? { min: 0, max: total, now: done } : undefined}
    style={styles.progress}>
    <Text style={[styles.jobText, { color: colors.textSecondary }]}>{text}</Text>
    <View style={[styles.progressTrack, { backgroundColor: colors.surfaceMuted }]}>
      <View style={[styles.progressFill, {
        width: `${known ? percent : 35}%`,
        backgroundColor: known ? colors.accent : colors.textMuted,
      }]} />
    </View>
  </View>;
}

export function BulkJobSummary({ totals = {}, samples = [], notes = [], palette, labels }) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(labels);
  return <View style={styles.jobBody}>
    <Text style={[styles.jobText, { color: colors.textSecondary }]}>
      <Text style={[styles.jobStrong, { color: colors.text }]}>
        {pluralize(totals.plays, copy.play)}
      </Text>
      {` across ${pluralize(totals.shows, copy.show)}.`}
    </Text>
    {samples.length > 0 ? <View style={styles.jobList}>
      {samples.map(sample => <Text key={sample.title} style={[styles.jobItem, { color: colors.textMuted }]}>
        {sample.title}: {pluralize(sample.add, copy.play)}
      </Text>)}
    </View> : null}
    {notes.length > 0 ? <View style={styles.jobList}>
      {notes.map(note => <Text key={note} style={[styles.jobItem, { color: colors.textMuted }]}>{note}</Text>)}
    </View> : null}
  </View>;
}

export function BulkJobProblems({ count = 0, problems = [], palette, labels }) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(labels);
  if (!count) return null;
  const remaining = count - problems.length;
  return <View style={styles.jobProblems}>
    <Text style={[styles.jobProblemTitle, { color: colors.warning }]}>
      {pluralize(count, copy.show)} {copy.couldNotUse}
    </Text>
    {problems.map((problem, index) => <Text key={index} style={[styles.jobItem, { color: colors.textMuted }]}>
      {problem.title}: {problem.reason}
    </Text>)}
    {remaining > 0 ? <Text style={[styles.jobItem, { color: colors.textMuted }]}>
      And {remaining.toLocaleString()} {copy.more}.
    </Text> : null}
  </View>;
}

export function BulkNote({ children, palette }) {
  const colors = mergePalette(palette);
  return <Text style={[styles.jobItem, { color: colors.textMuted }]}>{children}</Text>;
}

export function BulkFieldRow({ children }) {
  return <View style={styles.fieldRow}>{children}</View>;
}

export function BulkActionRow({ children }) {
  return <View style={styles.dialogActions}>{children}</View>;
}

export function BulkJobMessage({ children, tone = 'text', palette }) {
  const colors = mergePalette(palette);
  return <Text style={[styles.jobText, { color: colors[tone] || colors.text }]}>{children}</Text>;
}

export function BulkJobCard({
  title,
  palette,
  labels,
  onHide,
  hideDisabled = false,
  children,
  footer,
}) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(labels);
  return <View accessibilityRole="group" accessibilityLabel={title}
    style={[styles.jobCard, { backgroundColor: colors.surface, borderColor: colors.border }]}>
    <View style={styles.jobHead}>
      <Text role="heading" style={[styles.jobTitle, { color: colors.text }]}>{title}</Text>
      {onHide ? <Button label={copy.hide} tone="surface" disabled={hideDisabled}
        accessibilityLabel={`${copy.hide}. ${copy.hideHint}`}
        onPress={onHide} palette={buttonPalette(colors)} /> : null}
    </View>
    {children}
    {footer ? <View style={styles.dialogActions}>{footer}</View> : null}
  </View>;
}

const styles = StyleSheet.create({
  toolbar: { borderWidth: 1, borderRadius: 10, padding: 12, gap: 10 },
  countRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' },
  countActions: { flexDirection: 'row', gap: 8, flexWrap: 'wrap' },
  count: { fontSize: 13 },
  countValue: { fontWeight: '700' },
  hint: { fontSize: 12, lineHeight: 17 },
  actionRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  modalRoot: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 16 },
  dialog: { width: '100%', maxWidth: 520, maxHeight: '85%', borderWidth: 1, padding: 16, gap: 12 },
  dialogHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  dialogTitle: { fontSize: 18, fontWeight: '700', flex: 1 },
  dialogText: { fontSize: 13, lineHeight: 19 },
  options: { maxHeight: 320 },
  optionsContent: { gap: 8 },
  option: { borderWidth: 1, borderRadius: 8, padding: 10, flexDirection: 'row', alignItems: 'flex-start', gap: 10 },
  radio: { width: 18, height: 18, borderRadius: 9, borderWidth: 2, alignItems: 'center', justifyContent: 'center', marginTop: 1 },
  radioDot: { width: 8, height: 8, borderRadius: 4 },
  optionBody: { flex: 1, gap: 2 },
  optionLabel: { fontSize: 14, fontWeight: '600' },
  optionDetail: { fontSize: 12, lineHeight: 17 },
  dialogActions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, justifyContent: 'flex-end' },
  jobCard: { borderWidth: 1, borderRadius: 10, padding: 12, gap: 10 },
  jobHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  jobTitle: { fontSize: 15, fontWeight: '700', flex: 1 },
  jobBody: { gap: 4 },
  jobText: { fontSize: 13, lineHeight: 18 },
  jobStrong: { fontWeight: '700' },
  jobList: { gap: 2 },
  jobItem: { fontSize: 12, lineHeight: 17 },
  jobProblems: { gap: 2, padding: 8, borderRadius: 8 },
  jobProblemTitle: { fontSize: 12, fontWeight: '600' },
  fieldRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  progress: { gap: 5 },
  progressTrack: { height: 8, borderRadius: 4, overflow: 'hidden' },
  progressFill: { height: 8, borderRadius: 4 },
});
