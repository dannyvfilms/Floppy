import React, { useState } from 'react';
import { Image, Pressable, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { Badge } from './Badge';
import { Button } from './Button';
import { MediaCardActionHost } from './MediaCardActionHost';
import { MediaCard } from './MediaCard';
import { ProgressBar } from './ProgressBar';

const DEFAULT_PALETTE = {
  background: '#18181b',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  surfaceBorder: '#3f3f46',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  accentContrast: '#ffffff',
  link: '#818cf8',
  danger: '#f87171',
  success: '#10b981',
  warning: '#f59e0b',
  radius: 10,
  radiusSmall: 6,
  mediaCard: {
    card: '#27272a',
    text: '#fafafa',
    textSecondary: '#d4d4d8',
    textMuted: '#a1a1aa',
    border: '#3f3f46',
    link: '#818cf8',
    star: '#facc15',
    chipBackground: 'rgba(24, 24, 27, 0.92)',
    chipText: '#ffffff',
    placeholder: '#3f3f46',
    progressTrack: 'rgba(24, 24, 27, 0.6)',
    progressFill: '#6366f1',
    progressPaused: 'rgba(99, 102, 241, 0.4)',
  },
  progress: {
    surface: '#27272a',
    surfaceMuted: '#52525b',
    fill: '#10b981',
    text: '#fafafa',
    textMuted: '#a1a1aa',
  },
  rating: {
    lit: '#facc15',
    unlit: '#52525b',
    muted: '#a1a1aa',
    focusStyle: {},
  },
  button: {
    radius: 6,
    primary: {
      background: '#4f46e5',
      pressed: '#4338ca',
      hovered: '#4338ca',
      text: '#ffffff',
      border: 'transparent',
    },
    surface: {
      background: '#3f3f46',
      pressed: '#52525b',
      hovered: '#52525b',
      text: '#fafafa',
      border: '#3f3f46',
    },
    'ghost-danger': {
      background: 'transparent',
      pressed: 'rgba(248, 113, 113, 0.18)',
      hovered: 'rgba(248, 113, 113, 0.18)',
      text: '#f87171',
      border: 'transparent',
    },
  },
};

const DEFAULT_LABELS = {
  seasons: 'Seasons',
  episodes: 'Episodes',
  issues: 'Issues',
  season: 'Season',
  dropped: 'Dropped',
  watched: 'Watched',
  unwatched: 'Unwatched',
  read: 'Read',
  unread: 'Unread',
  collected: 'Collected',
  notAired: 'Not aired yet',
  history: 'History',
  noHistory: 'No activity recorded yet.',
  noChildren: 'Nothing to show yet.',
  toggleOrder: 'Toggle row order',
  oldestFirst: 'Oldest first',
  newestFirst: 'Newest first',
  showAllThumbnails: 'Show all thumbnails',
  hideUnseenThumbnails: 'Hide unseen thumbnails',
  revealThumbnail: 'Reveal thumbnail',
  hiddenThumbnail: 'Thumbnail hidden',
  rate: 'Rate',
  close: 'Close',
  track: 'Track',
  lists: 'Lists',
  collection: 'Collection',
};

const BUTTON_TONES = {
  watch: 'primary',
  read: 'primary',
  checkin: 'primary',
  track: 'primary',
  unwatch: 'surface',
  unread: 'surface',
  history: 'surface',
  lists: 'surface',
  collection: 'surface',
  reveal: 'surface',
  drop: 'ghost-danger',
  restore: 'surface',
};

const ACTION_GLYPHS = {
  watch: '✓',
  read: '✓',
  checkin: '▶',
  track: '▶',
  unwatch: '↺',
  unread: '↺',
  history: '◷',
  lists: '☰',
  collection: '▣',
  reveal: '◉',
  drop: '✕',
  restore: '↺',
};

function mergePalette(palette) {
  return {
    ...DEFAULT_PALETTE,
    ...(palette || {}),
    mediaCard: { ...DEFAULT_PALETTE.mediaCard, ...(palette?.mediaCard || {}) },
    progress: { ...DEFAULT_PALETTE.progress, ...(palette?.progress || {}) },
    rating: { ...DEFAULT_PALETTE.rating, ...(palette?.rating || {}) },
    button: {
      ...DEFAULT_PALETTE.button,
      ...(palette?.button || {}),
      primary: { ...DEFAULT_PALETTE.button.primary, ...(palette?.button?.primary || {}) },
      surface: { ...DEFAULT_PALETTE.button.surface, ...(palette?.button?.surface || {}) },
      'ghost-danger': {
        ...DEFAULT_PALETTE.button['ghost-danger'],
        ...(palette?.button?.['ghost-danger'] || {}),
      },
    },
  };
}

function sortedRows(rows, order) {
  if (!Array.isArray(rows)) return [];
  if (!order) return rows;
  return [...rows].sort((left, right) => {
    const difference = (Number(left.number) || 0) - (Number(right.number) || 0);
    return order === 'desc' ? -difference : difference;
  });
}

function metaLine(item, labels) {
  const parts = [];
  if (item.code) parts.push({ text: item.code });
  if (item.dateLabel) parts.push({ text: item.dateLabel, muted: true });
  if (item.runtime) parts.push({ text: item.runtime, muted: true });
  if (item.unreleased) parts.push({ text: labels.notAired, muted: true });
  return parts.length ? { join: 'dot', parts } : null;
}

function historyLine(item, labels) {
  const parts = [];
  if (item.history?.summary) parts.push({ text: item.history.summary, muted: true });
  if (item.dropped) parts.push({ text: labels.dropped, muted: true });
  if (item.collectedLabel) parts.push({ text: item.collectedLabel, muted: true });
  return parts.length ? { join: 'dot', parts } : null;
}

function actionRow(item, palette) {
  const actions = item.actions || [];
  if (!actions.length) return null;
  return {
    title: item.title,
    href: null,
    ordering: null,
    items: actions.map(action => ({
      kind: 'action',
      key: action.key,
      title: action.label,
      glyph: ACTION_GLYPHS[action.key] || '•',
      tone: action.tone || BUTTON_TONES[action.key] || 'surface',
      disabled: Boolean(action.disabled),
    })),
  };
}

function cardPalette(palette) {
  return {
    ...palette.mediaCard,
    actionText: palette.accentContrast,
    actionTones: {
      primary: palette.accentStrong,
      surface: palette.surfaceStrong,
      indigo: palette.accentStrong,
      emerald: palette.success,
      amber: palette.warning,
      rose: palette.danger,
    },
    overlay: 'rgba(0, 0, 0, 0.5)',
    reorder: palette.accentStrong,
    focusStyle: {},
  };
}

function lineText(line) {
  if (!line) return null;
  return line.parts.map(part => part.text).join(line.join === 'dot' ? ' · ' : ' ');
}

function runChildAction(action, item, { onOpenHistory, onAction, onReveal }) {
  if (action.key === 'reveal') {
    onReveal?.();
    return;
  }
  if (action.key === 'history') {
    onOpenHistory?.(item);
    return;
  }
  onAction?.(action.key, item);
}

function actionTone(action) {
  return action.tone || BUTTON_TONES[action.key] || 'surface';
}

function DetailChildCard({
  item,
  kind,
  labels,
  palette,
  revealed = false,
  renderRating,
  onOpen,
  onOpenHistory,
  onRate,
  onAction,
  onReveal,
}) {
  const { width } = useWindowDimensions();
  const wide = width >= 768;
  const obscured = Boolean(item.obfuscated) && !revealed;
  const [ratingOpen, setRatingOpen] = useState(false);
  const actions = [...(item.actions || [])];
  if (item.obfuscated && !revealed) {
    actions.unshift({ key: 'reveal', label: labels.revealThumbnail });
  }
  const imageSource = !obscured && item.image?.src ? { uri: item.image.src } : null;
  const overview = obscured ? labels.hiddenThumbnail : item.overview;
  const ratingPalette = palette.rating;

  return <View style={[styles.detailCard, {
    backgroundColor: item.unreleased ? palette.surfaceStrong : palette.surface,
    borderColor: palette.surfaceBorder,
  }, wide ? styles.detailWide : styles.detailNarrow]}>
    <View style={wide ? (kind === 'issue' ? styles.detailArtworkIssue : styles.detailArtworkEpisode) : styles.detailArtworkNarrow}>
      <Pressable accessibilityRole={onOpen ? 'link' : undefined}
        accessibilityLabel={item.title} disabled={!onOpen} onPress={() => onOpen?.(item)}
        style={[styles.detailArtwork, {
          backgroundColor: palette.surfaceStrong,
          borderColor: palette.surfaceBorder,
          aspectRatio: wide ? undefined : 16 / 9,
          height: wide ? 144 : undefined,
        }]}>
        {imageSource ? <Image source={imageSource} resizeMode="cover" style={styles.detailImage} /> : null}
      </Pressable>
      {item.obfuscated && !revealed ? <View style={styles.detailReveal}>
        <Button label={labels.revealThumbnail} tone="surface" size="sm"
          palette={palette.button} onPress={() => onReveal?.()} />
      </View> : null}
    </View>
    <View style={styles.detailBody}>
      <View style={styles.detailHeader}>
        <Pressable accessibilityRole={onOpen ? 'link' : undefined}
          accessibilityLabel={item.title} disabled={!onOpen} onPress={() => onOpen?.(item)}
          style={styles.detailTitleWrap}>
          <Text numberOfLines={2} style={[styles.detailTitle, { color: palette.text }]}>{item.title}</Text>
        </Pressable>
        {item.canRate ? <Pressable accessibilityRole="button"
          accessibilityLabel={item.rateLabel || labels.rate} accessibilityState={{ expanded: ratingOpen }}
          onPress={() => setRatingOpen(current => !current)}
          style={[styles.detailScore, { backgroundColor: palette.surfaceStrong, borderColor: palette.surfaceBorder }]}>
          <Text style={[styles.detailScoreText, { color: item.score == null ? palette.textMuted : palette.warning }]}>
            {item.score == null ? `☆ ${item.rateLabel || labels.rate}` : `★ ${item.score}`}
          </Text>
        </Pressable> : null}
      </View>
      {lineText(metaLine(item, labels)) ? <Text style={[styles.detailMeta, { color: palette.textMuted }]}>
        {lineText(metaLine(item, labels))}
      </Text> : null}
      {overview ? <Text numberOfLines={3}
        style={[styles.detailOverview, { color: palette.textSecondary }]}>{overview}</Text> : null}
      {lineText(historyLine(item, labels)) ? <Text style={[styles.detailHistory, { color: palette.textMuted }]}>
        {lineText(historyLine(item, labels))}
      </Text> : null}
      {ratingOpen && item.canRate && renderRating ? <View style={[styles.detailRating, {
        backgroundColor: palette.surfaceStrong,
        borderColor: palette.surfaceBorder,
      }]}>
        {renderRating({
          value: item.score == null ? null : item.score,
          label: item.rateLabel || labels.rate,
          scaleMax: item.scaleMax || 10,
          palette: ratingPalette,
          onSelect: score => {
            setRatingOpen(false);
            onRate?.(item, score);
          },
        })}
      </View> : null}
      {actions.length ? <View style={styles.detailActions}>
        {actions.map(action => <Button key={action.key} label={action.label}
          tone={actionTone(action)} size="sm" disabled={Boolean(action.disabled)}
          palette={palette.button}
          onPress={() => runChildAction(action, item, { onOpenHistory, onAction, onReveal })} />)}
      </View> : null}
    </View>
  </View>;
}

function DetailChildRow({
  item,
  kind,
  labels,
  palette,
  variant,
  revealed = false,
  renderRating,
  onOpen,
  onOpenHistory,
  onRate,
  onAction,
  onReveal,
}) {
  if (variant === 'detail') {
    return <DetailChildCard item={item} kind={kind} labels={labels} palette={palette}
      revealed={revealed} renderRating={renderRating} onOpen={onOpen}
      onOpenHistory={onOpenHistory} onRate={onRate} onAction={onAction}
      onReveal={onReveal} />;
  }
  const obscured = Boolean(item.obfuscated) && !revealed;
  const actions = [...(item.actions || [])];
  if (item.obfuscated && !revealed) {
    actions.unshift({ key: 'reveal', label: labels.revealThumbnail, tone: 'surface' });
  }
  const model = {
    layout: 'row',
    mediaType: kind,
    title: item.title,
    image: obscured ? { src: null, fallback: '' } : item.image || { src: null, fallback: '' },
    altTitle: item.altTitle || null,
    lines: [metaLine(item, labels), historyLine(item, labels), obscured
      ? { join: 'plain', parts: [{ text: labels.hiddenThumbnail, muted: true }] }
      : null].filter(Boolean),
    rating: item.canRate ? {
      label: item.score == null ? null : String(item.score),
      value: item.score == null ? null : item.score,
      scaleMax: item.scaleMax || 10,
      rateLabel: item.rateLabel || labels.rate,
    } : null,
    ratingEditable: Boolean(item.canRate),
    actions: actionRow({ ...item, actions }, palette),
  };

  return <View style={[styles.child, {
    backgroundColor: item.unreleased ? palette.surfaceStrong : palette.surface,
    borderColor: palette.surfaceBorder,
  }]}>
    <MediaCard model={model} labels={labels} palette={cardPalette(palette)}
      selection={undefined} actions={model.actions} onOpen={() => onOpen?.(item)}
      onAction={action => runChildAction(action, item, { onOpenHistory, onAction, onReveal })}
      onRate={score => onRate?.(item, score)}
      renderRating={renderRating} />
  </View>;
}

export function DetailEpisodeRow(props) {
  return <DetailChildRow kind="episode" {...props} />;
}

export function DetailIssueRow(props) {
  return <DetailChildRow kind="issue" {...props} />;
}

export function DetailSeasonRow({ season, labels, palette, onOpen, onAction }) {
  const copy = { ...DEFAULT_LABELS, ...(labels || {}) };
  const colors = mergePalette(palette);
  const percent = season.percent == null ? null : Math.max(0, Math.min(100, season.percent));
  return <View style={[styles.season, { backgroundColor: colors.surface, borderColor: colors.surfaceBorder }]}>
    <View style={styles.seasonMain}>
      <Pressable accessibilityRole={onOpen ? 'link' : undefined}
        accessibilityLabel={season.title} disabled={!onOpen}
        onPress={() => onOpen?.(season)} style={styles.seasonTitleWrap}>
        <Text numberOfLines={1} style={[styles.seasonTitle, { color: colors.text }]}>{season.title}</Text>
        {season.subtitle ? <Text numberOfLines={1}
          style={[styles.seasonSubtitle, { color: colors.textMuted }]}>{season.subtitle}</Text> : null}
      </Pressable>
      <View style={styles.badges}>
        {season.statusLabel ? <Badge label={season.statusLabel} tone="outline"
          palette={{ outline: { color: colors.textSecondary, borderColor: colors.surfaceMuted, borderWidth: 1 } }} /> : null}
        {season.dropped ? <Badge label={copy.dropped} tone="outline"
          palette={{ outline: { color: colors.danger, borderColor: colors.danger, borderWidth: 1 } }} /> : null}
      </View>
    </View>
    <View style={styles.seasonMeta}>
      <Text style={[styles.seasonCount, { color: colors.textSecondary }]}>{season.countLabel}</Text>
      {percent == null ? null : <Text style={[styles.seasonPercent, { color: colors.text }]}>{percent}%</Text>}
    </View>
    {percent == null ? null : <ProgressBar percent={percent} height={6}
      palette={colors.progress} label={season.title} />}
    {season.actions?.length ? <View style={styles.seasonActions}>
      {season.actions.map(action => <Button key={action.key} label={action.label}
        tone={BUTTON_TONES[action.key] || action.tone || 'surface'} size="sm"
        disabled={Boolean(action.disabled)} palette={colors.button}
        onPress={() => onAction?.(action.key, season)} />)}
    </View> : null}
  </View>;
}

export function DetailSeasonList({ seasons = [], order, labels, palette, onOpenSeason, onAction }) {
  const copy = { ...DEFAULT_LABELS, ...(labels || {}) };
  const colors = mergePalette(palette);
  if (!seasons.length) return null;
  return <View style={styles.section}>
    <Text style={[styles.heading, { color: colors.text }]}>{copy.seasons}</Text>
    {sortedRows(seasons, order).map((season, index) => <DetailSeasonRow key={season.key || season.number || index}
      season={season} labels={copy} palette={colors} onOpen={onOpenSeason} onAction={onAction} />)}
  </View>;
}

export function DetailChildren({
  model,
  labels,
  palette,
  order,
  variant,
  showHeading = true,
  onOrderChange,
  onOpenSeason,
  onOpenChild,
  onOpenHistory,
  onRate,
  onAction,
  onToggleObfuscation,
  renderRating,
}) {
  const copy = { ...DEFAULT_LABELS, ...(labels || {}) };
  const colors = mergePalette(palette);
  const [revealed, setRevealed] = useState({});
  const episodes = sortedRows(model?.episodes, order);
  const issues = sortedRows(model?.issues, order);
  const seasons = model?.seasons || [];
  const kind = model?.kind === 'comic' ? 'issue' : 'episode';
  const rows = kind === 'issue' ? issues : episodes;
  const rowLabel = kind === 'issue' ? copy.issues : copy.episodes;
  const obfuscation = model?.obfuscation || null;

  function reveal(item) {
    const key = item.key || item.number;
    setRevealed(current => ({ ...current, [key]: true }));
  }

  return <View style={styles.root}>
    <DetailSeasonList seasons={seasons} order={order} labels={copy} palette={colors}
      onOpenSeason={onOpenSeason} onAction={onAction} />
    <View style={styles.section}>
      {showHeading ? <View style={styles.toolbar}>
        <View style={styles.headingWrap}>
          <Text style={[styles.heading, { color: colors.text }]}>{rowLabel}</Text>
          <Text style={[styles.count, { color: colors.textMuted }]}>{rows.length}</Text>
        </View>
        <View style={styles.toolbarActions}>
          {onOrderChange ? <Button
            label={order === 'desc' ? copy.newestFirst : copy.oldestFirst}
            accessibilityLabel={copy.toggleOrder} tone="surface" size="sm"
            palette={colors.button} onPress={onOrderChange} /> : null}
          {obfuscation?.canToggle ? <Button
            label={obfuscation.active ? copy.showAllThumbnails : copy.hideUnseenThumbnails}
            tone="surface" size="sm" palette={colors.button}
            onPress={() => onToggleObfuscation?.(!obfuscation.active)} /> : null}
        </View>
      </View> : null}
      {rows.length ? rows.map((item, index) => {
        const key = item.key || item.number || index;
        const Row = kind === 'issue' ? DetailIssueRow : DetailEpisodeRow;
        return <Row key={key} item={item} kind={kind} labels={copy} palette={colors}
          variant={variant} revealed={Boolean(revealed[key])} renderRating={renderRating}
          onOpen={onOpenChild} onOpenHistory={onOpenHistory} onRate={onRate}
          onAction={onAction} onReveal={() => reveal(item)} />;
      }) : <Text style={[styles.empty, { color: colors.textMuted, borderColor: colors.surfaceBorder }]}>
        {copy.noChildren}
      </Text>}
    </View>
  </View>;
}

export function DetailHistoryDialog({ open = false, title, rows = [], labels, palette, onClose }) {
  const copy = { ...DEFAULT_LABELS, ...(labels || {}) };
  const colors = mergePalette(palette);
  return <MediaCardActionHost open={open} action={{ title: title || copy.history }}
    labels={{ close: copy.close }} onClose={onClose}
    palette={{
      surface: colors.surface,
      border: colors.surfaceBorder,
      text: colors.text,
      textMuted: colors.textMuted,
      backdrop: 'rgba(0, 0, 0, 0.6)',
    }}>
    <View style={styles.historyRows}>
      {rows.length ? rows.map((row, index) => <View key={row.key || index}
        style={[styles.historyRow, { borderColor: colors.surfaceBorder }]}>
        <Text style={[styles.historyDate, { color: colors.text }]}>{row.dateLabel}</Text>
        <Text style={[styles.historyAction, { color: colors.textSecondary }]}>{row.actionLabel}</Text>
        {row.score == null ? null : <Text style={[styles.historyScore, { color: colors.warning }]}>
          ★ {row.score}
        </Text>}
        {row.note ? <Text style={[styles.historyNote, { color: colors.textMuted }]}>{row.note}</Text> : null}
      </View>) : <Text style={[styles.empty, { color: colors.textMuted, borderColor: colors.surfaceBorder }]}>
        {copy.noHistory}
      </Text>}
    </View>
  </MediaCardActionHost>;
}

const styles = StyleSheet.create({
  root: { gap: 24 },
  section: { gap: 12 },
  headingWrap: { flexDirection: 'row', alignItems: 'baseline', gap: 8 },
  heading: { fontSize: 17, fontWeight: '600' },
  count: { fontSize: 12, fontWeight: '600' },
  toolbar: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' },
  toolbarActions: { flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  season: { borderWidth: 1, borderRadius: 10, padding: 12, gap: 8 },
  seasonMain: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 },
  seasonTitleWrap: { flex: 1, minWidth: 0 },
  seasonTitle: { fontSize: 15, fontWeight: '600' },
  seasonSubtitle: { marginTop: 2, fontSize: 12 },
  badges: { flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' },
  seasonMeta: { flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 },
  seasonCount: { fontSize: 12 },
  seasonPercent: { fontSize: 15, fontWeight: '700' },
  seasonActions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  child: { borderWidth: 1, borderRadius: 10, overflow: 'hidden' },
  empty: { borderWidth: 1, borderStyle: 'dashed', borderRadius: 8, paddingHorizontal: 12, paddingVertical: 10, fontSize: 12 },
  historyRows: { gap: 8 },
  historyRow: { borderTopWidth: 1, paddingTop: 8, gap: 2 },
  historyDate: { fontSize: 13, fontWeight: '600' },
  historyAction: { fontSize: 12 },
  historyScore: { fontSize: 12, fontWeight: '600' },
  historyNote: { fontSize: 12, lineHeight: 17 },
  detailCard: { borderWidth: 1, borderRadius: 10, overflow: 'hidden' },
  detailWide: { flexDirection: 'row' },
  detailNarrow: { flexDirection: 'column' },
  detailArtworkIssue: { width: 256 },
  detailArtworkEpisode: { width: 224 },
  detailArtworkNarrow: { width: '100%' },
  detailArtwork: { width: '100%', overflow: 'hidden' },
  detailImage: { width: '100%', height: '100%' },
  detailReveal: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, alignItems: 'center', justifyContent: 'center' },
  detailBody: { flex: 1, minWidth: 0, padding: 12, gap: 6 },
  detailHeader: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 },
  detailTitleWrap: { flex: 1, minWidth: 0 },
  detailTitle: { fontSize: 18, fontWeight: '600' },
  detailScore: { flexDirection: 'row', alignItems: 'center', borderWidth: 1, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4, flexShrink: 0 },
  detailScoreText: { fontSize: 12, fontWeight: '600' },
  detailMeta: { fontSize: 13 },
  detailOverview: { fontSize: 13, lineHeight: 19 },
  detailHistory: { fontSize: 12 },
  detailRating: { borderWidth: 1, borderRadius: 8, padding: 10 },
  detailActions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 2 },
});
