import React, { useState } from 'react';
import { ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { Button } from './Button';
import { CollectionGroup, CollectionRow, CollectionTextRow } from './CollectionCopies';
import { sectionSpacing } from './sectionSpacing';
import { FormError, FormHeader, FormSelect, FormStatus, FormTextField } from './MediaCardFormControls';
import { ALL_LISTS, listsCount, listsCountLabel, visibleLists } from './mediaCardForms';

const DEFAULT_LABELS = {
  title: 'Lists',
  close: 'Close',
  loading: 'Loading',
  loadFailed: "Couldn't load your lists.",
  retry: 'Try again',
  filterByTag: 'Filter by tag',
  allLists: 'All lists',
  countOne: 'On %s list',
  countMany: 'On %s lists',
  add: 'Add',
  remove: 'Remove',
  addTo: 'Add item to %s',
  removeFrom: 'Remove item from %s',
  emptyTag: 'No lists with this tag.',
  emptyLists: "You haven't created any lists yet.",
  create: 'Create list',
  createName: 'Name',
  createPlaceholder: 'Movie night',
  createSubmit: 'Create',
  createFailed: "Couldn't create this list. Please try again.",
  cancel: 'Cancel',
};

const DEFAULT_PALETTE = {
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  border: '#3f3f46',
  danger: '#f87171',
  focusStyle: {},
};

function text(labels, key, value = '') {
  return String(labels[key] || DEFAULT_LABELS[key] || '').replace('%s', String(value));
}

export function ListsForm({
  model,
  membership = {},
  tag = ALL_LISTS,
  status = 'ready',
  pending = {},
  errors = {},
  labels: suppliedLabels,
  palette: suppliedPalette,
  onTagChange,
  onToggle,
  onRetry,
  onCreate,
  onClose,
  showHeader = true,
  embedded = false,
  closeRef,
  nativeID,
}) {
  const labels = { ...DEFAULT_LABELS, ...(suppliedLabels || {}) };
  const palette = { ...DEFAULT_PALETTE, ...(suppliedPalette || {}) };
  const { height, width } = useWindowDimensions();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState('');
  const shown = model ? visibleLists(model, tag) : [];
  const count = model ? listsCount(model, membership) : 0;
  const countLabel = listsCountLabel(labels, count);
  const tagOptions = model?.tags?.length
    ? [{ value: ALL_LISTS, label: labels.allLists }, ...model.tags.map(entry => ({ value: entry, label: entry }))]
    : [];

  async function submitCreate() {
    const trimmed = name.trim();
    if (!trimmed || createBusy) return;
    setCreateBusy(true);
    setCreateError('');
    try {
      await onCreate(trimmed);
      setName('');
      setCreating(false);
    } catch (error) {
      setCreateError(error?.message || text(labels, 'createFailed'));
    }
    setCreateBusy(false);
  }

  const ghost = { background: 'transparent', pressed: palette.surfaceStrong, hovered: palette.surfaceStrong,
    text: palette.textSecondary, border: palette.border };
  // Same footer as the Collection modal: Cancel beside a full-width primary action.
  const createFooter = status === 'ready' && model && onCreate ? creating ? <View style={styles.footerStack}>
    <FormTextField label={labels.createName} value={name} onChangeText={setName}
      placeholder={labels.createPlaceholder} error={createError} palette={palette} />
    <View style={styles.footer}>
      <View style={styles.footerButton}><Button label={labels.cancel} tone="ghost" size="lg" width="full"
        disabled={createBusy} onPress={() => { setCreating(false); setCreateError(''); }}
        palette={{ ...palette, ghost }} /></View>
      <View style={styles.footerButton}><Button label={labels.createSubmit} size="lg" width="full"
        busy={createBusy} disabled={createBusy || !name.trim()} palette={palette} onPress={submitCreate} /></View>
    </View>
  </View> : <View style={styles.footer}>
    <View style={styles.footerButton}><Button label={labels.create} size="lg" width="full"
      palette={palette} onPress={() => setCreating(true)} /></View>
  </View> : null;

  // Native sheet: the same structure as the Collection and Tracking sheets. Grouped rows scroll, and the
  // Cancel and primary footer sits below them, outside the scroll (see CollectionCopyDialog `embedded`).
  if (embedded) {
    const ready = status === 'ready' && model;
    const ghostFooter = { ...palette, ghost };
    return <View nativeID={nativeID} style={styles.embedded}>
      <ScrollView keyboardShouldPersistTaps="handled" style={styles.scroll}
        contentContainerStyle={{ gap: sectionSpacing(width), paddingBottom: 8 }}>
        {status === 'loading' ? <FormStatus message={labels.loading} tone="loading" palette={palette} /> : null}
        {status === 'error' ? <View style={styles.stack}>
          <FormError message={text(labels, 'loadFailed')} palette={palette} />
          <Button label={labels.retry} tone="surface" onPress={onRetry} palette={palette} />
        </View> : null}
        {ready && tagOptions.length ? <FormSelect label={labels.filterByTag} value={tag} options={tagOptions}
          onChange={value => onTagChange?.(value)} palette={palette} /> : null}
        {ready && shown.length ? <CollectionGroup title={count > 0 ? countLabel : undefined} palette={palette}>
          {shown.map(list => {
            const has = Boolean(membership[list.id]);
            const busy = Boolean(pending[list.id]);
            return <View key={list.id}>
              <CollectionRow label={list.name} palette={palette}>
                <View style={styles.rowAction}>
                  <Button label={busy ? '' : has ? labels.remove : labels.add} tone={has ? 'primary' : 'surface'}
                    busy={busy} disabled={busy} accessibilityLabel={has ? text(labels, 'removeFrom', list.name) : text(labels, 'addTo', list.name)}
                    palette={palette} onPress={() => onToggle?.(list)} />
                </View>
              </CollectionRow>
              {errors[list.id] ? <Text accessibilityRole="alert" style={[styles.rowError, { color: palette.danger }]}>{errors[list.id]}</Text> : null}
            </View>;
          })}
        </CollectionGroup> : null}
        {ready && !shown.length ? <Text style={[styles.empty, { color: palette.textSecondary }]}>
          {model.lists.length ? labels.emptyTag : labels.emptyLists}
        </Text> : null}
        {ready && onCreate && creating ? <CollectionGroup palette={palette}>
          <CollectionTextRow label={labels.createName} value={name} onChangeText={setName}
            placeholder={labels.createPlaceholder} error={createError} palette={palette} />
        </CollectionGroup> : null}
      </ScrollView>
      {ready && onCreate ? <View style={styles.embeddedFooter}>
        <View style={styles.footerButton}><Button label={creating ? labels.cancel : labels.close} tone="ghost" size="lg" width="full"
          disabled={createBusy} palette={ghostFooter}
          onPress={creating ? () => { setCreating(false); setCreateError(''); } : onClose} /></View>
        <View style={styles.footerButton}><Button label={creating ? labels.createSubmit : labels.create} size="lg" width="full"
          palette={palette} busy={createBusy} disabled={createBusy || (creating && !name.trim())}
          onPress={creating ? submitCreate : () => setCreating(true)} /></View>
      </View> : null}
    </View>;
  }

  return <View nativeID={nativeID} style={[styles.card, { backgroundColor: palette.surface, maxHeight: height * 0.86 }]}>
    {showHeader ? <FormHeader title={text(labels, 'title')} closeLabel={labels.close}
      onClose={onClose} closeRef={closeRef} palette={palette} /> : null}
    {status === 'loading' ? <FormStatus message={labels.loading} tone="loading" palette={palette} /> : null}
    {status === 'error' ? <View style={styles.stack}>
      <FormError message={text(labels, 'loadFailed')} palette={palette} />
      <Button label={labels.retry} tone="surface" onPress={onRetry} palette={palette} />
    </View> : null}
    {status === 'ready' && model ? <ScrollView keyboardShouldPersistTaps="handled" style={styles.scroll}
      contentContainerStyle={styles.stack}>
      {tagOptions.length ? <View style={styles.filter}>
        <View style={styles.filterField}>
          <FormSelect label={labels.filterByTag} value={tag} options={tagOptions}
            onChange={value => onTagChange?.(value)} palette={palette} />
        </View>
        {count > 0 ? <Text style={[styles.count, { color: palette.textSecondary }]}>{countLabel}</Text> : null}
      </View> : count > 0 ? <Text style={[styles.count, { color: palette.textSecondary }]}>{countLabel}</Text> : null}
      {shown.map(list => {
        const has = Boolean(membership[list.id]);
        const busy = Boolean(pending[list.id]);
        const actionLabel = has ? text(labels, 'removeFrom', list.name) : text(labels, 'addTo', list.name);
        return <View key={list.id} style={[styles.row, { backgroundColor: palette.surfaceStrong }]}>
          <Text style={[styles.name, { color: palette.text }]}>{list.name}</Text>
          <Button label={busy ? '' : has ? labels.remove : labels.add}
            tone={has ? 'primary' : 'surface'} busy={busy} disabled={busy}
            accessibilityLabel={actionLabel} palette={palette} onPress={() => onToggle?.(list)} />
          {errors[list.id] ? <Text accessibilityRole="alert" style={[styles.rowError, { color: palette.danger }]}>{errors[list.id]}</Text> : null}
        </View>;
      })}
      {shown.length === 0 ? <Text style={[styles.empty, { color: palette.textSecondary }]}>
        {model.lists.length ? labels.emptyTag : labels.emptyLists}
      </Text> : null}
    </ScrollView> : null}
    {createFooter}
  </View>;
}

const styles = StyleSheet.create({
  card: {
    width: '100%', borderRadius: 8, padding: 24, gap: 16,
    shadowColor: '#000000', shadowOpacity: 0.35, shadowRadius: 24, shadowOffset: { width: 0, height: 12 }, elevation: 16,
  },
  scroll: { flexGrow: 0 },
  stack: { gap: 12 },
  filter: { gap: 6 },
  filterField: { minWidth: 0 },
  count: { fontSize: 13 },
  row: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 8, borderRadius: 6, padding: 12 },
  name: { flexShrink: 1, minWidth: 0, fontSize: 14 },
  rowError: { flexBasis: '100%', fontSize: 12, lineHeight: 17 },
  empty: { fontSize: 13 },
  footer: { flexDirection: 'row', gap: 8 },
  embedded: { flex: 1, paddingHorizontal: 16 },
  rowAction: { marginLeft: 'auto', alignSelf: 'center' },
  embeddedFooter: { flexDirection: 'row', gap: 8, paddingTop: 12, paddingBottom: 8 },
  footerStack: { gap: 12 },
  footerButton: { flex: 1 },
});
