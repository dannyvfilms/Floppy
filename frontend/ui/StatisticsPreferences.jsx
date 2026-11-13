import React, { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Button } from './Button';
import { Icon } from './Icon';
import { Modal } from './Modal';
import { SelectField } from './SelectField';
import { actionIcons } from './actionIcons';

// The statistics page's preferences modal and its building/refreshing notice,
// as props-only presentation. The owner loads and saves through
// /api/v1/statistics/preferences/; `values` and `choices` use that payload.
const FIELDS = [
  { key: 'activity_history_view', label: 'Activity History View', options: { heatmap: 'Activity Heatmap', stacked: 'Stacked Bar Chart' } },
  { key: 'duration_format', label: 'Duration Format', options: { hours_minutes: 'Hours and minutes (500h 30min)', long_units: 'Days and hours (20d 20h 30min)' } },
  { key: 'week_start_day', label: 'Week Start Day', options: { monday: 'Monday', sunday: 'Sunday' } },
  { key: 'rating_scale', label: 'Rating Scale', options: { 10: '1-10 stars', 5: '1-5 stars', 0: 'Disabled' } },
];

const ANIME_OPTIONS = [
  { value: false, label: 'Display in TV Shows' },
  { value: true, label: 'Display as Anime' },
];

export function StatisticsPreferencesButton({ palette, label = 'Statistics preferences', onPress }) {
  return <View style={styles.fabRow}>
    <Pressable accessibilityRole="button" accessibilityLabel={label} onPress={onPress}
      style={[styles.fab, { backgroundColor: palette.accentStrong }]}>
      <Icon spec={actionIcons.horizontalSliders} size={20} color={palette.accentText} />
    </Pressable>
  </View>;
}

export function StatisticsPreferencesModal({ open, values, choices = {}, splitAvailable = false, saving = false, error = '', palette, onSave, onClose }) {
  const [draft, setDraft] = useState(values || {});
  useEffect(() => {
    if (open) setDraft(values || {});
  }, [open, values]);
  if (!open) return null;
  const selectPalette = {
    surface: palette.surface,
    surfaceStrong: palette.surfaceStrong,
    border: palette.border,
    text: palette.text,
    textSecondary: palette.textSecondary,
    textMuted: palette.textMuted,
    accent: palette.accentStrong,
    accentText: palette.accentText,
    overlay: palette.overlay,
  };
  return <Modal transparent visible animationType="fade" onRequestClose={onClose}>
    <View style={[styles.overlay, { backgroundColor: palette.overlay }]}>
      <View style={[styles.sheet, { backgroundColor: palette.surface }]} accessibilityViewIsModal>
        <View style={styles.header}>
          <Text style={[styles.title, { color: palette.text }]}>Statistics Preferences</Text>
          <Pressable accessibilityRole="button" accessibilityLabel="Close" onPress={onClose}>
            <Icon spec={actionIcons.x} size={20} color={palette.textMuted} />
          </Pressable>
        </View>
        {FIELDS.map(field => {
          const allowed = choices[field.key] || Object.keys(field.options);
          return <SelectField key={field.key} label={field.label} name={field.key}
            palette={selectPalette}
            options={allowed.map(value => ({ value: String(value), label: field.options[value] || String(value) }))}
            value={String(draft[field.key] ?? '')}
            onChange={event => setDraft(current => ({ ...current, [field.key]: event.target.value }))} />;
        })}
        {splitAvailable ? <>
          <Text style={[styles.help, { color: palette.textMuted }]}>Choose how TV shows tagged as Anime via TVDB appear.</Text>
          <SelectField label="Anime Statistics" name="stats_split_tv_anime" palette={selectPalette}
            options={ANIME_OPTIONS.map(option => ({ value: String(option.value), label: option.label }))}
            value={String(Boolean(draft.stats_split_tv_anime))}
            onChange={event => setDraft(current => ({ ...current, stats_split_tv_anime: event.target.value === 'true' }))} />
        </> : null}
        {error ? <Text style={[styles.error, { color: palette.danger }]}>{error}</Text> : null}
        <Button label={saving ? 'Saving...' : 'Save'} tone="primary" disabled={saving}
          onPress={() => onSave?.({
            ...Object.fromEntries(FIELDS.map(field => [field.key, String(draft[field.key])])),
            ...(splitAvailable ? { stats_split_tv_anime: Boolean(draft.stats_split_tv_anime) } : {}),
          })} />
      </View>
    </View>
  </Modal>;
}

// The web's toast: "Building" on the first build, "Refreshing" afterwards.
export function StatisticsBanner({ building = false, refreshing = false, palette, onDismiss }) {
  if (!building && !refreshing) return null;
  return <View accessibilityLiveRegion="polite"
    style={[styles.banner, { backgroundColor: palette.surface, borderColor: palette.border }]}>
    <Icon spec={actionIcons.info} size={16} color={palette.accent} />
    <Text style={[styles.bannerText, { color: palette.text }]}>
      {building ? 'Building your statistics for the first time...' : 'Refreshing statistics in background...'}
    </Text>
    <Pressable accessibilityRole="button" accessibilityLabel="Dismiss" onPress={onDismiss}>
      <Icon spec={actionIcons.x} size={16} color={palette.textMuted} />
    </Pressable>
  </View>;
}

const styles = StyleSheet.create({
  fabRow: { alignItems: 'flex-end' },
  fab: { width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center' },
  overlay: { flex: 1, justifyContent: 'flex-end' },
  sheet: { borderTopLeftRadius: 16, borderTopRightRadius: 16, padding: 24, gap: 16 },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  title: { fontSize: 18, fontWeight: '600' },
  help: { fontSize: 12 },
  error: { fontSize: 13 },
  banner: { flexDirection: 'row', alignItems: 'center', gap: 8, borderWidth: 1, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 8 },
  bannerText: { flex: 1, fontSize: 14, fontWeight: '500' },
});
