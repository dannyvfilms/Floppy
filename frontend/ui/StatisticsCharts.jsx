import React, { useMemo } from 'react';
import {
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from 'react-native';
import { StatisticsState } from './StatisticsSummary';

const DEFAULT_PALETTE = {
  background: '#181b2e',
  surface: 'rgba(23, 27, 49, 0.72)',
  surfaceStrong: '#252b49',
  surfaceMuted: '#292f4c',
  border: '#343c5e',
  text: '#f8f9ff',
  textSecondary: '#d1d5db',
  textMuted: '#aab3d1',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  accentContrast: '#ffffff',
  link: '#67e8f9',
  danger: '#ef4444',
  warning: '#f59e0b',
  success: '#10b981',
  radius: 18,
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
  statusTitle: 'Status Composition',
  statusCopy: 'What portion of your library is in each state.',
  statusEmpty: 'No status data available for this range.',
  statusTotal: 'total items',
  ratingTitle: 'Rating Distribution',
  ratingCopy: 'How your {count} rated items are distributed.',
  ratingEmpty: 'No ratings yet for this filter.',
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

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MAX_TICK_COLOR = '#D1D5DB';
const AXIS_MUTED = '#6b7280';

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

function formatChartHours(hours) {
  const minutes = Math.round(numberValue(hours) * 60);
  return `${Math.floor(minutes / 60)}h ${minutes % 60}min`;
}

function niceStep(max) {
  if (max <= 5) return 1;
  if (max <= 10) return 2;
  if (max <= 40) return 5;
  return 10;
}

function ChartCard({ title, copy, palette, children, headerRight, padding, flat }) {
  return <View style={[styles.card, !flat && {
    backgroundColor: palette.surface,
    borderRadius: palette.radius,
    padding,
  }]}>
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
  return <View style={styles.emptyWrap}>
    <Text style={[styles.emptyCopy, { color: palette.textMuted }]}>{text}</Text>
  </View>;
}

function RingChart({
  segments, palette, accessibilityLabel, centerTitle, centerCaption, size = 150, thickness = 26, testID,
}) {
  const total = segments.reduce((sum, segment) => sum + numberValue(segment.value), 0);
  const tickCount = 180;
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
  const innerSize = Math.round(size * 0.66);
  const radius = size / 2 - thickness / 2;
  const tickWidth = Math.max(3, (Math.PI * (size - thickness)) / tickCount + 1.8);
  return <View accessible accessibilityRole="image"
    accessibilityLabel={accessibilityLabel} testID={testID}
    style={[styles.ring, { width: size, height: size }]}>
    {ticks.map((color, index) => {
      const angle = (360 / tickCount) * index;
      return <View key={index} style={[styles.ringTick, {
        width: tickWidth,
        height: thickness,
        backgroundColor: color,
        left: size / 2 - tickWidth / 2,
        top: size / 2 - thickness / 2,
        transform: [{ rotate: `${angle}deg` }, { translateY: -radius }],
      }]} />;
    })}
    <View style={[styles.ringCenter, {
      width: innerSize,
      height: innerSize,
      borderRadius: innerSize / 2,
      left: (size - innerSize) / 2,
      top: (size - innerSize) / 2,
    }]}>
      {centerTitle ? <Text style={[styles.ringCenterTitle, { color: palette.text }]}>{centerTitle}</Text> : null}
      {centerCaption ? <Text style={[styles.ringCenterCaption, { color: '#9ca3af' }]}>{centerCaption}</Text> : null}
    </View>
  </View>;
}

function LegendRow({
  color, label, percent, value, palette, labelWidth, rowGap, percentColor, valueMinWidth,
}) {
  return <View testID="statistics-legend-row" style={[styles.legendRow, { gap: rowGap || 14 }]}>
    <View style={[styles.legendLabelWrap, { width: labelWidth || 74 }]}>
      <View style={[styles.legendSwatch, { backgroundColor: color }]} />
      <Text numberOfLines={1} style={[styles.legendLabel, { color: '#d1d5db' }]}>{label}</Text>
    </View>
    <View style={[styles.legendTrack, { backgroundColor: 'rgba(255,255,255,0.07)' }]}>
      <View style={[styles.legendFill, { width: `${percent}%`, backgroundColor: color }]} />
    </View>
    <Text style={[styles.legendPercent, { color: percentColor || palette.textSecondary }]}>{percent}%</Text>
    {value ? <Text style={[styles.legendValue, { color: AXIS_MUTED, minWidth: valueMinWidth || 80 }]}>{value}</Text> : null}
  </View>;
}

function usePadding() {
  const { width } = useWindowDimensions();
  return { padding: width >= 640 ? 24 : 16 };
}

export function StatisticsRhythmChart({ chart = {}, labels, palette }) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const sizing = usePadding();
  const matrix = chart.matrix || [];
  const sessions = matrix.reduce((sum, row) => sum + row.reduce((rowSum, value) => rowSum + numberValue(value), 0), 0);
  const active = matrix.reduce((sum, row) => sum + row.filter(value => numberValue(value) > 0).length, 0);
  let peak = 0;
  matrix.forEach(row => row.forEach(value => { peak = Math.max(peak, numberValue(value)); }));
  const summary = `${copy.rhythmTitle}. ${active} active hours across ${formatNumber(sessions)} sessions. Peak ${formatNumber(peak)} sessions.`;
  const dayLabels = chart.weekdayLabels || ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const tiers = [0.33, 0.47, 0.6, 0.73, 0.87, 1];
  return <ChartCard title={copy.rhythmTitle} copy={copy.rhythmCopy} palette={colors}
      padding={sizing.padding}
      headerRight={<View style={styles.rhythmLegend}>
        <Text style={[styles.rhythmLegendLabel, { color: AXIS_MUTED }]}>{copy.low}</Text>
        {[5, 7, 8, 9, 11, 12].map((size, index) => <View key={size} style={{
          width: size,
          height: size,
          borderRadius: size / 2,
          backgroundColor: withAlpha(colors.accent, tiers[index]),
        }} />)}
        <Text style={[styles.rhythmLegendLabel, { color: AXIS_MUTED }]}>{copy.high}</Text>
      </View>}>
      {sessions <= 0
        ? <EmptyCopy text={copy.rhythmEmpty} palette={colors} />
        : <View accessible accessibilityRole="image" accessibilityLabel={summary} style={styles.rhythmBody}>
          <View style={styles.rhythmHours}>
            {['12 AM', '6 AM', '12 PM', '6 PM'].map((label, index) => <View key={label} style={[styles.rhythmHourSlot, {
              left: `${(index + 0.5) * 25 - 7}%`,
            }]}>
              <Text style={[styles.rhythmHourLabel, { color: AXIS_MUTED }]}>{label}</Text>
            </View>)}
          </View>
          {matrix.map((row, rowIndex) => <View key={rowIndex} style={styles.rhythmRow}>
            <Text style={[styles.rhythmDay, { color: AXIS_MUTED }]}>{dayLabels[rowIndex] || ''}</Text>
            <View style={styles.rhythmCells}>
              {row.map((value, columnIndex) => {
                const count = numberValue(value);
                const tier = count <= 0 ? 0 : Math.min(6, Math.ceil((count / Math.max(1, peak)) * 6));
                const size = count <= 0 ? 3.6 : 4 + tier * 1.4;
                return <View key={columnIndex} style={styles.rhythmCell}>
                  <View style={{
                    width: size,
                    height: size,
                    borderRadius: size / 2,
                    backgroundColor: count <= 0 ? 'rgba(255,255,255,0.05)' : withAlpha(colors.accent, tiers[tier - 1]),
                  }} />
                </View>;
              })}
            </View>
          </View>)}
        </View>}
  </ChartCard>;
}

export function StatisticsHeatmapChart({ chart = {}, labels, palette }) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const sizing = usePadding();
  const weeks = chart.weeks || [];
  const monthLabels = chart.monthLabels || [];
  const dayLabels = chart.weekdayLabels || ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const levels = [
    colors.surfaceMuted,
    '#4338ca',
    '#4f46e5',
    '#6366f1',
    '#818cf8',
  ];
  const activeDays = weeks.reduce((sum, week) => sum + week.days.filter(day => numberValue(day.level) > 0).length, 0);
  const summary = `${copy.heatmapTitle}. ${activeDays} active days${chart.rangeLabel ? ` in ${chart.rangeLabel}` : ''}.`;
  const cell = 16;
  const gap = 4;
  if (!weeks.length) {
    return <ChartCard title={copy.heatmapTitle} copy={copy.heatmapCopy} palette={colors}
      padding={sizing.padding}>
      <EmptyCopy text={copy.heatmapEmpty} palette={colors} />
    </ChartCard>;
  }
  const gridWidth = weeks.length * cell + (weeks.length - 1) * gap;
  return <ChartCard title={copy.heatmapTitle} copy={copy.heatmapCopy} palette={colors}
      padding={sizing.padding}
      headerRight={<View style={styles.heatmapLegend}>
        <Text style={[styles.heatmapLegendLabel, { color: colors.textMuted }]}>{copy.less}</Text>
        {levels.map(level => <View key={level} style={[styles.heatmapLegendCell, { backgroundColor: level }]} />)}
        <Text style={[styles.heatmapLegendLabel, { color: colors.textMuted }]}>{copy.more}</Text>
      </View>}>
      <View accessible accessibilityRole="image" accessibilityLabel={summary}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false}>
          <View>
            <View style={styles.heatmapMonths}>
              <View style={styles.heatmapMonthSpacer} />
              {monthLabels.map((month, index) => <View key={`${month.label}-${index}`}
                style={[styles.heatmapMonthCell, {
                  width: month.span * (cell + gap) - gap,
                  borderLeftWidth: index === 0 ? 0 : 1,
                  borderLeftColor: colors.border,
                  paddingLeft: index === 0 ? 0 : 4,
                }]}>
                <Text numberOfLines={1} style={[styles.heatmapMonth, { color: colors.textMuted }]}>{month.label}</Text>
              </View>)}
            </View>
            <View style={styles.heatmapBody}>
              <View style={styles.heatmapDays}>
                {dayLabels.map((day, index) => <View key={day} style={[styles.heatmapDaySlot, { height: cell }]}>
                  {index % 2 === 0 ? <Text style={[styles.heatmapDay, { color: colors.textMuted }]}>{(day || '').slice(0, 3)}</Text> : null}
                </View>)}
              </View>
              <View style={[styles.heatmapWeeks, { width: gridWidth, gap }]}>
                {weeks.map((week, weekIndex) => <View key={weekIndex} style={{ gap }}>
                  {week.days.map((day, dayIndex) => {
                    const level = numberValue(day.level);
                    return <View key={`${weekIndex}-${dayIndex}`} style={{
                      width: cell,
                      height: cell,
                      borderRadius: 2,
                      backgroundColor: levels[Math.max(0, Math.min(4, level))],
                    }} />;
                  })}
                </View>)}
              </View>
            </View>
          </View>
        </ScrollView>
      </View>
  </ChartCard>;
}

export function StatisticsHoursByMediaTypeChart({ chart = {}, labels, palette }) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const sizing = usePadding();
  const { width } = useWindowDimensions();
  const stacked = width >= 1024 && width < 1420;
  const chartLabels = chart.labels || [];
  const data = (chart.data || []).map(numberValue);
  const segmentColors = chart.colors || [];
  const total = data.reduce((sum, value) => sum + value, 0);
  const segments = chartLabels.map((label, index) => ({
    key: label, label, value: data[index] || 0, color: segmentColors[index] || colors.accent,
  }));
  const rows = segments
    .map((segment, index) => ({
      ...segment,
      key: segment.key || index,
      percent: total > 0 ? Math.round((segment.value / total) * 100) : 0,
    }))
    .sort((a, b) => b.value - a.value);
  const summary = `${chart.title || copy.hoursTitle}. Total ${formatChartHours(total)}. ${rows.map(row => `${row.label} ${formatChartHours(row.value)}, ${row.percent} percent`).join('. ')}.`;
  return <ChartCard title={chart.title || copy.hoursTitle} copy={chart.copy || copy.hoursCopy}
      palette={colors} padding={sizing.padding}>
      {total <= 0
        ? <EmptyCopy text={copy.hoursEmpty} palette={colors} />
        : <View style={[styles.donutRow, stacked && styles.donutRowStacked]}>
          <RingChart segments={segments} palette={colors} accessibilityLabel={summary}
            centerTitle={formatChartHours(total)} centerCaption={chart.totalLabel || copy.hoursTotal} />
          <View style={[styles.legendScroll, stacked && styles.legendScrollStacked]}>
            {rows.map((row, index) => <View key={row.key} style={index ? styles.legendRowSpacing : undefined}>
              <LegendRow color={row.color} label={row.label}
                percent={row.percent} value={formatChartHours(row.value)}
                palette={colors} labelWidth={74} rowGap={14} />
            </View>)}
          </View>
        </View>}
  </ChartCard>;
}

function BarChart({
  labels, values, color, palette, accessibilityLabel, emptyText, height,
  showValues, valueFormatter, rotateLabels,
}) {
  const total = values.reduce((sum, value) => sum + numberValue(value), 0);
  if (!labels.length || total <= 0) {
    return <EmptyCopy text={emptyText} palette={palette} />;
  }
  const max = Math.max(...values.map(numberValue));
  const step = niceStep(max);
  const top = Math.max(step, Math.ceil(max / step) * step);
  const tickCount = Math.round(top / step);
  const ticks = [];
  for (let index = 0; index <= tickCount; index += 1) ticks.push(index * step);
  const labelHeight = rotateLabels ? 44 : 24;
  const labelStep = rotateLabels && labels.length > 12 ? 2 : 1;
  const chartHeight = height - labelHeight;
  const barWidth = Math.max(8, Math.min(20, Math.round(340 / labels.length)));
  return <View accessible accessibilityRole="image" accessibilityLabel={accessibilityLabel}>
    <View style={[styles.barChart, { height: chartHeight }]}>
      <View style={styles.barAxis}>
        {ticks.slice().reverse().map(tick => <Text key={tick} style={[styles.barTick, { color: MAX_TICK_COLOR }]}>{tick}</Text>)}
      </View>
      <View style={styles.barPlot}>
        {ticks.slice().reverse().map((tick, index) => <View key={tick} style={[styles.barGridLine, {
          top: `${(index / Math.max(1, ticks.length - 1)) * 100}%`,
          backgroundColor: 'rgba(255,255,255,0.1)',
        }]} />)}
        <View style={styles.barRow}>
          {labels.map((label, index) => {
            const value = numberValue(values[index]);
            const fillHeight = value > 0 ? Math.max(2, (value / top) * chartHeight) : 0;
            return <View key={`${label}-${index}`} style={styles.barSlot}>
              {showValues && value > 0 ? <Text style={[styles.barValue, { color: palette.textSecondary }]}>
                {valueFormatter ? valueFormatter(value, total) : value}
              </Text> : null}
              {value > 0 ? <View style={[styles.barFill, {
                height: fillHeight,
                width: barWidth,
                backgroundColor: color || palette.accent,
                borderColor: 'rgba(255,255,255,0.1)',
              }]} /> : null}
            </View>;
          })}
        </View>
      </View>
    </View>
    <View style={[styles.barLabels, { height: labelHeight }]}>
      <View style={styles.barLabelSpacer} />
      {labels.map((label, index) => <View key={`${label}-label-${index}`} style={styles.barLabelSlot}>
        {index % labelStep === 0 ? <Text numberOfLines={rotateLabels ? undefined : 1} style={[styles.barLabel, {
          color: MAX_TICK_COLOR,
          width: rotateLabels ? 64 : undefined,
          transform: rotateLabels ? [{ rotate: '-45deg' }] : undefined,
        }]}>{label}</Text> : null}
      </View>)}
    </View>
  </View>;
}

export function StatisticsHoursChart({ chart = {}, labels, palette, title, flat = false }) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const sizing = usePadding();
  const chartLabels = (chart.labels || []).map(label => MONTH_NAMES[Number(label)] || label);
  const rawLabels = chart.labels || [];
  const data = (chart.data || []).map(numberValue);
  const total = data.reduce((sum, value) => sum + value, 0);
  const heading = title || chart.title || copy.hoursTitle;
  const summary = `${heading}. ${rawLabels.map((label, index) => `${label} ${formatChartHours(data[index] || 0)}`).join('. ')}.`;
  const rotate = (chart.labels || []).length > 7;
  return <ChartCard title={heading} copy={chart.copy} palette={colors} padding={sizing.padding} flat={flat}>
      <BarChart labels={chartLabels} values={data}
        color={chart.color || colors.accent}
        palette={colors} accessibilityLabel={summary}
        emptyText={copy.hoursChartEmpty}
        height={256} rotateLabels={rotate}
        valueFormatter={value => formatChartHours(value)} />
  </ChartCard>;
}

export function StatisticsStatusCompositionChart({ chart = {}, labels, palette }) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const sizing = usePadding();
  const { width } = useWindowDimensions();
  const stacked = width >= 1024 && width < 1420;
  const chartLabels = chart.labels || [];
  const data = (chart.data || []).map(numberValue);
  const segmentColors = chart.colors || [];
  const total = data.reduce((sum, value) => sum + value, 0);
  const segments = chartLabels.map((label, index) => ({
    key: label, label, value: data[index] || 0, color: segmentColors[index] || colors.accent,
  }));
  const rows = segments.map((segment, index) => ({
    ...segment,
    key: segment.key || index,
    percent: total > 0 ? Math.round((segment.value / total) * 100) : 0,
  })).sort((a, b) => b.value - a.value);
  const summary = `${copy.statusTitle}. Total ${formatNumber(total)} items. ${rows.map(row => `${row.label} ${formatNumber(row.value)}, ${row.percent} percent`).join('. ')}.`;
  return <ChartCard title={copy.statusTitle} copy={copy.statusCopy} palette={colors}
      padding={sizing.padding}>
      {total <= 0
        ? <EmptyCopy text={copy.statusEmpty} palette={colors} />
        : <View style={[styles.donutRow, stacked && styles.donutRowStacked]}>
          <RingChart segments={segments} palette={colors} accessibilityLabel={summary}
            testID="status-composition-chart"
            centerTitle={formatNumber(total)} centerCaption={copy.statusTotal} />
          <ScrollView testID="status-composition-legend" horizontal={!stacked} showsHorizontalScrollIndicator={false}
            style={[styles.legendScroll, stacked && styles.legendScrollStacked]}>
            <View style={styles.statusLegendRows}>
              {rows.map(row => <LegendRow key={row.key} color={row.color} label={row.label}
                percent={row.percent} value={formatNumber(row.value)}
                palette={colors} labelWidth={84} rowGap={10} percentColor={colors.text}
                valueMinWidth={60} />)}
            </View>
          </ScrollView>
        </View>}
  </ChartCard>;
}

export function StatisticsRatingDistributionChart({ chart = {}, labels, palette }) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const sizing = usePadding();
  const chartLabels = chart.labels || [];
  const data = (chart.data || []).map(numberValue);
  const total = data.reduce((sum, value) => sum + value, 0);
  const copyText = interpolate(copy.ratingCopy, { count: formatNumber(total) });
  const summary = `${copy.ratingTitle}. ${chartLabels.map((label, index) => `${label}: ${formatNumber(data[index] || 0)} items`).join('. ')}.`;
  return <ChartCard title={copy.ratingTitle} copy={copyText} palette={colors}
      padding={sizing.padding}>
      {total <= 0
        ? <View style={[styles.ratingEmpty, { height: 174 }]}>
          <Text style={[styles.ratingEmptyText, { color: colors.textMuted }]}>{copy.ratingEmpty}</Text>
        </View>
        : <BarChart labels={chartLabels.map(String)} values={data}
          color={colors.accent} palette={colors} accessibilityLabel={summary}
          emptyText={copy.ratingEmpty} height={174} showValues
          valueFormatter={(value, chartTotal) => `${formatNumber(value)} (${Math.round((value / chartTotal) * 100)}%)`} />}
  </ChartCard>;
}

export function StatisticsStatusBreakdownChart({ chart = {}, labels, palette }) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const sizing = usePadding();
  const rows = chart.rows || [];
  const columns = (chart.columns || []).filter(column => rows.some(row => numberValue(row.statuses?.[column.label]) > 0));
  const sortedRows = rows.slice().sort((a, b) => numberValue(b.total) - numberValue(a.total));
  const summary = `${copy.breakdownTitle}. ${sortedRows.map(row => `${row.label} total ${formatNumber(row.total)}`).join('. ')}.`;
  return <ChartCard title={copy.breakdownTitle} palette={colors} padding={sizing.padding}>
      {!sortedRows.length || !columns.length
        ? <EmptyCopy text={copy.breakdownEmpty} palette={colors} />
        : <View accessible accessibilityRole="image" accessibilityLabel={summary}>
          <ScrollView horizontal showsHorizontalScrollIndicator={false}>
            <View>
              <View style={[styles.tableHeader, { borderBottomColor: colors.border }]}>
                <Text style={[styles.tableTypeHeader, { color: colors.textMuted }]}>{copy.breakdownCopy}</Text>
                <Text style={[styles.tableTotalHeader, { color: colors.textMuted }]}>{copy.breakdownTotal}</Text>
                {columns.map(column => <Text key={column.label} style={[styles.tableColumnHeader, { color: column.color }]}>
                  {column.label}
                </Text>)}
              </View>
              {sortedRows.map(row => <View key={row.label} style={[styles.tableRow, { borderBottomColor: colors.border }]}>
                <Text numberOfLines={1} style={[styles.tableType, { color: colors.textSecondary }]}>{row.label}</Text>
                <Text style={[styles.tableTotal, { color: colors.text }]}>{formatNumber(row.total)}</Text>
                {columns.map(column => {
                  const value = numberValue(row.statuses?.[column.label]);
                  if (column.completed) {
                    const pct = row.total > 0 ? (value / row.total) * 100 : 0;
                    return <View key={column.label} style={styles.tableCompletedCell}>
                      <View style={[styles.tableProgressTrack, { backgroundColor: 'rgba(255,255,255,0.1)' }]}>
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
        </View>}
  </ChartCard>;
}

export function StatisticsCompletionChart({ chart = {}, labels, palette }) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const sizing = usePadding();
  const rows = (chart.rows || []).filter(row => numberValue(row.total) > 0);
  const summary = `${copy.completionTitle}. ${rows.map(row => `${row.label} ${formatNumber(row.completed)} of ${formatNumber(row.total)} completed`).join('. ')}.`;
  return <ChartCard title={copy.completionTitle} copy={copy.completionCopy} palette={colors}
      padding={sizing.padding}>
      {!rows.length
        ? <EmptyCopy text={copy.completionEmpty} palette={colors} />
        : <View accessible accessibilityRole="image" accessibilityLabel={summary} style={styles.completionList}>
          {rows.map(row => {
            const pct = row.total > 0 ? Math.round((row.completed / row.total) * 100) : 0;
            return <View key={row.label} style={styles.completionRow}>
              <Text numberOfLines={1} style={[styles.completionLabel, { color: colors.textSecondary }]}>{row.label}</Text>
              <View style={[styles.completionTrack, { backgroundColor: 'rgba(255,255,255,0.08)' }]}>
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
  const sizing = usePadding();
  const featured = model.featured;
  const pct = Math.max(0, Math.min(100, numberValue(featured?.pctOfLibrary)));
  const title = model.title || copy.featuredTitle;
  const intro = model.copy || copy.featuredCopy;
  const split = [
    { label: copy.featuredMovies, value: numberValue(featured?.uniqueMovies), color: '#60a5fa' },
    numberValue(featured?.uniqueGames) > 0
      ? { label: copy.featuredGames, value: numberValue(featured.uniqueGames), color: '#a78bfa' }
      : null,
    { label: copy.featuredShows, value: numberValue(featured?.uniqueShows), color: '#34d399' },
  ].filter(Boolean);
  const summary = featured
    ? `${featured.name}, featured in ${formatNumber(featured.uniqueTitles)} titles, ${pct} percent of titles. `
      + split.map(item => `${item.label} ${formatNumber(item.value)}`).join(', ')
    : copy.featuredEmpty;
  return <View style={[styles.featuredCard, {
      backgroundColor: colors.surface, borderRadius: colors.radius, padding: sizing.padding,
    }]}>
      <View style={styles.featuredHeader}>
        <Text style={[styles.featuredTitle, { color: colors.text }]}>{title}</Text>
        <Text style={[styles.featuredCopy, { color: colors.textMuted }]}>{intro}</Text>
      </View>
      {!featured
        ? <EmptyCopy text={copy.featuredEmpty} palette={colors} />
        : <View style={styles.featuredLayout}>
          <View style={styles.featuredIdentity}>
            <View style={styles.featuredPortraitWrap}>
              {featured.image
                ? <Image source={{ uri: featured.image }} accessibilityLabel={featured.name}
                  style={[styles.featuredImage, { backgroundColor: colors.surfaceStrong }]} resizeMode="cover" />
                : <View style={[styles.featuredImage, styles.featuredImageFallback, { backgroundColor: colors.surfaceStrong }]}>
                  <Text style={[styles.featuredInitial, { color: colors.textMuted }]}>{(featured.name || '?').slice(0, 1)}</Text>
                </View>}
            </View>
            <View style={styles.featuredStats}>
              <Text style={[styles.featuredName, { color: colors.text }]} numberOfLines={1}>{featured.name}</Text>
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
                  { key: 'other', label: 'Other', value: 100 - pct, color: 'rgba(255,255,255,0.08)' },
                ]}
                size={96} thickness={14} palette={colors}
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
              <Text style={[styles.featuredProfileText, { color: colors.link }]}>{copy.featuredViewProfile} {'\u2192'}</Text>
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
  const { width } = useWindowDimensions();
  const wide = width >= 1024;
  const halfStyle = [styles.cardHalf, !wide && styles.cardFull];
  const thirdStyle = [styles.cardThird, !wide && styles.cardFull];
  return <View style={styles.root}>
    {visible.has('overview') ? <View style={styles.row}>
      <View style={halfStyle}>
        <StatisticsRhythmChart chart={model.rhythm} labels={copy} palette={colors} />
      </View>
      <View style={halfStyle}>
        <StatisticsHoursByMediaTypeChart chart={model.mediaTypeHours} labels={copy} palette={colors} />
      </View>
    </View> : null}
    {visible.has('heatmap')
      ? <StatisticsHeatmapChart chart={model.heatmap} labels={copy} palette={colors} />
      : null}
    {visible.has('hours') ? <View style={styles.row}>
      <View style={thirdStyle}>
        <StatisticsHoursChart chart={model.hoursByMonth} labels={copy} palette={colors}
          title={copy.hoursMonthTitle} />
      </View>
      <View style={thirdStyle}>
        <StatisticsHoursChart chart={model.hoursByWeekday} labels={copy} palette={colors}
          title={copy.hoursWeekdayTitle} />
      </View>
      <View style={thirdStyle}>
        <StatisticsHoursChart chart={model.hoursByTimeOfDay} labels={copy} palette={colors}
          title={copy.hoursTimeTitle} />
      </View>
    </View> : null}
    {visible.has('status') ? <View style={styles.row}>
      <View style={halfStyle}>
        <StatisticsStatusCompositionChart chart={model.statusComposition} labels={copy} palette={colors} />
      </View>
      <View style={halfStyle}>
        <StatisticsRatingDistributionChart chart={model.ratingDistribution} labels={copy} palette={colors} />
      </View>
    </View> : null}
    {visible.has('breakdown') ? <View style={styles.row}>
      <View style={[styles.cardWide, !wide && styles.cardFull]}>
        <StatisticsStatusBreakdownChart chart={model.statusBreakdown} labels={copy} palette={colors} />
      </View>
      <View style={thirdStyle}>
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
  cardFull: { flexGrow: 0, flexBasis: '100%' },
  card: { width: '100%' },
  cardHeader: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, marginBottom: 12 },
  cardHeaderCopy: { flexShrink: 1, minWidth: 0, gap: 2 },
  cardTitle: { fontSize: 16, lineHeight: 24, fontWeight: '600' },
  cardCopy: { fontSize: 12, lineHeight: 16 },
  emptyWrap: { paddingVertical: 32, alignItems: 'center' },
  emptyCopy: { fontSize: 14, lineHeight: 20, textAlign: 'center' },
  ring: { alignItems: 'center', justifyContent: 'center' },
  ringTick: { position: 'absolute', borderRadius: 0 },
  ringCenter: { position: 'absolute', alignItems: 'center', justifyContent: 'center' },
  ringCenterTitle: { fontSize: 16, lineHeight: 19, fontWeight: '700' },
  ringCenterCaption: { fontSize: 10.4, lineHeight: 12.5 },
  donutRow: { flexDirection: 'row', alignItems: 'center', gap: 24, minHeight: 150 },
  donutRowStacked: { flexDirection: 'column', alignItems: 'center', gap: 16 },
  legendScroll: { flexGrow: 1, flexShrink: 1, minWidth: 0, maxHeight: 150, overflow: 'hidden' },
  legendScrollStacked: { width: '100%', flexGrow: 0, maxHeight: 150 },
  statusLegendRows: { gap: 8, minWidth: 250 },
  legendRow: { flexDirection: 'row', alignItems: 'center' },
  legendRowSpacing: { marginTop: 10 },
  legendLabelWrap: { flexShrink: 0, flexDirection: 'row', alignItems: 'center', gap: 6 },
  legendSwatch: { width: 10, height: 10, borderRadius: 2 },
  legendLabel: { flexShrink: 1, fontSize: 11, lineHeight: 14.3 },
  legendTrack: { flexGrow: 1, flexShrink: 1, height: 5, borderRadius: 3, overflow: 'hidden', minWidth: 40 },
  legendFill: { height: 5, borderRadius: 3 },
  legendPercent: { flexShrink: 0, width: 34, textAlign: 'center', fontSize: 11, lineHeight: 14.3, fontWeight: '600' },
  legendValue: { flexShrink: 0, textAlign: 'center', fontSize: 11, lineHeight: 14.3 },
  rhythmBody: { height: 153 },
  rhythmHours: { height: 20 },
  rhythmHourSlot: { position: 'absolute', width: 44, alignItems: 'center' },
  rhythmHourLabel: { fontSize: 11, lineHeight: 14 },
  rhythmRow: { flex: 1, flexDirection: 'row', alignItems: 'center' },
  rhythmDay: { width: 32, fontSize: 11, lineHeight: 14, textAlign: 'right', paddingRight: 6 },
  rhythmCells: { flex: 1, flexDirection: 'row', alignItems: 'center' },
  rhythmCell: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  rhythmLegend: { flexDirection: 'row', alignItems: 'center', gap: 6, flexShrink: 0 },
  rhythmLegendLabel: { fontSize: 9, lineHeight: 13.5 },
  heatmapLegend: { flexShrink: 0, flexDirection: 'row', alignItems: 'center', gap: 8 },
  heatmapLegendLabel: { fontSize: 12, lineHeight: 16 },
  heatmapLegendCell: { width: 12, height: 12, borderRadius: 3 },
  heatmapMonths: { flexDirection: 'row', marginBottom: 8 },
  heatmapMonthSpacer: { width: 37 },
  heatmapMonthCell: { height: 16 },
  heatmapMonth: { fontSize: 12, lineHeight: 16 },
  heatmapBody: { flexDirection: 'row' },
  heatmapDays: { width: 37, paddingRight: 8, gap: 4 },
  heatmapDaySlot: { justifyContent: 'center' },
  heatmapDay: { fontSize: 14, lineHeight: 16, textAlign: 'right' },
  heatmapWeeks: { flexDirection: 'row' },
  barChart: { flexDirection: 'row' },
  barAxis: { width: 32, justifyContent: 'space-between', paddingRight: 6 },
  barTick: { fontSize: 12, lineHeight: 14, textAlign: 'right', marginTop: -7 },
  barPlot: { flex: 1, minWidth: 0, justifyContent: 'flex-end' },
  barGridLine: { position: 'absolute', left: 0, right: 0, height: 1 },
  barRow: { flexDirection: 'row', alignItems: 'flex-end', height: '100%' },
  barSlot: { flex: 1, alignItems: 'center', justifyContent: 'flex-end', minWidth: 0 },
  barFill: { borderRadius: 6, borderWidth: 1 },
  barValue: { fontSize: 10, lineHeight: 12, textAlign: 'center', marginBottom: 2 },
  barLabels: { flexDirection: 'row' },
  barLabelSpacer: { width: 32 },
  barLabelSlot: { flex: 1, alignItems: 'center', justifyContent: 'center', minWidth: 0, overflow: 'visible' },
  barLabel: { fontSize: 12, lineHeight: 14, textAlign: 'center' },
  ratingEmpty: { alignItems: 'center', justifyContent: 'center' },
  ratingEmptyText: { fontSize: 14, lineHeight: 20, textAlign: 'center' },
  tableHeader: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingBottom: 8, borderBottomWidth: 1, minWidth: 420 },
  tableTypeHeader: { flexGrow: 1, minWidth: 110, fontSize: 12, fontWeight: '500' },
  tableTotalHeader: { width: 56, fontSize: 12, fontWeight: '500', textAlign: 'right' },
  tableColumnHeader: { width: 84, fontSize: 12, fontWeight: '500', textAlign: 'right' },
  tableRow: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 8, borderBottomWidth: 1, minWidth: 420 },
  tableType: { flexGrow: 1, minWidth: 110, fontSize: 14 },
  tableTotal: { width: 56, fontSize: 14, fontWeight: '600', textAlign: 'right' },
  tableCompletedCell: { width: 116, flexDirection: 'row', alignItems: 'center', gap: 8 },
  tableProgressTrack: { width: 34, height: 4, borderRadius: 2, overflow: 'hidden' },
  tableProgressFill: { height: 4, borderRadius: 2 },
  tableCompletedValue: { flexGrow: 1, fontSize: 14, textAlign: 'right' },
  tableColumnValue: { width: 84, fontSize: 14, textAlign: 'right' },
  completionList: { gap: 8 },
  completionRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  completionLabel: { width: 72, fontSize: 12 },
  completionTrack: { flexGrow: 1, flexShrink: 1, height: 6, borderRadius: 3, overflow: 'hidden', minWidth: 30 },
  completionFill: { height: 6, borderRadius: 3 },
  completionValue: { width: 62, fontSize: 12, textAlign: 'right' },
  completionPercent: { width: 34, fontSize: 12, textAlign: 'right' },
  featuredCard: { width: '100%' },
  featuredHeader: { gap: 2, marginBottom: 16 },
  featuredTitle: { fontSize: 20, lineHeight: 28, fontWeight: '600' },
  featuredCopy: { fontSize: 14, lineHeight: 20 },
  featuredLayout: { gap: 16 },
  featuredIdentity: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  featuredPortraitWrap: { width: 96 },
  featuredImage: { width: 96, height: 96, borderRadius: 48 },
  featuredImageFallback: { alignItems: 'center', justifyContent: 'center' },
  featuredInitial: { fontSize: 28, fontWeight: '700' },
  featuredStats: { flexShrink: 1, flexGrow: 1, minWidth: 0, gap: 4 },
  featuredName: { fontSize: 18, lineHeight: 22, fontWeight: '600' },
  featuredTitles: { fontSize: 36, lineHeight: 36, fontWeight: '700' },
  featuredTitlesLabel: { fontSize: 12, lineHeight: 12, textTransform: 'uppercase', letterSpacing: 0.6 },
  featuredSplit: { flexDirection: 'row', gap: 16, flexWrap: 'wrap' },
  featuredSplitItem: { minWidth: 60 },
  featuredSplitValue: { fontSize: 24, lineHeight: 24, fontWeight: '600' },
  featuredSplitLabel: { fontSize: 12, lineHeight: 12, marginTop: 4 },
  featuredRing: { alignItems: 'center', justifyContent: 'center' },
  featuredFooter: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12, paddingTop: 16, borderTopWidth: 1, flexWrap: 'wrap' },
  featuredKnownFor: { flexShrink: 1, flexGrow: 1, gap: 8, minWidth: 160 },
  featuredKnownForLabel: { fontSize: 14, lineHeight: 20 },
  featuredPills: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  featuredPill: { borderRadius: 6, paddingHorizontal: 8, paddingVertical: 4 },
  featuredPillText: { fontSize: 12, lineHeight: 16, fontWeight: '500' },
  featuredNoRoles: { fontSize: 14, lineHeight: 20 },
  featuredProfile: { paddingVertical: 4 },
  featuredProfileText: { fontSize: 14, lineHeight: 20, fontWeight: '500' },
  pressed: { opacity: 0.72 },
});
