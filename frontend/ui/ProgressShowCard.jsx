import React, { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { ArtworkImage } from './ArtworkImage';
import { MediaCard } from './MediaCard';
import { COMPACT_CARD_WIDTH } from './mediaCardSizing';
import { ProgressBar, progressFallbackPalette } from './ProgressBar';
import { DisclosureChevron } from './ProgressBreakdown';

const defaultLabels = {
  watched: 'watched',
  toggleSeasons: 'Show seasons',
  loadingSeasons: 'Loading seasons…',
  seasonsError: 'Seasons could not be loaded.',
  season: 'Season',
  openProgress: 'Open the season and episode breakdown',
  caughtUp: 'Caught up',
};

const GAP = 16;
// The row needs the poster, a text column and the horizontal episode card; narrower than this a
// show is just the episode card.
const WIDE = 640;
const COMPACT_MAX = 640;
const LANDSCAPE = 16 / 9;

/**
 * One show on the Progress page.
 *
 * Wide: the 2:3 poster, the title, watched bar and season disclosure, and the next episode as a
 * horizontal media card, with the poster and episode card the same height. Narrow (a phone): the
 * horizontal episode card alone, carrying the show title, a fuller subtitle and the bottom progress
 * bar, and a tap opens the progress dialog.
 *
 * Presentation only: the caller owns the row, the loaded seasons, the dialog and navigation.
 */
export function ProgressShowCard({
  row,
  seasons,
  expanded = false,
  labels,
  palette,
  onOpen,
  onOpenShow,
  onOpenEpisode,
  onToggleSeasons,
}) {
  const colors = { ...progressFallbackPalette, ...palette };
  const text = { ...defaultLabels, ...labels };
  const [width, setWidth] = useState(0);
  const wide = width >= WIDE;
  const episode = row.next_episode_card;
  const title = row.year ? `${row.title} (${row.year})` : row.title;
  const left = row.left > 0 ? `${row.left} remaining (${row.time_left})` : text.caughtUp;
  // The card's title and subtitle sit on a dark scrim over the artwork, so their text stays light in
  // every theme.
  const cardPalette = {
    card: colors.surfaceStrong,
    text: '#ffffff',
    textSecondary: 'rgba(255, 255, 255, 0.86)',
    textMuted: 'rgba(255, 255, 255, 0.74)',
    border: colors.surfaceBorder,
    link: '#ffffff',
    placeholder: colors.surfaceMuted,
  };
  const measure = event => setWidth(Math.floor(event.nativeEvent.layout.width));

  if (!wide) {
    // One horizontal card per show. Without a next episode it falls back to the show's artwork.
    const code = episode?.lines?.[0]?.parts?.[0]?.text;
    const status = row.left > 0
      ? `${row.watched}/${row.total} · ${row.left} left (${row.time_left})`
      : `${row.watched}/${row.total} · ${text.caughtUp}`;
    const base = episode || {
      mediaType: 'tv', image: { src: row.image, fallback: '', source: 'primary' },
      statusChip: null, cornerChips: [], titleLinks: [], altTitle: null,
    };
    const model = {
      ...base,
      shape: 'landscape',
      aspectRatio: LANDSCAPE,
      title: row.title,
      subtitleAlways: true,
      lines: [
        ...(code ? [{ parts: [{ text: code }, ...(episode.title ? [{ text: episode.title }] : [])], dormant: false }] : []),
        { parts: [{ text: status }], dormant: false },
      ],
      // "dormant" keeps the web grid card showing its bar at rest, not only on hover.
      progressBar: { percent: row.percent, dormant: true },
    };
    const cardWidth = width ? Math.min(width, COMPACT_MAX) : undefined;
    return <View onLayout={measure} style={styles.compact}>
      {cardWidth ? <View style={{ width: cardWidth }}>
        <MediaCard variant="grid" model={model} readOnly width={cardWidth} onOpen={() => onOpen?.(row)} palette={cardPalette} />
      </View> : null}
    </View>;
  }

  // Poster and episode card share one height: the poster is 2:3 at the compact card width Home
  // shelves use, and the landscape episode card is as tall as it. A row is a list entry, so it is
  // sized like a shelf card, not like a grid card.
  const posterWidth = COMPACT_CARD_WIDTH;
  const height = posterWidth * 1.5;
  const episodeWidth = height * LANDSCAPE;
  return <View onLayout={measure}
    style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.surfaceBorder }]}>
    <View style={styles.top}>
      <Pressable accessibilityRole="link" accessibilityLabel={title} onPress={() => onOpenShow?.(row)}
        style={{ width: posterWidth }}>
        <ArtworkImage src={row.image} title={row.title} style={[styles.poster, { width: posterWidth, aspectRatio: 2 / 3 }]}
          palette={{ placeholder: colors.surfaceStrong, textMuted: colors.textMuted }} />
      </Pressable>
      <View style={styles.main}>
        <Pressable accessibilityRole="link" onPress={() => onOpenShow?.(row)}>
          <Text numberOfLines={2} style={[styles.title, { color: colors.text }]}>{title}</Text>
        </Pressable>
        <Pressable accessibilityRole="button"
          accessibilityLabel={`${row.title}, ${row.percent}%`}
          accessibilityHint={text.openProgress}
          onPress={() => onOpen?.(row)} style={styles.bar}>
          <ProgressBar percent={row.percent} height={10} palette={colors} label={row.title} />
        </Pressable>
        <View style={styles.subtitle}>
          <View style={styles.facts}>
            <Text style={[styles.fact, { color: colors.textSecondary }]}>{row.watched}/{row.total} {text.watched}</Text>
            <Text style={[styles.fact, { color: colors.textMuted }]}>{left}</Text>
          </View>
          <DisclosureChevron open={expanded} label={text.toggleSeasons} palette={colors} size={22}
            onPress={() => onToggleSeasons?.(row)} />
        </View>
      </View>
      {episode ? <View style={{ width: episodeWidth, height, overflow: 'hidden', borderRadius: 8 }}>
        {/* The card draws inside a 1 pt border, so it is given 2 pt more than the box to fill it. */}
        <MediaCard variant="grid" model={episode} readOnly width={episodeWidth + 2}
          onOpen={onOpenEpisode ? () => onOpenEpisode(episode) : undefined} palette={cardPalette} />
      </View> : null}
    </View>
    {expanded ? <View style={[styles.seasons, { backgroundColor: colors.surfaceStrong }]}>
      {!seasons || seasons.status === 'loading' ? <Text style={[styles.fact, { color: colors.textMuted }]}>{text.loadingSeasons}</Text> : null}
      {seasons?.status === 'error' ? <Text style={[styles.fact, { color: colors.textMuted }]}>{text.seasonsError}</Text> : null}
      {seasons?.status === 'ready' ? seasons.rows.map(season => <View key={season.number} style={styles.season}>
        <Text style={[styles.seasonTitle, { color: colors.text }]}>{season.title || `${text.season} ${season.number}`}
          <Text style={{ color: colors.textMuted }}>  {season.watched}/{season.total}</Text></Text>
        <ProgressBar percent={season.percent} height={8} palette={colors} label={season.title || `${text.season} ${season.number}`} />
      </View>) : null}
    </View> : null}
  </View>;
}

const styles = StyleSheet.create({
  compact: { minWidth: 0 },
  card: { borderWidth: 1, borderRadius: 16, padding: GAP, gap: 12, minWidth: 0 },
  top: { flexDirection: 'row', alignItems: 'flex-start', gap: GAP },
  poster: { borderRadius: 8 },
  main: { flex: 1, minWidth: 0, gap: 10 },
  title: { fontSize: 20, lineHeight: 26, fontWeight: '600' },
  bar: { paddingVertical: 4 },
  // The facts wrap inside their own block; the chevron stays at the right edge of the line.
  subtitle: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  facts: { flex: 1, minWidth: 0, flexDirection: 'row', flexWrap: 'wrap', columnGap: 16, rowGap: 2 },
  fact: { fontSize: 14, lineHeight: 20 },
  seasons: { borderRadius: 8, padding: 12, gap: 12 },
  season: { gap: 6 },
  seasonTitle: { fontSize: 14, lineHeight: 20, fontWeight: '500' },
});
