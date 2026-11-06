import React, { useMemo } from 'react';
import {
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { StatisticsState } from './StatisticsSummary';

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
  rhythmTitle: 'Activity Rhythm',
  rhythmCopy: 'Each cell is one day. Brighter means more.',
  rhythmEmpty: 'No activity data for this range.',
  low: 'Low',
  high: 'High',
  heatmapTitle: 'Activity History',
  heatmapCopy: 'Each cell is one day. Brighter means more activity.',
  heatmapEmpty: 'No activity history for this range.',
  less: 'Less',
  more: 'More',
  hoursTitle: 'Hours by Media Type',
  hoursCopy: 'Where your hours go.',
  hoursTotal: 'total',
  hoursEmpty: 'No time data available for this range.',
  hoursMonthTitle: 'Hours by Month',
  hoursWeekdayTitle: 'Hours by Day of Week',
  hoursTimeTitle: 'Hours by Time of Day',
  hoursChartEmpty: 'No data for this filter.',
  hoursSuffix: 'h',
  statusTitle: 'Status Composition',
  statusCopy: 'What portion of your library is in each state.',
  statusEmpty: 'No status data available for this range.',
  ratingTitle: 'Rating Distribution',
  ratingCopy: 'How your rated items are distributed.',
  ratingCopyCount: 'How your {count} rated items are distributed.',
  ratingEmpty: 'No ratings yet.',
  breakdownTitle: 'Status Breakdown',
  breakdownCopy: 'Breakdown by type across all status states.',
  breakdownEmpty: 'No status data available for this range.',
  breakdownTotal: 'Total',
  completionTitle: 'Completion by Media Type',
  completionCopy: 'Completed items by type.',
  completionEmpty: 'No completion data for this range.',
  featuredTitle: 'Featured Repeat Player',
  featuredCopy: 'The most recurring talent in your library.',
  featuredEmpty: 'No repeat cast or crew found for this range.',
  featuredTitles: 'titles',
  featuredMovies: 'Movies',
  featuredGames: 'Games',
  featuredShows: 'Shows',
  featuredOfTitles: 'of titles',
  featuredKnownFor: 'Known For:',
  featuredNoRoles: 'No primary roles available.',
  featuredViewProfile: 'View Profile',
  ratingLabel: 'Rating {rating}',
  itemsLabel: '{count} items',
  loadError: 'Statistics charts could not be loaded.',
  loadErrorCopy: 'Check the server connection and try again.',
  empty: 'Nothing tracked in this range',
  emptyCopy: 'Choose a wider range or add something to your library.',
  loading: 'Loading charts...',
  loadingCopy: 'Calculated on the server from your tracked history.',
  retry: 'Try again',
};

function mergeLabels(labels) {
  return { ...DEFAULT_LABELS, ...(labels || {}) };
}

function mergePalette(palette) {
  return { ...DEFAULT_PALETTE, ...(palette || {}) };
}

function numberValue(value) {
  return Number(value) || 0;
}

function formatNumber(value) {
  return Math.round(numberValue(value)).toLocaleString();
}

function formatHours(value) {
  const rounded = Math.round(numberValue(value) * 10) / 10;
  return Number.isInteger(rounded) ? formatNumber(rounded) : String(rounded);
}

function percentOf(value, total) {
  if (!total) return 0;
  return Math.round((numberValue(value) / total) * 100);
}

function interpolate(template, values) {
  return String(template).replace(/\{(\w+)\}/g, (match, key) => (
    Object.prototype.hasOwnProperty.call(values, key) ? String(values[key]) : match
  ));
}

function withAlpha(hex, alpha) {
  const value = String(hex || '').replace('#', '');
  const expanded = value.length === 3
    ? value.split('').map(part => part + part).join('')
    : value;
  if (!/^[0-9a-fA-F]{6}$/.test(expanded)) return hex;
  const r = parseInt(expanded.slice(0, 2), 16);
  const g = parseInt(expanded.slice(2, 4), 16);
  const b = parseInt(expanded.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function ChartCard({ title, copy, palette, children, headerRight }) {
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

function EmptyCopy({ text, palette }) {
  return <Text style={[styles.emptyCopy, { color: palette.textMuted }]}>{text}</Text>;
}

function RingChart({ segments, size, thickness, palette, accessibilityLabel, centerTitle, centerCaption }) {
  const total = segments.reduce((sum, segment) => sum + numberValue(segment.value), 0);
  const ringSize = size || 132;
  const ringThickness = thickness || 14;
  const tickCount = 64;
  const ticks = useMemo(() => {
    const colors = [];
    if (total <= 0) return colors;
    let cumulative = 0;
    let assigned = 0;
    segments.forEach((segment, index) => {
      cumulative += numberValue(segment.value);
      const isLast = index === segments.length - 1;
      const target = isLast ? tickCount : Math.round((cumulative / total) * tickCount);
      const count = Math.max(numberValue(segment.value) > 0 ? 1 : 0, target - assigned);
      for (let tick = 0; tick < count; tick += 1) colors.push(segment.color);
      assigned += count;
    });
    return colors.slice(0, tickCount);
  }, [segments, total]);
  const innerSize = Math.max(24, ringSize - ringThickness * 2 - 8);
  const radius = ringSize / 2 - ringThickness / 2;
  return <View accessible accessibilityRole="image"
    accessibilityLabel={accessibilityLabel}
    style={[styles.ring, { width: ringSize, height: ringSize }]}>
    {ticks.map((color, index) => {
      const angle = (360 / tickCount) * index;
      return <View key={index} style={[styles.ringTick, {
        width: 4,
        height: ringThickness,
        borderRadius: 2,
        backgroundColor: color,
        left: ringSize / 2 - 2,
        top: ringSize / 2 - ringThickness / 2,
        transform: [{ rotate: `${angle}deg` }, { translateY: -radius }],
      }]} />;
    })}
    <View style={[styles.ringCenter, {
      width: innerSize,
      height: innerSize,
      borderRadius: innerSize / 2,
      left: (ringSize - innerSize) / 2,
      top: (ringSize - innerSize) / 2,
      backgroundColor: palette.surface,
    }]}>
      {centerTitle ? <Text style={[styles.ringCenterTitle, { color: palette.text }]}>{centerTitle}</Text> : null}
      {centerCaption ? <Text style={[styles.ringCenterCaption, { color: palette.textMuted }]}>{centerCaption}</Text> : null}
    </View>
  </View>;
}

function LegendRows({ rows, palette, valueLabel }) {
  return <View style={styles.legend}>
    {rows.map(row => <View key={row.key} style={styles.legendRow}>
      <View style={[styles.legendSwatch, { backgroundColor: row.color }]} />
      <Text numberOfLines={1} style={[styles.legendLabel, { color: palette.textSecondary }]}>{row.label}</Text>
      <View style={[styles.legendTrack, { backgroundColor: withAlpha(palette.text, 0.08) }]}>
        <View style={[styles.legendFill, { width: `${row.percent}%`, backgroundColor: row.color }]} />
      </View>
      <Text style={[styles.legendPercent, { color: palette.text }]}>{row.percent}%</Text>
      <Text style={[styles.legendValue, { color: palette.textMuted }]}>{valueLabel(row.value)}</Text>
    </View>)}
  </View>;
}

function BarChart({
  labels,
  values,
  colors,
  palette,
  accessibilityLabel,
  emptyText,
  height = 140,
  showValues = false,
  valueLabel,
  labelColor,
}) {
  const total = values.reduce((sum, value) => sum + numberValue(value), 0);
  if (!labels.length || !values.length || total <= 0) {
    return <EmptyCopy text={emptyText} palette={palette} />;
  }
  const max = Math.max(1, ...values.map(numberValue));
  const compact = labels.length > 8;
  const bars = labels.map((label, index) => {
    const value = numberValue(values[index]);
    const color = colors[index] || palette.accent;
    const fillHeight = value > 0 ? Math.max(3, Math.round((value / max) * height)) : 0;
    return <View key={`${label}-${index}`} style={[styles.barSlot, compact ? styles.barSlotCompact : styles.barSlotFlex]}>
      {showValues ? <Text numberOfLines={2} style={[styles.barValue, { color: palette.textMuted }]}>
        {value > 0 && valueLabel ? valueLabel(value, total) : ''}
      </Text> : null}
      <View style={[styles.barTrack, { height }]}>
        <View style={[styles.barFill, { height: fillHeight, backgroundColor: color }]} />
      </View>
      <Text numberOfLines={1} style={[styles.barLabel, { color: labelColor || palette.textSecondary }]}>{label}</Text>
    </View>;
  });
  const body = <View style={styles.barRow}>{bars}</View>;
  return <View accessible accessibilityRole="image" accessibilityLabel={accessibilityLabel}>
    {compact
      ? <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.barScroll}>{body}</ScrollView>
      : body}
  </View>;
}

function buildTiers(matrix) {
  const values = [];
  matrix.forEach(row => row.forEach(cell => {
    const value = numberValue(cell);
    if (value > 0) values.push(value);
  }));
  values.sort((a, b) => a - b);
  return value => {
    if (value <= 0 || !values.length) return 0;
    let low = 0;
    let high = values.length;
    while (low < high) {
      const mid = (low + high) >> 1;
      if (values[mid] < value) low = mid + 1;
      else high = mid;
    }
    const ratio = low / values.length;
    return Math.min(6, Math.floor(ratio * 6) + 1);
  };
}

function DotMatrix({ matrix, labels, palette }) {
  const rows = matrix || [];
  const dayLabels = labels.weekdayLabels || ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const tierFor = useMemo(() => buildTiers(rows), [rows]);
  const dotSize = 9;
  const gap = 3;
  const color = palette.accent;
  return <View style={styles.matrix}>
    <View style={styles.matrixHourRow}>
      <View style={styles.matrixDaySpacer} />
      {['12am', '6am', '12pm', '6pm'].map(label => (
        <Text key={label} style={[styles.matrixHourLabel, { color: palette.textMuted }]}>{label}</Text>
      ))}
    </View>
    {rows.map((row, rowIndex) => <View key={rowIndex} style={styles.matrixRow}>
      <Text style={[styles.matrixDayLabel, { color: palette.textMuted }]}>{dayLabels[rowIndex] || ''}</Text>
      <View style={styles.matrixCells}>
        {row.map((value, columnIndex) => {
          const tier = tierFor(numberValue(value));
          const dot = tier === 0 ? dotSize / 2 : 3 + (tier / 6) * (dotSize / 2);
          return <View key={columnIndex} style={{
            width: dotSize,
            height: dotSize,
            alignItems: 'center',
            justifyContent: 'center',
            marginRight: gap,
          }}>
            <View style={{
              width: dot,
              height: dot,
              borderRadius: dot / 2,
              backgroundColor: tier === 0 ? withAlpha(palette.text, 0.08) : withAlpha(color, 0.2 + 0.8 * (tier / 6)),
            }} />
          </View>;
        })}
      </View>
    </View>)}
  </View>;
}

function RhythmLegend({ palette, labels }) {
  const sizes = [5, 7, 9, 11, 13, 15];
  return <View style={styles.rhythmLegend}>
    <Text style={[styles.rhythmLegendLabel, { color: palette.textMuted }]}>{labels.low}</Text>
    {sizes.map((size, index) => <View key={size} style={{
      width: size,
      height: size,
      borderRadius: size / 2,
      backgroundColor: withAlpha(palette.accent, 0.2 + 0.8 * ((index + 1) / 6)),
    }} />)}
    <Text style={[styles.rhythmLegendLabel, { color: palette.textMuted }]}>{labels.high}</Text>
  </View>;
}

export function StatisticsRhythmChart({ chart = {}, labels, palette }) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const matrix = chart.matrix || [];
  const sessions = matrix.reduce((sum, row) => sum + row.reduce((rowSum, value) => rowSum + numberValue(value), 0), 0);
  const active = matrix.reduce((sum, row) => sum + row.filter(value => numberValue(value) > 0).length, 0);
  let peak = 0;
  matrix.forEach(row => row.forEach(value => { peak = Math.max(peak, numberValue(value)); }));
  const summary = `${copy.rhythmTitle}. ${active} active hours across ${formatNumber(sessions)} sessions. Peak ${formatNumber(peak)} sessions.`;
  return <ChartCard title={copy.rhythmTitle} copy={copy.rhythmCopy} palette={colors}
    headerRight={<RhythmLegend palette={colors} labels={copy} />}>
    {sessions <= 0
      ? <EmptyCopy text={copy.rhythmEmpty} palette={colors} />
      : <View accessible accessibilityRole="image" accessibilityLabel={summary}>
        <DotMatrix matrix={matrix} labels={{ weekdayLabels: chart.weekdayLabels }} palette={colors} />
      </View>}
  </ChartCard>;
}

export function StatisticsHeatmapChart({ chart = {}, labels, palette }) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const weeks = chart.weeks || [];
  const monthLabels = chart.monthLabels || [];
  const dayLabels = chart.weekdayLabels || ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const levels = [
    withAlpha(colors.text, 0.06),
    '#4338ca',
    '#4f46e5',
    '#6366f1',
    '#818cf8',
  ];
  const activeDays = weeks.reduce((sum, week) => sum + week.days.filter(day => numberValue(day.level) > 0).length, 0);
  const summary = `${copy.heatmapTitle}. ${activeDays} active days${chart.rangeLabel ? ` in ${chart.rangeLabel}` : ''}.`;
  if (!weeks.length) {
    return <ChartCard title={copy.heatmapTitle} copy={copy.heatmapCopy} palette={colors}>
      <EmptyCopy text={copy.heatmapEmpty} palette={colors} />
    </ChartCard>;
  }
  return <ChartCard title={copy.heatmapTitle} copy={copy.heatmapCopy} palette={colors}>
    <View accessible accessibilityRole="image" accessibilityLabel={summary}>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.heatmapScroll}>
        <View>
          <View style={styles.heatmapMonths}>
            <View style={styles.heatmapMonthSpacer} />
            {monthLabels.map((month, index) => <View key={`${month.label}-${index}`} style={{ width: month.span * 13 }}>
              <Text numberOfLines={1} style={[styles.heatmapMonth, { color: colors.textMuted }]}>{month.label}</Text>
            </View>)}
          </View>
          <View style={styles.heatmapBody}>
            <View style={styles.heatmapDays}>
              {dayLabels.map((day, index) => <View key={day} style={styles.heatmapDaySlot}>
                {index % 2 === 0 ? <Text style={[styles.heatmapDay, { color: colors.textMuted }]}>{day.slice(0, 3)}</Text> : null}
              </View>)}
            </View>
            <View style={styles.heatmapWeeks}>
              {weeks.map((week, weekIndex) => <View key={weekIndex} style={styles.heatmapWeek}>
                {week.days.map((day, dayIndex) => {
                  const level = numberValue(day.level);
                  const future = Boolean(day.future);
                  return <View key={`${weekIndex}-${dayIndex}`} style={{
                    width: 10,
                    height: 10,
                    borderRadius: 2,
                    backgroundColor: future ? 'transparent' : levels[Math.max(0, Math.min(4, level))],
                    borderWidth: future ? 1 : 0,
                    borderColor: withAlpha(colors.text, 0.08),
                  }} />;
                })}
              </View>)}
            </View>
          </View>
        </View>
      </ScrollView>
    </View>
    <View style={styles.heatmapLegend}>
      <Text style={[styles.heatmapLegendLabel, { color: colors.textMuted }]}>{copy.less}</Text>
      {levels.map(level => <View key={level} style={[styles.heatmapLegendCell, { backgroundColor: level }]} />)}
      <Text style={[styles.heatmapLegendLabel, { color: colors.textMuted }]}>{copy.more}</Text>
    </View>
  </ChartCard>;
}

export function StatisticsHoursByMediaTypeChart({ chart = {}, labels, palette }) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const chartLabels = chart.labels || [];
  const data = (chart.data || []).map(numberValue);
  const segmentColors = chart.colors || [];
  const total = data.reduce((sum, value) => sum + value, 0);
  const segments = chartLabels.map((label, index) => ({ key: label, label, value: data[index] || 0, color: segmentColors[index] || colors.accent }));
  const rows = segments
    .map((segment, index) => ({
      ...segment,
      key: segment.key || index,
      percent: percentOf(segment.value, total),
    }))
    .sort((a, b) => b.value - a.value);
  const summary = `${chart.title || copy.hoursTitle}. Total ${formatHours(total)} hours. ${rows.map(row => `${row.label} ${formatHours(row.value)} hours, ${row.percent} percent`).join('. ')}.`;
  return <ChartCard title={chart.title || copy.hoursTitle} copy={chart.copy || copy.hoursCopy} palette={colors}>
    {total <= 0
      ? <EmptyCopy text={copy.hoursEmpty} palette={colors} />
      : <View style={styles.donutRow}>
        <RingChart segments={segments} palette={colors} accessibilityLabel={summary}
          centerTitle={formatHours(total) + copy.hoursSuffix} centerCaption={chart.totalLabel || copy.hoursTotal} />
        <LegendRows rows={rows} palette={colors} valueLabel={value => `${formatHours(value)}${copy.hoursSuffix}`} />
      </View>}
  </ChartCard>;
}

export function StatisticsHoursChart({ chart = {}, labels, palette, title }) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const chartLabels = chart.labels || [];
  const data = (chart.data || []).map(numberValue);
  const total = data.reduce((sum, value) => sum + value, 0);
  const heading = title || chart.title || copy.hoursTitle;
  const summary = `${heading}. ${chartLabels.map((label, index) => `${label} ${formatHours(data[index] || 0)} hours`).join('. ')}.`;
  return <ChartCard title={heading} copy={chart.copy} palette={colors}>
    <BarChart labels={chartLabels} values={data}
      colors={data.map(() => chart.color || colors.accent)}
      palette={colors} accessibilityLabel={summary}
      emptyText={copy.hoursChartEmpty}
      valueLabel={value => formatHours(value)} />
  </ChartCard>;
}

export function StatisticsStatusCompositionChart({ chart = {}, labels, palette }) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const chartLabels = chart.labels || [];
  const data = (chart.data || []).map(numberValue);
  const segmentColors = chart.colors || [];
  const total = data.reduce((sum, value) => sum + value, 0);
  const segments = chartLabels.map((label, index) => ({ key: label, label, value: data[index] || 0, color: segmentColors[index] || colors.accent }));
  const rows = segments.map((segment, index) => ({
    ...segment,
    key: segment.key || index,
    percent: percentOf(segment.value, total),
  })).sort((a, b) => b.value - a.value);
  const summary = `${copy.statusTitle}. Total ${formatNumber(total)} items. ${rows.map(row => `${row.label} ${formatNumber(row.value)}, ${row.percent} percent`).join('. ')}.`;
  return <ChartCard title={copy.statusTitle} copy={copy.statusCopy} palette={colors}>
    {total <= 0
      ? <EmptyCopy text={copy.statusEmpty} palette={colors} />
      : <View style={styles.donutRow}>
        <RingChart segments={segments} palette={colors} accessibilityLabel={summary}
          centerTitle={formatNumber(total)} centerCaption="total items" />
        <LegendRows rows={rows} palette={colors} valueLabel={formatNumber} />
      </View>}
  </ChartCard>;
}

export function StatisticsRatingDistributionChart({ chart = {}, labels, palette }) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const chartLabels = chart.labels || [];
  const data = (chart.data || []).map(numberValue);
  const total = data.reduce((sum, value) => sum + value, 0);
  const copyText = total > 0
    ? interpolate(copy.ratingCopyCount, { count: formatNumber(total) })
    : copy.ratingCopy;
  const summary = `${copy.ratingTitle}. ${chartLabels.map((label, index) => `${interpolate(copy.ratingLabel, { rating: label })}: ${formatNumber(data[index] || 0)} items`).join('. ')}.`;
  return <ChartCard title={copy.ratingTitle} copy={copyText} palette={colors}>
    <BarChart labels={chartLabels} values={data}
      colors={data.map(() => colors.accent)}
      palette={colors} accessibilityLabel={summary}
      emptyText={copy.ratingEmpty} height={130} showValues
      valueLabel={(value, chartTotal) => `${formatNumber(value)}\n${percentOf(value, chartTotal)}%`} />
  </ChartCard>;
}

export function StatisticsStatusBreakdownChart({ chart = {}, labels, palette }) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const rows = chart.rows || [];
  const columns = (chart.columns || []).filter(column => rows.some(row => numberValue(row.statuses?.[column.label]) > 0));
  const sortedRows = rows.slice().sort((a, b) => numberValue(b.total) - numberValue(a.total));
  if (!sortedRows.length || !columns.length) {
    return <ChartCard title={copy.breakdownTitle} copy={copy.breakdownCopy} palette={colors}>
      <EmptyCopy text={copy.breakdownEmpty} palette={colors} />
    </ChartCard>;
  }
  const summary = `${copy.breakdownTitle}. ${sortedRows.map(row => `${row.label} total ${formatNumber(row.total)}`).join('. ')}.`;
  return <ChartCard title={copy.breakdownTitle} copy={copy.breakdownCopy} palette={colors}>
    <View accessible accessibilityRole="image" accessibilityLabel={summary}>
      <ScrollView horizontal showsHorizontalScrollIndicator={false}>
        <View>
          <View style={[styles.tableHeader, { borderBottomColor: colors.border }]}>
            <Text style={[styles.tableTypeHeader, { color: colors.textMuted }]}>{copy.breakdownCopy}</Text>
            <Text style={[styles.tableTotalHeader, { color: colors.textMuted }]}>{copy.breakdownTotal}</Text>
            {columns.map(column => <Text key={column.label} style={[styles.tableColumnHeader, { color: column.color }]}>
              {column.label}
            </Text>)}
          </View>
          {sortedRows.map(row => <View key={row.label} style={[styles.tableRow, { borderBottomColor: withAlpha(colors.border, 0.6) }]}>
            <Text numberOfLines={1} style={[styles.tableType, { color: colors.textSecondary }]}>{row.label}</Text>
            <Text style={[styles.tableTotal, { color: colors.text }]}>{formatNumber(row.total)}</Text>
            {columns.map(column => {
              const value = numberValue(row.statuses?.[column.label]);
              if (column.completed) {
                const pct = percentOf(value, row.total);
                return <View key={column.label} style={styles.tableCompletedCell}>
                  <View style={[styles.tableProgressTrack, { backgroundColor: withAlpha(colors.text, 0.1) }]}>
                    <View style={[styles.tableProgressFill, { width: `${pct}%`, backgroundColor: column.color }]} />
                  </View>
                  <Text style={[styles.tableCompletedValue, { color: column.color }]}>{formatNumber(value)}</Text>
                </View>;
              }
              return <Text key={column.label} style={[styles.tableColumnValue, { color: column.color }]}>
                {formatNumber(value)}
              </Text>;
            })}
          </View>)}
        </View>
      </ScrollView>
    </View>
  </ChartCard>;
}

export function StatisticsCompletionChart({ chart = {}, labels, palette }) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const rows = (chart.rows || []).filter(row => numberValue(row.total) > 0);
  const summary = `${copy.completionTitle}. ${rows.map(row => `${row.label} ${formatNumber(row.completed)} of ${formatNumber(row.total)} completed`).join('. ')}.`;
  return <ChartCard title={copy.completionTitle} copy={copy.completionCopy} palette={colors}>
    {!rows.length
      ? <EmptyCopy text={copy.completionEmpty} palette={colors} />
      : <View accessible accessibilityRole="image" accessibilityLabel={summary} style={styles.completionList}>
        {rows.map(row => {
          const pct = percentOf(row.completed, row.total);
          return <View key={row.label} style={styles.completionRow}>
            <Text numberOfLines={1} style={[styles.completionLabel, { color: colors.textSecondary }]}>{row.label}</Text>
            <View style={[styles.completionTrack, { backgroundColor: withAlpha(colors.text, 0.08) }]}>
              <View style={[styles.completionFill, { width: `${pct}%`, backgroundColor: row.color || colors.success }]} />
            </View>
            <Text style={[styles.completionValue, { color: colors.text }]}>
              {formatNumber(row.completed)} / {formatNumber(row.total)}
            </Text>
            <Text style={[styles.completionPercent, { color: colors.textMuted }]}>{pct}%</Text>
          </View>;
        })}
      </View>}
  </ChartCard>;
}

export function StatisticsFeaturedRepeat({ model = {}, labels, palette, onSelectPerson }) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const featured = model.featured;
  const pct = Math.max(0, Math.min(100, numberValue(featured?.pctOfLibrary)));
  const title = model.title || copy.featuredTitle;
  const intro = model.copy || copy.featuredCopy;
  const split = [
    { label: copy.featuredMovies, value: numberValue(featured?.uniqueMovies), color: '#3b82f6' },
    numberValue(featured?.uniqueGames) > 0
      ? { label: copy.featuredGames, value: numberValue(featured.uniqueGames), color: '#a855f7' }
      : null,
    { label: copy.featuredShows, value: numberValue(featured?.uniqueShows), color: '#10b981' },
  ].filter(Boolean);
  const summary = featured
    ? `${featured.name}, featured in ${formatNumber(featured.uniqueTitles)} titles, ${pct} percent of titles. `
      + split.map(item => `${item.label} ${formatNumber(item.value)}`).join(', ')
    : copy.featuredEmpty;
  return <View style={[styles.featuredCard, { backgroundColor: colors.surface }]}>
    <View style={styles.cardHeader}>
      <View style={styles.cardHeaderCopy}>
        <Text style={[styles.cardTitle, { color: colors.text }]}>{title}</Text>
        <Text style={[styles.cardCopy, { color: colors.textMuted }]}>{intro}</Text>
      </View>
    </View>
    {!featured
      ? <EmptyCopy text={copy.featuredEmpty} palette={colors} />
      : <View style={styles.featuredLayout}>
        <View style={styles.featuredIdentity}>
          {featured.image
            ? <Image source={{ uri: featured.image }} accessibilityLabel={featured.name}
              style={styles.featuredImage} resizeMode="cover" />
            : <View style={[styles.featuredImage, styles.featuredImageFallback, { backgroundColor: colors.surfaceStrong }]}>
              <Text style={[styles.featuredInitial, { color: colors.textMuted }]}>{(featured.name || '?').slice(0, 1)}</Text>
            </View>}
          <View style={styles.featuredStats}>
            <Text style={[styles.featuredName, { color: colors.text }]} numberOfLines={2}>{featured.name}</Text>
            <Text accessibilityLabel={summary} style={[styles.featuredTitles, { color: colors.link }]}>{formatNumber(featured.uniqueTitles)}</Text>
            <Text style={[styles.featuredTitlesLabel, { color: colors.textMuted }]}>{copy.featuredTitles}</Text>
            <View style={styles.featuredSplit}>
              {split.map(item => <View key={item.label} style={styles.featuredSplitItem}>
                <Text style={[styles.featuredSplitValue, { color: item.color }]}>{formatNumber(item.value)}</Text>
                <Text style={[styles.featuredSplitLabel, { color: colors.textMuted }]}>{item.label}</Text>
              </View>)}
            </View>
          </View>
          <View style={styles.featuredRing}>
            <RingChart
              segments={[
                { key: 'featured', label: 'Featured', value: pct, color: colors.accent },
                { key: 'other', label: 'Other', value: 100 - pct, color: withAlpha(colors.text, 0.07) },
              ]}
              size={112} thickness={12} palette={colors}
              accessibilityLabel={`${featured.name}: ${pct}% ${copy.featuredOfTitles}`}
              centerTitle={`${pct}%`} centerCaption={copy.featuredOfTitles} />
          </View>
        </View>
        <View style={[styles.featuredFooter, { borderTopColor: colors.border }]}>
          <View style={styles.featuredKnownFor}>
            <Text style={[styles.featuredKnownForLabel, { color: colors.textMuted }]}>{copy.featuredKnownFor}</Text>
            <View style={styles.featuredPills}>
              {(featured.knownFor || []).length
                ? featured.knownFor.map((pill, index) => <View key={`${pill.label}-${index}`}
                  style={[styles.featuredPill, { backgroundColor: colors.surfaceStrong }]}>
                  <Text style={[styles.featuredPillText, { color: colors.textSecondary }]}>{pill.label}</Text>
                </View>)
                : <Text style={[styles.featuredNoRoles, { color: colors.textMuted }]}>{copy.featuredNoRoles}</Text>}
            </View>
          </View>
          {onSelectPerson ? <Pressable accessibilityRole="button"
            accessibilityLabel={copy.featuredViewProfile}
            onPress={() => onSelectPerson(featured)}
            style={({ pressed }) => [styles.featuredProfile, pressed && styles.pressed]}>
            <Text style={[styles.featuredProfileText, { color: colors.link }]}>{copy.featuredViewProfile} →</Text>
          </Pressable> : null}
        </View>
      </View>}
  </View>;
}

const CHART_GROUPS = ['overview', 'heatmap', 'hours', 'status', 'breakdown', 'featured'];

export function StatisticsCharts({
  model = {},
  labels,
  palette,
  onSelectPerson,
  groups = CHART_GROUPS,
  showFeatured = true,
}) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const loading = Boolean(model.loading);
  const error = Boolean(model.error);
  const empty = Boolean(model.empty);
  if (error || loading || empty) {
    return <StatisticsState kind={error ? 'error' : loading ? 'loading' : 'empty'}
      labels={{
        loading: copy.loading,
        loadingCopy: copy.loadingCopy,
        loadError: copy.loadError,
        loadErrorCopy: copy.loadErrorCopy,
        empty: copy.empty,
        emptyCopy: copy.emptyCopy,
        retry: copy.retry,
      }}
      palette={colors} />;
  }
  const visible = new Set(groups || []);
  return <View style={styles.root}>
    {visible.has('overview') ? <View style={styles.row}>
      <View style={styles.cardHalf}>
        <StatisticsRhythmChart chart={model.rhythm} labels={copy} palette={colors} />
      </View>
      <View style={styles.cardHalf}>
        <StatisticsHoursByMediaTypeChart chart={model.mediaTypeHours} labels={copy} palette={colors} />
      </View>
    </View> : null}
    {visible.has('heatmap')
      ? <StatisticsHeatmapChart chart={model.heatmap} labels={copy} palette={colors} />
      : null}
    {visible.has('hours') ? <View style={styles.row}>
      <View style={styles.cardThird}>
        <StatisticsHoursChart chart={model.hoursByMonth} labels={copy} palette={colors}
          title={copy.hoursMonthTitle} />
      </View>
      <View style={styles.cardThird}>
        <StatisticsHoursChart chart={model.hoursByWeekday} labels={copy} palette={colors}
          title={copy.hoursWeekdayTitle} />
      </View>
      <View style={styles.cardThird}>
        <StatisticsHoursChart chart={model.hoursByTimeOfDay} labels={copy} palette={colors}
          title={copy.hoursTimeTitle} />
      </View>
    </View> : null}
    {visible.has('status') ? <View style={styles.row}>
      <View style={styles.cardHalf}>
        <StatisticsStatusCompositionChart chart={model.statusComposition} labels={copy} palette={colors} />
      </View>
      <View style={styles.cardHalf}>
        <StatisticsRatingDistributionChart chart={model.ratingDistribution} labels={copy} palette={colors} />
      </View>
    </View> : null}
    {visible.has('breakdown') ? <View style={styles.row}>
      <View style={styles.cardWide}>
        <StatisticsStatusBreakdownChart chart={model.statusBreakdown} labels={copy} palette={colors} />
      </View>
      <View style={styles.cardThird}>
        <StatisticsCompletionChart chart={model.completion} labels={copy} palette={colors} />
      </View>
    </View> : null}
    {showFeatured && visible.has('featured')
      ? <StatisticsFeaturedRepeat model={{ featured: model.featured }} labels={copy}
        palette={colors} onSelectPerson={onSelectPerson} />
      : null}
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: 16, width: '100%' },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: 16, width: '100%' },
  cardHalf: { flexGrow: 1, flexBasis: 320, minWidth: 0 },
  cardThird: { flexGrow: 1, flexBasis: 220, minWidth: 0 },
  cardWide: { flexGrow: 2, flexBasis: 460, minWidth: 0 },
  card: { borderRadius: 12, padding: 24, gap: 12, flexGrow: 1 },
  cardHeader: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 },
  cardHeaderCopy: { flexShrink: 1, gap: 2 },
  cardTitle: { fontSize: 16, fontWeight: '600' },
  cardCopy: { fontSize: 12, lineHeight: 16 },
  emptyCopy: { fontSize: 12, textAlign: 'center', paddingVertical: 24 },
  ring: { alignItems: 'center', justifyContent: 'center' },
  ringTick: { position: 'absolute' },
  ringCenter: { position: 'absolute', alignItems: 'center', justifyContent: 'center' },
  ringCenterTitle: { fontSize: 15, fontWeight: '700' },
  ringCenterCaption: { fontSize: 9, textAlign: 'center' },
  donutRow: { flexDirection: 'row', alignItems: 'center', gap: 16, flexWrap: 'wrap' },
  legend: { flexShrink: 1, flexGrow: 1, gap: 6, minWidth: 160 },
  legendRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  legendSwatch: { width: 9, height: 9, borderRadius: 2 },
  legendLabel: { width: 68, fontSize: 10, fontWeight: '600' },
  legendTrack: { flexGrow: 1, flexShrink: 1, height: 5, borderRadius: 3, overflow: 'hidden', minWidth: 28 },
  legendFill: { height: 5, borderRadius: 3 },
  legendPercent: { width: 34, fontSize: 10, fontWeight: '700', textAlign: 'right' },
  legendValue: { width: 46, fontSize: 10, textAlign: 'right' },
  barRow: { flexDirection: 'row', alignItems: 'flex-end', gap: 6, minWidth: '100%' },
  barScroll: { minWidth: '100%' },
  barSlot: { alignItems: 'center', gap: 3 },
  barSlotFlex: { flexGrow: 1, flexShrink: 1, flexBasis: 0 },
  barSlotCompact: { width: 24 },
  barValue: { fontSize: 8, textAlign: 'center', lineHeight: 10 },
  barTrack: { width: '100%', justifyContent: 'flex-end', alignItems: 'center' },
  barFill: { width: '70%', minWidth: 3, borderRadius: 3 },
  barLabel: { fontSize: 8, textAlign: 'center' },
  matrix: { gap: 3 },
  matrixHourRow: { flexDirection: 'row', alignItems: 'center' },
  matrixDaySpacer: { width: 30 },
  matrixHourLabel: { flexGrow: 1, flexBasis: 0, fontSize: 8, textAlign: 'center' },
  matrixRow: { flexDirection: 'row', alignItems: 'center' },
  matrixDayLabel: { width: 30, fontSize: 8 },
  matrixCells: { flexDirection: 'row', alignItems: 'center' },
  rhythmLegend: { flexDirection: 'row', alignItems: 'center', gap: 3, flexWrap: 'wrap', justifyContent: 'flex-end' },
  rhythmLegendLabel: { fontSize: 8 },
  heatmapScroll: { paddingRight: 4 },
  heatmapMonths: { flexDirection: 'row', marginBottom: 4 },
  heatmapMonthSpacer: { width: 26 },
  heatmapMonth: { fontSize: 8 },
  heatmapBody: { flexDirection: 'row' },
  heatmapDays: { width: 26, paddingTop: 1 },
  heatmapDaySlot: { height: 13 },
  heatmapDay: { fontSize: 8, lineHeight: 10 },
  heatmapWeeks: { flexDirection: 'row', gap: 3 },
  heatmapWeek: { gap: 3 },
  heatmapLegend: { flexDirection: 'row', alignItems: 'center', justifyContent: 'flex-end', gap: 4 },
  heatmapLegendLabel: { fontSize: 8 },
  heatmapLegendCell: { width: 9, height: 9, borderRadius: 2 },
  tableHeader: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingBottom: 6, borderBottomWidth: 1, minWidth: 420 },
  tableTypeHeader: { width: 120, fontSize: 9, fontWeight: '600' },
  tableTotalHeader: { width: 48, fontSize: 9, fontWeight: '600', textAlign: 'right' },
  tableColumnHeader: { width: 72, fontSize: 9, fontWeight: '600', textAlign: 'right' },
  tableRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 7, borderBottomWidth: 1, minWidth: 420 },
  tableType: { width: 120, fontSize: 11 },
  tableTotal: { width: 48, fontSize: 11, fontWeight: '600', textAlign: 'right' },
  tableCompletedCell: { width: 72, flexDirection: 'row', alignItems: 'center', gap: 4 },
  tableProgressTrack: { width: 34, height: 4, borderRadius: 2, overflow: 'hidden' },
  tableProgressFill: { height: 4, borderRadius: 2 },
  tableCompletedValue: { flexGrow: 1, fontSize: 10, textAlign: 'right' },
  tableColumnValue: { width: 72, fontSize: 11, textAlign: 'right' },
  completionList: { gap: 8 },
  completionRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  completionLabel: { width: 58, fontSize: 10 },
  completionTrack: { flexGrow: 1, flexShrink: 1, height: 6, borderRadius: 3, overflow: 'hidden', minWidth: 30 },
  completionFill: { height: 6, borderRadius: 3 },
  completionValue: { width: 62, fontSize: 10, textAlign: 'right' },
  completionPercent: { width: 30, fontSize: 10, textAlign: 'right' },
  featuredCard: { borderRadius: 10, padding: 16, gap: 12 },
  featuredLayout: { gap: 12 },
  featuredIdentity: { flexDirection: 'row', alignItems: 'center', gap: 12, flexWrap: 'wrap' },
  featuredImage: { width: 84, height: 84, borderRadius: 42 },
  featuredImageFallback: { alignItems: 'center', justifyContent: 'center' },
  featuredInitial: { fontSize: 28, fontWeight: '700' },
  featuredStats: { flexShrink: 1, flexGrow: 1, minWidth: 140, gap: 1 },
  featuredName: { fontSize: 15, fontWeight: '600' },
  featuredTitles: { fontSize: 24, fontWeight: '700' },
  featuredTitlesLabel: { fontSize: 9, textTransform: 'uppercase', letterSpacing: 0.8 },
  featuredSplit: { flexDirection: 'row', gap: 14, marginTop: 4, flexWrap: 'wrap' },
  featuredSplitItem: { gap: 1 },
  featuredSplitValue: { fontSize: 16, fontWeight: '600' },
  featuredSplitLabel: { fontSize: 9 },
  featuredRing: { alignItems: 'center', justifyContent: 'center' },
  featuredFooter: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12, paddingTop: 12, borderTopWidth: 1, flexWrap: 'wrap' },
  featuredKnownFor: { flexShrink: 1, flexGrow: 1, gap: 5, minWidth: 160 },
  featuredKnownForLabel: { fontSize: 11 },
  featuredPills: { flexDirection: 'row', flexWrap: 'wrap', gap: 5 },
  featuredPill: { borderRadius: 5, paddingHorizontal: 8, paddingVertical: 4 },
  featuredPillText: { fontSize: 10, fontWeight: '600' },
  featuredNoRoles: { fontSize: 11 },
  featuredProfile: { paddingVertical: 4 },
  featuredProfileText: { fontSize: 12, fontWeight: '600' },
  pressed: { opacity: 0.72 },
});
