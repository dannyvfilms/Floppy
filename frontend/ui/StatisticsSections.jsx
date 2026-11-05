import React from 'react';
import {
  Image,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { StatisticsState } from './StatisticsSummary';
import { StatisticsHoursChart } from './StatisticsCharts';

const DEFAULT_PALETTE = {
  background: '#18181b',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#3f3f46',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  accentContrast: '#ffffff',
  link: '#818cf8',
  danger: '#ef4444',
  warning: '#f59e0b',
  success: '#10b981',
  radius: 10,
  radiusSmall: 6,
};

const DEFAULT_LABELS = {
  comparisonTitle: 'Comparison',
  comparisonCopy: 'Your activity against another period.',
  compareTo: 'Compare to:',
  comparisonEmpty: 'No comparison data available for this range.',
  roleTitle: 'Role Leaders',
  roleCopy: 'The people you return to most.',
  roleEmpty: 'No cast or crew data available for this range.',
  studioTitle: 'Studio Footprint',
  studioCopy: 'Studios that appear most often.',
  studioEmpty: 'No studio data available for this range.',
  tasteTitle: 'Taste Signals',
  tasteCopy: 'What your library says about your taste.',
  genresTitle: 'Top Genres',
  erasTitle: 'Era Spotlight',
  genresEmpty: 'No genre data available for this range.',
  erasEmpty: 'No release-year data available for this range.',
  overviewTitle: 'Activity Overview',
  overviewEmpty: 'No activity data available for this range.',
  noItems: 'No data available for this range.',
  time: 'Time',
  plays: 'Plays',
  titles: 'Titles',
};

function mergeLabels(labels) {
  return { ...DEFAULT_LABELS, ...(labels || {}) };
}

function mergePalette(palette) {
  return { ...DEFAULT_PALETTE, ...(palette || {}) };
}

function text(value) {
  return value === null || value === undefined ? '' : String(value);
}

function plural(count, one, many) {
  return Number(count) === 1 ? one : many;
}

function SectionCard({ title, copy, palette, headerRight, children }) {
  return <View style={[styles.card, { backgroundColor: palette.surface }]}>
    <View style={styles.cardHeader}>
      <View style={styles.cardHeaderCopy}>
        <Text style={[styles.cardTitle, { color: palette.text }]}>{title}</Text>
        {copy ? <Text style={[styles.cardCopy, { color: palette.textMuted }]}>{copy}</Text> : null}
      </View>
      {headerRight}
    </View>
    {children}
  </View>;
}

function EmptyCopy({ copy, palette }) {
  return <Text style={[styles.emptyCopy, { color: palette.textMuted }]}>{copy}</Text>;
}

function ChoiceChips({ options = [], selected, palette, onChange, label, compact }) {
  if (!options.length) return null;
  return <View style={styles.chipWrap} accessibilityLabel={label}>
    {options.map(option => {
      const isSelected = option.value === selected;
      return <Pressable key={option.value}
        accessibilityRole="button"
        accessibilityLabel={option.label}
        accessibilityState={{ selected: isSelected, disabled: Boolean(option.disabled) }}
        disabled={option.disabled}
        onPress={() => onChange?.(option.value)}
        style={({ pressed }) => [
          styles.chip,
          compact && styles.chipCompact,
          {
            backgroundColor: isSelected ? palette.accentStrong : palette.surfaceStrong,
            borderColor: isSelected ? palette.accentStrong : palette.border,
            opacity: option.disabled ? 0.45 : 1,
          },
          pressed && styles.pressed,
        ]}>
        <Text style={[styles.chipText, { color: isSelected ? palette.accentContrast : palette.textSecondary }]}>
          {option.label}
        </Text>
      </Pressable>;
    })}
  </View>;
}

function MetricBar({ percent, color, palette }) {
  const width = Math.max(0, Math.min(100, Number(percent) || 0));
  return <View style={[styles.metricTrack, { backgroundColor: palette.surfaceMuted }]}>
    <View style={[styles.metricFill, { width: `${width}%`, backgroundColor: color || palette.accent }]} />
  </View>;
}

function RankedRow({ rank, label, value, percent, color, palette, onPress, accessibilityLabel }) {
  const body = <View style={styles.rankedRow}>
    {rank ? <Text style={[styles.rank, { color: palette.textMuted }]}>{rank}</Text> : null}
    <Text numberOfLines={1} style={[styles.rankedLabel, { color: palette.text }]}>{label}</Text>
    <MetricBar percent={percent} color={color} palette={palette} />
    {value ? <Text numberOfLines={1} style={[styles.rankedValue, { color: palette.textSecondary }]}>{value}</Text> : null}
  </View>;
  if (onPress) {
    return <Pressable accessibilityRole="button" accessibilityLabel={accessibilityLabel || label}
      onPress={onPress} style={({ pressed }) => pressed && styles.pressed}>
      {body}
    </Pressable>;
  }
  return <View accessible accessibilityLabel={accessibilityLabel || `${label} ${value || ''}`.trim()}>{body}</View>;
}

function PanelList({ panel, palette, onSelectItem }) {
  const items = panel.items || [];
  const summary = items.map(item => `${item.title} ${item.subtitle || item.value || ''}`.trim()).join('. ');
  return <View style={[styles.panel, { backgroundColor: palette.surfaceStrong }]}>
    <Text style={[styles.panelTitle, { color: palette.textSecondary }]}>{panel.title}</Text>
    {!items.length
      ? <EmptyCopy copy={panel.empty || DEFAULT_LABELS.noItems} palette={palette} />
      : <View accessibilityLabel={summary} style={styles.panelRows}>
        {items.map((item, index) => {
          const body = <View style={styles.mediaRow}>
            <Text style={[styles.rank, { color: palette.textMuted }]}>{item.rank || index + 1}</Text>
            {item.image
              ? <Image source={{ uri: item.image }} accessibilityLabel={item.title}
                style={[styles.mediaImage, panel.roundImages && styles.mediaImageRound]} />
              : <View style={[styles.mediaImage, panel.roundImages && styles.mediaImageRound,
                { backgroundColor: palette.surface, alignItems: 'center', justifyContent: 'center' }]}>
                <Text style={[styles.mediaInitial, { color: palette.textMuted }]}>
                  {text(item.title).slice(0, 1).toUpperCase() || '?'}
                </Text>
              </View>}
            <View style={styles.mediaCopy}>
              <Text numberOfLines={1} style={[styles.mediaTitle, { color: palette.text }]}>{item.title}</Text>
              {item.subtitle ? <Text numberOfLines={1} style={[styles.mediaMeta, { color: palette.textMuted }]}>{item.subtitle}</Text> : null}
            </View>
            {item.value ? <Text style={[styles.mediaValue, { color: palette.textSecondary }]}>{item.value}</Text> : null}
          </View>;
          if (item.onPress && onSelectItem) {
            return <Pressable key={item.key || item.title} accessibilityRole="button"
              accessibilityLabel={`${item.title}, ${item.subtitle || item.value || ''}`.trim()}
              onPress={() => onSelectItem(item)}
              style={({ pressed }) => pressed && styles.pressed}>
              {body}
            </Pressable>;
          }
          return <View key={item.key || item.title} accessible
            accessibilityLabel={`${item.title}, ${item.subtitle || item.value || ''}`.trim()}>
            {body}
          </View>;
        })}
      </View>}
  </View>;
}

export function StatisticsComparison({
  model = {},
  labels,
  palette,
  onCompareMode,
}) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const rows = model.rows || [];
  const options = model.options || [];
  const summary = rows.map(row => (
    `${row.label}: ${row.currentLabel || row.current || ''}`
    + (row.comparisonLabel ? ` versus ${row.comparisonLabel}` : '')
    + (row.deltaLabel ? `, ${row.deltaLabel}` : '')
  )).join('. ');
  if (model.loading || model.error || model.empty) {
    return <StatisticsState kind={model.error ? 'error' : model.loading ? 'loading' : 'empty'}
      labels={model.stateLabels} palette={colors} onRetry={model.onRetry} />;
  }
  return <SectionCard title={model.title || copy.comparisonTitle}
    copy={model.copy || copy.comparisonCopy} palette={colors}
    headerRight={<View style={styles.headerControls}>
      {options.length ? <Text style={[styles.controlLabel, { color: colors.textMuted }]}>{copy.compareTo}</Text> : null}
      <ChoiceChips options={options} selected={model.selected} palette={colors}
        onChange={onCompareMode} label={copy.comparisonTitle} compact />
    </View>}>
    {!rows.length
      ? <EmptyCopy copy={model.emptyCopy || copy.comparisonEmpty} palette={colors} />
      : <View accessible accessibilityLabel={summary} style={styles.comparisonRows}>
        {rows.map(row => <View key={row.key || row.label} style={[styles.comparisonRow, { borderBottomColor: colors.border }]}>
          <View style={styles.comparisonLabelWrap}>
            <View style={[styles.comparisonDot, { backgroundColor: row.color || colors.accent }]} />
            <Text numberOfLines={1} style={[styles.comparisonLabel, { color: colors.text }]}>{row.label}</Text>
          </View>
          <Text style={[styles.comparisonValue, { color: colors.text }]}>{row.currentLabel || row.current}</Text>
          <Text style={[styles.comparisonValue, { color: colors.textMuted }]}>{row.comparisonLabel || '--'}</Text>
          {row.deltaLabel ? <View style={[styles.deltaPill, {
            backgroundColor: row.state === 'up' ? `${colors.success}22` : row.state === 'down' ? `${colors.danger}22` : `${colors.textMuted}22`,
          }]}>
            <Text style={[styles.deltaText, {
              color: row.state === 'up' ? colors.success : row.state === 'down' ? colors.danger : colors.textMuted,
            }]}>{row.deltaLabel}</Text>
          </View> : <View style={styles.deltaPill} />}
        </View>)}
      </View>}
  </SectionCard>;
}

export function StatisticsRoleLeaders({
  model = {},
  labels,
  palette,
  onSortChange,
  onSelectPerson,
}) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const columns = model.columns || [];
  return <SectionCard title={model.title || copy.roleTitle}
    copy={model.copy || copy.roleCopy} palette={colors}
    headerRight={<ChoiceChips options={model.sortOptions || [
      { value: 'plays', label: copy.plays },
      { value: 'time', label: copy.time },
      { value: 'titles', label: copy.titles },
    ]} selected={model.selected} palette={colors}
      onChange={onSortChange} label={copy.roleTitle} compact />}>
    {!columns.length
      ? <EmptyCopy copy={model.emptyCopy || copy.roleEmpty} palette={colors} />
      : <View style={styles.leaderColumns}>
        {columns.map(column => <View key={column.bucket || column.label} style={styles.leaderColumn}>
          <Text style={[styles.leaderTitle, { color: column.color || colors.textSecondary }]}>{column.label}</Text>
          {(column.entries || []).map((entry, index) => <Pressable key={`${entry.source || ''}:${entry.personId || entry.name}`}
            accessibilityRole="button"
            accessibilityLabel={`${entry.name}, ${entry.displayMetric || ''}`.trim()}
            accessibilityState={{ selected: Boolean(entry.selected) }}
            onPress={() => onSelectPerson?.(entry)}
            style={({ pressed }) => pressed && styles.pressed}>
            <View style={styles.leaderRow}>
              <Text style={[styles.rank, { color: colors.textMuted }]}>{entry.rank || index + 1}</Text>
              <Text numberOfLines={1} style={[styles.leaderName, {
                color: entry.selected ? colors.link : colors.text,
              }]}>{entry.name}</Text>
              <Text style={[styles.leaderMetric, { color: colors.textMuted }]}>{entry.displayMetric}</Text>
            </View>
          </Pressable>)}
        </View>)}
      </View>}
  </SectionCard>;
}

export function StatisticsStudioFootprint({
  model = {},
  labels,
  palette,
  onSortChange,
}) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const studios = model.studios || [];
  const summary = studios.map(studio => `${studio.name} ${studio.pct} percent, ${studio.metricLabel}`).join('. ');
  return <SectionCard title={model.title || copy.studioTitle}
    copy={model.copy || copy.studioCopy} palette={colors}
    headerRight={<ChoiceChips options={model.sortOptions || [
      { value: 'plays', label: copy.plays },
      { value: 'time', label: copy.time },
    ]} selected={model.selected} palette={colors}
      onChange={onSortChange} label={copy.studioTitle} compact />}>
    {model.delta ? <View style={styles.studioDelta}>
      <Text style={[styles.studioDeltaText, {
        color: model.delta.state === 'down' ? colors.danger : colors.success,
      }]}>{model.delta.label}</Text>
      {model.delta.label ? <Text style={[styles.studioDeltaCopy, { color: colors.textMuted }]}>{model.delta.copy}</Text> : null}
    </View> : null}
    {!studios.length
      ? <EmptyCopy copy={model.emptyCopy || copy.studioEmpty} palette={colors} />
      : <View accessibilityLabel={summary} style={styles.stackedRows}>
        {studios.map((studio, index) => <RankedRow key={studio.name || index}
          rank={index + 1} label={studio.name} percent={studio.pct}
          color={studio.color || colors.accent} value={studio.metricLabel} palette={colors} />)}
      </View>}
  </SectionCard>;
}

function TastePanel({ title, rows, palette, emptyCopy, durationSuffix }) {
  const summary = (rows || []).map(row => (
    `${row.name || row.label} ${row.formattedDuration || `${row.plays} ${plural(row.plays, 'play', 'plays')}`}, ${row.pct} percent`
  )).join('. ');
  return <View style={styles.tastePanel}>
    <Text style={[styles.panelTitle, { color: palette.textSecondary }]}>{title}</Text>
    {!(rows || []).length
      ? <EmptyCopy copy={emptyCopy} palette={palette} />
      : <View accessibilityLabel={summary} style={styles.stackedRows}>
        {(rows || []).map((row, index) => <RankedRow key={`${row.name || row.label}-${index}`}
          rank={index + 1}
          label={row.name || row.label}
          percent={row.pct}
          color={row.color || (title === DEFAULT_LABELS.erasTitle ? palette.warning : palette.accent)}
          value={row.formattedDuration || `${row.plays} ${plural(row.plays, durationSuffix || 'play', `${durationSuffix || 'play'}s`)}`}
          palette={palette} />)}
      </View>}
  </View>;
}

export function StatisticsTasteSignals({
  model = {},
  labels,
  palette,
  onSortChange,
}) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  return <SectionCard title={model.title || copy.tasteTitle}
    copy={model.copy || copy.tasteCopy} palette={colors}
    headerRight={<ChoiceChips options={model.sortOptions || [
      { value: 'time', label: copy.time },
      { value: 'plays', label: copy.plays },
    ]} selected={model.selected} palette={colors}
      onChange={onSortChange} label={copy.tasteTitle} compact />}>
    <View style={styles.tasteGrid}>
      <TastePanel title={model.genresTitle || copy.genresTitle} rows={model.genres}
        palette={colors} emptyCopy={model.genresEmpty || copy.genresEmpty} />
      <TastePanel title={model.erasTitle || copy.erasTitle} rows={model.eras}
        palette={colors} emptyCopy={model.erasEmpty || copy.erasEmpty} />
    </View>
  </SectionCard>;
}

export function StatisticsTalentSection({
  model = {},
  labels,
  palette,
  onRoleSortChange,
  onStudioSortChange,
  onTasteSortChange,
  onSelectPerson,
}) {
  const colors = mergePalette(palette);
  return <View style={styles.talentGrid}>
    <View style={styles.talentPrimary}>
      <StatisticsRoleLeaders model={model.roleLeaders} labels={labels} palette={colors}
        onSortChange={onRoleSortChange} onSelectPerson={onSelectPerson} />
    </View>
    <View style={styles.talentSecondary}>
      <StatisticsStudioFootprint model={model.studioFootprint} labels={labels}
        palette={colors} onSortChange={onStudioSortChange} />
    </View>
    <View style={styles.talentFull}>
      <StatisticsTasteSignals model={model.tasteSignals} labels={labels}
        palette={colors} onSortChange={onTasteSortChange} />
    </View>
  </View>;
}

export function StatisticsMediaTypeOverview({
  model = {},
  labels,
  palette,
  onSelectItem,
}) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const charts = model.charts || [];
  const panels = model.panels || [];
  const facts = model.facts || [];
  const hasContent = charts.some(chart => (chart.labels || []).length)
    || panels.some(panel => (panel.items || []).length)
    || facts.length;
  return <View style={[styles.overviewCard, { backgroundColor: colors.surface }]}>
    <View style={styles.overviewHeader}>
      <Text style={[styles.overviewEyebrow, { color: colors.textMuted }]}>{model.typeLabel}</Text>
      <Text style={[styles.overviewTitle, { color: colors.text }]}>{model.title || copy.overviewTitle}</Text>
      {model.rangeLabel ? <Text style={[styles.overviewRange, { color: colors.textMuted }]}>{model.rangeLabel}</Text> : null}
    </View>
    {!hasContent
      ? <EmptyCopy copy={model.emptyCopy || copy.overviewEmpty} palette={colors} />
      : <View style={styles.overviewBody}>
        {facts.length ? <View style={styles.factGrid}>
          {facts.map(fact => <View key={fact.key || fact.label}
            accessible accessibilityLabel={`${fact.label}: ${fact.value}`}
            style={[styles.factCard, { backgroundColor: colors.surfaceStrong }]}>
            <Text style={[styles.factLabel, { color: colors.textSecondary }]}>{fact.label}</Text>
            <Text style={[styles.factValue, { color: colors.text }]}>{fact.value}</Text>
            {fact.copy ? <Text style={[styles.factCopy, { color: colors.textMuted }]}>{fact.copy}</Text> : null}
          </View>)}
        </View> : null}
        {charts.length ? <View style={styles.overviewCharts}>
          {charts.map(chart => <View key={chart.key || chart.title}
            style={[styles.chartCard, { backgroundColor: colors.surfaceStrong }]}>
            <StatisticsHoursChart chart={chart} labels={labels} palette={colors} />
          </View>)}
        </View> : null}
        {panels.length ? <View style={styles.panelGrid}>
          {panels.map(panel => <View key={panel.key || panel.title} style={styles.panelCell}>
            <PanelList panel={panel} palette={colors} onSelectItem={onSelectItem} />
          </View>)}
        </View> : null}
      </View>}
  </View>;
}

export function StatisticsMediaTypeOverviews({
  model = {},
  labels,
  palette,
  onSelectItem,
}) {
  const overviews = model.items || [];
  if (!overviews.length) {
    return <StatisticsState kind="empty" labels={model.stateLabels} palette={mergePalette(palette)} />;
  }
  return <View style={styles.overviewList}>
    {overviews.map(overview => <StatisticsMediaTypeOverview key={overview.id || overview.typeLabel}
      model={overview} labels={labels} palette={palette} onSelectItem={onSelectItem} />)}
  </View>;
}

const styles = StyleSheet.create({
  card: { borderRadius: 10, padding: 16, gap: 12, width: '100%' },
  cardHeader: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' },
  cardHeaderCopy: { flexShrink: 1, minWidth: 180, gap: 2 },
  cardTitle: { fontSize: 15, fontWeight: '600' },
  cardCopy: { fontSize: 11, lineHeight: 16 },
  headerControls: { alignItems: 'flex-end', gap: 4, flexShrink: 1 },
  controlLabel: { fontSize: 10, fontWeight: '600', textTransform: 'uppercase' },
  chipWrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  chip: { minHeight: 30, paddingHorizontal: 10, borderRadius: 999, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  chipCompact: { minHeight: 26, paddingHorizontal: 8 },
  chipText: { fontSize: 11, fontWeight: '600' },
  pressed: { opacity: 0.75 },
  emptyCopy: { fontSize: 12, textAlign: 'center', paddingVertical: 20 },
  comparisonRows: { gap: 0 },
  comparisonRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 9, borderBottomWidth: StyleSheet.hairlineWidth, flexWrap: 'wrap' },
  comparisonLabelWrap: { flexDirection: 'row', alignItems: 'center', gap: 6, minWidth: 120, flexGrow: 1 },
  comparisonDot: { width: 8, height: 8, borderRadius: 4 },
  comparisonLabel: { fontSize: 12, fontWeight: '600', flexShrink: 1 },
  comparisonValue: { width: 68, fontSize: 12, textAlign: 'right' },
  deltaPill: { minWidth: 56, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 999, alignItems: 'center' },
  deltaText: { fontSize: 10, fontWeight: '700' },
  leaderColumns: { flexDirection: 'row', flexWrap: 'wrap', gap: 14 },
  leaderColumn: { flexGrow: 1, flexBasis: 130, minWidth: 130, gap: 2 },
  leaderTitle: { fontSize: 11, fontWeight: '700', textTransform: 'uppercase', marginBottom: 3 },
  leaderRow: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingVertical: 2 },
  rank: { width: 16, fontSize: 10, fontWeight: '600' },
  leaderName: { flexGrow: 1, flexShrink: 1, fontSize: 11, fontWeight: '600' },
  leaderMetric: { fontSize: 10 },
  stackedRows: { gap: 8 },
  rankedRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  rankedLabel: { width: 90, fontSize: 12, fontWeight: '600' },
  metricTrack: { flexGrow: 1, flexShrink: 1, height: 8, borderRadius: 4, overflow: 'hidden', minWidth: 30 },
  metricFill: { height: 8, borderRadius: 4 },
  rankedValue: { width: 64, fontSize: 11, textAlign: 'right' },
  studioDelta: { flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' },
  studioDeltaText: { fontSize: 12, fontWeight: '700' },
  studioDeltaCopy: { fontSize: 11 },
  tasteGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 18 },
  tastePanel: { flexGrow: 1, flexBasis: 260, minWidth: 220, gap: 8 },
  panelTitle: { fontSize: 11, fontWeight: '700', textTransform: 'uppercase' },
  talentGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12, width: '100%' },
  talentPrimary: { flexGrow: 2, flexBasis: 420, minWidth: 0 },
  talentSecondary: { flexGrow: 1, flexBasis: 320, minWidth: 0 },
  talentFull: { flexBasis: '100%', flexGrow: 1 },
  overviewList: { gap: 16, width: '100%' },
  overviewCard: { borderRadius: 10, padding: 16, gap: 14, width: '100%' },
  overviewHeader: { gap: 2 },
  overviewEyebrow: { fontSize: 10, fontWeight: '700', letterSpacing: 1, textTransform: 'uppercase' },
  overviewTitle: { fontSize: 20, fontWeight: '600' },
  overviewRange: { fontSize: 11 },
  overviewBody: { gap: 14 },
  factGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  factCard: { flexGrow: 1, flexBasis: 180, borderRadius: 8, padding: 11, gap: 2 },
  factLabel: { fontSize: 10, fontWeight: '700', textTransform: 'uppercase' },
  factValue: { fontSize: 18, fontWeight: '700' },
  factCopy: { fontSize: 10 },
  overviewCharts: { gap: 10 },
  chartCard: { borderRadius: 8, padding: 10 },
  panelGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  panelCell: { flexGrow: 1, flexBasis: 260, minWidth: 220 },
  panel: { borderRadius: 8, padding: 10, gap: 8, height: '100%' },
  panelRows: { gap: 4 },
  mediaRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 3 },
  mediaImage: { width: 36, height: 36, borderRadius: 6, backgroundColor: 'transparent' },
  mediaImageRound: { borderRadius: 18 },
  mediaInitial: { fontSize: 13, fontWeight: '700' },
  mediaCopy: { flexGrow: 1, flexShrink: 1, minWidth: 0 },
  mediaTitle: { fontSize: 12, fontWeight: '600' },
  mediaMeta: { fontSize: 10 },
  mediaValue: { fontSize: 11, fontWeight: '600', textAlign: 'right' },
});
