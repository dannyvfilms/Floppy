import React, { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { actionIcons } from './actionIcons';
import { Icon } from './Icon';
import { Modal } from './Modal';

// Filter and sort toolbar for a person's filmography (status-free: rated,
// collected, department, year, genre, sort and direction), the same controls
// the web page's filter toolbar offers. Props only: the adapter owns the
// request and passes back the chosen values through `onChange`.

const copyDefaults = {
  sort: 'Sort',
  direction: 'Direction',
  asc: 'Ascending',
  desc: 'Descending',
  rating: 'Rating',
  collection: 'Collection',
  department: 'Department',
  year: 'Year',
  genre: 'Genre',
  all: 'All',
  rated: 'Rated',
  notRated: 'Not Rated',
  collected: 'Collected',
  notCollected: 'Not Collected',
  any: 'Any',
};

function Group({ label, options, value, onSelect, palette }) {
  if (!options.length) return null;
  return <View style={styles.group}>
    <Text style={[styles.groupLabel, { color: palette.textMuted }]}>{label}</Text>
    <View style={styles.pills}>
      {options.map(option => {
        const active = option.value === value;
        return <Pressable key={option.value} accessibilityRole="button"
          accessibilityLabel={`${label}: ${option.label}`}
          accessibilityState={{ selected: active }}
          onPress={() => onSelect(option.value)}
          style={[styles.pill, {
            backgroundColor: active ? palette.accentStrong || palette.accent : palette.surface,
            borderColor: active ? palette.accentStrong || palette.accent : palette.border,
          }]}>
          <Text numberOfLines={1} style={[styles.pillText, {
            color: active ? palette.accentContrast || palette.text : palette.textSecondary,
          }]}>{option.label}</Text>
        </Pressable>;
      })}
    </View>
  </View>;
}

// The web page shows two dropdown labels, the filter menu ("All") and the sort
// ("Release Date"); each opens a sheet holding the option groups.
export function PeopleToolbar({ filters, labels = {}, palette = {}, onChange, testID }) {
  const [open, setOpen] = useState(null);
  if (!filters) return null;
  const copy = { ...copyDefaults, ...(labels || {}) };
  const choose = key => value => onChange?.({ [key]: value });
  const anyOption = { value: '', label: copy.any };
  const sortChoices = filters.sortChoices || [];
  const sortLabel = sortChoices.find(choice => choice.value === filters.sort)?.label || copy.sort;
  const active = ['rating', 'collection'].filter(key => filters[key] && filters[key] !== 'all').length
    + ['department', 'year', 'genre'].filter(key => filters[key]).length;
  const trigger = (key, label) => <Pressable accessibilityRole="button"
    accessibilityLabel={label} accessibilityState={{ expanded: open === key }}
    onPress={() => setOpen(key)} style={styles.trigger}>
    <Text numberOfLines={1} style={[styles.triggerText, { color: palette.textSecondary }]}>{label}</Text>
    <Icon spec={actionIcons.chevronDown} color={palette.textSecondary} size={14} />
  </Pressable>;
  const sheet = (key, title, children) => <Modal visible={open === key} transparent
    animationType="fade" onRequestClose={() => setOpen(null)}>
    <View style={[styles.overlay, { backgroundColor: palette.overlay || 'rgba(0,0,0,0.55)' }]}>
      <Pressable accessibilityRole="button" accessibilityLabel={copy.close || 'Close'}
        onPress={() => setOpen(null)} style={styles.backdrop} />
      <View style={[styles.sheet, { backgroundColor: palette.surface, borderColor: palette.border }]}>
        <Text accessibilityRole="header" style={[styles.sheetTitle, { color: palette.text }]}>{title}</Text>
        <ScrollView contentContainerStyle={styles.sheetBody}>{children}</ScrollView>
      </View>
    </View>
  </Modal>;
  return <View style={styles.root} testID={testID}>
    <View style={styles.row}>
      {trigger('filters', active ? `${copy.filters || 'Filters'} (${active})` : copy.all)}
      {trigger('sort', `${sortLabel} ${filters.direction === 'asc' ? '\u2191' : '\u2193'}`)}
    </View>
    {sheet('sort', copy.sort, <>
      <Group label={copy.sort} palette={palette} value={filters.sort}
        options={sortChoices.map(choice => ({ value: choice.value, label: choice.label }))}
        onSelect={choose('sort')} />
      <Group label={copy.direction} palette={palette} value={filters.direction}
        options={[{ value: 'desc', label: copy.desc }, { value: 'asc', label: copy.asc }]}
        onSelect={choose('direction')} />
    </>)}
    {sheet('filters', copy.filters || 'Filters', <>
      <Group label={copy.rating} palette={palette} value={filters.rating}
        options={[
          { value: 'all', label: copy.all },
          { value: 'rated', label: copy.rated },
          { value: 'not_rated', label: copy.notRated },
        ]}
        onSelect={choose('rating')} />
      <Group label={copy.collection} palette={palette} value={filters.collection}
        options={[
          { value: 'all', label: copy.all },
          { value: 'collected', label: copy.collected },
          { value: 'not_collected', label: copy.notCollected },
        ]}
        onSelect={choose('collection')} />
      <Group label={copy.department} palette={palette} value={filters.department}
        options={filters.departments?.length
          ? [anyOption, ...filters.departments.map(value => ({ value, label: value }))]
          : []}
        onSelect={choose('department')} />
      <Group label={copy.year} palette={palette} value={filters.year}
        options={filters.years?.length
          ? [anyOption, ...filters.years.map(year => ({ value: year.value, label: year.label }))]
          : []}
        onSelect={choose('year')} />
      <Group label={copy.genre} palette={palette} value={filters.genre}
        options={filters.genres?.length
          ? [anyOption, ...filters.genres.map(value => ({ value, label: value }))]
          : []}
        onSelect={choose('genre')} />
    </>)}
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: 10, minWidth: 0 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 20 },
  trigger: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 4 },
  triggerText: { fontSize: 16 },
  overlay: { flex: 1, justifyContent: 'flex-end' },
  backdrop: { ...StyleSheet.absoluteFillObject },
  sheet: { maxHeight: '80%', borderTopLeftRadius: 16, borderTopRightRadius: 16, borderWidth: 1, padding: 20, gap: 12 },
  sheetTitle: { fontSize: 18, fontWeight: '700' },
  sheetBody: { gap: 14, paddingBottom: 8 },
  group: { gap: 4, minWidth: 0 },
  groupLabel: { fontSize: 12, fontWeight: '600', lineHeight: 16 },
  pills: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, paddingRight: 8 },
  pill: { borderWidth: 1, borderRadius: 9999, paddingHorizontal: 12, paddingVertical: 6, maxWidth: 220 },
  pillText: { fontSize: 13, lineHeight: 18, fontWeight: '500' },
});
