import React, { useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Image,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from 'react-native';
import { Badge } from './Badge';
import { Button } from './Button';
import { DateTimePicker } from './DateTimePicker';

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
  range: 'Range',
  mediaType: 'Media type',
  refresh: 'Refresh statistics',
  refreshing: 'Refreshing statistics',
  close: 'Close',
  apply: 'Apply range',
  customRange: 'Custom range',
  startDate: 'Start date',
  endDate: 'End date',
  predefinedRanges: 'Predefined ranges',
  allMedia: 'All media',
  spent: "You've spent",
  hours: 'hours',
  with: 'with',
  titles: 'titles',
  daysOf: "That's",
  days: 'days of',
  keepExploring: '. Keep exploring.',
  completed: 'Completed Items',
  averageRating: 'Average Rating',
  mostActiveDay: 'Most Active Day',
  currentStreak: 'Current Streak',
  activity: 'Activity',
  ofActivity: '% of activity',
  day: 'day',
  daysLabel: 'days',
  longest: 'Longest: ',
  showStreakDates: 'Show information',
  loading: 'Loading statistics...',
  loadingCopy: 'Calculated on the server from your tracked history.',
  loadError: 'Statistics could not be loaded.',
  loadErrorCopy: 'Check the server connection and try again.',
  retry: 'Try again',
  empty: 'Nothing tracked in this range',
  emptyCopy: 'Choose a wider range or add something to your library.',
  updated: 'Updated',
  firstPlay: 'First Play',
  lastPlay: 'Last Play',
  today: 'Today',
  notAvailable: '--',
  vs: 'vs',
  selectedTypes: 'types selected',
  rangeSelected: 'range selected',
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
  return numberValue(value).toLocaleString();
}

function plural(count, one, many) {
  return count === 1 ? one : many;
}

function todayLabel(iso) {
  if (!iso) return '';
  return String(iso);
}

function buttonPalette(palette) {
  return {
    radius: palette.radiusSmall,
    primary: {
      background: palette.accentStrong,
      pressed: palette.accentStrong,
      hovered: palette.accent,
      text: palette.accentContrast,
      border: 'transparent',
    },
    surface: {
      background: palette.surfaceStrong,
      pressed: palette.surfaceMuted,
      hovered: palette.surfaceMuted,
      text: palette.text,
      border: palette.border,
    },
    focusStyle: {},
  };
}

function dateTimePalette(palette) {
  return {
    text: palette.text,
    textSecondary: palette.textSecondary,
    textMuted: palette.textMuted,
    surface: palette.surface,
    surfaceStrong: palette.surfaceStrong,
    surfaceMuted: palette.surfaceMuted,
    border: palette.border,
    accent: palette.accent,
    accentContrast: palette.accentContrast,
    link: palette.link,
    danger: palette.danger,
    radius: palette.radius,
    radiusSmall: palette.radiusSmall,
    fontSize: 14,
    smallFontSize: 12,
  };
}

const dateLabels = {
  field: 'Date',
  mobileLabel: 'Date',
  notSet: 'Not set',
  openPicker: 'Open date picker',
  picker: 'Date picker',
  quickActions: 'Quick actions',
  clear: 'Clear date',
  close: 'Close date picker',
  previousMonth: 'Previous month',
  nextMonth: 'Next month',
  selectMonth: 'Select month',
  previousYear: 'Previous year',
  nextYear: 'Next year',
  selectYear: 'Select year',
  previousYears: 'Previous years',
  nextYears: 'Next years',
  year: 'Year',
  back: 'Back',
  time: 'Time',
  now: 'Now',
  none: 'None',
  suggestedDate: 'Suggested date',
  hour: 'Hour',
  minute: 'Minute',
  second: 'Second',
  earlierHour: 'Earlier hour',
  laterHour: 'Later hour',
  earlierMinute: 'Earlier minute',
  laterMinute: 'Later minute',
  earlierSecond: 'Earlier second',
  laterSecond: 'Later second',
  activity: 'View activity for',
};

function SummaryCard({ icon, color, label, value, caption, badge, info, palette }) {
  const [infoOpen, setInfoOpen] = useState(false);
  return <View style={[styles.card, { backgroundColor: palette.surface }]}>
    <View style={[styles.cardIcon, { backgroundColor: `${color}22` }]}>
      <Text style={[styles.cardIconText, { color }]}>{icon}</Text>
    </View>
    <View style={styles.cardBody}>
      <Text style={[styles.cardLabel, { color: palette.textMuted }]}>{label}</Text>
      <View style={styles.cardValueRow}>
        {badge ? <Badge label={badge.label} size="xs" tone="outline"
          palette={{
            outline: {
              color: badge.state === 'up' ? palette.success : badge.state === 'down' ? palette.danger : palette.textMuted,
              borderColor: palette.border,
              borderWidth: 1,
            },
          }} /> : null}
        <Text style={[styles.cardValue, { color: badge && badge.state === 'up' ? palette.success : badge && badge.state === 'down' ? palette.danger : palette.text }]} numberOfLines={1}>{value}</Text>
      </View>
      {caption ? <Text style={[styles.cardCaption, { color: palette.textMuted }]}>{caption}</Text> : null}
      {info ? <Pressable accessibilityRole="button"
        accessibilityLabel={info.label}
        accessibilityState={{ expanded: infoOpen }}
        onPress={() => setInfoOpen(value => !value)}
        style={styles.infoTrigger}>
        <Text style={[styles.infoGlyph, { color: palette.textMuted }]}>i</Text>
      </Pressable> : null}
      {info && infoOpen ? <Text style={[styles.infoText, { color: palette.textSecondary }]}>{info.text}</Text> : null}
    </View>
  </View>;
}

export function StatisticsHero({ model, labels, palette }) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const summary = model.summary || {};
  const totalHours = numberValue(summary.totalHours);
  const total = numberValue(summary.total);
  const totalDays = numberValue(summary.totalDays);
  return <View style={styles.hero}>
    <Text style={[styles.heroLine, { color: colors.text }]}>
      {copy.spent} <Text style={[styles.heroAccent, { color: colors.link }]}>{formatNumber(totalHours)}</Text> {copy.hours}
    </Text>
    <Text style={[styles.heroLine, { color: colors.text }]}>
      {copy.with} <Text style={[styles.heroAccent, { color: colors.link }]}>{formatNumber(total)}</Text> {summary.typeLabel || copy.titles}.
    </Text>
    <View style={styles.heroBadgeRow}>
      <View style={[styles.heroSpark, { backgroundColor: colors.surface }]}>
        <Text style={[styles.heroSparkText, { color: colors.link }]}>✦</Text>
      </View>
      <Text style={[styles.heroCaption, { color: colors.textMuted }]}>
        {copy.daysOf} <Text style={{ color: colors.textSecondary }}>{formatNumber(totalDays)}</Text> {copy.days} {summary.typeFlavor || copy.titles}{copy.keepExploring}
      </Text>
    </View>
  </View>;
}

export function StatisticsHighlights({ model, labels, palette, onSelectHighlight }) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const { width } = useWindowDimensions();
  const compact = width < 720;
  const cards = (model.highlights || []).slice(0, 3);
  const cardWidth = compact ? 250 : undefined;
  const content = cards.map(item => {
    const pressable = Boolean(item.href && onSelectHighlight);
    const body = <View style={[styles.highlightCard, { backgroundColor: colors.surface }, cardWidth ? { width: cardWidth } : styles.highlightGrow]}>
      {item.image ? <Image source={{ uri: item.image }} style={styles.highlightImage}
        accessibilityIgnoresInvertColors accessibilityLabel={item.title || item.label} /> : <View style={[styles.highlightImage, { backgroundColor: colors.surfaceStrong }]} />}
      <View style={styles.highlightBody}>
        <Badge label={item.label} size="xs" tone="outline"
          palette={{ outline: { color: colors.textMuted, borderColor: colors.border, borderWidth: 1 } }} />
        <Text style={[styles.highlightTitle, { color: colors.text }]} numberOfLines={1}>{item.title || copy.notAvailable}</Text>
        {item.meta ? <Text style={[styles.highlightMeta, { color: colors.textMuted }]} numberOfLines={1}>{item.meta}</Text> : null}
        {item.date ? <Text style={[styles.highlightDate, { color: colors.textMuted }]}>{item.date}</Text> : null}
      </View>
    </View>;
    return pressable
      ? <Pressable key={item.key || item.label} accessibilityRole="link"
        accessibilityLabel={`${item.label}: ${item.title}`}
        onPress={() => onSelectHighlight?.(item)} style={({ pressed }) => pressed && styles.pressed}>
        {body}
      </Pressable>
      : <View key={item.key || item.label}>{body}</View>;
  });
  if (!content.length) {
    return null;
  }
  if (compact) {
    return <ScrollView horizontal showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.highlightRow}>{content}</ScrollView>;
  }
  return <View style={[styles.highlightRow, styles.highlightRowWide]}>{content}</View>;
}

export function StatisticsSummaryCards({ model, labels, palette }) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const summary = model.summary || {};
  const scaleMax = numberValue(model.scaleMax) || 10;
  const hasTotal = numberValue(summary.total) > 0;
  const completedValue = hasTotal
    ? `${formatNumber(summary.completed)} / ${formatNumber(summary.total)}`
    : copy.notAvailable;
  const ratingValue = summary.hasScore
    ? `${summary.averageScore} / ${scaleMax}`
    : copy.notAvailable;
  const mostActiveValue = summary.mostActiveDayLabel || summary.mostActiveDay || copy.notAvailable;
  const mostActiveCaption = summary.mostActiveDay
    ? `${numberValue(summary.mostActiveDayPercentage)}${copy.ofActivity}`
    : '';
  const currentStreak = numberValue(summary.currentStreak);
  const longestStreak = numberValue(summary.longestStreak);
  const streakValue = hasTotal
    ? `${currentStreak} ${plural(currentStreak, copy.day, copy.daysLabel)}`
    : copy.notAvailable;
  const streakCaption = hasTotal
    ? `${copy.longest}${longestStreak} ${plural(longestStreak, copy.day, copy.daysLabel)}`
    : '';
  const comparison = summary.comparison || {};
  const activityValue = comparison.label || copy.notAvailable;
  const activityCaption = comparison.periodLabel ? `${copy.vs} ${comparison.periodLabel}` : '';
  return <View style={styles.cardGrid}>
    <SummaryCard icon="✓" color={colors.link} label={copy.completed}
      value={completedValue} palette={colors} />
    <SummaryCard icon="★" color={colors.warning} label={copy.averageRating}
      value={ratingValue} palette={colors} />
    <SummaryCard icon="▦" color={colors.success} label={copy.mostActiveDay}
      value={mostActiveValue} caption={mostActiveCaption} palette={colors} />
    <SummaryCard icon="◔" color={colors.danger} label={copy.currentStreak}
      value={streakValue} caption={streakCaption} palette={colors}
      info={summary.longestStreakStart ? {
        label: copy.showStreakDates,
        text: summary.longestStreakDates || todayLabel(summary.longestStreakStart),
      } : null} />
    <SummaryCard icon={comparison.state === 'down' ? '↘' : comparison.state === 'up' ? '↗' : '→'}
      color={comparison.state === 'up' ? colors.success : comparison.state === 'down' ? colors.danger : colors.textMuted}
      label={copy.activity} value={activityValue} caption={activityCaption}
      palette={colors}
      info={comparison.details ? {
        label: copy.activity,
        text: comparison.details,
      } : null} />
  </View>;
}

export function StatisticsActivityOverview({ model, labels, palette, onSelectHighlight }) {
  return <View style={styles.activityOverview}>
    <StatisticsHero model={model} labels={labels} palette={palette} />
    <StatisticsHighlights model={model} labels={labels} palette={palette}
      onSelectHighlight={onSelectHighlight} />
    <StatisticsSummaryCards model={model} labels={labels} palette={palette} />
  </View>;
}

export function StatisticsState({ kind = 'loading', labels, palette, onRetry }) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const isError = kind === 'error';
  const isEmpty = kind === 'empty';
  return <View style={[styles.stateCard, { backgroundColor: colors.surface, borderColor: colors.border }]}>
    {kind === 'loading' ? <ActivityIndicator color={colors.accent} /> : null}
    <Text style={[styles.stateTitle, { color: colors.text }]}>
      {isError ? copy.loadError : isEmpty ? copy.empty : copy.loading}
    </Text>
    <Text style={[styles.stateCopy, { color: colors.textMuted }]}>
      {isError ? copy.loadErrorCopy : isEmpty ? copy.emptyCopy : copy.loadingCopy}
    </Text>
    {isError && onRetry ? <Button label={copy.retry} width="auto"
      onPress={onRetry} palette={buttonPalette(colors)} /> : null}
  </View>;
}

export function StatisticsToolbar({
  model,
  labels,
  palette,
  onChangeRange,
  onChangeMediaTypes,
  onRefresh,
}) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const { width } = useWindowDimensions();
  const compact = width < 720;
  const [open, setOpen] = useState(null);
  const [custom, setCustom] = useState(false);
  const [customStart, setCustomStart] = useState(model.range?.startDate || '');
  const [customEnd, setCustomEnd] = useState(model.range?.endDate || '');
  const rangeOptions = model.range?.options || [];
  const mediaOptions = model.mediaTypes?.options || [];
  const selectedTypes = model.mediaTypes?.selected || [];
  const selectedSet = useMemo(() => new Set(selectedTypes), [selectedTypes]);
  const selectedCount = selectedTypes.length;
  const mediaLabel = selectedCount === 0
    ? copy.allMedia
    : selectedCount === 1
      ? (mediaOptions.find(option => option.value === selectedTypes[0])?.label || selectedTypes[0])
      : `${selectedCount} ${copy.selectedTypes}`;
  const rangeLabel = model.range?.label || copy.range;
  const refreshing = Boolean(model.refreshing || model.loading);
  const close = () => {
    setOpen(null);
    setCustom(false);
  };
  function chooseRange(option) {
    if (option.custom) {
      setCustom(true);
      return;
    }
    onChangeRange?.({ value: option.value, label: option.label, startDate: option.startDate, endDate: option.endDate });
    close();
  }
  function applyCustomRange() {
    if (!customStart || !customEnd) return;
    onChangeRange?.({
      value: 'custom',
      label: `${customStart} – ${customEnd}`,
      startDate: customStart,
      endDate: customEnd,
    });
    close();
  }
  function toggleMediaType(value) {
    if (value === 'all') {
      onChangeMediaTypes?.([]);
      close();
      return;
    }
    const next = selectedSet.has(value)
      ? selectedTypes.filter(item => item !== value)
      : [...selectedTypes, value];
    onChangeMediaTypes?.(next);
  }
  return <View style={[styles.toolbar, compact && styles.toolbarCompact]}>
    <View style={styles.toolbarButtons}>
      <Pressable accessibilityRole="button"
        accessibilityLabel={`${copy.range}: ${rangeLabel}`}
        accessibilityState={{ expanded: open === 'range' }}
        onPress={() => setOpen(open === 'range' ? null : 'range')}
        style={({ pressed }) => [styles.trigger, { backgroundColor: colors.surface, borderColor: colors.border }, open === 'range' && { borderColor: colors.accent }, pressed && styles.pressed]}>
        <Text style={[styles.triggerGlyph, { color: colors.link }]}>▦</Text>
        <Text style={[styles.triggerText, { color: colors.textSecondary }]} numberOfLines={1}>{rangeLabel}</Text>
        <Text style={[styles.chevron, { color: colors.textMuted }]}>▾</Text>
      </Pressable>
      <Pressable accessibilityRole="button"
        accessibilityLabel={`${copy.mediaType}: ${mediaLabel}`}
        accessibilityState={{ expanded: open === 'media' }}
        onPress={() => setOpen(open === 'media' ? null : 'media')}
        style={({ pressed }) => [styles.trigger, { backgroundColor: colors.surface, borderColor: colors.border }, open === 'media' && { borderColor: colors.accent }, pressed && styles.pressed]}>
        <Text style={[styles.triggerGlyph, { color: colors.link }]}>⌄</Text>
        <Text style={[styles.triggerText, { color: colors.textSecondary }]} numberOfLines={1}>{mediaLabel}</Text>
        <Text style={[styles.chevron, { color: colors.textMuted }]}>▾</Text>
      </Pressable>
      <Button label={refreshing ? copy.refreshing : copy.refresh} tone="surface"
        busy={refreshing} onPress={() => onRefresh?.()}
        palette={buttonPalette(colors)} />
    </View>
    {model.updatedLabel ? <Text style={[styles.updated, { color: colors.textMuted }]}>
      {copy.updated} {model.updatedLabel}
    </Text> : null}

    <Modal visible={open === 'range'} transparent animationType="fade" onRequestClose={close}>
      <View style={[styles.overlay, { backgroundColor: 'rgba(0,0,0,0.55)' }]}>
        <Pressable accessibilityRole="button" accessibilityLabel={copy.close}
          onPress={close} style={styles.backdrop} />
        <View style={[styles.sheet, { backgroundColor: colors.surface, borderColor: colors.border }, compact && styles.sheetCompact]}>
          <View style={[styles.sheetHeader, { borderBottomColor: colors.border }]}>
            <Text style={[styles.sheetTitle, { color: colors.text }]}>{copy.range}</Text>
            <Pressable accessibilityRole="button" accessibilityLabel={copy.close}
              onPress={close} style={({ pressed }) => [styles.closeButton, { backgroundColor: colors.surfaceStrong }, pressed && styles.pressed]}>
              <Text style={[styles.closeText, { color: colors.textSecondary }]}>×</Text>
            </Pressable>
          </View>
          <ScrollView style={styles.sheetScroll} contentContainerStyle={styles.sheetContent}
            keyboardShouldPersistTaps="handled">
            {!custom ? <View style={styles.optionList}>
              <Text style={[styles.sheetSectionTitle, { color: colors.textMuted }]}>{copy.predefinedRanges}</Text>
              {rangeOptions.map(option => {
                const selected = model.range?.selected === option.value;
                return <Pressable key={option.value}
                  accessibilityRole="button"
                  accessibilityState={{ selected }}
                  onPress={() => chooseRange(option)}
                  style={({ pressed }) => [styles.option, { backgroundColor: selected ? colors.accentStrong : colors.surfaceStrong }, pressed && styles.pressed]}>
                  <View style={styles.optionCopy}>
                    <Text style={[styles.optionTitle, { color: selected ? colors.accentContrast : colors.text }]}>{option.label}</Text>
                    {option.dateLabel ? <Text style={[styles.optionMeta, { color: selected ? colors.accentContrast : colors.textMuted }]}>{option.dateLabel}</Text> : null}
                  </View>
                  {selected ? <Text style={[styles.optionCheck, { color: colors.accentContrast }]}>✓</Text> : null}
                </Pressable>;
              })}
              <Pressable accessibilityRole="button" onPress={() => setCustom(true)}
                style={({ pressed }) => [styles.customButton, { borderColor: colors.border }, pressed && styles.pressed]}>
                <Text style={[styles.customButtonText, { color: colors.textSecondary }]}>{copy.customRange}</Text>
              </Pressable>
            </View> : <View style={styles.customPane}>
              <Text style={[styles.sheetSectionTitle, { color: colors.textMuted }]}>{copy.customRange}</Text>
              <Text style={[styles.fieldLabel, { color: colors.textSecondary }]}>{copy.startDate}</Text>
              <DateTimePicker value={customStart} onChange={setCustomStart}
                trackTime={false} labels={dateLabels} palette={dateTimePalette(colors)} />
              <Text style={[styles.fieldLabel, { color: colors.textSecondary }]}>{copy.endDate}</Text>
              <DateTimePicker value={customEnd} onChange={setCustomEnd}
                trackTime={false} labels={dateLabels} palette={dateTimePalette(colors)} />
              <View style={styles.customActions}>
                <Pressable accessibilityRole="button" onPress={() => setCustom(false)}
                  style={({ pressed }) => [styles.cancelButton, { borderColor: colors.border }, pressed && styles.pressed]}>
                  <Text style={[styles.cancelText, { color: colors.textSecondary }]}>{copy.close}</Text>
                </Pressable>
                <Button label={copy.apply} width="auto" onPress={applyCustomRange}
                  palette={buttonPalette(colors)} />
              </View>
            </View>}
          </ScrollView>
        </View>
      </View>
    </Modal>

    <Modal visible={open === 'media'} transparent animationType="fade" onRequestClose={close}>
      <View style={[styles.overlay, { backgroundColor: 'rgba(0,0,0,0.55)' }]}>
        <Pressable accessibilityRole="button" accessibilityLabel={copy.close}
          onPress={close} style={styles.backdrop} />
        <View style={[styles.sheet, { backgroundColor: colors.surface, borderColor: colors.border }, compact && styles.sheetCompact]}>
          <View style={[styles.sheetHeader, { borderBottomColor: colors.border }]}>
            <Text style={[styles.sheetTitle, { color: colors.text }]}>{copy.mediaType}</Text>
            <Pressable accessibilityRole="button" accessibilityLabel={copy.close}
              onPress={close} style={({ pressed }) => [styles.closeButton, { backgroundColor: colors.surfaceStrong }, pressed && styles.pressed]}>
              <Text style={[styles.closeText, { color: colors.textSecondary }]}>×</Text>
            </Pressable>
          </View>
          <ScrollView style={styles.sheetScroll} contentContainerStyle={styles.sheetContent}
            keyboardShouldPersistTaps="handled">
            <View style={styles.optionList}>
              <Pressable accessibilityRole="button"
                accessibilityState={{ selected: selectedCount === 0 }}
                onPress={() => toggleMediaType('all')}
                style={({ pressed }) => [styles.option, {
                  backgroundColor: selectedCount === 0 ? colors.accentStrong : colors.surfaceStrong,
                }, pressed && styles.pressed]}>
                <Text style={[styles.optionTitle, { color: selectedCount === 0 ? colors.accentContrast : colors.text }]}>{copy.allMedia}</Text>
                {selectedCount === 0 ? <Text style={[styles.optionCheck, { color: colors.accentContrast }]}>✓</Text> : null}
              </Pressable>
              {mediaOptions.map(option => {
                const selected = selectedSet.has(option.value);
                return <Pressable key={option.value}
                  accessibilityRole="button"
                  accessibilityState={{ selected }}
                  onPress={() => toggleMediaType(option.value)}
                  style={({ pressed }) => [styles.option, {
                    backgroundColor: selected ? colors.accentStrong : colors.surfaceStrong,
                  }, pressed && styles.pressed]}>
                  <Text style={[styles.optionTitle, { color: selected ? colors.accentContrast : colors.text }]}>{option.label}</Text>
                  {selected ? <Text style={[styles.optionCheck, { color: colors.accentContrast }]}>✓</Text> : null}
                </Pressable>;
              })}
            </View>
          </ScrollView>
        </View>
      </View>
    </Modal>
  </View>;
}

export function StatisticsSummary({
  model = {},
  labels,
  palette,
  onChangeRange,
  onChangeMediaTypes,
  onRefresh,
  onSelectHighlight,
  onRetry,
}) {
  const colors = mergePalette(palette);
  const loading = Boolean(model.loading);
  const error = Boolean(model.error);
  const empty = Boolean(model.empty);
  return <View style={styles.root}>
    <StatisticsToolbar model={model} labels={labels} palette={colors}
      onChangeRange={onChangeRange}
      onChangeMediaTypes={onChangeMediaTypes}
      onRefresh={onRefresh} />
    {error ? <StatisticsState kind="error" labels={labels} palette={colors} onRetry={onRetry} />
      : loading ? <StatisticsState kind="loading" labels={labels} palette={colors} />
        : empty ? <StatisticsState kind="empty" labels={labels} palette={colors} />
          : <StatisticsActivityOverview model={model} labels={labels} palette={colors}
            onSelectHighlight={onSelectHighlight} />}
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: 16, width: '100%' },
  toolbar: { gap: 8, width: '100%' },
  toolbarCompact: { gap: 6 },
  toolbarButtons: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 },
  trigger: {
    minHeight: 40,
    maxWidth: 240,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 12,
    borderRadius: 8,
    borderWidth: 1,
  },
  triggerGlyph: { fontSize: 14, fontWeight: '700' },
  triggerText: { flexShrink: 1, fontSize: 13, fontWeight: '600' },
  chevron: { fontSize: 12 },
  updated: { fontSize: 11 },
  hero: { gap: 2 },
  heroLine: { fontSize: 24, fontWeight: '700', lineHeight: 30 },
  heroAccent: { fontWeight: '700' },
  heroBadgeRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 12 },
  heroSpark: { width: 28, height: 28, borderRadius: 14, alignItems: 'center', justifyContent: 'center' },
  heroSparkText: { fontSize: 13 },
  heroCaption: { flexShrink: 1, fontSize: 12, lineHeight: 17 },
  highlightRow: { gap: 12, paddingVertical: 2 },
  highlightRowWide: { flexDirection: 'row', alignItems: 'stretch' },
  highlightGrow: { flex: 1 },
  highlightCard: { borderRadius: 10, overflow: 'hidden' },
  highlightImage: { width: '100%', aspectRatio: 3 / 2 },
  highlightBody: { padding: 10, gap: 4 },
  highlightTitle: { fontSize: 13, fontWeight: '600' },
  highlightMeta: { fontSize: 11 },
  highlightDate: { fontSize: 11 },
  cardGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  card: {
    flexGrow: 1,
    flexBasis: 150,
    minWidth: 140,
    borderRadius: 10,
    padding: 12,
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
  },
  cardIcon: { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center' },
  cardIconText: { fontSize: 15, fontWeight: '700' },
  cardBody: { flexShrink: 1, gap: 2 },
  cardLabel: { fontSize: 11, fontWeight: '600' },
  cardValueRow: { flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' },
  cardValue: { fontSize: 18, fontWeight: '700' },
  cardCaption: { fontSize: 11, lineHeight: 15 },
  infoTrigger: { alignSelf: 'flex-start', paddingVertical: 2, paddingHorizontal: 2 },
  infoGlyph: { fontSize: 11, fontWeight: '700', fontStyle: 'italic' },
  infoText: { fontSize: 11, lineHeight: 15 },
  activityOverview: { gap: 16 },
  stateCard: { alignItems: 'center', gap: 8, padding: 24, borderRadius: 10, borderWidth: 1 },
  stateTitle: { fontSize: 15, fontWeight: '600', textAlign: 'center' },
  stateCopy: { fontSize: 12, textAlign: 'center', lineHeight: 17 },
  overlay: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  backdrop: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0 },
  sheet: { width: 420, maxWidth: '92%', maxHeight: '82%', borderRadius: 12, borderWidth: 1, overflow: 'hidden' },
  sheetCompact: { width: '100%', maxHeight: '86%', borderBottomLeftRadius: 0, borderBottomRightRadius: 0, alignSelf: 'flex-end' },
  sheetHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8, paddingHorizontal: 16, paddingVertical: 12, borderBottomWidth: 1 },
  sheetTitle: { fontSize: 16, fontWeight: '700' },
  closeButton: { width: 32, height: 32, alignItems: 'center', justifyContent: 'center', borderRadius: 8 },
  closeText: { fontSize: 20, lineHeight: 22 },
  sheetScroll: { flexGrow: 0 },
  sheetContent: { padding: 12, gap: 12 },
  sheetSectionTitle: { fontSize: 11, fontWeight: '700', letterSpacing: 0.8, textTransform: 'uppercase' },
  optionList: { gap: 6 },
  option: { minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 12, borderRadius: 8 },
  optionCopy: { flexShrink: 1, flex: 1, gap: 1 },
  optionTitle: { fontSize: 14, fontWeight: '600' },
  optionMeta: { fontSize: 11 },
  optionCheck: { marginLeft: 'auto', fontSize: 14, fontWeight: '700' },
  customButton: { minHeight: 44, alignItems: 'center', justifyContent: 'center', borderRadius: 8, borderWidth: 1 },
  customButtonText: { fontSize: 13, fontWeight: '600' },
  customPane: { gap: 8 },
  fieldLabel: { fontSize: 12, fontWeight: '600', marginTop: 4 },
  customActions: { flexDirection: 'row', justifyContent: 'flex-end', alignItems: 'center', gap: 8, marginTop: 8 },
  cancelButton: { minHeight: 42, paddingHorizontal: 16, alignItems: 'center', justifyContent: 'center', borderRadius: 8, borderWidth: 1 },
  cancelText: { fontSize: 14, fontWeight: '600' },
  pressed: { opacity: 0.72 },
});
