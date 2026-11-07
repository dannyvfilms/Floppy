import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { TagIndex } from '../ui/TagManagement';
import { PageHeading, PageState } from './PageChrome';

const defaultLabels = {
  name: 'Name',
  mostUsed: 'Most used',
  empty: 'No tags yet. Add tags to items from their detail page to see them here.',
  loading: 'Loading tags…',
  errorTitle: 'Tags could not load',
  errorBody: 'Please try again.',
  retry: 'Try again',
};

// One Tags page composition for web and native: heading, sort control, and the
// shared tag index with its per-media counts, delete action and empty state.
// Both adapters pass the same tag records and named intents, so section order
// and copy cannot drift.
export function TagsPageView({
  title = 'Tags',
  subtitle = "All tags you've created, with how many items use each one",
  tags = [],
  sort = 'name',
  labels = {},
  palette = {},
  onSortChange,
  onDelete,
  onOpenType,
  state = 'ready',
  error,
  onRetry,
  testID,
}) {
  const copy = { ...defaultLabels, ...(labels || {}) };
  const sorts = [
    { value: 'name', label: copy.name },
    { value: 'count', label: copy.mostUsed },
  ];
  return <View style={styles.root} testID={testID}>
    <PageHeading
      title={title}
      subtitle={subtitle}
      palette={palette}
      actions={<View style={styles.sorts}>
        {sorts.map(option => <Pressable
          key={option.value}
          accessibilityRole="button"
          accessibilityState={{ selected: sort === option.value }}
          accessibilityLabel={option.label}
          onPress={() => onSortChange?.(option.value)}
          style={[styles.sortButton, {
            backgroundColor: sort === option.value
              ? palette.border || '#3f3f46'
              : 'transparent',
          }]}>
          <Text style={[styles.sortText, {
            color: sort === option.value
              ? palette.text || '#fafafa'
              : palette.textMuted || '#a1a1aa',
          }]}>{option.label}</Text>
        </Pressable>)}
      </View>} />
    <PageState
      state={state}
      labels={copy}
      palette={palette}
      error={error}
      onRetry={onRetry} />
    {state === 'ready' ? <TagIndex
      tags={tags}
      sort={sort}
      palette={palette}
      showControls={false}
      emptyText={copy.empty}
      onSortChange={onSortChange}
      onDelete={onDelete}
      onOpenType={onOpenType} /> : null}
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: 16, minWidth: 0 },
  sorts: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  sortButton: { borderRadius: 6, paddingHorizontal: 12, paddingVertical: 6 },
  sortText: { fontSize: 13, fontWeight: '600' },
});
