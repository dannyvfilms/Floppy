import { Modal, ModalCloseButton } from './Modal';
import React, { useState } from 'react';
import {
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from 'react-native';
import { ArtworkImage } from './ArtworkImage';
import { Badge } from './Badge';
import { Button } from './Button';
import { CollectionGroup, CollectionRow } from './CollectionCopies';
import { Icon } from './Icon';
import { MediaCard } from './MediaCard';
import { actionIcons } from './actionIcons';
import { creditCardModel, personCardModel } from './cardModels';

// Shared person, studio, credit, gallery and medium-extra presentation. Values
// arrive already shaped by the server or feature adapter; these components
// never parse URLs, own permissions or fetch provider data.

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
  star: '#facc15',
  warning: '#f59e0b',
  success: '#10b981',
  overlay: 'rgba(0, 0, 0, 0.55)',
  chipBackground: 'rgba(24, 24, 27, 0.92)',
  chipText: '#ffffff',
  placeholder: '#3f3f46',
  radius: 10,
  radiusSmall: 6,
};

const DEFAULT_LABELS = {
  showMore: 'Show more',
  showLess: 'Show less',
  viewReads: 'View Reads in History',
  viewPlays: 'View Plays in History',
  visitWebsite: 'Visit Website',
  source: 'Source',
  born: 'Born',
  died: 'Died',
  placeOfBirth: 'Place of Birth',
  founded: 'Founded',
  titles: 'Titles',
  developed: 'Developed',
  published: 'Published',
  overview: 'Overview',
  playTrailer: 'Play trailer',
  viewFullSize: 'View full size',
  fitImage: 'Fit image',
  fillFrame: 'Fill frame',
  previous: 'Previous',
  next: 'Next',
  close: 'Close',
  timeToBeat: 'Time to Beat',
  submissions: 'submissions',
  timeToBeatPending: 'Fetching cached time-to-beat data in the background.',
  timeToBeatEmpty: 'Time-to-beat data is not available yet.',
  watchedOnYouTube: 'Watched on YouTube',
  started: 'Started',
  youtubeTime: 'Time',
  youtubeEstimate: 'Estimated from how far you got in each video. Your playtime is not affected.',
  readingActivity: 'Reading Activity',
  listeningTime: 'Listening Time',
  mostRead: 'Most Read',
  topAuthors: 'Top Authors',
  noReadingData: 'No reading data available.',
  noBiography: 'No biography available.',
  noTitles: 'No titles available.',
  watchedContent: 'Watched Content',
  readContent: 'Read Content',
  filmography: 'Filmography',
  bibliography: 'Bibliography',
  noFilmography: 'No filmography available.',
  noBibliography: 'No bibliography available.',
  noWatched: 'No watched titles yet.',
  noRead: 'No read titles yet.',
};

function mergePalette(palette) {
  return { ...DEFAULT_PALETTE, ...(palette || {}) };
}

function mergeLabels(labels) {
  return { ...DEFAULT_LABELS, ...(labels || {}) };
}

function badgePalette(colors) {
  return {
    indigo: { color: colors.accentContrast, backgroundColor: colors.accentStrong },
    outline: { color: colors.textSecondary, borderColor: colors.border, borderWidth: 1 },
  };
}

function text(value) {
  return value === null || value === undefined ? '' : String(value);
}

function plural(count, one, many) {
  return Number(count) === 1 ? one : many;
}

function Artwork({ uri, fallback, title, ratio = 2 / 3, palette, rounded = true, children }) {
  return <ArtworkImage src={uri} fallback={fallback} title={title}
    style={[styles.artwork, rounded && styles.artworkRounded, { aspectRatio: ratio }]}
    palette={{ placeholder: palette.placeholder, textMuted: palette.textMuted }}
    labels={{ loading: title || '', unavailable: title || '' }}>
    {children}
  </ArtworkImage>;
}

function Fact({ label, value, palette, onPress }) {
  const content = <>
    <Text style={[styles.factLabel, { color: palette.textMuted }]}>{label}</Text>
    <Text style={[styles.factValue, { color: onPress ? palette.link : palette.textSecondary }]}>{value}</Text>
  </>;
  if (!onPress) return <View style={[styles.fact, { backgroundColor: palette.surface }]}>{content}</View>;
  return <Pressable accessibilityRole="link" accessibilityLabel={`${label}: ${value}`} onPress={onPress}
    style={({ pressed }) => [styles.fact, { backgroundColor: palette.surface, opacity: pressed ? 0.8 : 1 }]}>
    {content}
  </Pressable>;
}

export function PersonHero({
  person = {},
  counts = [],
  labels,
  palette,
  onViewHistory,
  onOpenSource,
  canViewHistory = true,
  biographyLines = 5,
  headingLevel = 2,
  actionPalette,
  actionSize,
  showBiography = true,
}) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const wide = useWindowDimensions().width >= 768;
  const [expanded, setExpanded] = useState(false);
  const biography = text(person.biography);
  const canExpand = biography.length > 260;
  const facts = [
    person.birthDate ? { label: copy.born, value: person.birthDate } : null,
    person.deathDate ? { label: copy.died, value: person.deathDate } : null,
    person.placeOfBirth ? { label: copy.placeOfBirth, value: person.placeOfBirth } : null,
  ].filter(Boolean);

  return <View style={[styles.hero, wide && styles.heroWide]}>
    <View style={[styles.heroMedia, wide && styles.heroMediaWide]}>
      <Artwork uri={person.imageUrl} title={person.name} palette={colors} />
      {onViewHistory && canViewHistory ? <View style={[styles.heroAction, { backgroundColor: colors.surface }]}>
        <Button label={person.isAuthor ? copy.viewReads : copy.viewPlays} width="full"
          size={actionSize} onPress={onViewHistory} palette={actionPalette || { radius: colors.radiusSmall }} />
      </View> : null}
    </View>
    <View style={[styles.heroBody, wide && styles.heroBodyWide]}>
      <Text role="heading" aria-level={headingLevel} style={[styles.heroTitle, { color: colors.text }]}>{person.name}</Text>
      {person.knownForDepartment || counts.length ? <View style={styles.chipRow}>
        {person.knownForDepartment ? <Badge label={person.knownForDepartment} tone="indigo" size="md"
          palette={badgePalette(colors)} /> : null}
        {counts.map((count, index) => <Badge key={`${count.label}-${index}`} label={count.label} size="md"
          palette={badgePalette(colors)} />)}
      </View> : null}
      {showBiography ? <View style={[styles.card, { backgroundColor: colors.surface }]}>
        <Text numberOfLines={expanded ? undefined : biographyLines}
          style={[styles.biography, { color: colors.textSecondary }]}>
          {biography || copy.noBiography}
        </Text>
        {canExpand ? <Pressable accessibilityRole="button"
          accessibilityLabel={expanded ? copy.showLess : copy.showMore}
          onPress={() => setExpanded(value => !value)} style={styles.inlineAction}>
          <Text style={[styles.inlineActionText, { color: colors.link }]}>{expanded ? copy.showLess : copy.showMore}</Text>
        </Pressable> : null}
      </View> : null}
      <View style={styles.factGrid}>
        {facts.map(fact => <Fact key={fact.label} label={fact.label} value={fact.value} palette={colors} />)}
        <Fact label={copy.source} value={person.sourceLabel || copy.source} palette={colors}
          onPress={person.sourceUrl && onOpenSource ? () => onOpenSource(person.sourceUrl) : undefined} />
      </View>
    </View>
  </View>;
}

export function StudioHero({
  studio = {},
  counts = [],
  labels,
  palette,
  onOpenWebsite,
  headingLevel = 2,
  sourcePlacement = 'media',
  showBiography = true,
}) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const wide = useWindowDimensions().width >= 768;
  const [expanded, setExpanded] = useState(false);
  const description = text(studio.description);
  const canExpand = description.length > 260;
  const facts = [
    studio.founded ? { label: copy.founded, value: studio.founded } : null,
    { label: studio.mediaLabel || copy.titles, value: text(studio.titleCount ?? 0) },
    studio.developedCount !== undefined && studio.developedCount !== null
      ? { label: copy.developed, value: text(studio.developedCount) } : null,
    studio.publishedCount !== undefined && studio.publishedCount !== null
      ? { label: copy.published, value: text(studio.publishedCount) } : null,
    sourcePlacement === 'facts'
      ? { label: copy.source, value: studio.sourceLabel || copy.source } : null,
  ].filter(Boolean);

  return <View style={[styles.hero, wide && styles.heroWide]}>
    <View style={[styles.heroMedia, wide && styles.heroMediaWide]}>
      <Artwork uri={studio.logoUrl} title={studio.name} ratio={1} palette={colors} />
      {studio.websiteUrl && onOpenWebsite ? <View style={[styles.heroAction, { backgroundColor: colors.surface }]}>
        <Button label={copy.visitWebsite} width="full" onPress={() => onOpenWebsite(studio.websiteUrl)}
          palette={{ radius: colors.radiusSmall }} />
      </View> : null}
      {sourcePlacement !== 'facts' ? <View style={[styles.sourceCard, { backgroundColor: colors.surface }]}>
        <Text style={[styles.factLabel, { color: colors.textMuted }]}>{copy.source}</Text>
        <Text style={[styles.factValue, { color: colors.textSecondary }]}>{studio.sourceLabel || copy.source}</Text>
      </View> : null}
    </View>
    <View style={[styles.heroBody, wide && styles.heroBodyWide]}>
      <Text role="heading" aria-level={headingLevel} style={[styles.heroTitle, { color: colors.text }]}>{studio.name}</Text>
      {counts.length ? <View style={styles.chipRow}>
        {counts.map((count, index) => index === 0
          ? <Badge key={`${count.label}-${index}`} label={count.label} tone="indigo" size="md"
            palette={badgePalette(colors)} />
          : <Badge key={`${count.label}-${index}`} label={count.label} size="md"
            palette={badgePalette(colors)} />)}
      </View> : null}
      {showBiography ? <View style={[styles.card, { backgroundColor: colors.surface }]}>
        <Text numberOfLines={expanded ? undefined : 5}
          style={[styles.biography, { color: colors.textSecondary }]}>{description}</Text>
        {canExpand ? <Pressable accessibilityRole="button"
          accessibilityLabel={expanded ? copy.showLess : copy.showMore}
          onPress={() => setExpanded(value => !value)} style={styles.inlineAction}>
          <Text style={[styles.inlineActionText, { color: colors.link }]}>{expanded ? copy.showLess : copy.showMore}</Text>
        </Pressable> : null}
      </View> : null}
      <View style={styles.factGrid}>
        {facts.map(fact => <Fact key={fact.label} label={fact.label} value={fact.value} palette={colors} />)}
      </View>
    </View>
  </View>;
}

// People and credits are media cards fed through `cardModels.js`; nothing here draws a poster.
function peoplePalette(colors) {
  return { ...colors, card: colors.surface };
}

export function PersonCard({ person = {}, palette, onOpen }) {
  const colors = mergePalette(palette);
  return <MediaCard variant="grid" model={personCardModel(person)} palette={peoplePalette(colors)} width="100%"
    onOpen={onOpen ? () => onOpen(person) : undefined} />;
}

export function CreditCard({ entry = {}, palette, onOpen }) {
  const colors = mergePalette(palette);
  return <MediaCard variant="grid" model={creditCardModel(entry)} palette={peoplePalette(colors)} width="100%"
    onOpen={onOpen ? () => onOpen(entry) : undefined} />;
}

export function MediaGallery({ items = [], labels, palette, onPlay, onOpenLightbox }) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const [selected, setSelected] = useState(0);
  const [fit, setFit] = useState('contain');
  if (!items.length) return null;
  const bounded = Math.max(0, Math.min(selected, items.length - 1));
  const current = items[bounded];
  const isVideo = current.kind === 'video';

  function move(delta) {
    setSelected(index => (index + delta + items.length) % items.length);
  }

  return <View style={styles.gallery}>
    <View style={[styles.galleryPreview, { backgroundColor: colors.background }]}>
      <Pressable accessibilityRole={isVideo ? 'button' : 'image'}
        accessibilityLabel={isVideo ? copy.playTrailer : current.label || copy.viewFullSize}
        onPress={() => isVideo ? onPlay?.(current) : onOpenLightbox?.(items, bounded)}
        style={styles.fill}>
        {current.posterUrl || current.url
          ? <Image source={{ uri: current.posterUrl || current.url }}
            resizeMode={isVideo || fit === 'cover' ? 'cover' : 'contain'} style={styles.fill} />
          : <View style={[styles.fill, styles.galleryEmpty]}><Text style={{ color: colors.textMuted }}>{current.label}</Text></View>}
        {isVideo ? <View style={styles.playOverlay}><View style={styles.playButton}>
          <Text style={styles.playGlyph}>▶</Text>
        </View></View> : null}
      </Pressable>
      <View style={[styles.counterChip, { backgroundColor: colors.chipBackground }]}>
        <Text style={[styles.cornerChipText, { color: colors.chipText }]}>{bounded + 1} / {items.length}</Text>
      </View>
      <View style={styles.galleryControls}>
        <Pressable accessibilityRole="button" accessibilityLabel={fit === 'cover' ? copy.fitImage : copy.fillFrame}
          onPress={() => setFit(value => value === 'cover' ? 'contain' : 'cover')}
          style={[styles.roundButton, { backgroundColor: colors.chipBackground }]}>
          <Text style={[styles.roundGlyph, { color: colors.chipText }]}>⤢</Text>
        </Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel={copy.viewFullSize}
          onPress={() => onOpenLightbox?.(items, bounded)}
          style={[styles.roundButton, { backgroundColor: colors.chipBackground }]}>
          <Text style={[styles.roundGlyph, { color: colors.chipText }]}>⛶</Text>
        </Pressable>
      </View>
      {bounded > 0 ? <Pressable accessibilityRole="button" accessibilityLabel={copy.previous}
        onPress={() => move(-1)} style={[styles.arrowButton, styles.arrowLeft, { backgroundColor: colors.chipBackground }]}>
        <Text style={[styles.arrowGlyph, { color: colors.chipText }]}>‹</Text>
      </Pressable> : null}
      {items.length > 1 ? <Pressable accessibilityRole="button" accessibilityLabel={copy.next}
        onPress={() => move(1)} style={[styles.arrowButton, styles.arrowRight, { backgroundColor: colors.chipBackground }]}>
        <Text style={[styles.arrowGlyph, { color: colors.chipText }]}>›</Text>
      </Pressable> : null}
    </View>
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.thumbRow}>
      {items.map((item, index) => {
        const active = index === bounded;
        return <Pressable key={item.id || index} accessibilityRole="button"
          accessibilityLabel={item.label || (item.kind === 'video' ? copy.playTrailer : copy.overview)}
          accessibilityState={{ selected: active }} onPress={() => setSelected(index)}
          style={[styles.thumb, { borderColor: active ? colors.accent : 'transparent', backgroundColor: colors.surfaceMuted }]}>
          {item.thumbUrl || item.posterUrl || item.url
            ? <Image source={{ uri: item.thumbUrl || item.posterUrl || item.url }} resizeMode="cover" style={styles.fill} />
            : <View style={styles.fill} />}
          {item.kind === 'video' ? <View style={styles.thumbPlay}><Text style={styles.thumbPlayGlyph}>▶</Text></View> : null}
          {item.kind === 'overview' ? <Text style={styles.thumbCaption}>{copy.overview}</Text> : null}
        </Pressable>;
      })}
    </ScrollView>
  </View>;
}

export function LightboxDialog({
  visible = false,
  items = [],
  index = 0,
  labels,
  palette,
  onClose,
  onIndexChange,
  onPlay,
}) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  if (!items.length) return null;
  const bounded = Math.max(0, Math.min(index, items.length - 1));
  const current = items[bounded];
  const isVideo = current.kind === 'video';

  function move(delta) {
    onIndexChange?.((bounded + delta + items.length) % items.length);
  }

  return <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
    <View style={[styles.lightbox, { backgroundColor: 'rgba(0, 0, 0, 0.94)' }]}>
      <View style={styles.lightboxTop}>
        <Text style={[styles.lightboxCount, { color: colors.chipText }]}>{bounded + 1} / {items.length}</Text>
        <ModalCloseButton accessibilityRole="button" accessibilityLabel={copy.close} onPress={onClose}
          style={[styles.roundButton, { backgroundColor: colors.chipBackground }]}>
          <Icon spec={actionIcons.x} size={18} color={colors.chipText} />
        </ModalCloseButton>
      </View>
      <View style={styles.lightboxBody}>
        <Image source={{ uri: isVideo ? current.posterUrl : current.url }} resizeMode="contain" style={styles.fill} />
        {isVideo ? <Pressable accessibilityRole="button" accessibilityLabel={copy.playTrailer}
          onPress={() => onPlay?.(current)} style={styles.playOverlay}>
          <View style={styles.playButton}><Text style={styles.playGlyph}>▶</Text></View>
        </Pressable> : null}
      </View>
      {items.length > 1 ? <View style={styles.lightboxControls}>
        <Pressable accessibilityRole="button" accessibilityLabel={copy.previous} onPress={() => move(-1)}
          style={[styles.roundButton, { backgroundColor: colors.chipBackground }]}>
          <Text style={[styles.arrowGlyph, { color: colors.chipText }]}>‹</Text>
        </Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel={copy.next} onPress={() => move(1)}
          style={[styles.roundButton, { backgroundColor: colors.chipBackground }]}>
          <Text style={[styles.arrowGlyph, { color: colors.chipText }]}>›</Text>
        </Pressable>
      </View> : null}
    </View>
  </Modal>;
}

// Time-to-beat rows by their label; unknown labels fall back to a clock.
const LENGTH_ICONS = {
  'Main Story': actionIcons.book,
  'Main + Extras': actionIcons.list,
  Completionist: actionIcons.star,
  'All PlayStyles': actionIcons.fourSquare,
  Hastily: actionIcons.historyClock,
  Normally: actionIcons.alarmClock,
  Completely: actionIcons.circleCheck,
};

export function MediumExtras({
  gameLengths,
  youtubeWatch,
  reading,
  labels,
  palette,
  onOpenSource,
  onOpenItem,
  variant = 'native',
}) {
  const copy = mergeLabels(labels);
  const colors = mergePalette(palette);
  const sections = [];

  const group = (key, title, rows) => <CollectionGroup key={key} title={title} palette={colors} variant={variant}>{rows}</CollectionGroup>;
  const note = (key, text) => <Text key={key} style={[styles.cardCopy, { color: colors.textMuted }]}>{text}</Text>;

  if (gameLengths) {
    const rows = gameLengths.available
      ? (gameLengths.cards || []).map((card, index) => <CollectionRow key={card.label || index}
        icon={LENGTH_ICONS[card.label] || actionIcons.alarmClock} label={card.label} palette={colors} multiline>
        <View style={styles.lengthEnd}>
          <Text style={[styles.lengthValue, { color: colors.text }]}>{card.value}</Text>
          {card.count !== undefined ? <Text style={[styles.cardMeta, { color: colors.textMuted }]}>
            {card.count} {copy.submissions}
          </Text> : null}
        </View>
      </CollectionRow>)
      : [<CollectionRow key="empty" icon={actionIcons.info} palette={colors} multiline
        label={gameLengths.pending ? copy.timeToBeatPending : copy.timeToBeatEmpty} />];
    if (gameLengths.sourceLabel) rows.push(<CollectionRow key="source" icon={actionIcons.externalLink} label={gameLengths.sourceLabel}
      palette={colors} onPress={gameLengths.sourceUrl && onOpenSource ? () => onOpenSource(gameLengths.sourceUrl) : undefined}
      chevron={!!(gameLengths.sourceUrl && onOpenSource)} />);
    sections.push(group('lengths', copy.timeToBeat, rows));
  }

  if (youtubeWatch) {
    sections.push(<View key="youtube" style={styles.extraSection}>
      {group('youtube-rows', copy.watchedOnYouTube, [
        <CollectionRow key="time" icon={actionIcons.play} label={copy.youtubeTime} palette={colors}
          value={youtubeWatch.seconds ? `~${youtubeWatch.hoursLabel}` : copy.started} />,
        <CollectionRow key="videos" icon={actionIcons.list} label={plural(youtubeWatch.videos, 'Video', 'Videos')} palette={colors}
          value={youtubeWatch.videos} />,
      ])}
      {note('note', copy.youtubeEstimate)}
    </View>);
  }

  if (reading) {
    const rows = [];
    if (reading.listening) rows.push(<CollectionRow key="listening" icon={actionIcons.play} label={copy.listeningTime}
      palette={colors} value={reading.listening} />);
    (reading.topItems || []).forEach((item, index) => rows.push(<CollectionRow key={`item-${item.id || index}`}
      icon={actionIcons.book} label={item.title} value={item.units} palette={colors}
      onPress={onOpenItem ? () => onOpenItem(item) : undefined} chevron={!!onOpenItem} />));
    (reading.topAuthors || []).forEach((author, index) => rows.push(<CollectionRow key={`author-${author.id || index}`}
      icon={actionIcons.edit} label={author.name} value={author.units} palette={colors}
      onPress={onOpenItem ? () => onOpenItem(author) : undefined} chevron={!!onOpenItem} />));
    if (!rows.length) rows.push(<CollectionRow key="empty" icon={actionIcons.info} label={copy.noReadingData} palette={colors} />);
    sections.push(group('reading', copy.readingActivity, rows));
  }

  if (!sections.length) return null;
  return <View style={styles.extras}>{sections}</View>;
}

const styles = StyleSheet.create({
  hero: { gap: 20 },
  heroWide: { flexDirection: 'row', alignItems: 'flex-start' },
  heroMedia: { gap: 12, alignSelf: 'stretch' },
  heroMediaWide: { width: 250, flexShrink: 0 },
  heroBody: { gap: 12, minWidth: 0 },
  heroBodyWide: { flex: 1 },
  heroTitle: { fontSize: 30, fontWeight: '700', lineHeight: 36 },
  heroAction: { padding: 12, borderRadius: 10 },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, alignItems: 'center' },
  card: { padding: 14, borderRadius: 10, gap: 8 },
  sourceCard: { padding: 12, borderRadius: 8, gap: 4 },
  biography: { fontSize: 14, lineHeight: 21 },
  inlineAction: { alignSelf: 'flex-start', paddingVertical: 2 },
  inlineActionText: { fontSize: 13, fontWeight: '600' },
  factGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  fact: { flexGrow: 1, flexBasis: 140, minWidth: 0, padding: 12, borderRadius: 10, gap: 2 },
  factLabel: { fontSize: 12, lineHeight: 16, fontWeight: '600', letterSpacing: 0.3, textTransform: 'uppercase' },
  factValue: { fontSize: 14, lineHeight: 20 },
  artwork: { width: '100%', overflow: 'hidden', justifyContent: 'center', alignItems: 'center' },
  artworkRounded: { borderRadius: 10 },
  artworkPlaceholder: { fontSize: 12, textAlign: 'center', paddingHorizontal: 12 },
  cardTitle: { fontSize: 14, fontWeight: '600', lineHeight: 20 },
  cardCopy: { fontSize: 12, lineHeight: 16 },
  cardMeta: { fontSize: 11, lineHeight: 15 },
cardMetaWrap: { overflow: 'hidden' },
  cornerChipText: { fontSize: 11, fontWeight: '600' },
  gallery: { gap: 10 },
  galleryPreview: { aspectRatio: 16 / 9, borderRadius: 10, overflow: 'hidden', position: 'relative' },
  fill: { flex: 1 },
  galleryEmpty: { alignItems: 'center', justifyContent: 'center' },
  counterChip: { position: 'absolute', top: 8, left: 8, borderRadius: 6, paddingHorizontal: 8, paddingVertical: 3 },
  galleryControls: { position: 'absolute', top: 8, right: 8, flexDirection: 'row', gap: 6 },
  roundButton: { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center' },
  roundGlyph: { fontSize: 16, fontWeight: '600' },
  arrowButton: { position: 'absolute', top: '50%', width: 36, height: 36, borderRadius: 18,
    alignItems: 'center', justifyContent: 'center', marginTop: -18 },
  arrowLeft: { left: 8 },
  arrowRight: { right: 8 },
  arrowGlyph: { fontSize: 24, lineHeight: 26, fontWeight: '600' },
  playOverlay: { ...StyleSheet.absoluteFillObject, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(0, 0, 0, 0.3)' },
  playButton: { width: 56, height: 56, borderRadius: 28, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(0, 0, 0, 0.65)' },
  playGlyph: { color: '#ffffff', fontSize: 20, marginLeft: 3 },
  thumbRow: { gap: 8, paddingRight: 8 },
  thumb: { width: 104, aspectRatio: 16 / 9, borderRadius: 8, borderWidth: 2, overflow: 'hidden', position: 'relative' },
  thumbPlay: { ...StyleSheet.absoluteFillObject, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(0, 0, 0, 0.3)' },
  thumbPlayGlyph: { color: '#ffffff', fontSize: 14 },
  thumbCaption: { position: 'absolute', bottom: 3, left: 0, right: 0, textAlign: 'center',
    fontSize: 10, fontWeight: '600', color: '#ffffff' },
  lightbox: { flex: 1, padding: 16, gap: 12 },
  lightboxTop: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  lightboxCount: { fontSize: 13, fontWeight: '600' },
  lightboxBody: { flex: 1, position: 'relative' },
  lightboxControls: { flexDirection: 'row', justifyContent: 'center', gap: 16, paddingBottom: 8 },
  extras: { gap: 24 },
  extraSection: { gap: 10 },
  extraHeading: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  extraTitle: { fontSize: 17, fontWeight: '600' },
  lengthGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  lengthCard: { flexGrow: 1, flexBasis: 150, minWidth: 0, flexDirection: 'row', alignItems: 'center', gap: 12, padding: 14, borderRadius: 10 },
  lengthGlyph: { fontSize: 22 },
  lengthCopy: { flex: 1, minWidth: 0, gap: 1 },
  lengthEnd: { alignItems: 'flex-end', flexShrink: 1 },
  lengthValue: { fontSize: 18, fontWeight: '700' },
  readingRow: { flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', gap: 12 },
  readingGroup: { gap: 6, marginTop: 4 },
  readingItem: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 3 },
});
