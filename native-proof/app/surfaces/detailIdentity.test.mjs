import assert from 'node:assert/strict';
import test from 'node:test';
import { detailEndpoint, detailGalleryEndpoint, identityFromDetailItem } from './detailIdentity.mjs';

test('provider links resolve identity and public-view state', () => {
  const identity = identityFromDetailItem({
    href: 'https://floppy.test/details/tmdb/movie/42/title?public_view=1',
  });
  assert.deepEqual(identity, {
    source: 'tmdb', mediaType: 'movie', mediaId: '42',
    href: 'https://floppy.test/details/tmdb/movie/42/title?public_view=1', publicView: true,
  });
  assert.equal(detailEndpoint(identity), '/api/v1/media/movie/tmdb/42/detail/?public_view=1');
  assert.equal(detailGalleryEndpoint(identity), '/api/v1/media/movie/tmdb/42/detail/gallery/');
});

test('music artist, album, and track routes resolve their native API identity', () => {
  assert.equal(identityFromDetailItem({ href: '/details/music/artist/12/the-artist/' }).musicKind, 'artist');
  assert.deepEqual(
    identityFromDetailItem({ href: '/details/music/artist/12/the-artist/album/34/the-album/' }),
    { musicKind: 'album', artistId: '12', musicId: '34', href: '/details/music/artist/12/the-artist/album/34/the-album/', publicView: false },
  );
  assert.deepEqual(
    identityFromDetailItem({ href: '/details/music/artist/12/the-artist/album/34/the-album/track/56/the-track/' }),
    { musicKind: 'track', artistId: '12', albumId: '34', musicId: '56', href: '/details/music/artist/12/the-artist/album/34/the-album/track/56/the-track/', publicView: false },
  );
});

test('podcast and item-provided identities resolve', () => {
  assert.equal(identityFromDetailItem({ href: '/podcast/show/88/' }).podcastId, '88');
  assert.deepEqual(identityFromDetailItem({ identity: { media_type: 'game', source: 'igdb', media_id: '99' } }), {
    mediaType: 'game', source: 'igdb', mediaId: '99', publicView: false,
  });
  assert.equal(identityFromDetailItem({ href: '/library/movie/' }), null);
});

test('season and episode links retain their provider parent and coordinates', () => {
  const season = identityFromDetailItem({ href: '/details/tmdb/tv/1001/show/season/2' });
  assert.deepEqual(season, {
    source: 'tmdb', mediaType: 'tv', mediaId: '1001', detailType: 'season',
    seasonNumber: 2, href: '/details/tmdb/tv/1001/show/season/2', publicView: false,
  });
  assert.equal(
    detailEndpoint(season),
    '/api/v1/media/tv/tmdb/1001/detail/?detail_type=season&season_number=2',
  );
  const episode = identityFromDetailItem({ href: '/details/tmdb/tv/1001/show/season/2/episode/4' });
  assert.equal(episode.detailType, 'episode');
  assert.equal(episode.seasonNumber, 2);
  assert.equal(episode.episodeNumber, 4);
});
