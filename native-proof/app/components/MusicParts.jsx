import { Modal, ModalCloseButton } from '../../../frontend/ui/Modal';
import React, { useEffect, useState } from 'react';
import {
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  useWindowDimensions,
} from 'react-native';
import { Badge } from '../../../frontend/ui/Badge';
import { Button } from '../../../frontend/ui/Button';
import { DateTimePicker } from '../../../frontend/ui/DateTimePicker';
import { MediaCard } from '../../../frontend/ui/MediaCard';
import { MarkdownNotes } from '../../../frontend/ui/MarkdownNotes';
import { MarkdownPreview } from '../../../frontend/ui/MarkdownPreview';
import { MusicAlbumGrid } from '../../../frontend/ui/MusicAlbumCard';
import { MusicRelationCard } from '../../../frontend/ui/MusicRelationCard';
import { ProgressBar } from '../../../frontend/ui/ProgressBar';
import { RatingChip } from '../../../frontend/ui/RatingChip';
import { RatingStars } from '../../../frontend/ui/RatingStars';
import { FormError, FormTextField } from '../../../frontend/ui/MediaCardFormControls';
import {
  dateTimePalette,
  mediaCardPalette,
  palette,
  progressDetailPalette,
  radius,
  ratingPalette,
  spacing,
} from '../theme';
import { actionIcons } from '../../../frontend/ui/actionIcons';

// The date picker's quick actions always reflect the device clock.
function quickActionDate(action, now = new Date()) {
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  const date = `${now.getFullYear()}-${month}-${day}`;
  if (action !== 'just-finished') return date;
  const hours = String(now.getHours()).padStart(2, '0');
  const minutes = String(now.getMinutes()).padStart(2, '0');
  return `${date}T${hours}:${minutes}`;
}

// Django's "N j, Y" month names, as the web prints them.
const MONTHS = ['Jan.', 'Feb.', 'March', 'April', 'May', 'June', 'July',
  'Aug.', 'Sept.', 'Oct.', 'Nov.', 'Dec.'];

export const STATUS_OPTIONS = ['Planning', 'In progress', 'Paused', 'Completed', 'Dropped'];

const STATUS_COLORS = {
  Completed: palette.success,
  'In progress': palette.accent,
  Paused: palette.warning,
  Planning: palette.link,
  Dropped: palette.danger,
};

const statusPalette = STATUS_OPTIONS.reduce((result, option) => {
  result[option] = { color: palette.onAccentStrong, backgroundColor: STATUS_COLORS[option] };
  return result;
}, {});

const outlinePalette = {
  outline: { color: palette.textSecondary, borderColor: palette.surfaceMuted, borderWidth: 1 },
};

const markdownPalette = {
  background: palette.background,
  surface: palette.surface,
  surfaceStrong: palette.surfaceStrong,
  border: palette.border,
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  accent: palette.accent,
  link: palette.accent,
  danger: palette.danger,
  codeBackground: palette.background,
  codeText: palette.text,
};

const markdownLabels = {
  write: 'Write',
  preview: 'Preview',
  hint: 'Markdown supported',
  heading: 'Heading',
  bold: 'Bold',
  italic: 'Italic',
  code: 'Code',
  link: 'Link',
  quote: 'Quote',
  bulletedList: 'Bulleted list',
  numberedList: 'Numbered list',
  emptyPreview: 'Nothing to preview yet.',
};

export const dateTimeLabels = {
  field: 'Listen date',
  notSet: 'Not set',
  openPicker: 'Open date picker',
  picker: 'Choose date',
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

const quickDateActions = [
  { id: 'today', label: 'Today' },
  { id: 'just-finished', label: 'Just Finished' },
];

export function star(lit, size = 20) {
  return <Text style={[styles.star, { fontSize: size, lineHeight: size, color: lit ? ratingPalette.lit : ratingPalette.unlit }]}>★</Text>;
}

export function dateLabel(value) {
  const [year, month, day] = String(value || '').split('-').map(Number);
  if (!year || !month || !day) return value || 'No date';
  return `${MONTHS[month - 1]} ${day}, ${year}`;
}

export function timeLabel(value) {
  const [hourText, minuteText] = String(value || '00:00').split(':');
  const hour = Number(hourText);
  const suffix = hour >= 12 ? 'PM' : 'AM';
  const shown = hour % 12 || 12;
  return `${shown}:${String(minuteText || '00').padStart(2, '0')} ${suffix}`;
}

export function listenDate(entry) {
  return `${dateLabel(entry.date)} · ${timeLabel(entry.time)}`;
}

function durationLabel(minutes) {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (!hours) return `${rest}m`;
  return rest ? `${hours}h ${rest}m` : `${hours}h`;
}

function actionGroup(title, items) {
  return { title, items, ordering: null, clickable: true };
}

function countLabel(count, singular, plural) {
  return count === 1 ? `1 ${singular}` : `${count} ${plural}`;
}

export function FilterChips({ options, value, onChange, label }) {
  return <View role="radiogroup" accessibilityLabel={label} style={styles.chipRow}>
    {options.map(option => {
      const selected = option.value === value;
      return <Pressable key={option.value}
        accessibilityRole="radio"
        accessibilityState={{ selected }}
        accessibilityLabel={option.count == null ? option.label : `${option.label}, ${option.count}`}
        onPress={() => onChange(option.value)}
        style={({ pressed }) => [styles.filterChip, selected && styles.filterChipActive, pressed && styles.filterChipPressed]}>
        <Text style={[styles.filterChipText, selected && styles.filterChipTextActive]}>
          {option.label}{option.count == null ? '' : ` ${option.count}`}
        </Text>
      </Pressable>;
    })}
  </View>;
}

export function SectionHeading({ title, meta, copy }) {
  return <View style={styles.sectionHeading}>
    <View style={styles.sectionTitleRow}>
      <Text role="heading" aria-level={2} style={styles.sectionTitle}>{title}</Text>
      {meta ? <Text style={styles.sectionMeta}>{meta}</Text> : null}
    </View>
    {copy ? <Text style={styles.sectionCopy}>{copy}</Text> : null}
  </View>;
}

export function StatCard({ label, value }) {
  return <View style={styles.statCard}>
    <Text style={styles.statLabel}>{label}</Text>
    <Text style={styles.statValue}>{value}</Text>
  </View>;
}

export function FactRow({ label, value }) {
  return <View style={styles.factRow}>
    <Text style={styles.factLabel}>{label}</Text>
    <Text style={styles.factValue}>{value}</Text>
  </View>;
}

export function ScoreChip({ value, onSelect, scaleMax = 10, label = 'Your score' }) {
  const [open, setOpen] = useState(false);
  return <RatingChip
    value={value}
    scaleMax={scaleMax}
    displayValue={value == null ? null : String(value)}
    cardDisplayValue={value == null ? null : `${value}`}
    layout="pill"
    labels={{ yourScore: label, rate: 'Rate', close: 'Close', addRating: 'Add rating', editRating: 'Edit rating' }}
    renderStar={star}
    palette={ratingPalette}
    open={open}
    onOpenChange={setOpen}
    onSelect={onSelect} />;
}

export function MusicBrainzScore({ rating, votes }) {
  if (rating == null) return null;
  return <View style={styles.mbScore}>
    <View style={styles.mbBadge}><Text style={styles.mbBadgeText}>MB</Text></View>
    <Text style={styles.mbValue}>{Number(rating).toFixed(1)}</Text>
    <Text style={styles.mbDivider}>|</Text>
    <Text style={styles.mbVotes}>{countLabel(votes, 'vote', 'votes')}</Text>
  </View>;
}

export function CoverArt({ image, title, shape = 'square', width = 200 }) {
  const [failed, setFailed] = useState(false);
  const aspect = shape === 'poster' ? 2 / 3 : shape === 'landscape' ? 16 / 9 : 1;
  useEffect(() => { setFailed(false); }, [image]);
  return <View style={[styles.cover, { width, aspectRatio: aspect }]}>
    {image && !failed
      ? <Image source={{ uri: image }} style={StyleSheet.absoluteFill} resizeMode="cover"
        accessible={false} accessibilityElementsHidden importantForAccessibility="no-hide-descendants"
        onError={() => setFailed(true)} />
      : <View style={styles.coverFallback}>
        <Text style={styles.coverGlyph}>♪</Text>
        <Text numberOfLines={2} style={styles.coverFallbackText}>{title}</Text>
      </View>}
  </View>;
}

export function MusicHero({ image, title, shape = 'square', eyebrow, subtitle, children }) {
  const { width } = useWindowDimensions();
  const stacked = width < 640;
  return <View style={[styles.hero, stacked && styles.heroStacked]}>
    <CoverArt image={image} title={title} shape={shape} width={stacked ? 168 : 208} />
    <View style={styles.heroBody}>
      {eyebrow ? <Text style={styles.heroEyebrow}>{eyebrow}</Text> : null}
      <Text role="heading" aria-level={1} style={[styles.heroTitle, stacked && styles.heroTitleStacked]}>{title}</Text>
      {subtitle ? <Text style={styles.heroSubtitle}>{subtitle}</Text> : null}
      {children}
    </View>
  </View>;
}

export function BadgeRow({ labels, status }) {
  return <View style={styles.badgeRow}>
    {status ? <Badge label={status} size="sm" tone={status} palette={statusPalette} /> : null}
    {labels.map(label => <Badge key={label} label={label} size="tag" tone="outline" palette={outlinePalette} />)}
  </View>;
}

export function PrimaryActions({ children }) {
  return <View style={styles.primaryActions}>{children}</View>;
}

export function MusicCardGrid({ items, renderItem, minWidth = 110, maxWidth = 178 }) {
  const { width } = useWindowDimensions();
  const columns = width >= 900 ? 6 : width >= 720 ? 4 : width >= 520 ? 3 : 2;
  const cardWidth = Math.floor(Math.min(maxWidth,
    Math.max(minWidth, (width - spacing.lg * 2 - (columns - 1) * spacing.md) / columns)));
  return <View style={styles.cardGrid}>
    {items.map((item, index) => renderItem(item, cardWidth, index))}
  </View>;
}

function MusicRatingPicker({ value, label, scaleMax, palette: colors, onSelect }) {
  return <RatingStars scaleMax={scaleMax} value={value} label={label} onSelect={onSelect}
    palette={colors} renderStar={lit => <Text style={[styles.star, {
      color: lit ? colors.lit : colors.unlit,
    }]}>★</Text>} />;
}


function trackActions() {
  return actionGroup('Track actions', [
    { kind: 'action', key: 'listen', title: 'Add listen', icon: actionIcons.listAdd, tone: 'indigo' },
    { kind: 'action', key: 'notes', title: 'Track notes', icon: actionIcons.edit, tone: 'surface' },
    { kind: 'action', key: 'history', title: 'View your activity history', icon: actionIcons.history, tone: 'amber' },
  ]);
}

function episodeActions() {
  return actionGroup('Episode actions', [
    { kind: 'action', key: 'play', title: 'Add play', icon: actionIcons.listAdd, tone: 'indigo' },
    { kind: 'action', key: 'notes', title: 'Episode notes', icon: actionIcons.edit, tone: 'surface' },
    { kind: 'action', key: 'history', title: 'View your activity history', icon: actionIcons.history, tone: 'amber' },
  ]);
}

export function TrackRow({ track, onOpen, onAction, onRate }) {
  const listens = track.playCount || 0;
  const last = track.lastPlayed;
  const collected = track.codec ? [{ text: `Collected: ${track.codec}`, muted: true }] : [];
  const model = {
    layout: 'row',
    mediaType: 'music',
    title: track.title,
    image: { src: track.image || '', fallback: '', source: 'primary' },
    altTitle: null,
    statusChip: null,
    lines: [
      {
        join: 'dot',
        parts: [
          { text: `Track ${track.number}${track.disc > 1 ? ` (Disc ${track.disc})` : ''}` },
          ...(track.duration ? [{ text: track.duration, muted: true }] : []),
        ],
      },
      ...(listens || collected.length ? [{
        join: 'dot',
        parts: listens
          ? [
            { text: last ? `Last listened: ${dateLabel(last.date)}` : 'Listened', muted: true },
            ...(listens > 1 ? [{ text: `Listened ${listens} times`, muted: true }] : []),
            ...collected,
          ]
          : collected,
      }] : []),
    ],
    rating: {
      label: track.score == null ? null : String(track.score),
      value: track.score,
      scaleMax: 10,
      rateLabel: 'Rate',
    },
    // Scores write to the caller's Music row; without one there is nothing to
    // rate yet, so the control stays read-only like an unrated card.
    ratingEditable: track.musicId != null,
    actions: trackActions(),
  };
  return <MediaCard model={model}
    labels={{ rate: 'Rate', close: 'Close' }}
    palette={mediaCardPalette}
    onOpen={() => onOpen?.(track)}
    onAction={action => onAction?.(action.key, track)}
    onRate={score => onRate?.(track, score)}
    renderRating={MusicRatingPicker} />;
}

export function EpisodeRow({ episode, showImage, onOpen, onAction, onRate }) {
  const state = episode.inProgress ? 'In progress' : episode.played ? 'Played' : 'Unplayed';
  const model = {
    layout: 'row',
    mediaType: 'podcast',
    title: episode.title,
    image: { src: showImage, fallback: '', source: 'primary' },
    altTitle: null,
    statusChip: null,
    lines: [
      {
        join: 'dot',
        parts: [
          { text: `Episode ${episode.number}` },
          ...(episode.published ? [{ text: dateLabel(episode.published), muted: true }] : []),
          ...(episode.duration ? [{ text: episode.duration, muted: true }] : []),
        ],
      },
      {
        join: 'dot',
        parts: [
          { text: state, muted: true },
          ...(episode.inProgress && episode.progressLabel
            ? [{ text: episode.progressLabel, muted: true }]
            : []),
        ],
      },
    ],
    rating: {
      label: episode.score == null ? null : String(episode.score),
      value: episode.score,
      scaleMax: 10,
      rateLabel: 'Rate',
    },
    // An episode can be scored once it has a tracked play row.
    ratingEditable: Boolean(episode.episodeId && onRate && (episode.played || episode.inProgress || episode.score != null)),
    actions: episodeActions(),
  };
  return <MediaCard model={model}
    labels={{ rate: 'Rate', close: 'Close' }}
    palette={mediaCardPalette}
    onOpen={() => onOpen?.(episode)}
    onAction={action => onAction?.(action.key, episode)}
    onRate={score => onRate?.(episode, score)}
    renderRating={MusicRatingPicker} />;
}

// "Played 12 times • Nov. 5, 2026 - Nov. 8, 2026", as the web subtitle prints it.
function activityLine(plays, first, last) {
  const played = plays ? (plays === 1 ? 'Played once' : `Played ${plays} times`) : '';
  const range = first && last && first !== last
    ? `${dateLabel(first)} - ${dateLabel(last)}`
    : dateLabel(first || last || '');
  return [played, first || last ? range : ''].filter(Boolean).join(' \u2022 ');
}

function collectionValue(count, total) {
  const percent = total ? Math.round((count / total) * 100) : 0;
  return `${count}/${total} \u2022 ${percent}%`;
}

export function ArtistPage({ artist, albums, onOpenAlbum, onTrack, onHistory, onRate, onSyncMembers }) {
  const origin = artist.origin || '';
  const formed = artist.formed || '';
  const collection = artist.collection || {};
  const mbRating = artist.musicbrainz?.rating ?? null;
  const mbVotes = artist.musicbrainz?.votes ?? null;
  return <View style={styles.page}>
    <MusicHero image={artist.image} title={artist.name} shape="poster"
      eyebrow={artist.type}
      subtitle={[origin, formed ? `Formed ${formed}` : ''].filter(Boolean).join(' · ')}>
      {activityLine(artist.totalPlays, artist.firstListened, artist.lastListened)
        ? <Text style={styles.bio}>{activityLine(artist.totalPlays, artist.firstListened, artist.lastListened)}</Text>
        : null}
      <BadgeRow labels={artist.genres || []} status={artist.status} />
      <View style={styles.scoreRow}>
        <MusicBrainzScore rating={mbRating} votes={mbVotes} />
        <ScoreChip value={artist.score} onSelect={onRate} />
      </View>
      <PrimaryActions>
        <Button label={artist.status || 'Add to Library'} onPress={onTrack} />
        <Button label="Activity history" tone="surface" onPress={onHistory} />
        {onSyncMembers ? <Button label="Sync members" tone="surface" onPress={onSyncMembers} /> : null}
      </PrimaryActions>
      {artist.bio ? <Text style={styles.bio}>{artist.bio}</Text> : null}
    </MusicHero>

    <View style={styles.panel}>
      <SectionHeading title="Details" />
      {artist.type ? <FactRow label="Type" value={artist.type} /> : null}
      {origin ? <FactRow label="Origin" value={origin} /> : null}
      {formed ? <FactRow label="Formed" value={formed} /> : null}
      <FactRow label="Releases" value={String(albums.length)} />
      {artist.totalPlays != null ? <FactRow label="Plays" value={String(artist.totalPlays)} /> : null}
      {collection.albums != null && collection.totalAlbums != null
        ? <FactRow label="Collected albums" value={collectionValue(collection.albums, collection.totalAlbums)} />
        : null}
      {collection.tracks != null && collection.totalTracks != null
        ? <FactRow label="Collected tracks" value={collectionValue(collection.tracks, collection.totalTracks)} />
        : null}
    </View>

    {(artist.relations?.members || []).length
      ? <View style={styles.section}>
        <SectionHeading title="Members" meta={String(artist.relations.members.length)} />
        <MusicCardGrid items={artist.relations.members}
          renderItem={(relation, width) => <MusicRelationCard key={relation.id} relation={relation} width={width} />} />
      </View>
      : null}

    {(artist.relations?.alsoIn || []).length
      ? <View style={styles.section}>
        <SectionHeading title="Also In" meta={String(artist.relations.alsoIn.length)} />
        <MusicCardGrid items={artist.relations.alsoIn}
          renderItem={(relation, width) => <MusicRelationCard key={relation.id} relation={relation} width={width} />} />
      </View>
      : null}

    <View style={styles.section}>
      <SectionHeading title="Discography" meta={countLabel(albums.length, 'release', 'releases')} />
      {(artist.discography || []).map(group => <View key={group.label} style={styles.group}>
        <View style={styles.groupHeading}>
          <Text style={styles.groupTitle}>{group.label}</Text>
          <Text style={styles.groupCount}>{countLabel(group.albums.length, 'release', 'releases')}</Text>
        </View>
        <MusicAlbumGrid albums={group.albums}
          onOpen={album => onOpenAlbum(album)} />
      </View>)}
    </View>
  </View>;
}

export function AlbumPage({ album, onBack, onOpenTrack, onTrack, onHistory, onRate, onAction, onTrackRate, onSyncMetadata, onChooseRelease }) {
  const subtitle = [album.artistName, album.year].filter(Boolean).join(' · ');
  return <View style={styles.page}>
    <View style={styles.inlineNav}>
      <Button label="Back to artist" tone="surface" onPress={onBack} />
    </View>
    <MusicHero image={album.image} title={album.title} shape="square"
      eyebrow={album.releaseType}
      subtitle={subtitle}>
      {album.totalTracks
        ? <Text style={styles.bio}>{[`Progress: ${album.libraryTracks}/${album.totalTracks}`,
          activityLine(0, album.firstListened, album.lastListened)].filter(Boolean).join(' \u2022 ')}</Text>
        : null}
      <BadgeRow labels={album.genres || []} status={null} />
      <View style={styles.scoreRow}>
        <ScoreChip value={album.score} onSelect={onRate} />
        {album.format ? <Badge label={album.format} size="sm" tone="outline" palette={outlinePalette} /> : null}
      </View>
      <PrimaryActions>
        <Button label={album.status || 'Add to Library'} onPress={onTrack} />
        <Button label="Activity history" tone="surface" onPress={onHistory} />
        {onSyncMetadata ? <Button label="Sync metadata" tone="surface" onPress={onSyncMetadata} /> : null}
        {onChooseRelease ? <Button label="Choose release" tone="surface" onPress={onChooseRelease} /> : null}
      </PrimaryActions>
    </MusicHero>

    <View style={styles.panel}>
      <SectionHeading title="Details" />
      {album.format ? <FactRow label="Format" value={album.format} /> : null}
      {album.releaseDate ? <FactRow label="Release date" value={dateLabel(album.releaseDate)} /> : null}
      <FactRow label="Tracks" value={String(album.tracks.length)} />
      {album.runtime ? <FactRow label="Total runtime" value={album.runtime} /> : null}
      {album.plays != null ? <FactRow label="Plays" value={String(album.plays)} /> : null}
    </View>

    {album.firstListened || album.lastListened || album.libraryTracks
      ? <View style={styles.panel}>
        <SectionHeading title="Your History" />
        {album.firstListened ? <FactRow label="First listened:" value={dateLabel(album.firstListened)} /> : null}
        {album.lastListened ? <FactRow label="Last listened:" value={dateLabel(album.lastListened)} /> : null}
        <FactRow label="Progress:" value={`${album.libraryTracks} / ${album.totalTracks}`} />
      </View>
      : null}

    <View style={styles.section}>
      <SectionHeading title="Tracks" meta={countLabel(album.tracks.length, 'track', 'tracks')}
        copy="Tap a track for its notes, score and play history. The action row records another listen and opens notes or history." />
      <View style={styles.rowList}>
        {album.tracks.map(track => <TrackRow key={track.id} track={{ ...track, image: album.image }}
          onOpen={() => onOpenTrack(track)}
          onAction={(key, target) => onAction(key, album, target)}
          onRate={onTrackRate} />)}
      </View>
    </View>
  </View>;
}

export function TrackPage({ album, track, onBack, onRate, onAddListen, onOpenNotes, onSaveNotes, onDeleteListen, onOpenHistory }) {
  const [scoreOpen, setScoreOpen] = useState(false);
  const [notes, setNotes] = useState(track.notes);
  const [saved, setSaved] = useState('');
  useEffect(() => {
    setNotes(track.notes);
  }, [track.id, track.notes]);
  useEffect(() => {
    setSaved('');
  }, [track.id]);
  const listens = track.listens || [];
  const playCount = track.playCount || listens.length;
  const lastPlayed = track.lastPlayed;
  return <View style={styles.page}>
    <View style={styles.inlineNav}>
      <Button label="Back to album" tone="surface" onPress={onBack} />
    </View>
    <MusicHero image={album.image} title={track.title} shape="square"
      eyebrow={`Track ${track.number} · ${album.title}`}
      subtitle={[album.artistName, track.duration].filter(Boolean).join(' · ')}>
      <BadgeRow labels={[`Track ${track.number}`, ...(track.duration ? [track.duration] : [])]} status={null} />
      <View style={styles.scoreRow}>
        <RatingChip value={track.score} scaleMax={10}
          displayValue={track.score == null ? null : String(track.score)}
          cardDisplayValue={track.score == null ? null : String(track.score)}
          labels={{ yourScore: 'Your score', rate: 'Rate', close: 'Close', addRating: 'Add rating', editRating: 'Edit rating' }}
          renderStar={star} palette={ratingPalette} open={scoreOpen} onOpenChange={setScoreOpen}
          onSelect={onRate} />
        <Text style={styles.metaText}>{countLabel(playCount, 'listen', 'listens')}</Text>
      </View>
      <PrimaryActions>
        <Button label="Add listen" onPress={onAddListen} />
        <Button label="Notes" tone="surface" onPress={onOpenNotes} />
        <Button label="Activity history" tone="surface" onPress={onOpenHistory} />
      </PrimaryActions>
    </MusicHero>

    <View style={styles.panel}>
      <SectionHeading title="Notes" copy="Private notes stay attached to this track and never create a listen." />
      <MarkdownNotes
        value={notes}
        onChangeText={value => { setNotes(value); setSaved(''); }}
        label="Track notes"
        labelHidden
        hint="Markdown supported"
        placeholder="What do you want to remember about this track?"
        accessibilityLabel="Track notes"
        labels={markdownLabels}
        palette={markdownPalette}
        Preview={MarkdownPreview} />
      <View style={styles.inlineEnd}>
        {saved ? <Text style={styles.savedText}>{saved}</Text> : null}
        <Button label="Save notes" onPress={() => { onSaveNotes(notes); setSaved('Notes saved'); }} />
      </View>
    </View>

    <View style={styles.section}>
      <SectionHeading title="Play history" meta={countLabel(playCount, 'listen', 'listens')} />
      {listens.length ? <View style={styles.rowList}>
        {listens.map((entry, index) => <View key={entry.id} style={styles.historyRow}>
          <View style={styles.historyCopy}>
            <Text style={styles.historyDate}>{listenDate(entry)}</Text>
            <Text style={styles.historyMeta}>{index === 0 ? 'Latest listen' : 'Repeat listen'}</Text>
          </View>
          <Button label="Delete" tone="ghost-danger" onPress={() => onDeleteListen(entry.id)} />
        </View>)}
      </View> : <View style={styles.rowList}>
        <View style={styles.historyRow}>
          <View style={styles.historyCopy}>
            <Text style={styles.historyDate}>
              {lastPlayed ? `Last listened ${dateLabel(lastPlayed.date)}` : 'Not listened yet'}
            </Text>
            <Text style={styles.historyMeta}>{countLabel(playCount, 'listen', 'listens')} recorded</Text>
          </View>
        </View>
      </View>}
    </View>
  </View>;
}

export function ShowPage({ show, episodes, episodeTotal, episodeFilter, onFilter, onLoadMore, hasMore,
  loadingEpisodes, onTrack, onHistory, onRate, onAction, onVisitWebsite, onRateEpisode, onManageEpisodes }) {
  const total = episodeTotal != null ? episodeTotal : episodes.length;
  const listened = episodes.filter(episode => episode.played && !episode.inProgress).length;
  const inProgress = episodes.filter(episode => episode.inProgress).length;
  const minutes = episodes.reduce((totalMinutes, episode) => (
    totalMinutes + (episode.played ? (episode.durationSeconds || 0) / 60 : 0)
  ), 0);
  const filtered = episodes.filter(episode => {
    if (episodeFilter === 'played') return episode.played && !episode.inProgress;
    if (episodeFilter === 'in_progress') return episode.inProgress;
    if (episodeFilter === 'unplayed') return !episode.played;
    return true;
  });
  // The web counts the show's play rows for "Progress: N/M".
  const progressListened = show.listenedCount ?? listened;
  const percent = total ? Math.round((progressListened / total) * 100) : 0;
  const filterOptions = [
    { value: 'all', label: 'All', count: total },
    { value: 'unplayed', label: 'Unplayed', count: Math.max(0, total - listened - inProgress) },
    { value: 'in_progress', label: 'In progress', count: inProgress },
    { value: 'played', label: 'Played', count: listened },
  ];
  return <View style={styles.page}>
    <MusicHero image={show.image} title={show.title} shape="square"
      eyebrow="Podcast"
      subtitle={show.author ? `by ${show.author}` : ''}>
      <Text style={styles.bio}>{`Progress: ${progressListened}/${total}`}</Text>
      <BadgeRow labels={show.genres || []} status={show.status} />
      <View style={styles.scoreRow}>
        <ScoreChip value={show.score} onSelect={onRate} />
        <Badge label={`${total} episodes`} size="sm" tone="outline" palette={outlinePalette} />
      </View>
      <PrimaryActions>
        <Button label={show.status || 'Add to Library'} onPress={onTrack} />
        <Button label="Activity history" tone="surface" onPress={onHistory} />
        {onVisitWebsite ? <Button label="Show website" tone="surface" onPress={onVisitWebsite} /> : null}
        {onManageEpisodes ? <Button label="Manage episodes" tone="surface" onPress={onManageEpisodes} /> : null}
      </PrimaryActions>
      {show.description ? <Text style={styles.bio}>{show.description}</Text> : null}
    </MusicHero>

    <View style={styles.statsRow}>
      <StatCard label="Episodes" value={String(total)} />
      <StatCard label="Listened" value={String(listened)} />
      <StatCard label="In progress" value={String(inProgress)} />
      <StatCard label="Time" value={durationLabel(Math.round(minutes))} />
    </View>

    <View style={styles.progressPanel}>
      <View style={styles.progressHeader}>
        <Text style={styles.progressLabel}>Show progress</Text>
        <Text style={styles.progressValue}>{percent}%</Text>
      </View>
      <ProgressBar percent={percent} height={8} palette={progressDetailPalette} label={`${percent}% of episodes played`} />
      <Text style={styles.progressCopy}>{progressListened} of {total} episodes played · {Math.max(0, total - listened - inProgress)} unplayed</Text>
    </View>

    <View style={styles.section}>
      <SectionHeading title="Episodes" meta={`${episodes.length} of ${total} loaded`}
        copy="Filter the feed, load older pages and record plays. Each play is dated and kept in the episode history." />
      <FilterChips label="Filter episodes" options={filterOptions} value={episodeFilter} onChange={onFilter} />
      <View style={styles.rowList}>
        {filtered.map(episode => <EpisodeRow key={episode.id} episode={episode} showImage={show.image}
          onOpen={() => onAction('play', episode)}
          onRate={onRateEpisode}
          onAction={(key, target) => onAction(key, target)} />)}
      </View>
      {!filtered.length ? <View style={styles.emptyPanel}>
        <Text style={styles.emptyText}>No episodes match this filter.</Text>
      </View> : null}
      {hasMore
        ? <View style={styles.loadMore}>
          <Button label={loadingEpisodes ? 'Loading…' : `Load more (${total - episodes.length} left)`}
            tone="surface" onPress={onLoadMore} />
        </View>
        : null}
    </View>
  </View>;
}

// Tracked artists, albums or shows: one tappable row each, with the loading,
// empty and error states the browse tabs share.
export function BrowseList({ rows, loading, error, emptyTitle, emptyCopy, onOpen, onRetry }) {
  if (loading) {
    return <View style={styles.emptyPanel}><Text style={styles.emptyText}>Loading…</Text></View>;
  }
  if (error) {
    return <View style={styles.emptyPanel}>
      <Text style={styles.emptyText}>{error}</Text>
      {onRetry ? <Button label="Try again" tone="surface" onPress={onRetry} /> : null}
    </View>;
  }
  if (!rows.length) {
    return <View style={styles.emptyPanel}>
      <Text style={styles.sectionTitle}>{emptyTitle}</Text>
      {emptyCopy ? <Text style={styles.emptyText}>{emptyCopy}</Text> : null}
    </View>;
  }
  return <View style={styles.rowList}>
    {rows.map(row => <Pressable key={row.key} accessibilityRole="button"
      accessibilityLabel={row.subtitle ? `${row.title}, ${row.subtitle}` : row.title}
      onPress={() => onOpen(row)}
      style={({ pressed }) => [styles.browseRow, pressed && styles.browsePressed]}>
      <CoverArt image={row.image} title={row.title} width={56} />
      <View style={styles.browseCopy}>
        <Text numberOfLines={2} style={styles.historyDate}>{row.title}</Text>
        {row.subtitle ? <Text numberOfLines={1} style={styles.historyMeta}>{row.subtitle}</Text> : null}
      </View>
      {row.status ? <Badge label={row.status} size="sm" palette={statusPalette} tone={row.status} /> : null}
    </Pressable>)}
  </View>;
}

// Releases (editions) of an album; picking one stores it for this account.
export function ReleasePickerModal({ open, title, state, onSelect, onClose }) {
  return <SheetModal open={open} title={title} subtitle="Choose the release whose tracklist to use" onClose={onClose}>
    {state.loading ? <Text style={styles.emptyText}>Loading releases…</Text> : null}
    {state.error ? <Text style={styles.emptyText}>{state.error}</Text> : null}
    {!state.loading && !state.error && !state.releases.length
      ? <Text style={styles.emptyText}>No releases found for this album.</Text> : null}
    {state.releases.map(release => {
      const selected = release.id === state.selectedId;
      return <Pressable key={release.id} accessibilityRole="button" accessibilityState={{ selected }}
        accessibilityLabel={release.title}
        onPress={() => onSelect(release)}
        style={({ pressed }) => [styles.browseRow, selected && styles.browseSelected, pressed && styles.browsePressed]}>
        <View style={styles.browseCopy}>
          <Text numberOfLines={2} style={styles.historyDate}>{release.title}</Text>
          {release.detail ? <Text style={styles.historyMeta}>{release.detail}</Text> : null}
        </View>
        {selected ? <Badge label="In use" size="sm" tone="outline" palette={outlinePalette} /> : null}
      </Pressable>;
    })}
  </SheetModal>;
}

const EMPTY_EPISODE = {
  title: '', description: '', episodeNumber: '', seasonNumber: '', published: '', duration: '', audioUrl: '', websiteUrl: '', imageUrl: '',
};

// Add, edit and delete the episodes of a manual show.
export function ManageEpisodesModal({ open, showTitle, state, onSave, onDelete, onClose }) {
  const [draft, setDraft] = useState(EMPTY_EPISODE);
  const [editingId, setEditingId] = useState(null);
  useEffect(() => {
    if (open) {
      setDraft(EMPTY_EPISODE);
      setEditingId(null);
    }
  }, [open]);
  const set = key => value => setDraft(current => ({ ...current, [key]: value }));
  function edit(episode) {
    setEditingId(episode.id);
    setDraft({ ...EMPTY_EPISODE, ...episode });
  }
  async function submit() {
    const saved = await onSave(editingId, draft);
    if (saved) {
      setDraft(EMPTY_EPISODE);
      setEditingId(null);
    }
  }
  return <SheetModal open={open} title="Manage episodes" subtitle={showTitle} onClose={onClose}>
    {state.loading ? <Text style={styles.emptyText}>Loading episodes…</Text> : null}
    {state.episodes.map(episode => <View key={episode.id} style={styles.historyRow}>
      <View style={styles.historyCopy}>
        <Text numberOfLines={2} style={styles.historyDate}>{episode.title}</Text>
        <Text style={styles.historyMeta}>
          {[episode.episodeNumber ? `Episode ${episode.episodeNumber}` : '', episode.published ? episode.published.slice(0, 10) : '']
            .filter(Boolean).join(' · ')}
        </Text>
      </View>
      <View style={styles.primaryActions}>
        <Button label="Edit" tone="surface" onPress={() => edit(episode)} />
        <Button label="Delete" tone="ghost-danger" onPress={() => onDelete(episode)} />
      </View>
    </View>)}
    {!state.loading && !state.episodes.length
      ? <Text style={styles.emptyText}>No episodes yet. Add the first one below.</Text> : null}
    <SectionHeading title={editingId ? 'Edit episode' : 'Add episode'} />
    <FormTextField label="Title" required value={draft.title} onChangeText={set('title')}
      error={state.errors.title} palette={palette} />
    <FormTextField label="Description" multiline value={draft.description} onChangeText={set('description')}
      error={state.errors.description} palette={palette} />
    <FormTextField label="Episode number" keyboardType="number-pad" value={draft.episodeNumber}
      onChangeText={set('episodeNumber')} error={state.errors.episode_number} palette={palette} />
    <FormTextField label="Season number" keyboardType="number-pad" value={draft.seasonNumber}
      onChangeText={set('seasonNumber')} error={state.errors.season_number} palette={palette} />
    <FormTextField label="Published" value={draft.published} placeholder="YYYY-MM-DDTHH:MM"
      onChangeText={set('published')} error={state.errors.published} palette={palette} />
    <FormTextField label="Duration" value={draft.duration} help="Minutes, mm:ss or h:mm:ss. Leave blank if unknown."
      onChangeText={set('duration')} error={state.errors.duration} palette={palette} />
    <FormTextField label="Audio URL" value={draft.audioUrl} onChangeText={set('audioUrl')}
      error={state.errors.audio_url} palette={palette} />
    <FormTextField label="Website URL" value={draft.websiteUrl} onChangeText={set('websiteUrl')}
      error={state.errors.website_url} palette={palette} />
    <FormTextField label="Image URL" value={draft.imageUrl} onChangeText={set('imageUrl')}
      error={state.errors.image} palette={palette} />
    <FormError message={state.errors.form} palette={palette} />
    <View style={styles.modalActions}>
      {editingId ? <Button label="Cancel edit" tone="surface" onPress={() => { setEditingId(null); setDraft(EMPTY_EPISODE); }} /> : null}
      <Button label={editingId ? 'Save episode' : 'Add episode'} busy={state.saving} disabled={state.saving || !draft.title.trim()} onPress={submit} />
    </View>
  </SheetModal>;
}

export function SheetModal({ open, title, subtitle, children, onClose }) {
  return <Modal visible={open} transparent animationType="fade" onRequestClose={onClose}>
    <View style={styles.modalRoot}>
      <Pressable accessibilityRole="button" accessibilityLabel="Close" onPress={onClose}
        style={[StyleSheet.absoluteFill, styles.modalBackdrop]} />
      <View accessibilityViewIsModal style={styles.modalSheet}>
        <View style={styles.modalHeader}>
          <View style={styles.modalHeading}>
            <Text role="heading" aria-level={2} style={styles.modalTitle}>{title}</Text>
            {subtitle ? <Text style={styles.modalSubtitle}>{subtitle}</Text> : null}
          </View>
          <ModalCloseButton accessibilityRole="button" accessibilityLabel="Close" onPress={onClose} style={styles.modalClose}>
            <Text style={styles.modalCloseText}>×</Text>
          </ModalCloseButton>
        </View>
        <ScrollView contentContainerStyle={styles.modalBody} keyboardShouldPersistTaps="handled">
          {children}
        </ScrollView>
      </View>
    </View>
  </Modal>;
}

export function DateEntryModal({ open, title, subtitle, value, onChange, onClose, onConfirm, confirmLabel = 'Save', suggestionDate = '' }) {
  return <SheetModal open={open} title={title} subtitle={subtitle} onClose={onClose}>
    <DateTimePicker
      value={value}
      onChange={onChange}
      trackTime={false}
      use12Hour={false}
      weekStart="monday"
      locale="en-US"
      labels={dateTimeLabels}
      quickActions={quickDateActions}
      suggestionDate={suggestionDate}
      suggestionLabel={suggestionDate ? 'Release date' : ''}
      onQuickAction={action => onChange(quickActionDate(action))}
      palette={dateTimePalette} />
    <View style={styles.modalActions}>
      <Button label="Cancel" tone="surface" onPress={onClose} />
      <Button label={confirmLabel} onPress={onConfirm} />
    </View>
  </SheetModal>;
}

export function TrackingModal({ open, title, subtitle, status, score, notes, onClose, onSave }) {
  const [draft, setDraft] = useState({ status, score, notes });
  useEffect(() => {
    if (open) setDraft({ status, score, notes });
  }, [open, status, score, notes]);
  return <SheetModal open={open} title={title} subtitle={subtitle} onClose={onClose}>
    <Text style={styles.fieldLabel}>Status</Text>
    <View style={styles.statusGrid}>
      {STATUS_OPTIONS.map(option => {
        const selected = draft.status === option;
        return <Pressable key={option}
          accessibilityRole="radio"
          accessibilityState={{ selected }}
          accessibilityLabel={option}
          onPress={() => setDraft(current => ({ ...current, status: option }))}
          style={({ pressed }) => [styles.statusOption, selected && {
            borderColor: STATUS_COLORS[option],
            backgroundColor: `${STATUS_COLORS[option]}22`,
          }, pressed && styles.filterChipPressed]}>
          <View style={[styles.statusDot, { backgroundColor: STATUS_COLORS[option] }]} />
          <Text style={[styles.statusOptionText, selected && { color: palette.text }]}>{option}</Text>
        </Pressable>;
      })}
    </View>
    <Text style={styles.fieldLabel}>Your score</Text>
    <RatingStars scaleMax={10} value={draft.score} label="Your score"
      palette={ratingPalette} renderStar={lit => star(lit, 28)}
      onSelect={value => setDraft(current => ({ ...current, score: value }))} />
    <Text style={styles.fieldLabel}>Notes</Text>
    <MarkdownNotes value={draft.notes}
      onChangeText={value => setDraft(current => ({ ...current, notes: value }))}
      label="Tracking notes"
      labelHidden
      hint="Markdown supported"
      placeholder="Add a private note"
      accessibilityLabel="Tracking notes"
      labels={markdownLabels}
      palette={markdownPalette}
      Preview={MarkdownPreview} />
    <View style={styles.modalActions}>
      <Button label="Cancel" tone="surface" onPress={onClose} />
      <Button label="Save" onPress={() => onSave(draft)} />
    </View>
  </SheetModal>;
}

export function NotesModal({ open, title, subtitle, value, error, onClose, onSave }) {
  const [draft, setDraft] = useState(value);
  useEffect(() => { if (open) setDraft(value); }, [open, value]);
  return <SheetModal open={open} title={title} subtitle={subtitle} onClose={onClose}>
    <MarkdownNotes
      value={draft}
      onChangeText={setDraft}
      label="Notes"
      hint="Markdown supported"
      placeholder="What do you want to remember?"
      error={error}
      labels={markdownLabels}
      palette={markdownPalette}
      Preview={MarkdownPreview} />
    <View style={styles.modalActions}>
      <Button label="Cancel" tone="surface" onPress={onClose} />
      <Button label="Save notes" onPress={() => onSave(draft)} />
    </View>
  </SheetModal>;
}

const styles = StyleSheet.create({
  page: { gap: spacing.xl },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  filterChip: { borderWidth: 1, borderColor: palette.border, borderRadius: radius.pill, paddingHorizontal: spacing.md, paddingVertical: 6 },
  filterChipActive: { borderColor: palette.accent, backgroundColor: palette.surfaceStrong },
  filterChipPressed: { opacity: 0.75 },
  filterChipText: { color: palette.textMuted, fontSize: 12, fontWeight: '600' },
  filterChipTextActive: { color: palette.text },
  sectionHeading: { gap: 2 },
  sectionTitleRow: { flexDirection: 'row', alignItems: 'baseline', gap: spacing.sm },
  sectionTitle: { color: palette.text, fontSize: 18, fontWeight: '700' },
  sectionMeta: { color: palette.textMuted, fontSize: 12, fontWeight: '600' },
  sectionCopy: { color: palette.textMuted, fontSize: 12, lineHeight: 17 },
  statCard: { flexGrow: 1, minWidth: 92, borderRadius: radius.md, borderWidth: 1, borderColor: palette.border, backgroundColor: palette.surface, padding: spacing.md, gap: 4 },
  statLabel: { color: palette.textMuted, fontSize: 10, fontWeight: '700', letterSpacing: 0.8, textTransform: 'uppercase' },
  statValue: { color: palette.text, fontSize: 20, fontWeight: '700' },
  factRow: { flexDirection: 'row', justifyContent: 'space-between', gap: spacing.md, borderBottomWidth: 1, borderBottomColor: palette.border, paddingVertical: spacing.sm },
  factLabel: { color: palette.textMuted, fontSize: 12, fontWeight: '600' },
  factValue: { color: palette.textSecondary, fontSize: 12, flexShrink: 1, textAlign: 'right' },
  star: { fontWeight: '600' },
  mbScore: { flexDirection: 'row', alignItems: 'center', gap: 6, borderRadius: radius.pill, borderWidth: 1, borderColor: palette.border, backgroundColor: palette.dangerSoft, paddingRight: spacing.md },
  mbBadge: { width: 30, height: 30, borderRadius: 15, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: palette.border, backgroundColor: palette.dangerSoft },
  mbBadgeText: { color: palette.text, fontSize: 9, fontWeight: '800', letterSpacing: 0.6 },
  mbValue: { color: palette.text, fontSize: 13, fontWeight: '700' },
  mbDivider: { color: palette.textMuted, fontSize: 13 },
  mbVotes: { color: palette.textSecondary, fontSize: 12 },
  cover: { borderRadius: radius.md, overflow: 'hidden', backgroundColor: palette.surfaceStrong },
  coverFallback: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 6, padding: spacing.md },
  coverGlyph: { color: palette.textMuted, fontSize: 36 },
  coverFallbackText: { color: palette.textMuted, fontSize: 12, textAlign: 'center' },
  hero: { flexDirection: 'row', gap: spacing.lg, alignItems: 'flex-start' },
  heroStacked: { flexDirection: 'column', alignItems: 'center' },
  heroBody: { flex: 1, minWidth: 0, gap: spacing.sm },
  heroEyebrow: { color: palette.accent, fontSize: 11, fontWeight: '700', letterSpacing: 0.8, textTransform: 'uppercase' },
  heroTitle: { color: palette.text, fontSize: 28, fontWeight: '700' },
  heroTitleStacked: { textAlign: 'center' },
  heroSubtitle: { color: palette.textMuted, fontSize: 13 },
  badgeRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, alignItems: 'center' },
  scoreRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, alignItems: 'center' },
  primaryActions: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  bio: { color: palette.textSecondary, fontSize: 13, lineHeight: 20 },
  panel: { borderWidth: 1, borderColor: palette.border, borderRadius: radius.md, backgroundColor: palette.surface, padding: spacing.lg, gap: spacing.xs },
  section: { gap: spacing.md },
  group: { gap: spacing.sm },
  groupHeading: { flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', gap: spacing.sm },
  groupTitle: { color: palette.textSecondary, fontSize: 15, fontWeight: '600' },
  groupCount: { color: palette.textMuted, fontSize: 11 },
  cardGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md },
  rowList: { gap: spacing.md },
  inlineNav: { flexDirection: 'row', justifyContent: 'flex-start' },
  inlineEnd: { flexDirection: 'row', alignItems: 'center', justifyContent: 'flex-end', gap: spacing.md },
  metaText: { color: palette.textMuted, fontSize: 12 },
  savedText: { color: palette.success, fontSize: 12 },
  historyRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.md, borderWidth: 1, borderColor: palette.border, borderRadius: radius.md, backgroundColor: palette.surface, padding: spacing.md },
  historyCopy: { gap: 2, flexShrink: 1 },
  historyDate: { color: palette.text, fontSize: 13, fontWeight: '600' },
  historyMeta: { color: palette.textMuted, fontSize: 11 },
  emptyPanel: { borderWidth: 1, borderColor: palette.border, borderRadius: radius.md, backgroundColor: palette.surface, padding: spacing.lg, alignItems: 'center' },
  emptyText: { color: palette.textMuted, fontSize: 13 },
  statsRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  progressPanel: { borderWidth: 1, borderColor: palette.border, borderRadius: radius.md, backgroundColor: palette.surface, padding: spacing.lg, gap: spacing.sm },
  progressHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.md },
  progressLabel: { color: palette.text, fontSize: 14, fontWeight: '600' },
  progressValue: { color: palette.text, fontSize: 14, fontWeight: '700' },
  progressCopy: { color: palette.textMuted, fontSize: 12 },
  browseRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, borderWidth: 1, borderColor: palette.border, borderRadius: radius.md, backgroundColor: palette.surface, padding: spacing.md },
  browseSelected: { borderColor: palette.accent },
  browsePressed: { opacity: 0.8 },
  browseCopy: { flex: 1, minWidth: 0, gap: 2 },
  loadMore: { flexDirection: 'row', justifyContent: 'center', paddingTop: spacing.sm },
  modalRoot: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: spacing.lg },
  modalBackdrop: { backgroundColor: palette.overlay },
  modalSheet: { width: '100%', maxWidth: 560, maxHeight: '88%', borderRadius: radius.lg, borderWidth: 1, borderColor: palette.border, backgroundColor: palette.background, overflow: 'hidden' },
  modalHeader: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.md, borderBottomWidth: 1, borderBottomColor: palette.border, paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  modalHeading: { flex: 1, gap: 2 },
  modalTitle: { color: palette.text, fontSize: 17, fontWeight: '700' },
  modalSubtitle: { color: palette.textMuted, fontSize: 12 },
  modalClose: { width: 32, height: 32, alignItems: 'center', justifyContent: 'center' },
  modalCloseText: { color: palette.textMuted, fontSize: 22, lineHeight: 24 },
  modalBody: { padding: spacing.lg, gap: spacing.md },
  modalActions: { flexDirection: 'row', justifyContent: 'flex-end', flexWrap: 'wrap', gap: spacing.sm },
  fieldLabel: { color: palette.textSecondary, fontSize: 12, fontWeight: '700', letterSpacing: 0.4, textTransform: 'uppercase' },
  statusGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  statusOption: { flexDirection: 'row', alignItems: 'center', gap: 6, borderWidth: 1, borderColor: palette.border, borderRadius: radius.pill, paddingHorizontal: spacing.md, paddingVertical: 6 },
  statusDot: { width: 8, height: 8, borderRadius: 4 },
  statusOptionText: { color: palette.textMuted, fontSize: 12, fontWeight: '600' },
});
