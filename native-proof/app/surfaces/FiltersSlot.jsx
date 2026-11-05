import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { FilterBar } from '../../../frontend/ui/FilterBar';
import { palette, radius, spacing } from '../theme';

export const surface = {
  id: 'FILTERS',
  title: 'Filter toolbar and saved views',
  where: 'Library, lists, History and Calendar',
  status: 'in_progress',
  note: 'The shared filter bar renders media type, status, sort, view and range controls with local selection, busy feedback, clear defaults and accessible labels.',
};

const filterPalette = {
  background: palette.background,
  surface: palette.surface,
  surfaceStrong: palette.surfaceStrong,
  surfaceHover: palette.surfaceMuted,
  border: palette.border,
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  accent: palette.accent,
  accentStrong: palette.accentStrong,
  accentText: '#ffffff',
  danger: palette.danger,
  disabled: palette.textMuted,
  overlay: 'rgba(24, 24, 27, 0.78)',
  radius: radius.md,
};

const options = {
  mediaTypes: [
    { value: 'movie', label: 'Movies' },
    { value: 'tv', label: 'Shows' },
    { value: 'anime', label: 'Anime' },
    { value: 'book', label: 'Books' },
    { value: 'game', label: 'Games' },
  ],
  statuses: [
    { value: 'planning', label: 'Planning' },
    { value: 'in_progress', label: 'In progress' },
    { value: 'paused', label: 'Paused' },
    { value: 'completed', label: 'Completed' },
    { value: 'dropped', label: 'Dropped' },
  ],
  sorts: [
    { value: 'added', label: 'Date added' },
    { value: 'title', label: 'Title' },
    { value: 'release', label: 'Release date' },
    { value: 'rating', label: 'Rating' },
    { value: 'last_watched', label: 'Last watched' },
  ],
  views: [
    { value: 'grid', label: 'Grid' },
    { value: 'table', label: 'Table' },
  ],
  savedViews: [
    { id: 'recent', label: 'Recently added' },
    { id: 'unrated', label: 'Unrated' },
    { id: 'continue', label: 'Continue watching' },
  ],
  ranges: [
    { key: 'rating', label: 'Rating', type: 'number', placeholder: '0–10' },
    {
      key: 'dateAdded',
      label: 'Date added',
      type: 'date',
      placeholder: 'YYYY-MM-DD',
      relative: true,
      units: [
        { value: 'days', label: 'Days' },
        { value: 'weeks', label: 'Weeks' },
        { value: 'months', label: 'Months' },
        { value: 'years', label: 'Years' },
      ],
    },
  ],
};

function defaultFilters() {
  return {
    mediaTypes: ['movie', 'tv'],
    statuses: ['in_progress'],
    sort: 'added',
    direction: 'desc',
    view: 'grid',
    ranges: {
      rating: { from: '', to: '', within: '', unit: 'days' },
      dateAdded: { from: '', to: '', within: '7', unit: 'days' },
    },
  };
}

export default function FiltersSlot() {
  const [filters, setFilters] = useState(defaultFilters);
  const [savedView, setSavedView] = useState('');
  const [busy, setBusy] = useState(false);

  function markBusy() {
    setBusy(true);
    setTimeout(() => setBusy(false), 450);
  }

  function change(intent) {
    if (intent.type === 'clear') {
      setFilters(defaultFilters());
      setSavedView('');
      markBusy();
      return;
    }
    if (intent.type === 'toggle') {
      setFilters((current) => {
        const values = current[intent.key] || [];
        return {
          ...current,
          [intent.key]: values.includes(intent.value)
            ? values.filter((value) => value !== intent.value)
            : [...values, intent.value],
        };
      });
      markBusy();
      return;
    }
    if (intent.type === 'set') {
      setFilters((current) => ({ ...current, [intent.key]: intent.value }));
      markBusy();
      return;
    }
    if (intent.type === 'range') {
      setFilters((current) => ({
        ...current,
        ranges: { ...current.ranges, [intent.key]: intent.value },
      }));
      markBusy();
      return;
    }
    if (intent.type === 'savedView') {
      setSavedView(intent.value);
      markBusy();
    }
  }

  const viewOptions = options.savedViews.map((view) => ({ ...view, active: view.id === savedView }));
  const currentOptions = { ...options, savedViews: viewOptions };

  return <View style={styles.group}>
    <FilterBar
      filters={filters}
      options={currentOptions}
      palette={filterPalette}
      busy={busy}
      resultCount={124}
      labels={{
        filters: 'Filters',
        status: 'Status',
        sort: 'Sort',
        view: 'View',
        range: 'Range',
        savedViews: 'Saved views',
      }}
      onChange={change} />
    <Text style={styles.caption}>
      {savedView ? `Saved view: ${viewOptions.find((view) => view.id === savedView)?.label}` : 'Library filters · local proof state'}
    </Text>
  </View>;
}

const styles = StyleSheet.create({
  group: { gap: spacing.sm },
  caption: { color: palette.textMuted, fontSize: 12 },
});
