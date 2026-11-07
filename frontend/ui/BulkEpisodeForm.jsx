import React, { useMemo } from 'react';
import { StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { Button } from './Button';
import { DateTimePicker } from './DateTimePicker';
import { FormError, FormField, FormStatus } from './MediaCardFormControls';
import { SelectField } from './SelectField';
import { valueFromDate } from './dateTime';

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
  warning: '#fbbf24',
  radius: 8,
  focusStyle: {},
};

const DEFAULT_LABELS = {
  startDate: 'Start date',
  endDate: 'End date',
  playHandling: 'Play handling',
  distribution: 'Distribution',
  save: 'Save plays',
  saving: 'Saving',
  chooseRange: 'Choose the first and last item to log a bulk play range.',
  invalidRange: 'Choose a valid ordered range to log plays.',
  lockedRange: 'This range is locked to one mapped season.',
  targetDates: 'the target dates within the selected date range',
  evenDistribution: 'an even distribution across the date range',
  fallbackEven: 'Saving will fall back to even distribution.',
  noExisting: 'No existing plays are currently logged in the selected range.',
  noTargetDateOne: '%(count)s selected item has no target date.',
  noTargetDateMany: '%(count)s selected items have no target date.',
  addOne: 'This will add plays for %(count)s ordered item using %(distribution)s.',
  addMany: 'This will add plays for %(count)s ordered items using %(distribution)s.',
  replaceOne: 'This will replace plays for %(count)s ordered item using %(distribution)s.',
  replaceMany: 'This will replace plays for %(count)s ordered items using %(distribution)s.',
  existingReplaceOne: 'This will delete %(count)s existing play in the selected range before adding the new ordered pass.',
  existingReplaceMany: 'This will delete %(count)s existing plays in the selected range before adding the new ordered pass.',
  existingAppendOne: 'This range already has %(count)s logged play. New plays will be appended in order.',
  existingAppendMany: 'This range already has %(count)s logged plays. New plays will be appended in order.',
  season: 'Season',
  episode: 'Episode',
  firstPlay: 'First Play',
  justFinished: 'Just Finished',
  lastPlay: 'Last Play',
  dateTime: {},
};

export function formatBulkTemplate(template, replacements) {
  return String(template || '').replace(/%\(([^)]+)\)s/g, (match, key) => (
    replacements[key] == null ? match : String(replacements[key])
  ));
}

function episodeLabel(episode) {
  return episode.selector_label
    || `E${episode.episode_number} - ${episode.episode_title}`;
}

export function bulkEpisodeSummary(domain, values, labels) {
  const seasonMap = domain?.seasonEpisodeMap || {};
  const episodesFor = season => seasonMap[String(season)] || [];
  const first = episodesFor(values.first_season_number)
    .find(episode => String(episode.episode_number) === String(values.first_episode_number));
  const last = episodesFor(values.last_season_number)
    .find(episode => String(episode.episode_number) === String(values.last_episode_number));
  if (!first || !last) {
    return { count: 0, summary: '', warning: '', summaryText: labels.invalidRange, rangeWarning: '', episodes: [] };
  }
  const episodes = Object.values(seasonMap).flat().filter(
    episode => first.order <= episode.order && episode.order <= last.order,
  );
  if (!episodes.length) {
    return { count: 0, summary: '', warning: '', summaryText: labels.invalidRange, rangeWarning: '', episodes: [] };
  }
  const existing = episodes.reduce(
    (total, episode) => total + (episode.existing_play_count || 0),
    0,
  );
  const distribution = values.distribution_mode === 'air_date'
    ? labels.targetDates
    : labels.evenDistribution;
  const one = episodes.length === 1;
  const template = (values.write_mode === 'replace'
    ? (one ? labels.replaceOne : labels.replaceMany)
    : (one ? labels.addOne : labels.addMany));
  const summaryText = formatBulkTemplate(template, {
    count: episodes.length,
    distribution,
  });
  let rangeWarning = '';
  if (values.distribution_mode === 'air_date') {
    const missing = episodes.filter(episode => !episode.air_date).length;
    if (missing > 0) {
      rangeWarning = formatBulkTemplate(
        missing === 1 ? labels.noTargetDateOne : labels.noTargetDateMany,
        { count: missing },
      );
      if (domain?.missingTargetDateFallbackDistribution === 'even') {
        rangeWarning = `${rangeWarning} ${labels.fallbackEven}`;
      }
    }
  }
  if (!rangeWarning && values.write_mode === 'replace') {
    rangeWarning = existing > 0
      ? formatBulkTemplate(
        existing === 1 ? labels.existingReplaceOne : labels.existingReplaceMany,
        { count: existing },
      )
      : labels.noExisting;
  }
  if (!rangeWarning && values.write_mode === 'add' && existing > 0) {
    rangeWarning = formatBulkTemplate(
      existing === 1 ? labels.existingAppendOne : labels.existingAppendMany,
      { count: existing },
    );
  }
  return {
    count: episodes.length,
    episodes,
    summaryText,
    rangeWarning,
  };
}

export function BulkEpisodeForm({
  model,
  values = {},
  errors = {},
  busy = false,
  labels: suppliedLabels,
  palette: suppliedPalette,
  onChange,
  onSubmit,
}) {
  const labels = { ...DEFAULT_LABELS, ...(suppliedLabels || {}) };
  const palette = { ...DEFAULT_PALETTE, ...(suppliedPalette || {}) };
  const { width } = useWindowDimensions();
  const wide = width >= 720;
  const domain = model?.domain || {};
  const summary = useMemo(
    () => bulkEpisodeSummary(domain, values, labels),
    [domain, values, labels],
  );

  function change(name, value) {
    onChange?.(name, value);
  }

  function changeSeason(side, seasonNumber) {
    const episodes = (domain.seasonEpisodeMap || {})[String(seasonNumber)] || [];
    const episodeField = side === 'first' ? 'first_episode_number' : 'last_episode_number';
    const current = values[episodeField];
    const hasCurrent = episodes.some(
      episode => String(episode.episode_number) === String(current),
    );
    const fallback = side === 'first'
      ? episodes[0]?.episode_number
      : episodes[episodes.length - 1]?.episode_number;
    onChange?.({ [side === 'first' ? 'first_season_number' : 'last_season_number']: seasonNumber, [episodeField]: hasCurrent ? current : (fallback ?? '') });
  }

  function selectedEpisode(side) {
    const season = side === 'first' ? values.first_season_number : values.last_season_number;
    const episode = side === 'first' ? values.first_episode_number : values.last_episode_number;
    return ((domain.seasonEpisodeMap || {})[String(season)] || []).find(
      entry => String(entry.episode_number) === String(episode),
    );
  }

  function quickAction(side, action) {
    if (action === 'release-date') {
      const airDate = selectedEpisode(side)?.air_date || '';
      change(side === 'first' ? 'start_date' : 'end_date', airDate);
      return;
    }
    change(side === 'first' ? 'start_date' : 'end_date',
      valueFromDate(new Date(), Boolean(model?.trackTime)));
  }

  function selection(side) {
    const title = side === 'first' ? labels.firstPlay : labels.lastPlay;
    const seasonValue = side === 'first' ? values.first_season_number : values.last_season_number;
    const episodeValue = side === 'first' ? values.first_episode_number : values.last_episode_number;
    const episodes = (domain.seasonEpisodeMap || {})[String(seasonValue)] || [];
    return <View style={[styles.panel, { backgroundColor: palette.surface, borderColor: palette.surfaceStrong }]}>
      <Text style={[styles.panelTitle, { color: palette.textMuted }]}>{title}</Text>
      {domain.hideSeasonSelectors ? null : <SelectField
        name={side === 'first' ? 'first_season_number' : 'last_season_number'}
        label={domain.seasonFieldLabel || labels.season}
        value={String(seasonValue ?? '')}
        options={(model?.seasonOptions || []).map(option => ({
          value: String(option.value),
          label: String(option.label),
        }))}
        onChange={event => changeSeason(side, event.target.value)}
        palette={palette} />}
      <SelectField
        name={side === 'first' ? 'first_episode_number' : 'last_episode_number'}
        label={domain.episodeFieldLabel || labels.episode}
        value={String(episodeValue ?? '')}
        options={episodes.map(episode => ({
          value: String(episode.episode_number),
          label: episodeLabel(episode),
        }))}
        onChange={event => change(side === 'first' ? 'first_episode_number' : 'last_episode_number', event.target.value)}
        palette={palette} />
    </View>;
  }

  const datePicker = (side) => {
    const name = side === 'first' ? 'start_date' : 'end_date';
    const suggestion = selectedEpisode(side)?.air_date || '';
    const quickActions = [
      { id: 'just-finished', label: labels.justFinished || 'Just Finished' },
    ];
    if (domain.dateShortcutLabel) {
      quickActions.push({
        id: 'release-date',
        label: domain.dateShortcutLabel,
        requiresSuggestion: true,
      });
    }
    return <FormField label={side === 'first' ? labels.startDate : labels.endDate}
      palette={palette} error={errors[name]}>
      <DateTimePicker
        value={values[name] || ''}
        onChange={next => change(name, next)}
        trackTime={Boolean(model?.trackTime)}
        labels={labels.dateTime || {}}
        palette={palette.dateTime || palette}
        quickActions={quickActions}
        suggestionDate={suggestion}
        suggestionLabel={domain.dateShortcutLabel || ''}
        onQuickAction={action => quickAction(side, action)} />
    </FormField>;
  };

  return <View style={styles.root}>
    {model?.notice ? <View style={[styles.notice, { borderColor: palette.accent, backgroundColor: palette.surfaceStrong }]}>
      <Text style={[styles.noticeText, { color: palette.textSecondary }]}>{model.notice}</Text>
    </View> : null}
    {errors.non_field ? <FormError message={errors.non_field} palette={palette} /> : null}
    <View style={[styles.grid, wide && styles.gridWide]}>
      {selection('first')}
      {selection('last')}
    </View>
    {domain.lockedSeasonNumber && !domain.hideSeasonSelectors
      ? <Text style={[styles.help, { color: palette.textMuted }]}>{labels.lockedRange}</Text>
      : null}
    <View style={[styles.panel, { backgroundColor: palette.surface, borderColor: palette.surfaceStrong }]}>
      <View style={[styles.grid, wide && styles.gridWide]}>
        {datePicker('first')}
        {datePicker('last')}
      </View>
      <View style={[styles.grid, wide && styles.gridWide, styles.spaced]}>
        <SelectField
          name="write_mode"
          label={labels.playHandling}
          value={String(values.write_mode || '')}
          options={(model?.writeModeOptions || []).map(option => ({
            value: String(option.value),
            label: String(option.label),
          }))}
          onChange={event => change('write_mode', event.target.value)}
          palette={palette} />
        <SelectField
          name="distribution_mode"
          label={labels.distribution}
          value={String(values.distribution_mode || '')}
          options={(model?.distributionModeOptions || []).map(option => ({
            value: String(option.value),
            label: String(option.label),
          }))}
          onChange={event => change('distribution_mode', event.target.value)}
          palette={palette} />
      </View>
    </View>
    <View style={[styles.summary, { borderColor: palette.warning, backgroundColor: palette.surface }]}>
      <FormStatus message={summary.summaryText || labels.chooseRange} palette={palette} />
      {summary.rangeWarning ? <Text style={[styles.warning, { color: palette.warning }]}>{summary.rangeWarning}</Text> : null}
    </View>
    <View style={styles.actions}>
      <Button label={busy ? labels.saving : (model?.submitLabel || labels.save)}
        busy={busy} disabled={busy} palette={palette}
        onPress={() => onSubmit?.({
          ...values,
          episode_count: summary.count || values.episode_count || '',
        })} />
    </View>
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: 14 },
  grid: { gap: 12 },
  gridWide: { flexDirection: 'row', alignItems: 'flex-start' },
  panel: { flex: 1, minWidth: 0, gap: 12, borderWidth: 1, borderRadius: 8, padding: 12 },
  panelTitle: { fontSize: 12, fontWeight: '700', textTransform: 'uppercase', letterSpacing: 0.4 },
  spaced: { marginTop: 14 },
  notice: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 10 },
  noticeText: { fontSize: 13, lineHeight: 19 },
  help: { fontSize: 12, lineHeight: 17 },
  summary: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 10, gap: 6 },
  warning: { fontSize: 12, lineHeight: 17 },
  actions: { flexDirection: 'row', justifyContent: 'flex-end' },
});
