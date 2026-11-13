import assert from 'node:assert/strict';
import test from 'node:test';
import { detailSecondaryModel, detailSecondaryOrder } from '../frontend/ui/detailSecondaryModel.js';

const dates = value => ({ '2020-01-01': 'Jan. 1, 2020', '2021-03-04': 'March 4, 2021' })[value] || '';

test('Details preserves structured values, air dates and the combined runtime/count row', () => {
  const model = detailSecondaryModel({ secondary: { details: {
    first_air_date: '2020-01-01', last_air_date: '2021-03-04', total_runtime: '12h 30min',
    runtime: '30 min', seasons: 2, episodes: 25, languages: ['English', 'French'], themes: ['Drama'], status: null,
  } } }, { formatDate: dates });
  assert.deepEqual(model.facts.map(row => row.key), ['first_air_date', 'total_runtime', 'languages', 'status']);
  assert.equal(model.facts[0].label, 'Air Dates');
  assert.deepEqual(model.facts[0].values, [{ text: 'Jan. 1, 2020 – March 4, 2021' }]);
  assert.equal(model.facts[1].label, 'Runtime (2 seasons)');
  assert.equal(model.facts[1].values[0].text, '12h 30min · 25 episodes');
  assert.deepEqual(model.facts[2].values, [{ text: 'English' }, { text: 'French' }]);
  assert.equal(model.facts[3].values[0].text, 'Unknown');
});

test('linked authors and book formats replace raw duplicated metadata without losing navigation', () => {
  const author = { name: 'An Author', source: 'hardcover', person_id: 7, href: '/person/hardcover/7/an-author' };
  const model = detailSecondaryModel({ book_formats: [{ label: 'Paperback', href: '/details/book/2' }], secondary: {
    details: { author: ['An Author'], format: 'Raw format', pages: 250 },
    authors_linked: [author], author_detail_keys: ['author'], book_formats_replaces: 'format',
  } });
  assert.deepEqual(model.facts.map(row => row.key), ['pages', 'book-formats', 'authors']);
  assert.deepEqual(model.facts[1].values, [{ text: 'Paperback', href: '/details/book/2' }]);
  assert.deepEqual(model.facts[2].values, [{ text: 'An Author', href: author.href, identity: author }]);
});

test('raw metadata is only suppressed when linked replacement values are present', () => {
  const model = detailSecondaryModel({ media_details: { author: 'Raw Author', studio: 'Raw Studio', format: 'Hardcover' },
    secondary: { author_detail_keys: ['author'], studio_detail_keys: ['studio'], book_formats_replaces: 'format' } });
  assert.deepEqual(model.facts.map(row => row.key), ['author', 'studio', 'format']);
});

test('partial publication dates retain their precision and promoted values remain separate', () => {
  const model = detailSecondaryModel({ identity: { media_type: 'tv' }, secondary: {
    details: { release_date: '2020', publish_date: '2020-01', total_runtime: '12h', episodes: 6 },
    promotion: { suppressed_keys: ['release_date', 'total_runtime'], fields: [
      { key: 'air_dates', label: 'Air Dates', value: ['2020-01-01', '2021-03-04'] },
      { key: 'total_runtime', label: 'Runtime', value: '12h' },
      { key: 'locale', label: 'Languages', value: { languages: ['English', 'French'], country: 'US' } },
    ] },
  } }, { formatDate: dates });
  assert.equal(model.facts[0].values[0].text, '2020');
  assert.equal(model.facts[1].values[0].text, '2020-01');
  assert.equal(model.facts[0].promoted, true);
  assert.equal(model.facts[1].promoted, false);
  assert.deepEqual(model.promoted.map(row => row.value), ['Jan. 1, 2020 – March 4, 2021', '12h · 6 episodes', 'English, French (US)']);
});

test('streaming preserves unavailable, unset and configured empty states', () => {
  assert.equal(detailSecondaryModel({}).watchProviders, null);
  assert.equal(detailSecondaryModel({}).watchProviderRegion, 'UNSET');
  const model = detailSecondaryModel({ secondary: { watch_provider_region: 'US', watch_providers: [] } });
  assert.equal(model.watchProviderRegion, 'US');
  assert.deepEqual(model.watchProviders, []);
});

test('game and YouTube data retain the existing shared MediumExtras contract', () => {
  const model = detailSecondaryModel({ game_lengths: { available: true, source_label: 'How Long to Beat',
    source_url: 'https://howlongtobeat.com/game/1', cards: [{ label: 'Main Story', value: '12h', count: 6 }] },
  youtube_watch: { seconds: 3600, hours_label: '1h', videos: 2 } });
  assert.deepEqual(model.gameLengths, { available: true, pending: false, sourceLabel: 'How Long to Beat',
    sourceUrl: 'https://howlongtobeat.com/game/1', cards: [{ label: 'Main Story', value: '12h', count: 6, glyph: '◷' }] });
  assert.deepEqual(model.youtubeWatch, { seconds: 3600, hoursLabel: '1h', videos: 2 });
  assert.deepEqual(detailSecondaryModel({ identity: { media_type: 'game' } }).gameLengths,
    { available: false, pending: false, sourceLabel: '', sourceUrl: '', cards: [] });
  assert.equal(detailSecondaryModel({ identity: { media_type: 'movie' } }).gameLengths, null);
});

test('canonical section order preserves explicit hidden zones and ignores duplicate/unknown entries', () => {
  assert.deepEqual(detailSecondaryOrder({ zones: { sidebar: ['studios', 'details', 'studios', 'unknown'], content: [] } },
    ['details', 'studios', 'notes'], 'sidebar'), ['studios', 'details']);
  assert.deepEqual(detailSecondaryOrder({ zones: { content: [] } }, ['notes', 'related'], 'content'), []);
  assert.deepEqual(detailSecondaryOrder(undefined, ['details', 'history'], 'sidebar'), ['history', 'details']);
});

test('the unconfigured YouTube estimate retains its PWA order-zero placement', () => {
  assert.deepEqual(detailSecondaryOrder({ zones: { content: ['notes', 'game_lengths'] } },
    ['notes', 'game_lengths', 'youtube_watch'], 'content'), ['notes', 'youtube_watch', 'game_lengths']);
  assert.deepEqual(detailSecondaryOrder({ zones: { content: ['notes', 'game_lengths'] } },
    ['game_lengths', 'youtube_watch'], 'content'), ['youtube_watch', 'game_lengths']);
});


test('server-formatted detail values are not formatted a second time', () => {
  const model = detailSecondaryModel({ secondary: {
    details: { release_date: '2020-01-01', languages: ['en'], first_air_date: '2020-01-01' },
    display_details: { release_date: 'Jan 01, 2020', languages: 'English', first_air_date: 'Jan 01, 2020 – Ongoing' },
  } }, { formatDate: () => { throw new Error('already formatted'); } });
  assert.deepEqual(model.facts.map(fact => fact.values[0].text), ['Jan 01, 2020', 'English', 'Jan 01, 2020 – Ongoing']);
});
