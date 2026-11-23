import React from 'react';
import { StyleSheet, View } from 'react-native';
import { FilterDropdown } from '../ui/controls/Menu';
import { FilterToolbar } from '../ui/controls/Navigation';

/**
 * Anime Seasons filters: one shared FilterDropdown per field (season, year,
 * format, sort) in the shared FilterToolbar. The caller owns navigation; a
 * change reports `{ name, value }` and the browser adapter loads the new URL.
 */
export function SeasonFilters({ label, filters = [], palette, onChange }) {
  return <FilterToolbar label={label} style={styles.toolbar}>
    {filters.map(filter => <View key={filter.name} style={styles.field}>
      <FilterDropdown id={`anime-season-${filter.name}`} name={filter.name}
        label={filter.label} options={filter.options} value={filter.value}
        palette={palette}
        onChange={event => {
          if (event.target.value !== filter.value) onChange?.(event.target);
        }} />
    </View>)}
  </FilterToolbar>;
}

const styles = StyleSheet.create({
  toolbar: { gap: 8 },
  field: { minWidth: 120 },
});
