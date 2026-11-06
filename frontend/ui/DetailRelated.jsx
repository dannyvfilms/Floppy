import React, { useState } from 'react';
import { Image, Pressable, StyleSheet, Text, View } from 'react-native';
import { MediaCard } from './MediaCard';
import { RatingStars } from './RatingStars';

const DEFAULT_LABELS = {
  showMore: 'Show more',
  showLess: 'Show less',
  dlcs: 'DLCs',
  empty: 'No related media available.',
  loading: 'Loading related media…',
  altTitle: 'Show alternative title',
  nextEpisode: 'Jump to next episode',
  noStatus: 'No Status',
  rate: 'Rate',
  close: 'Close',
};

const DEFAULT_PALETTE = {
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
  rating: { lit: '#facc15', unlit: '#52525b', muted: '#a1a1aa', focusStyle: {} },
};

function resolvePalette(palette) {
  return {
    ...DEFAULT_PALETTE,
    ...(palette || {}),
    rating: { ...DEFAULT_PALETTE.rating, ...(palette?.rating || {}) },
  };
}

function resolveLabels(labels) {
  return { ...DEFAULT_LABELS, ...(labels || {}) };
}

function webColumns(width) {
  if (width <= 900) return 3;
  const gap = 16;
  return Math.max(3, Math.floor((width + gap) / (150 + gap)));
}

function defaultRenderRating({ value, label, scaleMax, palette, onSelect }) {
  return <RatingStars scaleMax={scaleMax} value={value} label={label} onSelect={onSelect}
    palette={palette}
    renderStar={lit => <Text style={[styles.star, { color: lit ? palette.lit : palette.unlit }]}>★</Text>} />;
}

function RelatedCard({ item, width, labels, palette, onOpen, onOpenLink, onAction, onRate, renderRating, renderActionIcon }) {
  const model = item?.model || item;
  if (!model) return null;
  const card = <MediaCard
    model={model}
    width={width}
    labels={labels}
    palette={palette}
    style={undefined}
    onOpen={onOpen ? () => onOpen(model) : undefined}
    onOpenLink={onOpenLink}
    onAction={onAction ? action => onAction(model, action) : undefined}
    onRate={onRate ? score => onRate(model, score) : undefined}
    renderRating={renderRating}
    renderActionIcon={renderActionIcon} />;
  return <View style={[styles.cardWrap, { width }, item?.active && styles.activeCard, item?.active && { borderColor: palette.link }]}>
    {card}
  </View>;
}

function RelatedSection({
  section,
  columns,
  cardWidth,
  expanded,
  onToggle,
  labels,
  palette,
  onOpen,
  onOpenLink,
  onAction,
  onRate,
  renderRating,
  renderActionIcon,
  web = false,
}) {
  const items = section.items || [];
  if (!items.length) return null;
  const visibleCount = Math.max(columns, 1) * 2;
  const shown = expanded ? items : items.slice(0, visibleCount);
  return <View style={styles.section}>
    <Text accessibilityRole="header" aria-level={2} style={[styles.sectionTitle, { color: palette.text }]}>
      {section.label}
    </Text>
    <View style={styles.grid}>
      {shown.map((item, index) => <RelatedCard key={item.key || item.model?.cardKey || index}
        item={item} width={cardWidth} labels={labels} palette={palette}
        onOpen={onOpen} onOpenLink={onOpenLink} onAction={onAction} onRate={onRate}
        renderRating={renderRating} renderActionIcon={renderActionIcon} />)}
    </View>
    {items.length > visibleCount ? <Pressable accessibilityRole="button" onPress={onToggle}
      style={styles.toggle}>
      <Text style={[styles.toggleText, { color: palette.link }]}>
        {expanded ? labels.showLess : labels.showMore}
      </Text>
    </Pressable> : null}
  </View>;
}

function SteamDlcCard({ dlc, width, palette }) {
  return <View style={{ width }}>
    <View style={[styles.steamArtwork, { width, backgroundColor: palette.placeholder,
      borderColor: palette.border }]}>
      {dlc.image
        ? <Image source={{ uri: dlc.image }} style={StyleSheet.absoluteFill} resizeMode="cover"
          accessible={false} accessibilityElementsHidden importantForAccessibility="no-hide-descendants" />
        : <Text numberOfLines={2} style={[styles.steamPlaceholder, { color: palette.textMuted }]}>{dlc.title}</Text>}
    </View>
    <Text numberOfLines={2} style={[styles.steamTitle, { color: palette.text }]}>{dlc.title}</Text>
  </View>;
}

function SteamDlcSection({ dlcs, width, labels, palette, onOpenExternal, web = false }) {
  if (!dlcs?.length) return null;
  const gap = 12;
  const cardWidth = web ? '100%' : Math.max(120, Math.floor((width - gap) / 2));
  return <View style={styles.section}>
    <Text accessibilityRole="header" aria-level={2} style={[styles.sectionTitle, { color: palette.text }]}>
      {labels.dlcs}
    </Text>
    <View style={styles.grid}>
      {dlcs.map((dlc, index) => <Pressable key={`${dlc.url}-${index}`} accessibilityRole="link"
        accessibilityLabel={dlc.title}
        disabled={!onOpenExternal}
        onPress={() => onOpenExternal?.(dlc.url)}
        style={styles.steamCard}>
        <SteamDlcCard dlc={dlc} width={cardWidth} palette={palette} />
      </Pressable>)}
    </View>
  </View>;
}

export function DetailRelated({
  model,
  labels,
  palette,
  status = 'ready',
  onOpen,
  onOpenLink,
  onOpenExternal,
  onAction,
  onRate,
  renderRating = defaultRenderRating,
  renderActionIcon,
  web = false,
}) {
  const copy = resolveLabels(labels);
  const colors = resolvePalette(palette);
  const [measuredWidth, setMeasuredWidth] = useState(0);
  const [expanded, setExpanded] = useState({});
  const width = measuredWidth || 320;
  const columns = web ? webColumns(width) : width >= 720 ? 4 : width >= 520 ? 3 : 2;
  const gap = web ? (width <= 600 ? 12 : width <= 768 ? 12 : 16) : 12;
  const cardWidth = Math.max(96, Math.floor((width - gap * (columns - 1)) / columns));
  const sections = (model?.sections || []).filter(section => section?.items?.length);
  const steamDlcs = model?.steamDlcs || [];

  if (status === 'loading') {
    return <View style={styles.state}>
      <Text style={[styles.stateText, { color: colors.textMuted }]}>{copy.loading}</Text>
      <View style={[styles.stateBar, { backgroundColor: colors.placeholder }]} />
    </View>;
  }

  if (!sections.length && !steamDlcs.length) {
    return <View style={styles.state}>
      <Text style={[styles.stateText, { color: colors.textMuted }]}>{copy.empty}</Text>
    </View>;
  }

  return <View style={[styles.root, web && styles.rootWeb]}
    onLayout={event => setMeasuredWidth(event.nativeEvent.layout.width)}>
    {sections.map(section => <RelatedSection key={section.id || section.label}
      section={section}
      columns={columns}
      cardWidth={cardWidth}
      expanded={Boolean(expanded[section.id])}
      onToggle={() => setExpanded(current => ({
        ...current,
        [section.id]: !current[section.id],
      }))}
      labels={copy}
      palette={colors}
      onOpen={onOpen}
      onOpenLink={onOpenLink}
      onAction={onAction}
      onRate={onRate}
      renderRating={renderRating}
      renderActionIcon={renderActionIcon}
      web={web} />)}
    <SteamDlcSection dlcs={steamDlcs} width={width} labels={copy} palette={colors}
      onOpenExternal={onOpenExternal} web={web} />
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: 24, width: '100%' },
  rootWeb: { gap: 32, marginBottom: 32 },
  section: { gap: 16, width: '100%' },
  sectionTitle: { fontSize: 20, fontWeight: '700', lineHeight: 28 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12, alignItems: 'flex-start' },
  activeCard: { borderWidth: 2, borderRadius: 10 },
  cardWrap: { minWidth: 0 },
  toggle: { alignSelf: 'flex-start', paddingVertical: 2 },
  toggleText: { fontSize: 14, fontWeight: '500' },
  steamCard: { gap: 8 },
  steamArtwork: {
    aspectRatio: 460 / 215,
    borderRadius: 8,
    borderWidth: 1,
    overflow: 'hidden',
    alignItems: 'center',
    justifyContent: 'center',
  },
  steamPlaceholder: { paddingHorizontal: 10, textAlign: 'center', fontSize: 12, fontWeight: '600' },
  steamTitle: { fontSize: 13, fontWeight: '500', lineHeight: 18 },
  state: { gap: 8, width: '100%' },
  stateText: { fontSize: 13, lineHeight: 19 },
  stateBar: { height: 8, width: '60%', borderRadius: 4 },
  star: { fontSize: 16 },
});
