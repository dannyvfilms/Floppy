import React from 'react';
import { Image, Pressable, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { MarkdownPreview } from './MarkdownPreview';
import { Badge } from './Badge';
import { Button } from './Button';
import { Icon } from './Icon';
import { actionIcons } from './actionIcons';
import { MediumExtras } from './People';
import { detailSecondaryOrder } from './detailSecondaryModel';

function Value({ value, palette, onOpenLink, centered = false }) {
  const text = <Text style={[styles.value, centered && styles.centeredText, { color: palette.textSecondary }]}>{value.text}</Text>;
  return value.href && onOpenLink
    ? <Pressable accessibilityRole="link" accessibilityLabel={value.text}
      onPress={() => onOpenLink(value.href, value.identity)}>{text}</Pressable> : text;
}

export function DetailMetadata({ facts = [], title = 'Details', emptyLabel = 'No details available',
  palette, onOpenLink, promoted = false, children }) {
  const { width } = useWindowDimensions();
  const rows = promoted ? facts.filter(fact => !fact.promoted) : facts;
  if (promoted && !rows.length && !children) return null;
  return <View style={styles.section}>
    {rows.length || !promoted ? <Text accessibilityRole="header" style={[styles.heading, { color: palette.text }]}>{title}</Text> : null}
    {children}
    {rows.length || !promoted ? <View style={[styles.card, rows.length && styles.metadataCard,
      width < 768 && styles.centered, { backgroundColor: palette.surface }]}>
      {rows.length ? rows.map(fact => <View key={fact.key} style={[styles.fact, width < 768 && styles.centered]}>
        <Text style={[styles.label, width < 768 && styles.centeredText, { color: palette.textMuted, textTransform: 'none' }]}>{fact.label}</Text>
        {fact.inline ? <View style={[styles.inlineValues, width < 768 && styles.inlineCentered]}>
          {(fact.values || []).map((value, index) => <React.Fragment key={`${fact.key}-${index}`}>
            <Value value={value} palette={palette} centered={width < 768} onOpenLink={onOpenLink} />
            {index < fact.values.length - 1 ? <Text style={[styles.value, { color: palette.textSecondary }]}>, </Text> : null}
          </React.Fragment>)}
        </View> : (fact.values || []).map((value, index) => <Value key={`${fact.key}-${index}`} value={value} palette={palette}
          centered={width < 768} onOpenLink={onOpenLink} />)}
      </View>) : <Text style={[styles.value, { color: palette.textSecondary }]}>{emptyLabel}</Text>}
    </View> : null}
  </View>;
}

export function DetailWatchProviders({ providers, region, title = 'Streaming', emptyLabel = 'No watch providers', palette }) {
  if (region === 'UNSET' || providers === null || providers === undefined) return null;
  return <View style={[styles.card, { backgroundColor: palette.surface }]}>
    <Text accessibilityRole="header" style={[styles.label, { color: palette.textMuted }]}>{title}</Text>
    <View style={styles.providers}>
      {providers.length ? providers.map((provider, index) => provider.image
        ? <Image key={provider.provider_id || provider.provider_name || index}
          source={{ uri: provider.image }} resizeMode="contain" accessibilityLabel={provider.provider_name || provider.name}
          style={styles.providerImage} />
        : <Text key={provider.provider_id || provider.provider_name || index}
          style={[styles.value, { color: palette.textSecondary }]}>{provider.provider_name || provider.name}</Text>)
        : <Text style={[styles.value, { color: palette.text }]}>{emptyLabel}</Text>}
    </View>
  </View>;
}

export function DetailStudios({ studios = [], title = 'Studios', palette, onOpenLink }) {
  const { width } = useWindowDimensions();
  if (!studios.length) return null;
  return <View style={styles.section}>
    <Text accessibilityRole="header" style={[styles.heading, { color: palette.text }]}>{title}</Text>
    <View style={[styles.card, styles.studios, width < 600 && styles.centered, { backgroundColor: palette.surface }]}>
      {studios.slice(0, 12).map((studio, index) => <Value key={studio.studio_id || index}
        value={{ text: studio.name || 'Unknown Studio', href: studio.href, identity: studio }} palette={palette}
        centered={width < 600} onOpenLink={onOpenLink} />)}
    </View>
  </View>;
}

export function DetailPromotedFacts({ facts = [], palette }) {
  const { width } = useWindowDimensions();
  if (!facts.length) return null;
  return <View style={[styles.promoted, { borderBottomColor: palette.border }]}>
    {facts.map(fact => <View key={fact.key} style={[styles.promotedFact, width < 768 && styles.promotedCompact]}>
      <Text style={[styles.promotedLabel, { color: palette.textMuted }]}>{fact.label}</Text>
      <Text style={[styles.value, { color: palette.textSecondary }]}>{fact.value}</Text>
    </View>)}
  </View>;
}

export function DetailMediumExtras({ gameLengths, youtubeWatch, labels, palette, onOpenLink }) {
  return <MediumExtras gameLengths={gameLengths} youtubeWatch={youtubeWatch}
    labels={labels} palette={palette} onOpenSource={onOpenLink} />;
}

export function DetailGenres({ genres = [], title = 'Genres', palette, onOpenLink }) {
  if (!genres.length) return null;
  return <View style={styles.section}>
    <Text accessibilityRole="header" style={[styles.heading, { color: palette.text }]}>{title}</Text>
    <View style={[styles.card, styles.genres, { backgroundColor: palette.surface }]}>
      {genres.map((genre, index) => <Badge key={`${genre.label}-${index}`} label={genre.label} size="tag" tone="genre"
        palette={{ genre: { color: palette.text, backgroundColor: 'rgba(139,92,246,.07)', borderColor: 'rgba(167,139,250,.18)', borderWidth: 1, fontWeight: '500' } }}
        onPress={genre.href && onOpenLink ? () => onOpenLink(genre.href) : undefined} />)}
    </View>
  </View>;
}

export function DetailTrackingHistory({ entries = [], count = entries.length + 1, hasMore = false,
  title = 'Your History', repeatsLabel = 'Show Repeats', palette, onEdit, onOpenHistory }) {
  const [expanded, setExpanded] = React.useState(false);
  if (count < 2) return null;
  return <View style={styles.section}>
    <Text accessibilityRole="header" style={[styles.heading, { color: palette.text }]}>{title}</Text>
    <Pressable accessibilityRole="button" accessibilityState={{ expanded }} onPress={() => setExpanded(value => !value)}
      style={[styles.repeatsToggle, { backgroundColor: palette.surfaceStrong }]}>
      <View style={expanded ? { transform: [{ rotate: '180deg' }] } : undefined}><Icon spec={actionIcons.chevronDown} size={16} color={palette.text} /></View>
      <Text style={[styles.value, { color: palette.text }]}>{repeatsLabel} ({Math.max(0, count - 1)})</Text>
    </Pressable>
    {expanded ? <View style={styles.historyEntries}>
      {entries.map(entry => <View key={entry.id} style={[styles.card, { backgroundColor: palette.surface }]}>
        <View style={styles.historyHeading}>
          <Text style={[styles.value, { color: entry.scoreLabel ? palette.textSecondary : palette.textMuted }]}>
            <Text style={{ color: entry.scoreLabel ? '#facc15' : palette.textMuted }}>★ </Text>{entry.scoreLabel || 'Not rated'}
          </Text>
          {entry.editable && onEdit ? <Pressable accessibilityRole="button" accessibilityLabel="Edit tracking entry" onPress={() => onEdit(entry)} hitSlop={8}>
            <Icon spec={actionIcons.edit} size={16} color={palette.textMuted} />
          </Pressable> : null}
        </View>
        {[entry.statusLabel, entry.progressLabel, entry.startedLabel, entry.finishedLabel].filter(Boolean).map((line, index) =>
          <Text key={index} style={[styles.historyCopy, { color: palette.textMuted }]}>{line}</Text>)}
        {entry.notes ? <MarkdownPreview markdown={entry.notes} palette={palette} /> : null}
      </View>)}
      {hasMore && onOpenHistory ? <Button label="View all history" tone="surface" palette={palette} onPress={onOpenHistory} /> : null}
    </View> : null}
  </View>;
}

/** Section slots keep requests, permissions and editable content in their adapters. */
export function DetailSecondary({ model = {}, sections = {}, layout = model.layout,
  palette, onOpenLink, promote = false }) {
  const { width } = useWindowDimensions();
  const wide = width >= 768;
  const promoted = promote && width >= 600 && model.promoted?.length > 0;
  const providers = model.watchProviderRegion !== 'UNSET' && Array.isArray(model.watchProviders)
    ? <DetailWatchProviders providers={model.watchProviders} region={model.watchProviderRegion}
      title={model.labels?.streaming} emptyLabel={model.labels?.noWatchProviders} palette={palette} /> : null;
  const showDetails = !promoted || (model.facts || []).some(fact => !fact.promoted) || (wide && providers);
  const slots = {
    details: showDetails ? <DetailMetadata facts={model.facts} title={model.labels?.details} emptyLabel={model.labels?.noDetails}
      palette={palette} onOpenLink={onOpenLink} promoted={promoted}>{wide ? providers : null}</DetailMetadata> : null,
    genres: model.genres?.length && !(wide && promote && !model.publicView)
      ? <DetailGenres genres={model.genres} palette={palette} onOpenLink={onOpenLink} /> : null,
    studios: model.studios?.length ? <DetailStudios studios={model.studios} palette={palette} onOpenLink={onOpenLink} /> : null,
    game_lengths: model.gameLengths ? <DetailMediumExtras gameLengths={model.gameLengths} palette={palette} onOpenLink={onOpenLink} /> : null,
    youtube_watch: model.youtubeWatch ? <DetailMediumExtras youtubeWatch={model.youtubeWatch} palette={palette} /> : null,
    ...sections,
  };
  const available = Object.keys(slots).filter(key => slots[key]);
  const sidebar = detailSecondaryOrder(layout, available, 'sidebar');
  const content = detailSecondaryOrder(layout, available, 'content');
  const railSections = ['seasons', 'cast', 'crew', 'recommendations'];
  const rows = (keys, compact = false, gap = 32) => keys.map((key, index) => <View key={key}
    style={[
      compact ? (['genres', 'studios', 'collection'].includes(key) ? styles.compactSection : styles.fullSection) : undefined,
      railSections.includes(key) && railSections.includes(keys[index - 1]) ? { marginTop: 12 - gap } : undefined,
    ]}>{slots[key]}</View>);
  return <View style={styles.secondary}>
    {promoted && sidebar.includes('details') ? <DetailPromotedFacts facts={model.promoted} palette={palette} /> : null}
    <View style={[styles.columns, wide && styles.columnsWide]}>
      {!wide ? providers : null}
      {sidebar.length ? <View style={[styles.sidebar, wide && styles.sidebarWide,
        width >= 600 && !wide && styles.sidebarCompact]}>{rows(sidebar, width >= 600 && !wide, width >= 600 && !wide ? 16 : 24)}</View> : null}
      {content.length ? <View style={[styles.content, wide && styles.contentWide]}>{rows(content)}</View> : null}
    </View>
  </View>;
}

const styles = StyleSheet.create({
  genres: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'center', gap: 8 },
  repeatsToggle: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8 },
  historyEntries: { gap: 8 },
  historyHeading: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 },
  historyCopy: { fontSize: 12, lineHeight: 16 },
  secondary: { gap: 24, width: '100%' },
  columns: { gap: 24, minWidth: 0 },
  columnsWide: { flexDirection: 'row', gap: 40, alignItems: 'flex-start' },
  sidebar: { gap: 24, minWidth: 0 },
  sidebarWide: { width: '25%', maxWidth: 250, flexShrink: 0 },
  sidebarCompact: { flexDirection: 'row', flexWrap: 'wrap', gap: 16 },
  compactSection: { flexBasis: '30%', flexShrink: 1, minWidth: 0 },
  fullSection: { width: '100%' },
  content: { minWidth: 0, gap: 32 },
  contentWide: { flex: 1 },
  section: { gap: 16, minWidth: 0 },
  heading: { fontSize: 20, lineHeight: 28, fontWeight: '700' },
  card: { padding: 16, borderRadius: 8, gap: 8 },
  metadataCard: { gap: 16, paddingBottom: 32 },
  fact: { width: '100%', gap: 0 },
  centered: { alignItems: 'center' },
  centeredText: { textAlign: 'center' },
  inlineValues: { flexDirection: 'row', flexWrap: 'wrap' },
  inlineCentered: { justifyContent: 'center' },
  label: { fontSize: 14, lineHeight: 20, fontWeight: '600', letterSpacing: 0.3, textTransform: 'uppercase' },
  value: { fontSize: 14, lineHeight: 20 },
  studios: { gap: 4 },
  providers: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-evenly', gap: 8 },
  providerImage: { width: 40, height: 40, borderRadius: 6 },
  promoted: { flexDirection: 'row', flexWrap: 'wrap', columnGap: 32, rowGap: 16,
    paddingBottom: 20, marginBottom: 4, borderBottomWidth: 1 },
  promotedFact: { maxWidth: 384, minWidth: 0, gap: 6 },
  promotedCompact: { flexBasis: '21%', flexGrow: 1 },
  promotedLabel: { fontSize: 14, lineHeight: 20, fontWeight: '600' },
});
