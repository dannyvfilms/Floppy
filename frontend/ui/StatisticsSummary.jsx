import { Modal, ModalCloseButton } from './Modal';
import React, { useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from 'react-native';
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
  radius: 18,
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
  showComparisonTotals: 'Show comparison totals',
  vs: 'vs',
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

function ActivityGlyph({ name, size, color }) {
  if (name === 'calendar') {
    const width = size * 0.82;
    return <View style={{ width, height: width * 0.92, borderWidth: 1.5, borderColor: color, borderRadius: 2 }}>
      <View style={{ height: 1.5, backgroundColor: color, marginTop: width * 0.22 }} />
      <View style={{ position: 'absolute', top: -2, left: width * 0.18, width: 1.5, height: 4, backgroundColor: color }} />
      <View style={{ position: 'absolute', top: -2, right: width * 0.18, width: 1.5, height: 4, backgroundColor: color }} />
    </View>;
  }
  if (name === 'bars') {
    const height = size * 0.8;
    return <View style={{ flexDirection: 'row', alignItems: 'flex-end', gap: size * 0.1 }}>
      {[0.45, 0.72, 1].map((ratio, index) => <View key={index} style={{
        width: size * 0.16,
        height: height * ratio,
        backgroundColor: color,
        borderRadius: 0.5,
      }} />)}
    </View>;
  }
  const initials = {
    completed: '\u2713',
    rating: '\u2606',
    flame: '\u2668',
  };
  return <Text style={{ fontSize: size * 0.82, lineHeight: size, color, fontWeight: '700' }}>
    {initials[name] || '\u2713'}
  </Text>;
}

function SummaryCard({
  icon, color, iconBackground, label, value, valueSuffix, caption, valueColor, info, palette, layout,
}) {
  const [infoOpen, setInfoOpen] = useState(false);
  return <View testID="stats-summary-card" style={[styles.summaryCard, layout.card, layout.minHeight && {
    minHeight: layout.minHeight,
  }, {
    backgroundColor: palette.surface,
  }]}>
    <View style={[styles.summaryIcon, {
      width: layout.iconBox,
      height: layout.iconBox,
      borderRadius: layout.iconBox / 2,
      padding: layout.iconPad,
      backgroundColor: iconBackground || `${color}33`,
    }]}>
      <ActivityGlyph name={icon} size={layout.iconSize} color={color} />
    </View>
    <View style={styles.summaryCopy}>
      <Text testID="stats-summary-label" style={[styles.summaryLabel, {
        fontSize: layout.labelSize,
        lineHeight: layout.labelLine,
        color: palette.textMuted,
      }]}
        numberOfLines={1}>{label}</Text>
      <Text testID="stats-summary-value" style={[styles.summaryValue, {
        fontSize: layout.valueSize,
        lineHeight: Math.round(layout.valueSize * 1.33),
        color: valueColor || palette.text,
      }]}
        numberOfLines={1}>{value}{valueSuffix ? <Text style={{
        fontSize: layout.suffixSize,
        fontWeight: '700',
        color: palette.textMuted,
      }}> / {valueSuffix}</Text> : null}</Text>
      {caption ? <View style={styles.summaryCaptionRow}>
        <Text style={[styles.summaryCaption, { fontSize: layout.captionSize, color: palette.textMuted }]}>
          {caption}
        </Text>
        {info ? <Pressable accessibilityRole="button"
          accessibilityLabel={info.label}
          accessibilityState={{ expanded: infoOpen }}
          onPress={() => setInfoOpen(open => !open)}
          style={styles.infoTrigger}>
          <Text style={[styles.infoGlyph, { color: palette.textMuted }]}>{'\u24D8'}</Text>
        </Pressable> : null}
      </View> : info ? <Pressable accessibilityRole="button"
        accessibilityLabel={info.label}
        accessibilityState={{ expanded: infoOpen }}
        onPress={() => setInfoOpen(open => !open)}
        style={styles.infoTrigger}>
        <Text style={[styles.infoGlyph, { color: palette.textMuted }]}>{'\u24D8'}</Text>
      </Pressable> : null}
    </View>
    {info && infoOpen ? <View style={[styles.infoPanel, { backgroundColor: palette.surfaceStrong, borderColor: palette.border }]}>
      <Text style={[styles.infoPanelText, { color: palette.text }]}>{info.text}</Text>
    </View> : null}
  </View>;
}

export function StatisticsHero({ model, labels, palette }) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const summary = model.summary || {};
  const totalHours = numberValue(summary.totalHours);
  const total = numberValue(summary.total);
  const totalDays = numberValue(summary.totalDays);
  const { width } = useWindowDimensions();
  const desktop = width >= 1024;
  const desktopContentWidth = Math.max(560, width - 320);
  const textWidth = (desktopContentWidth - 16) * 0.4;
  const titleSize = desktop ? Math.min(56, Math.max(19.2, textWidth * 0.08)) : 24;
  const typeLabel = summary.typeLabel || copy.titles;
  return <View style={styles.hero}>
    <Text numberOfLines={1} style={[styles.heroLine, {
      fontSize: titleSize,
      lineHeight: titleSize * 1.1,
      color: colors.text,
    }]}>
      {copy.spent} <Text style={{ color: colors.link }}>{formatNumber(totalHours)}</Text> {copy.hours}
    </Text>
    <Text testID="stats-hero-count" numberOfLines={1} style={[styles.heroLine, {
      fontSize: titleSize,
      lineHeight: titleSize * 1.1,
      color: colors.text,
    }]}>
      {copy.with} <Text style={{ color: colors.link }}>{formatNumber(total)}</Text> {typeLabel}.
    </Text>
    <View style={styles.heroCaptionRow}>
      <View style={[styles.heroSpark, { backgroundColor: colors.surface }]}>
        <Text style={[styles.heroSparkText, { color: colors.link }]}>{'\u2726'}</Text>
      </View>
      <Text style={[styles.heroCaption, { color: colors.textMuted }]}>
        {copy.daysOf} <Text style={{ color: colors.textSecondary }}>{formatNumber(totalDays)}</Text> {copy.days}{' '}
        {summary.typeFlavor || copy.titles}{copy.keepExploring}
      </Text>
    </View>
  </View>;
}

function HighlightCard({ item, palette, onSelectHighlight, style }) {
  const pressable = Boolean(item.href && onSelectHighlight);
  const body = <View style={[styles.highlightCard, { backgroundColor: palette.surface }, style]}>
    {item.image
      ? <Image source={{ uri: item.image }} style={styles.highlightImage}
        resizeMode="cover" accessibilityIgnoresInvertColors
        accessibilityLabel={item.title || item.label} />
      : <View style={[styles.highlightImage, { backgroundColor: palette.surfaceStrong }]} />}
    <View pointerEvents="none" style={styles.highlightShade}>
      {Array.from({ length: 26 }, (_, index) => {
        const ratio = (index + 1) / 26;
        return <View key={index} style={{
          flex: 1,
          backgroundColor: `rgba(9, 11, 24, ${(0.03 + 0.9 * ratio ** 1.4).toFixed(3)})`,
        }} />;
      })}
    </View>
    <View style={styles.highlightBody}>
      <Text style={[styles.highlightLabel, { color: palette.textMuted }]} numberOfLines={1}>
        {item.label}
      </Text>
      <Text style={[styles.highlightTitle, { color: palette.text }]} numberOfLines={1}>
        {item.title || DEFAULT_LABELS.notAvailable}
      </Text>
    </View>
  </View>;
  if (!pressable) return <View style={style ? { flex: 1 } : undefined}>{body}</View>;
  return <Pressable accessibilityRole="link"
    accessibilityLabel={`${item.label}: ${item.title}`}
    onPress={() => onSelectHighlight?.(item)}
    style={({ pressed }) => [style ? { flex: 1 } : undefined, pressed && styles.pressed]}>
    {body}
  </Pressable>;
}

export function StatisticsHighlights({ model, labels, palette, onSelectHighlight }) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const { width } = useWindowDimensions();
  const [trackWidth, setTrackWidth] = useState(0);
  const [page, setPage] = useState(0);
  const scrollRef = useRef(null);
  const cards = (model.highlights || []).slice(0, 3);
  if (!cards.length) return null;

  if (width >= 640) {
    return <View style={styles.highlightRow}
      onLayout={event => setTrackWidth(event.nativeEvent.layout.width)}>
      {cards.map(item => <HighlightCard key={item.key || item.label} item={item}
        palette={colors} onSelectHighlight={onSelectHighlight} style={styles.highlightGrow} />)}
    </View>;
  }

  const pageWidth = trackWidth || width - 48;
  return <View>
    <ScrollView ref={scrollRef} horizontal
      showsHorizontalScrollIndicator={false}
      pagingEnabled
      onMomentumScrollEnd={event => {
        const offset = event.nativeEvent.contentOffset.x;
        setPage(Math.round(offset / Math.max(1, pageWidth)));
      }}
      contentContainerStyle={styles.highlightCarousel}>
      {cards.map(item => <View key={item.key || item.label} style={{ width: pageWidth }}>
        <HighlightCard item={item} palette={colors} onSelectHighlight={onSelectHighlight}
          style={styles.highlightGrow} />
      </View>)}
    </ScrollView>
    <View style={styles.highlightDots}>
      {cards.map((item, index) => <Pressable key={item.key || item.label}
        accessibilityRole="button"
        accessibilityLabel={`Show ${item.label} highlight`}
        onPress={() => {
          setPage(index);
          scrollRef.current?.scrollTo?.({ x: index * pageWidth, animated: true });
        }}
        style={[styles.highlightDot, {
          backgroundColor: index === page ? '#818cf8' : colors.textMuted,
        }]} />)}
    </View>
  </View>;
}

export function StatisticsSummaryCards({ model, labels, palette }) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const summary = model.summary || {};
  const scaleMax = numberValue(model.scaleMax) || 10;
  const { width } = useWindowDimensions();
  const compact = width >= 1024 && width < 1536;
  const desktop = width >= 1024;
  const columns = desktop ? 5 : width >= 640 ? 3 : 2;
  const gap = width >= 640 ? 16 : 12;
  const layout = {
    card: {
      padding: width >= 1536 ? 20 : 12,
      flexDirection: (width < 400 || compact) ? 'column' : 'row',
      alignItems: (width < 400 || compact) ? 'flex-start' : 'center',
      gap: 8,
    },
    iconBox: width < 640 ? 32 : compact ? 28 : 48,
    iconPad: width < 640 ? 8 : compact ? 4 : 12,
    iconSize: width < 640 ? 16 : compact ? 20 : 24,
    labelSize: width < 640 ? 12 : 14,
    labelLine: width < 640 ? 16 : 20,
    valueSize: compact ? 16 : 20,
    suffixSize: width < 640 ? 14 : 18,
    captionSize: width < 640 ? 12 : 14,
    minHeight: width >= 1024 ? 121 : undefined,
  };

  const hasTotal = numberValue(summary.total) > 0;
  const completedValue = hasTotal ? formatNumber(summary.completed) : copy.notAvailable;
  const completedSuffix = hasTotal ? formatNumber(summary.total) : '';
  const ratingValue = summary.hasScore ? String(summary.averageScore) : copy.notAvailable;
  const ratingSuffix = summary.hasScore ? String(scaleMax) : '';
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
  const comparisonColor = comparison.state === 'up' ? colors.success
    : comparison.state === 'down' ? colors.danger
      : colors.textMuted;

  const cards = [
    <SummaryCard key="completed" icon="completed" color={colors.link}
      iconBackground="rgba(79, 70, 229, 0.2)" label={copy.completed}
      value={completedValue} valueSuffix={completedSuffix} palette={colors} layout={layout} />,
    <SummaryCard key="rating" icon="rating" color="#facc15"
      iconBackground="rgba(202, 138, 4, 0.2)" label={copy.averageRating}
      value={ratingValue} valueSuffix={ratingSuffix} palette={colors} layout={layout} />,
    <SummaryCard key="active" icon="calendar" color="#34d399"
      iconBackground="rgba(5, 150, 105, 0.2)" label={copy.mostActiveDay}
      value={mostActiveValue} caption={mostActiveCaption} palette={colors} layout={layout} />,
    <SummaryCard key="streak" icon="flame" color="#fb7185"
      iconBackground="rgba(220, 38, 38, 0.2)" label={copy.currentStreak}
      value={streakValue} caption={streakCaption} palette={colors} layout={layout}
      info={summary.longestStreakStart ? {
        label: copy.showStreakDates,
        text: summary.longestStreakDates || todayLabel(summary.longestStreakStart),
      } : null} />,
    <SummaryCard key="activity" icon="bars" color={comparisonColor}
      iconBackground={comparison.state === 'up'
        ? 'rgba(22, 163, 74, 0.2)'
        : comparison.state === 'down' ? 'rgba(220, 38, 38, 0.2)' : 'rgba(75, 85, 99, 0.2)'}
      label={copy.activity}
      value={activityValue} caption={activityCaption} valueColor={comparisonColor}
      palette={colors} layout={layout}
      info={comparison.details ? {
        label: copy.showComparisonTotals,
        text: comparison.details,
      } : null} />,
  ];
  const rows = [];
  for (let index = 0; index < cards.length; index += columns) {
    const row = cards.slice(index, index + columns);
    while (row.length < columns) row.push(null);
    rows.push(row);
  }
  return <View testID="stats-summary-cards" style={[styles.summaryColumn, { gap }]}>
    {rows.map((row, rowIndex) => <View key={rowIndex} testID="stats-summary-row" style={[styles.summaryRow, { gap }]}>
      {row.map((card, cardIndex) => <View key={cardIndex} testID="stats-summary-cell" style={styles.summaryCell}>
        {card}
      </View>)}
    </View>)}
  </View>;
}

export function StatisticsActivityOverview({ model, labels, palette, onSelectHighlight }) {
  const colors = mergePalette(palette);
  const { width } = useWindowDimensions();
  const desktop = width >= 1024;
  return <View style={styles.activityOverview}>
    <View style={[styles.heroRow, desktop && styles.heroRowWide]}>
      <View style={desktop ? styles.heroTextWide : undefined}>
        <StatisticsHero model={model} labels={labels} palette={colors} />
      </View>
      <View style={desktop ? styles.heroCardsWide : undefined}>
        <StatisticsHighlights model={model} labels={labels} palette={colors}
          onSelectHighlight={onSelectHighlight} />
      </View>
    </View>
    <StatisticsSummaryCards model={model} labels={labels} palette={colors} />
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
      label: `${customStart} \u2013 ${customEnd}`,
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
        <Text style={[styles.triggerGlyph, { color: colors.link }]}>{'\u25A6'}</Text>
        <Text style={[styles.triggerText, { color: colors.textSecondary }]} numberOfLines={1}>{rangeLabel}</Text>
        <Text style={[styles.chevron, { color: colors.textMuted }]}>{'\u25BE'}</Text>
      </Pressable>
      <Pressable accessibilityRole="button"
        accessibilityLabel={`${copy.mediaType}: ${mediaLabel}`}
        accessibilityState={{ expanded: open === 'media' }}
        onPress={() => setOpen(open === 'media' ? null : 'media')}
        style={({ pressed }) => [styles.trigger, { backgroundColor: colors.surface, borderColor: colors.border }, open === 'media' && { borderColor: colors.accent }, pressed && styles.pressed]}>
        <Text style={[styles.triggerGlyph, { color: colors.link }]}>{'\u2304'}</Text>
        <Text style={[styles.triggerText, { color: colors.textSecondary }]} numberOfLines={1}>{mediaLabel}</Text>
        <Text style={[styles.chevron, { color: colors.textMuted }]}>{'\u25BE'}</Text>
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
        <View style={[styles.sheet, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }, compact && styles.sheetCompact]}>
          <View style={[styles.sheetHeader, { borderBottomColor: colors.border }]}>
            <Text style={[styles.sheetTitle, { color: colors.text }]}>{copy.range}</Text>
            <ModalCloseButton accessibilityRole="button" accessibilityLabel={copy.close}
              onPress={close} style={({ pressed }) => [styles.closeButton, { backgroundColor: colors.surfaceMuted }, pressed && styles.pressed]}>
              <Text style={[styles.closeText, { color: colors.textSecondary }]}>{'\u00D7'}</Text>
            </ModalCloseButton>
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
                  style={({ pressed }) => [styles.option, { backgroundColor: selected ? colors.accentStrong : 'transparent' }, pressed && styles.pressed]}>
                  <View style={styles.optionCopy}>
                    <Text style={[styles.optionTitle, { color: selected ? colors.accentContrast : colors.text }]}>{option.label}</Text>
                    {option.dateLabel ? <Text style={[styles.optionMeta, { color: selected ? colors.accentContrast : colors.textMuted }]}>{option.dateLabel}</Text> : null}
                  </View>
                  {selected ? <Text style={[styles.optionCheck, { color: colors.accentContrast }]}>{'\u2713'}</Text> : null}
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
        <View style={[styles.sheet, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }, compact && styles.sheetCompact]}>
          <View style={[styles.sheetHeader, { borderBottomColor: colors.border }]}>
            <Text style={[styles.sheetTitle, { color: colors.text }]}>{copy.mediaType}</Text>
            <ModalCloseButton accessibilityRole="button" accessibilityLabel={copy.close}
              onPress={close} style={({ pressed }) => [styles.closeButton, { backgroundColor: colors.surfaceMuted }, pressed && styles.pressed]}>
              <Text style={[styles.closeText, { color: colors.textSecondary }]}>{'\u00D7'}</Text>
            </ModalCloseButton>
          </View>
          <ScrollView style={styles.sheetScroll} contentContainerStyle={styles.sheetContent}
            keyboardShouldPersistTaps="handled">
            <View style={styles.optionList}>
              <Pressable accessibilityRole="button"
                accessibilityState={{ selected: selectedCount === 0 }}
                onPress={() => toggleMediaType('all')}
                style={({ pressed }) => [styles.option, {
                  backgroundColor: selectedCount === 0 ? colors.accentStrong : 'transparent',
                }, pressed && styles.pressed]}>
                <Text style={[styles.optionTitle, { color: selectedCount === 0 ? colors.accentContrast : colors.text }]}>{copy.allMedia}</Text>
                {selectedCount === 0 ? <Text style={[styles.optionCheck, { color: colors.accentContrast }]}>{'\u2713'}</Text> : null}
              </Pressable>
              {mediaOptions.map(option => {
                const selected = selectedSet.has(option.value);
                return <Pressable key={option.value}
                  accessibilityRole="button"
                  accessibilityState={{ selected }}
                  onPress={() => toggleMediaType(option.value)}
                  style={({ pressed }) => [styles.option, {
                    backgroundColor: selected ? colors.accentStrong : 'transparent',
                  }, pressed && styles.pressed]}>
                  <Text style={[styles.optionTitle, { color: selected ? colors.accentContrast : colors.text }]}>{option.label}</Text>
                  {selected ? <Text style={[styles.optionCheck, { color: colors.accentContrast }]}>{'\u2713'}</Text> : null}
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
  hero: { gap: 0, justifyContent: 'center' },
  heroRow: { gap: 12, width: '100%' },
  heroRowWide: { flexDirection: 'row', alignItems: 'flex-start', gap: 16 },
  heroTextWide: { flex: 2, minWidth: 0, alignSelf: 'center' },
  heroCardsWide: { flex: 3, minWidth: 0 },
  heroLine: { fontWeight: '700' },
  heroCaptionRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 16, paddingBottom: 12 },
  heroSpark: { width: 28, height: 28, borderRadius: 14, alignItems: 'center', justifyContent: 'center' },
  heroSparkText: { fontSize: 13 },
  heroCaption: { flexShrink: 1, fontSize: 14, lineHeight: 20 },
  highlightRow: { flexDirection: 'row', alignItems: 'stretch', gap: 16 },
  highlightGrow: { flex: 1, minWidth: 0 },
  highlightCarousel: {},
  highlightCard: {
    borderRadius: 18,
    overflow: 'hidden',
    aspectRatio: 3 / 2,
    shadowColor: '#000000',
    shadowOpacity: 0.35,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 6 },
  },
  highlightImage: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, width: '100%', height: '100%' },
  highlightShade: { position: 'absolute', left: 0, right: 0, bottom: 0, height: '68%' },
  highlightBody: { position: 'absolute', left: 0, right: 0, bottom: 0, padding: 12, gap: 4 },
  highlightLabel: { fontSize: 12, lineHeight: 16, letterSpacing: 0.6, textTransform: 'uppercase' },
  highlightTitle: { fontSize: 14, lineHeight: 20, fontWeight: '600' },
  highlightDots: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, marginTop: 12, marginBottom: 12 },
  highlightDot: { width: 8, height: 8, borderRadius: 4 },
  summaryColumn: { width: '100%' },
  summaryRow: { flexDirection: 'row', width: '100%' },
  summaryCell: { flex: 1, minWidth: 0 },
  summaryCard: {
    borderRadius: 18,
    minWidth: 0,
    overflow: 'visible',
  },
  summaryIcon: { alignItems: 'center', justifyContent: 'center', flexShrink: 0 },
  summaryCopy: { flexShrink: 1, minWidth: 0, gap: 0 },
  summaryLabel: { fontWeight: '500' },
  summaryValue: { fontWeight: '700' },
  summaryCaptionRow: { flexDirection: 'row', alignItems: 'center', gap: 4, flexWrap: 'wrap' },
  summaryCaption: { lineHeight: 18 },
  infoTrigger: { paddingHorizontal: 2, paddingVertical: 1 },
  infoGlyph: { fontSize: 13, lineHeight: 13, fontWeight: '400' },
  infoPanel: {
    position: 'absolute',
    left: 8,
    right: 8,
    bottom: 8,
    zIndex: 20,
    borderRadius: 8,
    borderWidth: 1,
    padding: 8,
  },
  infoPanelText: { fontSize: 11, lineHeight: 15 },
  activityOverview: { gap: 16, width: '100%' },
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
  optionList: { gap: 2 },
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
