import React, { useEffect, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { Icon } from './Icon';
import { Button } from './Button';
import { FormError, FormStatus, FormTextField } from './MediaCardFormControls';
import { SelectField } from './SelectField';

const DEFAULT_LABELS = {
  general: 'General',
  loading: 'Loading',
  loadFailed: "Couldn't load this tab.",
  retry: 'Try again',
  tags: 'Tags',
  noTags: 'No tags yet. Create one below.',
  newTag: 'New tag...',
  addTag: 'Add',
  add: 'Add',
  remove: 'Remove',
  tagFailed: "Couldn't update this tag.",
  metadata: 'Metadata',
  artwork: 'Artwork URL',
  saveArtwork: 'Save artwork',
  artworkFailed: "Couldn't save the artwork.",
  artworkUnavailable: 'Save this item before changing its artwork.',
  collection: 'Collection',
  noCollection: 'No owned copies recorded.',
  plays: 'Plays',
  noPlays: 'No plays recorded yet.',
  statusHistory: 'Status history',
  noStatusChanges: 'No status changes recorded yet.',
  noStatus: 'No Status',
  sourceNotRecorded: 'source not recorded',
  discover: 'Discover',
  hidden: 'Hidden from Discover',
  shown: 'Shown in Discover',
  hide: 'Hide from Discover',
  unhide: 'Show in Discover',
  discoverFailed: "Couldn't update Discover.",
};

const DEFAULT_PALETTE = {
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#3f3f46',
  accent: '#6366f1',
  accentContrast: '#ffffff',
  danger: '#f87171',
  radius: 8,
  focusStyle: {},
};

function resolvePalette(palette) {
  return { ...DEFAULT_PALETTE, ...(palette || {}) };
}

function labelsFor(supplied) {
  return { ...DEFAULT_LABELS, ...(supplied || {}) };
}

function tabLabel(tab, labels) {
  if (tab.id === 'general') return labels.general;
  if (tab.label) return tab.label;
  return tab.id;
}

function SideTab({ tab, active, onSelect, palette, labels, wide }) {
  const color = active ? palette.text : palette.textMuted;
  return <Pressable accessibilityRole="tab" accessibilityLabel={tabLabel(tab, labels)}
    accessibilityState={{ selected: active }} onPress={() => onSelect(tab.id)}
    style={({ pressed, hovered, focused }) => [styles.sideTab, wide ? styles.sideTabWide : styles.sideTabNarrow, {
      backgroundColor: active ? palette.tabActive || palette.border
        : pressed || hovered ? palette.hoverDim || palette.surface : 'transparent',
    }, focused && palette.focusStyle]}>
    {tab.icon ? <Icon spec={tab.icon} color={color} size={wide ? 20 : 16} /> : null}
    <Text style={[styles.sideTabText, { color, fontSize: wide ? 14 : 12 }]}>{tabLabel(tab, labels)}</Text>
  </Pressable>;
}

function TabButton({ tab, active, onSelect, palette, labels }) {
  return <Pressable accessibilityRole="tab" accessibilityLabel={tabLabel(tab, labels)}
    accessibilityState={{ selected: active }} onPress={() => onSelect(tab.id)}
    style={({ pressed, focused }) => [styles.tab, {
      backgroundColor: active ? palette.surfaceStrong : pressed ? palette.surfaceMuted : 'transparent',
      borderColor: active ? palette.accent : palette.border,
    }, focused && palette.focusStyle]}>
    <Text style={[styles.tabText, { color: active ? palette.text : palette.textMuted }]}>
      {tabLabel(tab, labels)}
    </Text>
  </Pressable>;
}

function EmptyRow({ text, palette }) {
  return <Text style={[styles.empty, { color: palette.textSecondary }]}>{text}</Text>;
}

function TagRow({ tag, palette, labels, onToggle }) {
  return <View style={[styles.row, { backgroundColor: palette.surfaceStrong }]}>
    <View style={styles.rowText}>
      <Text style={[styles.rowTitle, { color: palette.text }]}>{tag.name}</Text>
      {tag.error ? <Text accessibilityRole="alert" style={[styles.rowError, { color: palette.danger }]}>{tag.error}</Text> : null}
    </View>
    <Button label={tag.hasTag ? labels.remove : labels.add} tone={tag.hasTag ? 'primary' : 'surface'}
      busy={tag.pending} disabled={tag.pending} accessibilityLabel={
        tag.hasTag ? `${labels.remove} ${tag.name}` : `${labels.add} ${tag.name}`
      } onPress={() => onToggle?.(tag)} />
  </View>;
}

function TagsBody({ tab, palette, labels, onTagToggle, onTagCreate }) {
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const tags = tab.tags || [];
  return <View style={styles.stack}>
    {tags.length === 0 ? <EmptyRow text={labels.noTags} palette={palette} /> : null}
    {tags.map(tag => <TagRow key={tag.id} tag={tag} palette={palette} labels={labels}
      onToggle={onTagToggle} />)}
    <View style={styles.inline}>
      <View style={styles.grow}>
        <FormTextField label={labels.tags} value={draft} onChangeText={value => { setDraft(value); setError(''); }}
          placeholder={labels.newTag} palette={palette} />
      </View>
      <Button label={labels.addTag} busy={busy} disabled={busy || !draft.trim()} onPress={async () => {
        setBusy(true);
        setError('');
        try {
          await onTagCreate?.(draft.trim());
          setDraft('');
        } catch (failure) {
          setError(failure.message || labels.tagFailed);
        }
        setBusy(false);
      }} palette={palette} />
    </View>
    {error ? <FormError message={error} palette={palette} /> : null}
  </View>;
}

function MetadataBody({ tab, palette, labels, onArtworkSave }) {
  const [imageUrl, setImageUrl] = useState(tab.imageUrl || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { setImageUrl(tab.imageUrl || ''); }, [tab.imageUrl]);
  return <View style={styles.stack}>
    {(tab.fields || []).map(field => <View key={field.label} style={styles.detailRow}>
      <Text style={[styles.detailLabel, { color: palette.textMuted }]}>{field.label}</Text>
      <Text style={[styles.detailValue, { color: palette.text }]}>{field.value}</Text>
    </View>)}
    <View style={styles.inline}>
      <View style={styles.grow}>
        <FormTextField label={labels.artwork} value={imageUrl} editable={Boolean(tab.canEditArtwork)}
          onChangeText={value => { setImageUrl(value); setError(''); }} palette={palette} />
      </View>
      <Button label={labels.saveArtwork} busy={busy} disabled={busy || !tab.canEditArtwork}
        onPress={async () => {
          setBusy(true);
          setError('');
          try {
            await onArtworkSave?.(imageUrl.trim());
          } catch (failure) {
            setError(failure.message || labels.artworkFailed);
          }
          setBusy(false);
        }} palette={palette} />
    </View>
    {!tab.canEditArtwork ? <Text style={[styles.help, { color: palette.textMuted }]}>{labels.artworkUnavailable}</Text> : null}
    {error ? <FormError message={error} palette={palette} /> : null}
  </View>;
}

function CollectionBody({ tab, palette, labels }) {
  const entries = tab.entries || [];
  if (!entries.length) return <EmptyRow text={labels.noCollection} palette={palette} />;
  return <View style={styles.stack}>
    {entries.map(entry => <View key={entry.id} style={[styles.row, { backgroundColor: palette.surfaceStrong }]}>
      <View style={styles.rowText}>
        <Text style={[styles.rowTitle, { color: palette.text }]}>{entry.title}</Text>
        {entry.detail ? <Text style={[styles.rowDetail, { color: palette.textSecondary }]}>{entry.detail}</Text> : null}
      </View>
      {entry.date ? <Text style={[styles.rowDate, { color: palette.textMuted }]}>{entry.date}</Text> : null}
    </View>)}
  </View>;
}

function PlaysBody({ tab, palette, labels }) {
  const entries = tab.entries || [];
  if (!entries.length) return <EmptyRow text={labels.noPlays} palette={palette} />;
  return <View style={styles.stack}>
    {entries.map(entry => <View key={entry.id} style={[styles.row, { backgroundColor: palette.surfaceStrong }]}>
      <View style={styles.rowText}>
        <Text style={[styles.rowTitle, { color: palette.text }]}>{entry.title}</Text>
        {entry.detail ? <Text style={[styles.rowDetail, { color: palette.textSecondary }]}>{entry.detail}</Text> : null}
      </View>
      {entry.date ? <Text style={[styles.rowDate, { color: palette.textMuted }]}>{entry.date}</Text> : null}
    </View>)}
  </View>;
}

function TabHeading({ title, help, palette, large = false }) {
  return <View style={styles.heading}>
    <Text accessibilityRole="header" style={[large ? styles.headingLarge : styles.headingSmall, {
      color: palette.textSecondary }]}>{title}</Text>
    {help ? <Text style={[large ? styles.headingHelpLarge : styles.headingHelp, { color: palette.textMuted }]}>{help}</Text> : null}
  </View>;
}

function StatusHistoryBody({ tab, palette, labels }) {
  const changes = tab.changes || [];
  return <View style={styles.stack}>
    <TabHeading title={labels.statusHistory} help={labels.statusHistoryHelp} palette={palette} />
    {!changes.length ? <EmptyRow text={labels.noStatusChanges} palette={palette} /> : null}
    {changes.map(change => <View key={change.id} style={[styles.historyRow, { backgroundColor: palette.surfaceStrong }]}>
      <View style={styles.historyTop}>
        <Text style={[styles.historyTitle, { color: palette.text }]}>
          {change.old ? `${change.old} → ` : ''}{change.next || labels.noStatus}
        </Text>
        {change.date ? <Text style={[styles.historyDate, { color: palette.textMuted }]}>{change.date}</Text> : null}
      </View>
      <Text style={[styles.historyReason, { color: palette.textSecondary }]}>
        {change.reason ? `by ${change.reason}` : labels.sourceNotRecorded}
      </Text>
    </View>)}
  </View>;
}

function DiscoverBody({ tab, palette, labels, onDiscoverToggle }) {
  const initial = tab.hidden ? 'hidden' : 'visible';
  const [value, setValue] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { setValue(initial); }, [initial]);
  const changed = value !== initial;
  return <View style={styles.stack}>
    <TabHeading large title={labels.discoverTitle || labels.discover}
      help={labels.discoverHelp} palette={palette} />
    <View style={[styles.panel, { backgroundColor: palette.surfaceStrong }]}>
      <View style={styles.panelTop}>
        <Text style={[styles.panelLabel, { color: palette.textSecondary }]}>{labels.discoverStatus || 'Status'}</Text>
        <Text style={[styles.panelHint, { color: palette.textMuted }]}>
          {tab.hidden ? labels.currentlyHidden : labels.currentlyVisible}
        </Text>
      </View>
      <SelectField labelHidden filter label={labels.discoverStatus || 'Status'} value={value}
        options={[{ value: 'visible', label: labels.discoverVisible || 'Visible' },
          { value: 'hidden', label: labels.discoverHiddenOption || 'Hidden' }]}
        palette={{ ...palette, surfaceStrong: palette.surface, border: palette.inputBorder || palette.border }}
        onChange={event => setValue(event.target.value)} />
    </View>
    <View style={styles.panelActions}>
      <Button label={labels.save || 'Save'} tone={changed ? 'primary' : 'surface'} busy={busy}
        disabled={busy || !tab.canToggle || !changed} onPress={async () => {
          setBusy(true);
          setError('');
          try {
            await onDiscoverToggle?.(value === 'hidden', tab.itemId);
          } catch (failure) {
            setError(failure.message || labels.discoverFailed);
          }
          setBusy(false);
        }} palette={palette} />
    </View>
    {error ? <FormError message={error} palette={palette} /> : null}
  </View>;
}

function TabBody({ tab, palette, labels, handlers }) {
  if (!tab || tab.id === 'general') return handlers.generalContent || null;
  if (tab.content) return tab.content;
  if (tab.status === 'loading') return <FormStatus message={labels.loading} tone="loading" palette={palette} />;
  if (tab.status === 'error') {
    return <View style={styles.stack}>
      <FormError message={tab.error || labels.loadFailed} palette={palette} />
      <Button label={labels.retry} tone="surface" onPress={() => handlers.onRetry?.(tab.id)} palette={palette} />
    </View>;
  }
  if (tab.kind === 'tags') return <TagsBody tab={tab} palette={palette} labels={labels}
    onTagToggle={handlers.onTagToggle} onTagCreate={handlers.onTagCreate} />;
  if (tab.kind === 'metadata') return <MetadataBody tab={tab} palette={palette} labels={labels}
    onArtworkSave={handlers.onArtworkSave} />;
  if (tab.kind === 'collection') return <CollectionBody tab={tab} palette={palette} labels={labels} />;
  if (tab.kind === 'plays') return <PlaysBody tab={tab} palette={palette} labels={labels} />;
  if (tab.kind === 'status-history') return <StatusHistoryBody tab={tab} palette={palette} labels={labels} />;
  if (tab.kind === 'discover') return <DiscoverBody tab={tab} palette={palette} labels={labels}
    onDiscoverToggle={handlers.onDiscoverToggle} />;
  return null;
}

export function TrackTabs({
  tabs = [],
  activeId = 'general',
  onChange,
  labels: suppliedLabels,
  palette: suppliedPalette,
  generalContent = null,
  onRetry,
  onTagToggle,
  onTagCreate,
  onArtworkSave,
  onDiscoverToggle,
  sidebar = false,
}) {
  const labels = labelsFor(suppliedLabels);
  const palette = resolvePalette(suppliedPalette);
  const { width } = useWindowDimensions();
  const allTabs = tabs.some(tab => tab.id === 'general')
    ? tabs : [{ id: 'general', label: labels.general }, ...tabs];
  const active = allTabs.find(tab => tab.id === activeId) || allTabs[0];
  const body = <TabBody tab={active} palette={palette} labels={labels} handlers={{
    generalContent, onRetry, onTagToggle, onTagCreate, onArtworkSave, onDiscoverToggle,
  }} />;
  if (sidebar) {
    const wide = width >= 640;
    return <View style={[styles.sideRoot, wide && styles.sideRootWide]}>
      <View style={[wide ? styles.aside : styles.asideNarrow, {
        backgroundColor: palette.background, borderColor: palette.border,
      }]}>
        {allTabs.map(tab => <SideTab key={tab.id} tab={tab} active={tab.id === active.id}
          onSelect={onChange} palette={palette} labels={labels} wide={wide} />)}
      </View>
      <ScrollView keyboardShouldPersistTaps="handled" style={styles.sideBody}
        contentContainerStyle={[styles.sideBodyContent, wide && styles.sideBodyWide]}>{body}</ScrollView>
    </View>;
  }
  return <View style={styles.root}>
    <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.nav}
      contentContainerStyle={styles.navContent}>
      {allTabs.map(tab => <TabButton key={tab.id} tab={tab} active={tab.id === active.id}
        onSelect={onChange} palette={palette} labels={labels} />)}
    </ScrollView>
    <View style={styles.body}>{body}</View>
  </View>;
}

const styles = StyleSheet.create({
  heading: { gap: 4, marginBottom: 4 },
  headingSmall: { fontSize: 14, fontWeight: '500' },
  headingLarge: { fontSize: 18, fontWeight: '500' },
  headingHelp: { fontSize: 12 },
  headingHelpLarge: { fontSize: 14 },
  historyRow: { borderRadius: 8, paddingHorizontal: 16, paddingVertical: 12, gap: 4 },
  historyTop: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'baseline', justifyContent: 'space-between', columnGap: 12 },
  historyTitle: { fontSize: 14 },
  historyDate: { fontSize: 12 },
  historyReason: { fontSize: 12 },
  panel: { borderRadius: 6, padding: 16, gap: 16 },
  panelTop: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  panelLabel: { fontSize: 14, fontWeight: '500' },
  panelHint: { fontSize: 12 },
  panelActions: { flexDirection: 'row', justifyContent: 'flex-end' },
  sideRoot: { flexShrink: 1, minHeight: 0 },
  sideRootWide: { flexDirection: 'row', minHeight: 576 },
  aside: { width: 224, flexShrink: 0, padding: 12, gap: 4, borderRightWidth: 1 },
  asideNarrow: { flexDirection: 'row', padding: 8, borderBottomWidth: 1 },
  sideTab: { flexDirection: 'row', alignItems: 'center', borderRadius: 8 },
  sideTabWide: { gap: 12, paddingHorizontal: 16, paddingVertical: 12 },
  sideTabNarrow: { flex: 1, justifyContent: 'center', gap: 8, paddingHorizontal: 12, paddingVertical: 8 },
  sideTabText: { fontWeight: '500' },
  sideBody: { flex: 1, minWidth: 0 },
  sideBodyContent: { padding: 16, gap: 12 },
  sideBodyWide: { padding: 24 },
  root: { gap: 12 },
  nav: { flexGrow: 0 },
  navContent: { flexDirection: 'row', gap: 8, paddingVertical: 2 },
  tab: { minHeight: 34, borderWidth: 1, borderRadius: 17, paddingHorizontal: 12,
    alignItems: 'center', justifyContent: 'center' },
  tabText: { fontSize: 12, fontWeight: '600' },
  body: { gap: 12 },
  stack: { gap: 10 },
  empty: { fontSize: 13, lineHeight: 19, paddingVertical: 8 },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    gap: 10, borderRadius: 6, padding: 10 },
  rowText: { flexShrink: 1, minWidth: 0, gap: 2 },
  rowTitle: { fontSize: 13, fontWeight: '600', lineHeight: 18 },
  rowDetail: { fontSize: 12, lineHeight: 17 },
  rowDate: { fontSize: 11, fontWeight: '500' },
  rowError: { fontSize: 11, lineHeight: 16 },
  inline: { flexDirection: 'row', alignItems: 'flex-end', gap: 8 },
  grow: { flex: 1, minWidth: 0 },
  detailRow: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 },
  detailLabel: { fontSize: 12, fontWeight: '600' },
  detailValue: { flexShrink: 1, fontSize: 12, textAlign: 'right' },
  help: { fontSize: 12, lineHeight: 17 },
});
