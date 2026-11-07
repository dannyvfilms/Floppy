import React from 'react';
import { ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { Button } from './Button';
import { FormError, FormHeader, FormSelect, FormStatus } from './MediaCardFormControls';
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
  onClose,
  showHeader = true,
  closeRef,
  nativeID,
}) {
  const labels = { ...DEFAULT_LABELS, ...(suppliedLabels || {}) };
  const palette = { ...DEFAULT_PALETTE, ...(suppliedPalette || {}) };
  const { height } = useWindowDimensions();
  const shown = model ? visibleLists(model, tag) : [];
  const count = model ? listsCount(model, membership) : 0;
  const countLabel = listsCountLabel(labels, count);
  const tagOptions = model?.tags?.length
    ? [{ value: ALL_LISTS, label: labels.allLists }, ...model.tags.map(entry => ({ value: entry, label: entry }))]
    : [];

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
});
