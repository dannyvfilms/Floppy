import assert from 'node:assert/strict';
import test from 'node:test';
import {
  featuredFromPerson,
  highlightsFromCards,
  overviewsFromPayload,
  statisticsModelFromPayload,
  talentFromPayload,
  talentFromTopTalent,
  typeColorsFromDistribution,
} from './statisticsTransportCore.js';

test('typeColorsFromDistribution maps labeled datasets only', () => {
  assert.deepEqual(typeColorsFromDistribution(undefined), {});
  assert.deepEqual(
    typeColorsFromDistribution({
      datasets: [
        { label: 'TV Show', background_color: '#111111' },
        { label: 'Movie' },
        { background_color: '#222222' },
      ],
    }),
    { 'TV Show': '#111111' },
  );
});

test('highlightsFromCards drops empty cards and placeholder artwork', () => {
  assert.deepEqual(highlightsFromCards(undefined), []);
  assert.deepEqual(highlightsFromCards({}), []);
  const cards = highlightsFromCards({
    first_play: {
      title: 'A',
      // No timezone designator: shortDate renders local time, so a UTC-midnight
      // stamp would shift a day in timezones behind UTC.
      played_at: '2026-01-02T12:00:00',
      media_type: 'movie',
      image: 'data:image/svg+xml;base64,x',
      item: { source: 'tmdb', media_type: 'movie', media_id: '5' },
    },
    last_play: { title: '' },
    today_card: { entry: { title: 'B' }, label: 'Today', year: '2026', date_prefix: 'Played in' },
  });
  assert.equal(cards.length, 2);
  assert.deepEqual(cards[0], {
    key: 'first',
    label: 'First Play',
    title: 'A',
    meta: 'Movie',
    date: 'Played Jan 2, 2026',
    image: '',
    href: '/details/tmdb/movie/5',
  });
  assert.equal(cards[1].key, 'today');
  assert.equal(cards[1].date, 'Played in 2026');
});

test('talentFromTopTalent falls back to plays and shares the studio total', () => {
  const empty = talentFromTopTalent(undefined);
  assert.deepEqual(empty.roleLeaders.columns, []);
  assert.deepEqual(empty.studioFootprint.studios, []);
  assert.deepEqual(empty.tasteSignals, { sortOptions: [] });
  const model = talentFromTopTalent({
    by_sort: {
      titles: { top_actors: [{ name: 'A', unique_titles: 3, plays: 9 }] },
      plays: {
        top_directors: [{ name: 'D', plays: '4' }],
        top_studios: [
          { name: 'Big', plays: 75, watched_time: '3 days' },
          { name: 'Small', plays: 25 },
        ],
      },
    },
  }, { roleSort: 'titles', studioSort: 'plays' });
  assert.equal(model.roleLeaders.selected, 'titles');
  assert.deepEqual(model.roleLeaders.columns, [{
    bucket: 'actors', label: 'Actors', entries: [
      { name: 'A', source: '', personId: '', rank: 1, plays: 9, titles: 3, time: '', displayMetric: '3' },
    ],
  }]);
  assert.equal(model.studioFootprint.selected, 'plays');
  assert.deepEqual(model.studioFootprint.studios.map(studio => studio.pct), [75, 25]);
  assert.equal(model.studioFootprint.studios[0].metricLabel, '75 plays');
  const zeroed = talentFromTopTalent({ by_sort: { plays: { top_studios: [{ name: 'X' }] } } });
  assert.deepEqual(zeroed.studioFootprint.studios.map(studio => studio.pct), [0]);
  const timed = talentFromTopTalent({
    by_sort: { time: { top_studios: [{ name: 'X', plays: 2, watched_minutes: 90, watched_time: '1h 30m' }] } },
  }, { studioSort: 'time' });
  assert.equal(timed.studioFootprint.selected, 'time');
  assert.equal(timed.studioFootprint.studios[0].metricLabel, '1h 30m');
});

test('overviewsFromPayload maps panels and hides placeholder artwork', () => {
  assert.deepEqual(overviewsFromPayload({}), {});
  const model = overviewsFromPayload({
    tv_consumption: { has_data: true },
    top_played: {
      tv: [{
        formatted_duration: '2h',
        episode_count: 4,
        media: { item: { source: 'tmdb', media_type: 'tv', media_id: '5', title: 'Show', image: 'data:image/svg+xml;x' } },
      }],
    },
    top_rated_by_type: {
      tv: [{ score: '8.5', item: { source: 'tmdb', media_type: 'tv', media_id: '6', title: 'Rated' } }],
    },
  });
  assert.equal(model.tv.typeLabel, 'TV Shows');
  assert.deepEqual(model.tv.charts, []);
  assert.deepEqual(model.tv.panels[0], {
    key: 'tv-most-played',
    title: 'Most Played',
    items: [{ key: 'tmdb:5', title: 'Show', subtitle: '2h \u00b7 4 episodes', value: '', image: '', href: '/details/tmdb/tv/5' }],
  });
  assert.deepEqual(model.tv.panels[1].items, [{
    key: 'tmdb:6', title: 'Rated', subtitle: '', value: '8.5', image: '', href: '/details/tmdb/tv/6',
  }]);
});

test('overviewsFromPayload covers games, books and podcasts', () => {
  const model = overviewsFromPayload({
    game_consumption: { has_data: true },
    book_consumption: { has_data: true, unit_name: 'Page' },
    podcast_consumption: { has_data: true },
  });
  assert.equal(model.game.typeLabel, 'Video Games');
  assert.deepEqual(model.game.charts, []);
  assert.deepEqual(model.game.panels, []);
  assert.equal(model.book.typeLabel, 'Book');
  assert.equal(model.podcast.typeLabel, 'Podcasts');
});

test('featuredFromPerson hides the none.svg placeholder', () => {
  assert.equal(featuredFromPerson(null), null);
  assert.equal(featuredFromPerson({ name: 'A', image: 'http://x/none.svg' }).image, '');
  const person = featuredFromPerson({
    name: 'A',
    image: 'http://x/p.jpg',
    unique_titles: '5',
    known_for_pills: [{ label: 'L' }],
  });
  assert.equal(person.image, 'http://x/p.jpg');
  assert.equal(person.uniqueTitles, 5);
  assert.deepEqual(person.knownFor, [{ label: 'L' }]);
  assert.deepEqual(featuredFromPerson({}).knownFor, []);
});

test('statisticsModelFromPayload answers with the empty model', () => {
  const model = statisticsModelFromPayload(undefined);
  assert.equal(model.summary.total, 0);
  assert.equal(model.summary.typeLabel, 'titles');
  assert.deepEqual(model.highlights, []);
  assert.equal(model.scaleMax, 10);
  assert.equal(model.rangeName, '');
  assert.deepEqual(model.mediaTypeOptions, []);
  assert.equal(model.selectedMediaTypes, null);
  assert.equal(model.building, false);
  assert.deepEqual(model.overviews, []);
  assert.deepEqual(model.comparison, {});
  assert.deepEqual(model.talent.roleLeaders.columns, []);
});

test('statisticsModelFromPayload selects the single type and its colors', () => {
  const model = statisticsModelFromPayload({
    statistics: {
      summary_stats_by_type: { movie: { total: '4' } },
      media_type_distribution: { labels: ['Movie'] },
      score_distribution: { datasets: [{ label: 'Movie', background_color: '#123456' }] },
      history_highlights: { first_play: { title: 'A', media_type: 'movie' } },
    },
  }, ['movie']);
  assert.equal(model.summary.total, 4);
  assert.equal(model.summary.typeLabel, 'films');
  assert.equal(model.highlights[0].key, 'first');
  assert.deepEqual(model.mediaTypeOptions, [{ value: 'movie', label: 'Movie' }]);
  assert.deepEqual(model.charts.completion.rows, [{ label: 'Movie', color: '#123456', completed: 0, total: 4 }]);
  assert.deepEqual(model.overviews, []);
});

test('talentFromPayload passes sections through and strips studio colors', () => {
  assert.equal(talentFromPayload(undefined), null);
  const model = talentFromPayload({
    talent: { studioFootprint: { studios: [{ name: 'X', color: '#123' }] }, extra: 1 },
  });
  assert.equal(model.extra, 1);
  assert.deepEqual(model.studioFootprint.studios, [{ name: 'X', color: undefined }]);
});
