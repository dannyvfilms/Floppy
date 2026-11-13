import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { StatisticsSummary, StatisticsState } from '../ui/StatisticsSummary';
import { StatisticsCharts } from '../ui/StatisticsCharts';
import {
  StatisticsComparison,
  StatisticsMediaTypeOverviews,
  StatisticsTalentSection,
} from '../ui/StatisticsSections';

// One Statistics composition for web and Expo. It owns the heading, the order
// of summary, comparison, charts, talent and per-media overviews, and the
// loading/error/retry states between them. The existing Statistics* components
// keep the controls, charts, talent columns and overview panels; adapters only
// supply server models, permissions and transport.

export const statisticsLabels = {
  title: 'Statistics',
  subtitle: 'Your viewing and reading over time',
  loading: 'Loading statistics…',
  retry: 'Try again',
  error: 'Statistics could not be loaded.',
};

export function StatisticsView({
  model = {},
  comparison = {},
  charts = {},
  talent = {},
  mediaOverviews = { items: [] },
  summary = null,
  talentState = 'ready',
  sections = ['summary', 'comparison', 'charts', 'talent', 'overviews'],
  title,
  subtitle,
  labels = {},
  palette = {},
  chrome = true,
  header,
  footer,
  children,
  onRetry,
  onChangeRange,
  onChangeMediaTypes,
  onRefresh,
  onSelectHighlight,
  onCompareMode,
  onRoleSortChange,
  onStudioSortChange,
  onTasteSortChange,
  onSelectPerson,
  onOpenPerson,
  onSelectItem,
}) {
  const copy = { ...statisticsLabels, ...(labels || {}) };
  const heading = title === undefined ? copy.title : title;
  const subheading = subtitle === undefined ? copy.subtitle : subtitle;
  const loading = Boolean(model.loading);
  const error = Boolean(model.error);
  const show = key => sections.includes(key);
  return <View style={styles.root}>
    {header || null}
    {chrome && heading ? <Text accessibilityRole="header" style={[styles.title, { color: palette.text || '#fafafa' }]}>{heading}</Text> : null}
    {chrome && subheading ? <Text style={[styles.subtitle, { color: palette.textMuted || '#a1a1aa' }]}>{subheading}</Text> : null}
    {show('summary') ? (summary || <StatisticsSummary
      model={model}
      labels={labels}
      palette={palette}
      onChangeRange={onChangeRange}
      onChangeMediaTypes={onChangeMediaTypes}
      onRefresh={onRefresh}
      comparison={comparison}
      onCompareMode={onCompareMode}
      onSelectHighlight={onSelectHighlight}
      onRetry={onRetry} />) : null}
    {!loading && !error ? <React.Fragment>
      {show('comparison') && comparison ? <StatisticsComparison model={comparison} labels={labels} palette={palette}
        onCompareMode={onCompareMode} onRetry={onRetry} /> : null}
      {show('charts') ? <StatisticsCharts model={charts} labels={labels} palette={palette}
        onSelectPerson={onOpenPerson || onSelectPerson} /> : null}
      {show('talent') ? (talentState === 'ready'
        ? <StatisticsTalentSection model={talent} labels={labels} palette={palette}
          onRoleSortChange={onRoleSortChange}
          onStudioSortChange={onStudioSortChange}
          onTasteSortChange={onTasteSortChange}
          onSelectPerson={onSelectPerson} />
        : <StatisticsState kind={talentState === 'error' ? 'error' : 'loading'}
          labels={{ ...copy, loading: copy.loading }}
          palette={palette} onRetry={onRetry} />) : null}
      {show('overviews') ? <StatisticsMediaTypeOverviews model={mediaOverviews} labels={labels} palette={palette}
        onSelectItem={onSelectItem} /> : null}
    </React.Fragment> : null}
    {footer || null}
    {children || null}
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: 16, minWidth: 0 },
  title: { fontSize: 28, lineHeight: 34, fontWeight: '700' },
  subtitle: { fontSize: 13, lineHeight: 19 },
});
