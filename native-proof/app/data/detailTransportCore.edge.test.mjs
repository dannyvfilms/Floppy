import assert from 'node:assert/strict';
import test from 'node:test';
import {
  DETAIL_STATUS_LABELS,
  activityLine,
  activityLineWithWatched,
  detailModelFromPayloads,
  detailRows,
  episodeActionPath,
  episodesFromPayload,
  historyFromConsumptions,
  identityFromItem,
  identityKey,
  issuesFromPayload,
  mediaPath,
  mergeScoreChips,
  notesFromConsumptions,
  seasonEpisodesPath,
  seasonsFromDetail,
  statusLabel,
  trackingFromState,
} from './detailTransportCore.js';

const identity = { mediaType: 'season', source: 'tmdb', mediaId: '5', seasonNumber: 2 };

test('provider chips require vote count and explicit empty synopsis stays empty', () => {
  const noVotes = detailModelFromPayloads({ detail: { score: 8.4, synopsis: '' }, metadata: { fields: { synopsis: 'stale' } } });
  assert.deepEqual(noVotes.providerScores, []);
  assert.equal(noVotes.synopsis, null);
  assert.equal(detailModelFromPayloads({ detail: { score: 0, score_count: 0 } }).providerScores.length, 1);
  assert.deepEqual(detailModelFromPayloads({ identity: { mediaType: 'book' }, detail: { imdb_rating: 8, imdb_rating_count: 1 } }).providerScores, []);
});

test('anime mapped episodes display flat numbers but address provider coordinates', () => {
  const rows = episodesFromPayload({ results: [{ item: { source: 'tmdb', media_id: '77', season_number: 2, episode_number: 1 }, display_episode_number: 14, watched: true, runtime: '24min', can_list: false }] }, { mediaType: 'anime', source: 'mal', mediaId: '5114' }, null);
  assert.equal(rows[0].number, 14);
  assert.equal(rows[0].watched, true);
  assert.equal(rows[0].runtime, '24min');
  assert.equal(rows[0].canList, false);
  assert.deepEqual(rows[0].identity, { mediaType: 'episode', source: 'tmdb', mediaId: '77', seasonNumber: 2, episodeNumber: 1 });
});

test('statusLabel round-trips codes, labels and unknown values', () => {
  assert.equal(DETAIL_STATUS_LABELS[3], 'Completed');
  assert.equal(statusLabel(3), 'Completed');
  assert.equal(statusLabel(null), '');
  assert.equal(statusLabel(99), '');
  assert.equal(statusLabel('Completed'), 'Completed');
  assert.equal(statusLabel('banana'), 'banana');
});

test('identity helpers and paths address seasons and episodes under tv', () => {
  assert.equal(identityKey(null), '');
  assert.equal(identityKey(identity), 'season|tmdb|5|2|');
  assert.equal(mediaPath(identity), '/api/v1/media/tv/tmdb/5/2');
  assert.equal(
    mediaPath({ ...identity, mediaType: 'episode', episodeNumber: 3 }),
    '/api/v1/media/tv/tmdb/5/2/3',
  );
  assert.equal(mediaPath({ mediaType: 'movie', source: 'tmdb', mediaId: '7' }), '/api/v1/media/movie/tmdb/7');
  assert.equal(seasonEpisodesPath(identity, 2), '/api/v1/media/tv/tmdb/5/2/episodes/');
  assert.equal(
    episodeActionPath({ source: 'tmdb', mediaId: '5', seasonNumber: 2, episodeNumber: 3 }, 'watch'),
    '/api/v1/media/tv/tmdb/5/2/episodes/3/watch/',
  );
});

test('identityFromItem reads season and episode coordinates out of web hrefs', () => {
  assert.equal(identityFromItem(null), null);
  assert.equal(identityFromItem({}), null);
  assert.deepEqual(
    identityFromItem({ href: '/base/details/tmdb/tv/5/season/2/episode/3?x=1' }),
    {
      mediaType: 'episode',
      source: 'tmdb',
      mediaId: '5',
      seasonNumber: 2,
      episodeNumber: 3,
    },
  );
  assert.deepEqual(
    identityFromItem({ href: '/details/tmdb/season/5' }),
    { mediaType: 'season', source: 'tmdb', mediaId: '5' }, // coordinates are omitted when the href has none
  );
});

test('seasonsFromDetail computes totals and falls back without episodes_left', () => {
  assert.deepEqual(seasonsFromDetail(undefined, identity), []);
  assert.deepEqual(seasonsFromDetail({ related: {} }, identity), []);
  const seasons = seasonsFromDetail({
    related: {
      seasons: [
        {
          item: { season_number: 2, title: 'Season 2', image: 's2.png', source: 'tmdb', media_id: '5' },
          progress: 4,
          episodes_left: 6,
          score: '8.5',
        },
        { item: { season_number: 1 }, progress: 3 },
      ],
    },
  }, identity);
  assert.equal(seasons[0].total, 10);
  assert.equal(seasons[0].percent, 40);
  assert.equal(seasons[0].countLabel, '4/10');
  assert.equal(seasons[0].score, 8.5);
  assert.deepEqual(seasons[0].identity, {
    mediaType: 'season',
    source: 'tmdb',
    mediaId: '5',
    seasonNumber: 2,
    title: 'Season 2',
  });
  assert.equal(seasons[1].total, null);
  assert.equal(seasons[1].countLabel, '3');
  assert.equal(seasons[1].percent, null);
});

test('episodesFromPayload tolerates empty payloads and missing artwork', () => {
  assert.deepEqual(episodesFromPayload({}, identity, 2), []);
  const episodes = episodesFromPayload({
    results: [
      { item: { episode_number: 3, title: 'Pilot', image: null, synopsis: '' }, status: 1 },
      { item: { episode_number: 4 }, end_date: '2026-02-01' },
    ],
  }, identity, 2);
  assert.equal(episodes[0].code, 'E3');
  assert.equal(episodes[0].image, null);
  assert.equal(episodes[0].overview, 'No synopsis available.');
  assert.equal(episodes[0].watched, false);
  assert.equal(episodes[0].dateLabel, '');
  assert.equal(episodes[0].endedLabel, '');
  assert.equal(episodes[0].history.summary, 'In progress');
  assert.deepEqual(episodes[0].identity, {
    mediaType: 'episode', source: 'tmdb', mediaId: '5', seasonNumber: 2, episodeNumber: 3,
  });
  assert.equal(episodes[1].watched, true);
  assert.equal(episodes[1].endedLabel, 'Ended: Feb. 1, 2026');
  assert.equal(episodes[1].playsLabel, '1\u00d7 watched');
  assert.equal(episodes[1].score, null);
});

test('trackingFromState maps the state consumptions and rejects untracked items', () => {
  assert.equal(trackingFromState(undefined, undefined), null);
  assert.equal(trackingFromState({ tracked: false }, { tracked: true }), null);
  assert.deepEqual(
    trackingFromState({
      tracked: true,
      consumptions: [{
        consumption_id: 9, status: 2, score: '8', progress: '12',
        start_date: '2026-01-01', end_date: '2026-02-01', notes: 'n',
      }],
    }),
    {
      id: 9, status: 'Paused', score: 8, progress: 12,
      startDate: 'Jan. 1, 2026', endDate: 'Feb. 1, 2026', notes: 'n',
    },
  );
  assert.deepEqual(trackingFromState({ tracked: true }), {
    id: null, status: '', score: null, progress: null, startDate: '', endDate: '', notes: '',
  });
});

test('notes drop blank rows and keep the consumption id as a string', () => {
  assert.deepEqual(notesFromConsumptions(undefined), []);
  assert.deepEqual(
    notesFromConsumptions([null, { notes: '   ', consumption_id: 2 }, { notes: 'hi', consumption_id: 3, end_date: '2026-02-01' }]),
    [{ id: '3', text: 'hi', date: 'Feb. 1, 2026' }],
  );
});

test('history rows survive consumptions without progress or score', () => {
  assert.deepEqual(historyFromConsumptions(undefined), []);
  const rows = historyFromConsumptions([
    { consumption_id: 4, status: 3, progress: 2, score: '7', start_date: '2026-01-01', end_date: '2026-01-02' },
    { consumption_id: 5 },
  ]);
  assert.equal(rows[0].title, 'Completed');
  assert.equal(rows[0].detail, 'Progress 2 · Score 7');
  assert.equal(rows[0].date, 'Jan. 1, 2026 - Jan. 2, 2026');
  assert.equal(rows[1].title, 'Play');
  assert.equal(rows[1].detail, '');
});

test('activityLine prints tracked progress for seasoned types and plays otherwise', () => {
  assert.equal(activityLine({ mediaType: 'tv', progress: '4', maxProgress: 6 }), 'Progress: 4/6');
  assert.equal(activityLine({ mediaType: 'season', progress: '4', maxProgress: 6 }), 'Progress: 4');
  assert.equal(activityLine({ mediaType: 'tv', progress: null }), '');
  assert.equal(activityLine({ mediaType: 'movie', runtime: '2h', plays: 1 }), '2h (Watched once)');
  assert.equal(activityLine({ mediaType: 'banana', runtime: '1h', plays: 2 }), '1h (Played 2 times)');
  assert.equal(activityLine({ mediaType: 'game', plays: 0, runtime: '' }), '');
  assert.equal(activityLine({ mediaType: 'game', plays: 1 }), 'Played once');
});

test('activityLineWithWatched only rewrites progress lines', () => {
  assert.equal(activityLineWithWatched(null, null), '');
  assert.equal(activityLineWithWatched('', '3h'), '3h');
  assert.equal(activityLineWithWatched('Progress: 4/6', '3h'), '3h (4/6)');
  assert.equal(activityLineWithWatched('Watched once', '3h'), '3h (Watched once)') // any non-empty line is wrapped, matching activityLine;
});

test('detailRows folds tv episode counts into runtime and drops season rows', () => {
  assert.deepEqual(detailRows(undefined, undefined), []);
  const tvRows = detailRows(
    { media_type: 'tv', details: { release_date: '2020-01-01', episodes: 12, seasons: 3, runtime: '24m' } },
    undefined,
  );
  assert.deepEqual(tvRows, [
    { label: 'Release Date', value: 'Jan. 1, 2020' },
    { label: 'RUNTIME', value: '24min \u00b7 12 episodes' },
  ]);
  const seasonRows = detailRows({ media_type: 'season', details: { episodes: 10, status: 'Returning' } }, undefined);
  assert.deepEqual(seasonRows, [{ label: 'Status', value: 'Returning' }]);
});

test('TV Details uses the shared server total and hides transport-only episode helpers', () => {
  assert.deepEqual(detailRows({ media_type: 'tv', details: {
    first_air_date: '2022-02-18', status: 'Returning', runtime: null,
    seasons: 3, episodes: 19, last_episode_season: 2, next_episode_season: null,
  } }, { total_runtime: '7h 44min' }), [
    { label: 'AIR DATES', value: 'Feb. 18, 2022' },
    { label: 'Status', value: 'Returning' },
    { label: 'RUNTIME (3 SEASONS)', value: '7h 44min · 19 episodes' },
  ]);
  assert.deepEqual(detailRows(undefined, { total_runtime: '7h 44min', status: 'Returning' }), [
    { label: 'RUNTIME', value: '7h 44min' },
    { label: 'Status', value: 'Returning' },
  ]);
});

test('detailRows falls back to the stored metadata projection', () => {
  const rows = detailRows(undefined, {
    release_datetime: '2020-03-04T05:00:00Z',
    runtime_minutes: 130,
    format: 'DVD',
    studios: ['A'],
  });
  assert.deepEqual(rows, [
    { label: 'Release Date', value: 'March 4, 2020' },
    { label: 'RUNTIME', value: '2h 10min' },
    { label: 'Format', value: 'DVD' },
    { label: 'Studios', value: 'A' },
  ]);
});

test('detailModelFromPayloads renders from the tapped card alone', () => {
  const longTitle = 'T'.repeat(500);
  const model = detailModelFromPayloads({
    item: { title: longTitle, image: { src: 'poster.jpg' } },
    identity: { mediaType: 'movie', source: 'tmdb', mediaId: '5' },
  });
  assert.equal(model.title, longTitle);
  assert.deepEqual(model.artwork, { src: 'poster.jpg', alt: longTitle, aspect: 'poster' });
  assert.equal(model.tracked, false);
  assert.equal(model.canRequest, true);
  assert.deepEqual(model.details, []);
  assert.deepEqual(model.repeats, []);
});

test('detailModelFromPayloads keeps season progress and repeats', () => {
  const model = detailModelFromPayloads({
    identity: { mediaType: 'season', source: 'tmdb', mediaId: '5', seasonNumber: 2 },
    state: {
      tracked: true,
      consumptions: [
        { progress: 4, end_date: '2026-02-01' },
        { progress: 2, end_date: '2026-01-01' },
      ],
    },
    detail: { max_progress: 6 },
  });
  assert.equal(model.tracked, true);
  assert.equal(model.activityLine, 'Progress: 4');
  assert.match(model.activityDates, /Feb\. 1, 2026/);
  assert.equal(model.history.length, 2);
  assert.equal(model.repeats.length, 1);
  assert.equal(model.canRequest, false);
});

test('related sections skip seasons and recommendations and title like the web', async () => {
  const { relatedSections } = await import('./detailTransportCore.js');
  const detail = { related: {
    seasons: [{ item: { title: 'S1', media_id: '1' } }],
    recommendations: [{ title: 'R', media_id: '2', media_type: 'movie' }],
    related_anime: [{ item: { title: 'Sequel', media_id: '9', media_type: 'anime', source: 'mal' } }, { item: null }],
    empty: [],
  } };
  const sections = relatedSections(detail, 'mal');
  assert.equal(sections.length, 1);
  assert.equal(sections[0].title, 'Related Anime');
  assert.equal(sections[0].items[0].identity.mediaId, '9');
});

test('score chips merge stored chips in the web order', async () => {
  const { mergeScoreChips } = await import('./detailTransportCore.js');
  const merged = mergeScoreChips([{ key: 'provider', label: 'TMDB', value: '7.0' }], {
    chips: [
      { key: 'opencritic', label: 'OpenCritic', rating: 81, percentRecommended: 70 },
      { key: 'trakt', label: 'Trakt', rating: 8.1, count: 1 },
    ],
  });
  assert.deepEqual(merged.map(chip => chip.key), ['provider', 'trakt', 'opencritic']);
  assert.equal(merged[1].count, '1 rating');
  assert.equal(merged[2].count, '70% recommend');
});

test('artwork payload maps hero, logo, trailer and gallery', async () => {
  const { artworkFromPayload } = await import('./detailTransportCore.js');
  assert.equal(artworkFromPayload({ available: false }), null);
  const art = artworkFromPayload({
    available: true, video: { key: 'abc' }, hero: { url: 'h', logo_url: 'l' },
    overview: null, photos: [{ url: 'p', thumb_url: 't' }, {}],
  });
  assert.equal(art.logoUrl, 'l');
  assert.equal(art.video.url, 'https://www.youtube.com/watch?v=abc');
  assert.deepEqual(art.photos, [{ url: 'p', thumbUrl: 't' }]);
});

test('recommendations come from their own endpoint when the detail leaves them out', () => {
  const model = detailModelFromPayloads({
    identity: { mediaType: 'movie', source: 'tmdb', mediaId: '603' },
    detail: { title: 'The Matrix', studios: [{ id: '1', name: 'Silver Pictures' }], details: {} },
    recommendations: [{ source: 'tmdb', media_type: 'movie', media_id: 534, title: 'Terminator Salvation', image: 'x' }],
  });
  assert.deepEqual(model.recommendations.map(row => row.title), ['Terminator Salvation']);
  assert.equal(model.recommendations[0].identity.mediaId, '534');
  assert.deepEqual(model.studios, ['Silver Pictures']);
  assert.deepEqual(model.studioLinks, [{ id: '1', name: 'Silver Pictures', source: 'tmdb' }]);
  assert.equal(model.mediaId, '603');
});

test('an episode page reads its guest stars and crew from the details block', () => {
  const model = detailModelFromPayloads({
    identity: { mediaType: 'episode', source: 'tmdb', mediaId: '95396', seasonNumber: 1, episodeNumber: 1 },
    detail: {
      title: 'Good News About Hell',
      details: {
        guest_stars: [{ id: 171689, name: 'Jeff McCarthy', character: 'Narrator', profile_path: '/a.jpg' }],
        crew: [{ id: 7399, name: 'Ben Stiller', job: 'Director', profile_path: null }],
      },
    },
  });
  assert.deepEqual(model.cast, [{ id: '171689', personId: '171689', name: 'Jeff McCarthy', role: 'Narrator', image: 'https://image.tmdb.org/t/p/w185/a.jpg' }]);
  assert.equal(model.crew[0].role, 'Director');
  assert.equal(model.crew[0].image, '');
});

test('issuesFromPayload maps the issues endpoint rows', () => {
  const page = issuesFromPayload({
    pagination: { total: 3, limit: 2, offset: 0 },
    results: [
      { media_id: '7', source: 'comicvine', title: '', issue_number: '1', cover_date: '1954-04-10', image: 'i', read: true },
      { media_id: '8', source: 'comicvine', title: 'Two', issue_number: '2', cover_date: '', image: '', read: false },
    ],
  }, { source: 'comicvine' });
  assert.equal(page.total, 3);
  assert.deepEqual(page.rows[0], {
    key: 'issue-7', title: 'Unknown', subtitle: 'Issue #1 · 1954-04-10', image: 'i', read: true,
    identity: { mediaType: 'comicissue', source: 'comicvine', mediaId: '7' },
  });
  assert.equal(page.rows[1].subtitle, 'Issue #2');
});

test('score logos reach the provider chip and the stored chips', () => {
  const chips = mergeScoreChips(
    [{ key: 'provider', label: 'TMDB', value: '8.3', count: '1 vote' }],
    { chips: [{ key: 'imdb', label: 'IMDb', rating: 8.46, count: 5 }], logos: { provider: 'p.png', imdb: 'i.png' } },
  );
  assert.equal(chips.find(chip => chip.key === 'provider').logo, 'p.png');
  assert.equal(chips.find(chip => chip.key === 'imdb').logo, 'i.png');
});
