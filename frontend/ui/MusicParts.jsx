import React, { useEffect, useState } from 'react';
import { Image, Pressable, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { Button } from './Button';
import { Badge } from './Badge';
import { DetailMetadata } from './DetailSecondary';
import { DetailSynopsis } from './DetailComposition';
import { MusicAlbumGrid } from './MusicAlbumCard';
import { MusicRelationGrid } from './MusicRelationCard';

function fact(key, label, value) {
  return value == null || value === '' ? null : { key, label, values: [{ text: String(value) }] };
}

function count(value, singular, plural) {
  return `${value} ${value === 1 ? singular : plural}`;
}

function dates(first, last, formatDate) {
  return [first, last && last !== first ? last : null].filter(Boolean).map(formatDate).join(' - ');
}

function Section({ title, palette, children, large = false, action }) {
  return <View style={styles.section}>
    <View style={styles.headingRow}>
      <Text accessibilityRole="header" style={[styles.heading, large && styles.largeHeading, { color: palette.text }]}>{title}</Text>
      {action}
    </View>
    {children}
  </View>;
}

/** PWA music headers use the 768px breakpoint and a cover bounded to 250px. */
export function MusicDetailHero({ image, title, subtitle, onTitle, onSubtitle, palette, poster = false, coverAction, children }) {
  const { width } = useWindowDimensions();
  const compact = width < 768;
  const [failed, setFailed] = useState(false);
  useEffect(() => { setFailed(false); }, [image]);
  return <View style={[styles.hero, compact ? styles.heroCompact : styles.heroWide]}>
    <View style={[styles.coverColumn, compact && styles.coverCentered]}>
      <View style={[styles.cover, { aspectRatio: poster ? 2 / 3 : 1, backgroundColor: palette.surface }]}>
        {image && !failed ? <Image source={{ uri: image }} resizeMode="cover" style={StyleSheet.absoluteFill}
          accessibilityLabel={title} onError={() => setFailed(true)} />
          : <Text style={[styles.placeholder, { color: palette.textMuted }]}>♪</Text>}
      </View>
      {coverAction ? <View style={styles.coverAction}>{coverAction}</View> : null}
    </View>
    <View style={[styles.heroBody, !compact && styles.heroBodyWide]}>
      <Pressable disabled={!onTitle} onPress={onTitle} accessibilityRole={onTitle ? 'link' : 'header'}>
        <Text style={[styles.title, compact && styles.centered, { color: palette.text }]}>{title}</Text>
      </Pressable>
      {subtitle ? <Pressable disabled={!onSubtitle} onPress={onSubtitle} accessibilityRole={onSubtitle ? 'link' : undefined}>
        <Text style={[styles.subtitle, compact && styles.centered, { color: palette.textMuted }]}>{subtitle}</Text>
      </Pressable> : null}
      {children}
    </View>
  </View>;
}

/** Presentation slots keep native dialogs, row actions and transport in the adapter. */
export function MusicDetailLayout({ sidebar, children }) {
  const { width } = useWindowDimensions();
  const wide = width >= 768;
  return <View style={[styles.layout, wide && styles.layoutWide]}>
    <View style={[styles.sidebar, wide && styles.sidebarWide]}>{sidebar}</View>
    <View style={[styles.content, wide && styles.contentWide]}>{children}</View>
  </View>;
}

function Actions({ children }) {
  return <View style={styles.actions}>{children}</View>;
}

function Notes({ value, palette, renderNotes, onOpenNotes }) {
  if (!value && !onOpenNotes) return null;
  return <Section title="Notes" palette={palette} action={onOpenNotes ? <Button label="Edit notes" tone="surface" onPress={onOpenNotes} /> : null}>
    {value ? renderNotes ? renderNotes(value) : <Text style={[styles.body, { color: palette.textSecondary }]}>{value}</Text> : null}
  </Section>;
}

function Genres({ values, palette }) {
  return values?.length ? <Section title="Genres" palette={palette}>
    <View style={styles.actions}>{values.map(value => <Badge key={value} label={value} size="tag" tone="outline"
      palette={{ outline: { color: palette.textSecondary, borderColor: palette.border, borderWidth: 1 } }} />)}</View>
  </Section> : null;
}

export function ArtistPage({ artist, albums = [], palette, cardPalette, formatDate, renderScore, renderProviderScore,
  renderNotes, onOpenAlbum, onOpenArtist, onTrack, onHistory, onRate, onSyncMembers, onOpenNotes }) {
  const collection = artist.collection || {};
  const facts = [fact('type', 'TYPE', artist.type), fact('origin', 'ORIGIN', artist.origin),
    fact('formed', artist.type === 'Group' ? 'FORMED' : 'BORN', artist.formed),
    fact('ended', artist.type === 'Group' ? 'DISBANDED' : 'DIED', artist.ended),
    fact('releases', 'RELEASES', artist.totalReleases ?? albums.length)].filter(Boolean);
  const collectionFacts = [
    collection.albums != null && collection.totalAlbums != null
      ? fact('albums', 'COLLECTED ALBUMS', `${collection.albums} / ${collection.totalAlbums}`) : null,
    collection.tracks != null && collection.totalTracks != null
      ? fact('tracks', 'COLLECTED TRACKS', `${collection.tracks} / ${collection.totalTracks}`) : null,
  ].filter(Boolean);
  const activity = [artist.totalPlays ? count(artist.totalPlays, 'play', 'plays') : '',
    dates(artist.firstListened, artist.lastListened, formatDate)].filter(Boolean).join(' • ');
  return <View>
    <MusicDetailHero image={artist.image} title={artist.name} poster palette={palette} subtitle={activity} onSubtitle={onHistory}>
      <View style={styles.scores}>
        {renderProviderScore?.(artist.musicbrainz?.rating, artist.musicbrainz?.votes)}
        {renderScore(artist.score, onRate)}
      </View>
      <Actions>
        <Button label={artist.status || 'Add to Library'} onPress={onTrack} />
        <Button label="Activity history" tone="surface" onPress={onHistory} />
        {onSyncMembers ? <Button label="Sync members" tone="surface" onPress={onSyncMembers} /> : null}
      </Actions>
      {artist.bio ? <DetailSynopsis model={{ synopsis: { text: artist.bio, previewLines: 3 } }} palette={palette} /> : null}
    </MusicDetailHero>
    <MusicDetailLayout sidebar={<>
      <DetailMetadata facts={facts} palette={palette} />
      <Genres values={artist.genres} palette={palette} />
      {collectionFacts.length ? <DetailMetadata title="Collection" facts={collectionFacts} palette={palette} /> : null}
    </>}>
      <Notes value={artist.notes} palette={palette} renderNotes={renderNotes} onOpenNotes={onOpenNotes} />
      {[['Members', artist.relations?.members], ['Also In', artist.relations?.alsoIn]].map(([title, relations]) => relations?.length
        ? <Section key={title} title={title} palette={palette}>
          <MusicRelationGrid relations={relations} palette={cardPalette} onOpen={onOpenArtist} />
        </Section> : null)}
      <Section title="Discography" palette={palette}>
        {(artist.discography || []).map(group => <View key={group.label} style={styles.section}>
          <Text accessibilityRole="header" style={[styles.groupHeading, { color: palette.text }]}>{group.label}</Text>
          <MusicAlbumGrid albums={group.albums} palette={cardPalette} onOpen={onOpenAlbum} />
        </View>)}
      </Section>
    </MusicDetailLayout>
  </View>;
}

export function AlbumPage({ album, palette, formatDate, renderScore, renderTrack, renderNotes,
  onBack, onOpenTrack, onTrack, onHistory, onRate, onAction, onTrackRate, onSyncMetadata, onChooseRelease, onOpenNotes }) {
  const facts = [fact('format', 'FORMAT', album.format), fact('released', 'RELEASE DATE', album.releaseDate ? formatDate(album.releaseDate) : ''),
    fact('tracks', 'TRACKS', album.totalTracks ?? album.tracks.length), fact('runtime', 'TOTAL RUNTIME', album.runtime)].filter(Boolean);
  const collectionFacts = album.libraryTracks != null && album.totalTracks != null
    ? [fact('tracks', 'COLLECTED TRACKS', `${album.libraryTracks} / ${album.totalTracks}`)] : [];
  const subtitle = [album.title, album.totalTracks != null ? `Progress: ${album.libraryTracks ?? 0}/${album.totalTracks}` : '',
    dates(album.firstListened, album.lastListened, formatDate)].filter(Boolean).join(' • ');
  return <View>
    <MusicDetailHero image={album.image} title={album.artistName || 'Unknown Artist'} onTitle={onBack}
      subtitle={subtitle} onSubtitle={onHistory} palette={palette}>
      <View style={styles.scores}>{renderScore(album.score, onRate)}</View>
      <Actions>
        <Button label={album.status || 'Add to Library'} onPress={onTrack} />
        <Button label="Activity history" tone="surface" onPress={onHistory} />
        {onSyncMetadata ? <Button label="Sync metadata" tone="surface" onPress={onSyncMetadata} /> : null}
        {onChooseRelease ? <Button label="Choose release" tone="surface" onPress={onChooseRelease} /> : null}
      </Actions>
    </MusicDetailHero>
    <MusicDetailLayout sidebar={<>
      <DetailMetadata facts={facts} palette={palette} />
      <Genres values={album.genres} palette={palette} />
      {collectionFacts.length ? <DetailMetadata title="Collection" facts={collectionFacts} palette={palette} /> : null}
    </>}>
      <Notes value={album.notes} palette={palette} renderNotes={renderNotes} onOpenNotes={onOpenNotes} />
      <Section title="Tracks" palette={palette}>
        <View style={[styles.rows, { backgroundColor: palette.surface }]}>
          {album.tracks.map(track => renderTrack(track, album, {
            onOpen: () => onOpenTrack(track), onAction: (key, target) => onAction(key, album, target), onRate: onTrackRate,
          }))}
        </View>
      </Section>
    </MusicDetailLayout>
  </View>;
}

export function TrackPage({ album, track, palette, formatDate, formatListenDate, renderScore, renderNotes,
  onBack, onRate, onAddListen, onOpenNotes, onDeleteListen, onOpenHistory }) {
  const listens = track.listens || [];
  const facts = [fact('track', 'TRACK', track.number ? `${track.number}${track.disc > 1 ? ` (Disc ${track.disc})` : ''}` : ''),
    fact('duration', 'DURATION', track.duration), fact('released', 'RELEASE DATE', album.releaseDate ? formatDate(album.releaseDate) : '')].filter(Boolean);
  return <View>
    <MusicDetailHero image={album.image} title={track.title} palette={palette}
      subtitle={[album.artistName, album.title].filter(Boolean).join(' • ')} onSubtitle={onBack}>
      <View style={styles.scores}>{renderScore(track.score, onRate)}</View>
      <Actions>
        <Button label="Add listen" onPress={onAddListen} />
        <Button label="Notes" tone="surface" onPress={onOpenNotes} />
        <Button label="Activity history" tone="surface" onPress={onOpenHistory} />
      </Actions>
    </MusicDetailHero>
    <MusicDetailLayout sidebar={<><DetailMetadata facts={facts} palette={palette} /><Genres values={track.genres || album.genres} palette={palette} /></>}>
      <Notes value={track.notes} palette={palette} renderNotes={renderNotes} onOpenNotes={onOpenNotes} />
      <Section title="Play history" palette={palette}>
        <View style={[styles.rows, { backgroundColor: palette.surface }]}>
          {listens.length ? listens.map(entry => <View key={entry.id} style={[styles.historyRow, { borderBottomColor: palette.border }]}>
            <Text style={[styles.body, styles.historyText, { color: palette.textSecondary }]}>{formatListenDate(entry)}</Text>
            <Button label="Delete" tone="ghost-danger" onPress={() => onDeleteListen(entry.id)} />
          </View>) : <Text style={[styles.body, styles.empty, { color: palette.textMuted }]}>No plays recorded yet.</Text>}
        </View>
      </Section>
    </MusicDetailLayout>
  </View>;
}

export function ShowPage({ show, episodes = [], episodeTotal, episodeFilter, palette, renderScore, renderEpisode, renderFilters,
  onFilter, onLoadMore, hasMore, loadingEpisodes, onTrack, onHistory, onRate, onAction, onVisitWebsite, onRateEpisode, onManageEpisodes }) {
  const total = episodeTotal ?? show.episodeTotal ?? episodes.length;
  const listened = show.listenedCount ?? episodes.filter(episode => episode.played && !episode.inProgress).length;
  const filters = [
    { value: 'all', label: 'All', count: total },
    { value: 'unplayed', label: 'Unplayed' },
    { value: 'in_progress', label: 'In progress' },
    { value: 'played', label: 'Played' },
  ];
  const filtered = episodes.filter(episode => episodeFilter === 'played' ? episode.played && !episode.inProgress
    : episodeFilter === 'in_progress' ? episode.inProgress : episodeFilter === 'unplayed' ? !episode.played : true);
  return <View>
    <MusicDetailHero image={show.image} title={show.title} subtitle={show.author ? `by ${show.author}` : ''} palette={palette}
      coverAction={<Button label={show.status || 'Add to Library'} onPress={onTrack} />}>
      <Genres values={show.genres} palette={palette} />
      {onVisitWebsite ? <Pressable accessibilityRole="link" onPress={onVisitWebsite}>
        <Text style={[styles.website, { color: palette.textSecondary }]}>Visit show website</Text>
      </Pressable> : null}
      <View style={styles.stats}>
        {[["EPISODES", total], ["LISTENED", listened], ...(show.totalMinutes ? [["TIME", `${show.totalMinutes}m`]] : [])].map(([label, value]) => <View key={label} style={[styles.stat, { backgroundColor: palette.surface }]}>
          <Text style={[styles.statLabel, { color: palette.textMuted }]}>{label}</Text>
          <Text style={[styles.statValue, { color: palette.text }]}>{value}</Text>
        </View>)}
        {renderScore(show.score, onRate)}
      </View>
      <Actions><Button label="Activity history" tone="surface" onPress={onHistory} /></Actions>
    </MusicDetailHero>
    <Section title="Episodes" large palette={palette} action={onManageEpisodes ? <Button label="Manage episodes" onPress={onManageEpisodes} /> : null}>
      {renderFilters(filters, episodeFilter, onFilter)}
      <View style={[styles.rows, { backgroundColor: palette.surface }]}>
        {filtered.map(episode => renderEpisode(episode, show, {
          onOpen: () => onAction('play', episode), onRate: onRateEpisode, onAction,
        }))}
        {!filtered.length ? <Text style={[styles.body, styles.empty, { color: palette.textMuted }]}>No episodes match this filter.</Text> : null}
      </View>
      {hasMore ? <Button label={loadingEpisodes ? 'Loading…' : 'Load more'} tone="surface" onPress={onLoadMore} /> : null}
    </Section>
  </View>;
}

const styles = StyleSheet.create({
  hero: { marginBottom: 32 }, heroCompact: { gap: 32, marginBottom: 48 }, heroWide: { flexDirection: 'row', gap: 40 },
  coverColumn: { width: '25%', maxWidth: 250 }, coverCentered: { width: '100%', alignSelf: 'center' },
  cover: { width: '100%', borderRadius: 8, overflow: 'hidden', alignItems: 'center', justifyContent: 'center' },
  coverAction: { marginTop: 16 }, placeholder: { fontSize: 72 }, heroBody: { minWidth: 0 }, heroBodyWide: { flex: 1 },
  title: { fontSize: 30, lineHeight: 36, fontWeight: '700', marginBottom: 4 },
  subtitle: { fontSize: 14, lineHeight: 20, fontWeight: '500', marginBottom: 12 }, centered: { textAlign: 'center' },
  body: { fontSize: 16, lineHeight: 24 }, scores: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 16, marginBottom: 20 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8, marginBottom: 24 },
  layout: { gap: 48 }, layoutWide: { flexDirection: 'row', gap: 40 }, sidebar: { gap: 24 },
  sidebarWide: { width: '25%', maxWidth: 250 }, content: { minWidth: 0, gap: 32 }, contentWide: { flex: 1 },
  section: { gap: 16 }, headingRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  heading: { fontSize: 20, lineHeight: 28, fontWeight: '700' }, largeHeading: { fontSize: 24, lineHeight: 32 },
  groupHeading: { fontSize: 18, lineHeight: 28, fontWeight: '600' }, rows: { borderRadius: 8, overflow: 'hidden' },
  historyRow: { flexDirection: 'row', alignItems: 'center', gap: 16, padding: 16, borderBottomWidth: 1 }, historyText: { flex: 1 },
  empty: { padding: 16 }, stats: { flexDirection: 'row', flexWrap: 'wrap', gap: 16, marginBottom: 24 },
  stat: { padding: 12, borderRadius: 8, alignItems: 'center' }, statLabel: { fontSize: 12, lineHeight: 16, fontWeight: '600', marginBottom: 4 },
  statValue: { fontSize: 18, lineHeight: 28, fontWeight: '700' }, website: { fontSize: 14, lineHeight: 20, marginBottom: 16 },
});
