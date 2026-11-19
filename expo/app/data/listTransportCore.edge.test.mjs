import assert from 'node:assert/strict';
import test from 'node:test';
import {
  LIST_PAGE_SIZE,
  activityFromPayload,
  applyTierPlacements,
  hasMorePages,
  itemsPageFromPayload,
  listItemsFromPayload,
  listSummaryFromPayload,
  listsFromPayload,
  memberUsernames,
  recommendationsFromPayload,
  searchPaginationFromPayload,
  searchResultsFromPayload,
  smartOptionsFromPayload,
  smartRulesFromPayload,
  tiersFromPayload,
} from './listTransportCore.js';

test('hasMorePages uses the total, the nested block or the next link', () => {
  assert.equal(LIST_PAGE_SIZE, 200);
  assert.equal(hasMorePages(undefined, 0), false);
  assert.equal(hasMorePages({ pagination: { total: 400 } }, 0), true);
  assert.equal(hasMorePages({ pagination: { total: 400 } }, 200), false);
  assert.equal(hasMorePages({ items: { pagination: { total: 200 } } }, 0), false);
  assert.equal(hasMorePages({ pagination: { next: 'https://x/?offset=200' } }, 0), true);
  assert.equal(hasMorePages({ pagination: {} }, 0), false);
});

test('itemsPageFromPayload counts the page and the total', () => {
  assert.deepEqual(itemsPageFromPayload(undefined), { count: 0, total: 0 });
  assert.deepEqual(
    itemsPageFromPayload({ items: { results: [1, 2], pagination: { total: '9' } } }),
    { count: 2, total: 9 },
  );
  assert.deepEqual(itemsPageFromPayload({ items: [1] }), { count: 1, total: 1 });
});

test('listItemsFromPayload maps rows and falls back for missing items', () => {
  assert.deepEqual(listItemsFromPayload(undefined), []);
  const rows = listItemsFromPayload({ items: [
    {
      id: 'x',
      item: { media_type: 'movie', title: 'T', source: 'tmdb', media_id: '5', release_datetime: '2020-05-01T00:00:00Z' },
      status: 3,
      score: '8',
      created_at: '2026-01-02T00:00:00Z',
    },
    { item: null },
    { item: { media_type: 'music', title: 'S' } },
    { item: { media_type: 'banana', title: 'U' } },
    { item: { media_type: 'game', title: 'G' } },
  ] });
  assert.equal(rows[0].statusLabel, 'Completed');
  assert.equal(rows[0].score, 8);
  assert.equal(rows[0].rank, 1);
  assert.equal(rows[0].tierRank, 1);
  assert.equal(rows[0].cardShape, 'poster');
  assert.equal(rows[0].releaseLabel, '2020');
  assert.equal(rows[0].identity.mediaId, '5');
  assert.deepEqual(rows[0].rating, { label: '8', value: 8, scaleMax: 10 });
  assert.equal(rows[1].title, '');
  assert.equal(rows[1].rank, 2);
  assert.equal(rows[2].cardShape, 'square');
  assert.equal(rows[3].cardShape, 'poster');
  assert.equal(rows[3].mediaTypeLabel, 'banana');
  assert.equal(rows[4].cardShape, 'landscape');
});

test('listItemsFromPayload ranks by offset unless the entry carries a rank', () => {
  const rows = listItemsFromPayload({ items: [{ item: {}, rank: '5' }, { item: {} }] }, 100);
  assert.equal(rows[0].rank, 5);
  assert.equal(rows[1].rank, 102);
  assert.equal(rows[1].tierRank, 102);
});

test('progressLabel reads every unit the web prints', () => {
  const label = entry => listItemsFromPayload({ items: [entry] })[0].progressLabel;
  assert.equal(label({ progress: 45, progress_unit: 'minutes' }), '45m played');
  assert.equal(label({ progress: 130, progress_unit: 'minutes' }), '2h 10m played');
  assert.equal(label({ progress: 'abc', progress_unit: 'minutes' }), 'abc');
  assert.equal(label({ progress: 1, progress_unit: 'plays' }), '1 play');
  assert.equal(label({ progress: 3, progress_unit: 'plays' }), '3 plays');
  assert.equal(label({ progress: 120, progress_unit: 'pages' }), '120 pages');
  assert.equal(label({ progress: 5, progress_unit: 'chapters' }), '5 chapters');
  assert.equal(label({ progress: 2, progress_unit: 'issues' }), '2 issues');
  assert.equal(label({ progress: 4, episodes_left: 2 }), '4 / 6 episodes');
  assert.equal(label({ progress: 7 }), '7');
  assert.equal(label({}), '');
});

test('tier placements skip unknown tiers and unplaced items keep their rank', () => {
  assert.deepEqual(tiersFromPayload(undefined), []);
  const items = listItemsFromPayload({ items: [
    { id: 5, item: {} },
    { id: 6, item: {} },
    { id: 7, item: {} },
  ] });
  const placed = applyTierPlacements(items, {
    tiers: [{ id: '1', name: 'Good', color: 'red' }],
    placements: [
      { tier: '1', item_id: 5 },
      { tier: 'zzz', item_id: 6 },
    ],
  });
  assert.equal(placed[0].tier, '1');
  assert.equal(placed[0].tierRank, 1);
  assert.equal(placed[1].tier, '');
  // An unknown tier counts as the blank "Unranked" bucket, so it ranks first there.
  assert.equal(placed[1].tierRank, 1);
  assert.equal(placed[2].tier, '');
  assert.equal(placed[2].tierRank, 3);
});

test('listSummaryFromPayload defaults the role and visibility for a bare list', () => {
  assert.equal(listSummaryFromPayload(null), null);
  const summary = listSummaryFromPayload({ id: 1 });
  assert.equal(summary.role, 'Viewer');
  assert.equal(summary.visibility, 'private');
  assert.equal(summary.visibilityLabel, 'Private');
  assert.equal(summary.members.length, 0);
  assert.equal(summary.itemsCount, 0);
  assert.equal(summary.completionPercent, null);
  assert.equal(summary.canEdit, false);
  assert.equal(summary.canDelete, false);
  assert.equal(summary.canRecommend, false);
  assert.equal(summary.href, '/lists/1');
  assert.deepEqual(summary.tags, []);
});

test('listSummaryFromPayload marks the owner and the collaborator role', () => {
  const summary = listSummaryFromPayload({
    id: 2,
    name: 'Favorites',
    owner: { id: 7, username: 'me' },
    collaborators: [{ id: 8, username: 'pal' }],
    viewers: [{ id: 9 }],
    visibility: 'public',
    allow_recommendations: true,
    items_count: '5',
    completion_percent: 40,
    tags: ['a', 3],
  }, 'me');
  assert.equal(summary.isOwner, true);
  assert.equal(summary.role, 'Owner');
  assert.equal(summary.memberCount, 3);
  assert.deepEqual(summary.members.map(member => member.role), ['owner', 'collaborator', 'viewer']);
  assert.equal(summary.members[1].handle, '@pal');
  assert.equal(summary.members[2].name, '');
  assert.equal(summary.itemsCount, 5);
  assert.equal(summary.completionPercent, 40);
  assert.equal(summary.canRecommend, true);
  assert.deepEqual(summary.tags, ['a']);
});

test('listsFromPayload accepts bare arrays and drops malformed rows', () => {
  assert.deepEqual(listsFromPayload(undefined), []);
  assert.deepEqual(listsFromPayload('nope'), []);
  const lists = listsFromPayload([null, { id: 1 }, { name: 'no id' }]);
  assert.equal(lists.length, 1);
  assert.equal(lists[0].id, '1');
});

test('activityFromPayload describes the known types and flags the unknown ones', () => {
  assert.deepEqual(activityFromPayload(undefined), []);
  const rows = activityFromPayload({ results: [
    { id: 1, activity_type: 'item_added', user: 'me', item_title: 'X', timestamp: new Date().toISOString(), details: 'note' },
    { id: 2, activity_type: 'banana', user: 'you', item_title: 'Y', timestamp: 'nope' },
    { id: 3, activity_type: 'list_created', user: 'me' },
  ] });
  assert.equal(rows[0].description, 'me added X: note');
  assert.equal(rows[0].agoLabel, 'moments');
  assert.equal(rows[1].description, 'Unknown activity');
  assert.equal(rows[1].user, 'you');
  assert.equal(rows[2].description, 'me created the list');
  assert.equal(rows[2].itemTitle, 'an item');
});

test('recommendationsFromPayload maps the card payload', () => {
  assert.deepEqual(recommendationsFromPayload(undefined), []);
  const rows = recommendationsFromPayload({ results: [
    { id: 4, item_id: 9, title: 'T', media_type: 'banana', recommended_by: 'me', note: 'n', season_number: 2 },
  ] });
  assert.equal(rows[0].id, '4');
  assert.equal(rows[0].mediaTypeLabel, 'banana');
  assert.equal(rows[0].recommender, 'me');
  assert.deepEqual(rows[0].identity, {
    mediaType: 'banana', source: undefined, mediaId: undefined, title: 'T', seasonNumber: 2, episodeNumber: undefined,
  });
  assert.deepEqual(rows[0].media.image, { src: null, fallback: '', source: 'primary' });
});

test('searchResultsFromPayload stringifies ids and keeps unknown types', () => {
  assert.deepEqual(searchResultsFromPayload(undefined), []);
  const rows = searchResultsFromPayload({ results: [
    { media_type: 'movie', source: 'tmdb', media_id: 5, title: 'T', year: 2020, platforms: ['PC'] },
    { media_type: 'banana', source: 's', media_id: null, title: 'U' },
  ] });
  assert.equal(rows[0].id, 'movie-tmdb-5');
  assert.equal(rows[0].mediaId, '5');
  assert.equal(rows[0].year, '2020');
  assert.equal(rows[1].mediaId, '');
  assert.equal(rows[1].year, '');
  assert.equal(rows[1].mediaTypeLabel, 'banana');
});

test('searchPaginationFromPayload defaults and rounds the page count', () => {
  assert.deepEqual(searchPaginationFromPayload(undefined), { total: 0, limit: 20, offset: 0, totalPages: 1 });
  assert.deepEqual(
    searchPaginationFromPayload({ pagination: { total: 45, limit: 20, offset: 20 } }),
    { total: 45, limit: 20, offset: 20, totalPages: 3 },
  );
});

test('memberUsernames keeps only named members of one role', () => {
  assert.deepEqual(
    memberUsernames([
      { role: 'collaborator', name: 'a' },
      { role: 'collaborator' },
      { role: 'owner', name: 'b' },
    ], 'collaborator'),
    ['a'],
  );
  assert.deepEqual(memberUsernames(undefined, 'owner'), []);
});

test('smart rules and options survive missing payloads', () => {
  assert.equal(smartRulesFromPayload(undefined), null);
  assert.deepEqual(smartRulesFromPayload({ rules: {} }), {});
  const options = smartOptionsFromPayload(undefined);
  assert.deepEqual(options.mediaTypes, []);
  assert.deepEqual(options.statuses.map(status => status.value), [
    'Planning', 'In progress', 'Paused', 'Completed', 'Dropped',
  ]);
  assert.equal(options.genres, undefined);
  const full = smartOptionsFromPayload({
    media_types: [{ value: 'movie', label: 'Movies' }],
    options: { genres: ['x'], show_languages: true, author_is_channel: 1 },
  });
  assert.deepEqual(full.mediaTypes, [{ value: 'movie', label: 'Movies' }]);
  assert.deepEqual(full.genres, ['x']);
  assert.equal(full.showLanguages, true);
  assert.equal(full.authorIsChannel, true);
});
