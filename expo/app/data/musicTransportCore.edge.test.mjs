import assert from 'node:assert/strict';
import test from 'node:test';
import {
  endDateStamp,
  flattenAlbums,
  formatDurationMs,
  groupAlbums,
  mapAlbumPayload,
  mapArtistPayload,
  mapBrowseList,
  mapEpisodesPayload,
  mapHistoryEntries,
  mapManagedEpisode,
  mapManagedEpisodes,
  mapReleases,
  mapShowPayload,
  mapTrackIdentity,
  mapTrackListens,
  mapTracksPayload,
  mapTracker,
  managedEpisodeBody,
  nowDateTimeStr,
  nowTimeStr,
  splitDateTime,
  todayStr,
} from './musicTransportCore.js';

test('date helpers format the local day and clock', () => {
  assert.equal(todayStr(new Date(2026, 0, 5)), '2026-01-05');
  assert.equal(nowTimeStr(new Date(2026, 0, 5, 9, 7)), '09:07');
  assert.equal(nowDateTimeStr(new Date(2026, 0, 5, 9, 7)), '2026-01-05T09:07');
});

test('splitDateTime keeps a 12:00 default for date-only values', () => {
  assert.deepEqual(splitDateTime('2026-01-02'), { date: '2026-01-02', time: '12:00' });
  assert.deepEqual(splitDateTime('2026-01-02T08:30:00'), { date: '2026-01-02', time: '08:30' });
  assert.deepEqual(splitDateTime('2026-01-02T08:30'), { date: '2026-01-02', time: '08:30' });
  assert.deepEqual(splitDateTime(''), { date: '', time: '' });
  assert.deepEqual(splitDateTime('nope'), { date: '', time: '' });
  assert.deepEqual(splitDateTime(undefined), { date: '', time: '' });
});

test('endDateStamp completes the stamp or returns empty', () => {
  assert.equal(endDateStamp('2026-01-02T08:30'), '2026-01-02T08:30:00');
  assert.equal(endDateStamp('2026-01-02'), '2026-01-02T12:00:00');
  assert.equal(endDateStamp(''), '');
});

test('formatDurationMs renders h:mm:ss only past one hour', () => {
  assert.equal(formatDurationMs(0), '');
  assert.equal(formatDurationMs(-5), '');
  assert.equal(formatDurationMs('nope'), '');
  assert.equal(formatDurationMs('3000'), '0:03');
  assert.equal(formatDurationMs(59000), '0:59');
  assert.equal(formatDurationMs(61000), '1:01');
  assert.equal(formatDurationMs(3600000), '1:00:00');
  assert.equal(formatDurationMs(3661000), '1:01:01');
});

test('mapTracker accepts junk payloads and string scores', () => {
  assert.deepEqual(mapTracker(undefined), { status: null, score: null, startDate: '', endDate: '', notes: '' });
  assert.deepEqual(mapTracker('nope'), { status: null, score: null, startDate: '', endDate: '', notes: '' });
  assert.deepEqual(mapTracker({ status: 'Completed', score: '8.5', notes: 'n' }), {
    status: 'Completed', score: 8.5, startDate: '', endDate: '', notes: 'n',
  });
});

test('mapAlbumPayload reads the year and rejects junk payloads', () => {
  assert.equal(mapAlbumPayload(null), null);
  const album = mapAlbumPayload({ id: 5, title: 'T', release_date: '2020-05-01', genres: ['a', null] });
  assert.equal(album.year, '2020');
  assert.deepEqual(album.genres, ['a']);
  assert.equal(album.status, null);
  assert.deepEqual(album.tracks, []);
  assert.equal(mapAlbumPayload({ release_date: 'May 2020' }).year, '');
  assert.equal(mapAlbumPayload({}).id, null);
});

test('mapArtistPayload groups the discography and tolerates null albums', () => {
  assert.equal(mapArtistPayload(null), null);
  const artist = mapArtistPayload({ id: 1, name: 'A', albums: [null, { id: 2 }] });
  assert.deepEqual(artist.discography.map(group => group.label), ['Unknown']);
  assert.equal(artist.musicbrainz.rating, null);
  assert.deepEqual(flattenAlbums(artist), artist.discography[0].albums);
  assert.deepEqual(flattenAlbums(undefined), []);
});

test('groupAlbums orders Album, Single, Unknown and splits combined labels', () => {
  const groups = groupAlbums([
    { id: 1, releaseType: 'Single' },
    { id: 2, releaseType: 'Album' },
    { id: 3, releaseType: null },
    { id: 4, releaseType: 'Album + Live' },
  ]);
  assert.deepEqual(groups.map(group => group.label), ['Album', 'Album + Live', 'Single', 'Unknown']);
  assert.equal(groups[1].primary, 'Album');
  assert.deepEqual(groupAlbums(undefined), []);
});

test('mapTracksPayload defaults numbers and drops junk rows', () => {
  assert.deepEqual(mapTracksPayload(undefined), []);
  assert.deepEqual(mapTracksPayload({ results: [null, {}] }).map(track => track.title), ['']);
  const [track] = mapTracksPayload({ results: [{
    id: '5', music_id: 6, title: 'T', duration_ms: null, play_count: '4', score: '',
  }] });
  assert.equal(track.id, 5);
  assert.equal(track.musicId, 6);
  assert.equal(track.number, 0);
  assert.equal(track.disc, 1);
  assert.equal(track.duration, '');
  assert.equal(track.durationMs, null);
  assert.equal(track.playCount, 4);
  assert.equal(track.score, null);
  assert.equal(track.lastPlayed, null);
});

test('mapShowPayload flags only manual shows', () => {
  assert.equal(mapShowPayload(null), null);
  assert.equal(mapShowPayload({ source: 'manual' }).isManual, true);
  assert.equal(mapShowPayload({}).isManual, false);
  assert.equal(mapShowPayload({ source: 'podcastindex' }).isManual, false);
});

test('mapEpisodesPayload derives played and in-progress flags', () => {
  const { episodes, total } = mapEpisodesPayload({ results: [
    { id: 1, status: 'In progress' },
    { id: 2, status: 'Completed' },
    { id: 3, has_history: true },
    { id: 4 },
  ], pagination: { total: '9' } });
  assert.equal(total, 9);
  assert.equal(episodes[0].inProgress, true);
  assert.equal(episodes[0].played, false);
  assert.equal(episodes[1].played, true);
  assert.equal(episodes[2].played, true);
  assert.equal(episodes[3].number, 0);
  assert.equal(episodes[3].score, null);
  assert.deepEqual(mapEpisodesPayload(undefined), { episodes: [], total: 0 });
});

test('mapHistoryEntries only makes numeric record ids deletable', () => {
  assert.deepEqual(mapHistoryEntries(undefined), []);
  const rows = mapHistoryEntries({ results: [
    { entry_key: '12', played_at_local: '2026-01-02T05:06:00', title: 'T', play_count: 3 },
    { entry_key: 'day-2026-01-02', end_date: '2026-01-02' },
    {},
  ] });
  assert.equal(rows[0].recordId, 12);
  assert.equal(rows[0].deletable, true);
  assert.equal(rows[0].dateLabel, '2026-01-02 05:06');
  assert.equal(rows[0].note, '3 plays');
  assert.equal(rows[1].recordId, null);
  assert.equal(rows[1].deletable, false);
  assert.equal(rows[2].deletable, false);
  assert.equal(rows[2].dateLabel, 'No date');
});

test('mapBrowseList keys rows by kind and drops rows without a numeric id', () => {
  assert.deepEqual(mapBrowseList(undefined, 'artist'), []);
  const rows = mapBrowseList({ results: [
    { id: 5, name: 'A' },
    { id: '6', title: 'T', artist_name: 'AR' },
    { title: 'no id' },
    { id: 0, title: 'zero' },
  ] }, 'album');
  assert.deepEqual(rows.map(row => row.key), ['album-5', 'album-6']);
  assert.equal(rows[0].title, '');
  assert.equal(rows[1].subtitle, 'AR');
});

test('mapTrackIdentity rejects junk payloads', () => {
  assert.equal(mapTrackIdentity(null), null);
  assert.deepEqual(mapTrackIdentity({}), {
    trackId: null, albumId: null, artistId: null, musicId: null, title: '',
  });
});

test('mapTrackListens keeps only rows with a numeric history id', () => {
  assert.deepEqual(mapTrackListens(undefined), []);
  const rows = mapTrackListens({ results: [
    { history_id: '9', played_at: '2026-01-02T08:00:00', score: 8 },
    { played_at: '2026-01-02T08:00:00' },
  ] });
  assert.equal(rows.length, 1);
  assert.equal(rows[0].id, 9);
  assert.equal(rows[0].date, '2026-01-02');
  assert.equal(rows[0].time, '08:00');
  assert.equal(rows[0].score, 8);
});

test('mapReleases keeps only identified releases', () => {
  assert.deepEqual(mapReleases(undefined), { selectedId: '', releases: [] });
  const { releases } = mapReleases({ results: [
    { release_id: 'r1', title: 'T', date: '2020', country: 'US', format: 'CD', label: 'L', track_count: 12 },
    { title: 'no id' },
  ] });
  assert.equal(releases.length, 1);
  assert.equal(releases[0].detail, '2020 \u00b7 US \u00b7 CD \u00b7 L \u00b7 12 tracks');
});

test('mapManagedEpisodes stringifies the season and episode numbers', () => {
  assert.deepEqual(mapManagedEpisodes(undefined), []);
  const [episode] = mapManagedEpisodes({ results: [{ id: 1, episodeNumber: 3, seasonNumber: 1 }] });
  assert.equal(episode.episodeNumber, '3');
  assert.equal(episode.seasonNumber, '1');
  assert.equal(mapManagedEpisode({}).episodeNumber, '');
  assert.equal(mapManagedEpisode({}).seasonNumber, '');
});

test('managedEpisodeBody trims the title and drops blank optional fields', () => {
  assert.deepEqual(managedEpisodeBody({ title: '  X  ' }), { title: 'X' });
  assert.deepEqual(
    managedEpisodeBody({ title: 'X', description: '', episodeNumber: 3, imageUrl: ' i.png ' }),
    { title: 'X', episode_number: '3', image: 'i.png' },
  );
  assert.deepEqual(managedEpisodeBody({}), { title: '' });
});
