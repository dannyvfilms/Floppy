# Library query engine

`src/app/library_query/` is the one engine for list-shaped library surfaces.
A surface describes what it wants as a `LibraryQuery` and asks
`LibraryQueryExecutor` for a page:

| Surface | Entry point |
|---|---|
| Web media list | `app.media_list_views.media_list` |
| Media-list API, including the all-types root endpoint | `app.media_list_filters.get_media_list_entries` |
| Smart-list membership: full sync, incremental sync, live matches | `lists.smart_rules` |
| Smart and custom list pages | `lists.views_helpers.paginate_list_items` |
| Home library shelves and list shelves | `users.home_screen._library_row_window`, `_custom_list_row_window` |

It replaced four implementations, each with its own filters, sorts and
pagination. Because of that, a performance fix in one (#691, #1004) missed
the others (#1248), and their semantics drifted apart.

Surfaces whose unit is not one item keep their own pipeline:

- separate-entry mode, which shows one card per tracker row;
- TV's "time left" order, which is grouped and caches its own order;
- the podcast show view;
- the music artist and album views;
- Home's "recently unrated" shelf, which is bounded by its time window.

## Contract

- **Candidates are `Item` rows.** Tracker state (status, score, dates) is read
  through subqueries, so an item is one candidate however many tracker rows
  (repeat viewings) it has.
  - `trackers.tracker_sources` is the one place that maps a library to its
    tracker model, including anime-library routing.
- **Membership is an uncorrelated `pk IN (…)`.** A correlated `EXISTS` makes
  SQLite walk every user's items; on the real library that took 35 s instead
  of 0.05 s.
- **Per-item subqueries go through the item's own rows.** Examples are latest
  status, score and "newest row" sorts. `TrackerSource.item_rows` compares the
  owner as `owner + 0`. Without that, SQLite (which has no statistics here)
  picks the `(user, created_at)` index and scans all of the user's rows for
  every item.
- **`page(offset, limit)` returns ordered `Item`s and the total.** Decorating
  them is the surface's job, and it only ever handles one page. Decorating
  means tracker rows (`media_list_entries_for_items`), card art and progress.
- **`ids()`, `contains()` and `matches()` serve smart-list membership.**
  `matches()` returns a `pk` subquery when every filter is SQL, so a scope can
  be passed on without loading it.
- **One ordering everywhere.** The sort value comes first, with nulls last.
  Ties then go to the lower-cased title, season, episode and id, all in the
  requested direction (`executor.tie_breakers`). Equal values cannot move
  between pages.
  - `random` is a seeded hash of the id. Home carries the seed through
    load-more.
  - **"Last Watched" is activity; "End Date" is completion.** The media list
    and Home map their `end_date` choice to the `last_watched` key, which uses
    `end_date` when set and `progressed_at` otherwise, so an in-progress item
    sorts by when it was last played. Custom list detail keeps `end_date` as
    the literal completion date because its label says "End Date". The API
    accepts both: `end_date` is unchanged, `last_watched` is opt-in.

## Two paths, derived rather than listed

A query runs on the SQL path when its sort has a SQL form and no active filter
needs Python. A sort's SQL form is either `sql` (one value) or `sql_order`
(composite keys over annotations). No list of "SQL-safe" filters is kept.

- **SQL path:** filtering, ordering, `COUNT` and `LIMIT`/`OFFSET` all run in
  the database.
- **Scan path:** every SQL condition narrows the candidates first. The rest
  are read in batches of `DEFAULT_BATCH_SIZE`, keeping only a compact rank row
  per match.
  - Tracker rows are loaded only when a predicate or sort needs them. They
    come one batch at a time, with the same prefetches and aggregation Home
    and the list use.
  - Filters can declare a per-batch `prepare` step for bulk annotation.
  - Memory is bounded by the batch and the page. Computing values in Python is
    still one pass over the narrowed candidates.

Home caches a Python-ordered shelf's id order for longer than the rendered
section, so "load more" and a warm revisit cost one page. A random shelf keeps
the short row lifetime: each new seed is a different order.

### Display levels on mixed Home shelves

An All Media library row stores selected families in `filters.media_types` and
one display level per hierarchical family in `filters.media_subviews`. TV can
show shows, seasons or episodes; music can show artists, albums or tracks;
podcasts can show shows or episodes. Missing selections preserve the original
mixed-row defaults: TV shows, music tracks and podcast episodes. The dedicated
music and podcast row defaults are independent.

Ordinary mixed shelves retain the normal executor path. A shelf with another
display level uses `users.home_mixed_rows`: item sources contribute the engine's
compact `rank_rows()` values, and Home's existing album, artist and podcast-show
adapters contribute equivalent ranks from batches of their trackers. One global
order uses nulls last, stable entity identities and the row's random seed. Only
the requested page is decorated; only its projected cards persist shell Items.
The combined identity order uses the existing Home cache registry and tracker
invalidation, including the row's display choices in its cache key.

Status and rating refer to the displayed entity, not its parent. TV child
membership is scoped through the viewer's TV library, including anime routing;
episode state comes from active episode plays and excludes archived/rating-only
rows. Collection and tags refer to the displayed Item (the existing shell for
projected entities). Release filtering uses the album's release date, a podcast
show's first publication date, or an unknown date for artists. Unknown dates
follow the shared Released/Not Released rule. Caught-up filters apply to shows
and seasons, as on other engine queries.

## Where filters come from

The engine is one half. The other half turns what a surface was given into
`FilterValues`, and there are exactly two of those:

| Input | Parser | Used by |
|---|---|---|
| A URL query string | `app.media_list_filters.parse_media_list_filters` | Web media list (`strict=False`), API (strict), custom list pages (`strict=False`) |
| Saved rule JSON | `lists.smart_rules.normalize_rule_payload`, then `adapters.filter_values_from_rules` | Smart lists, Home shelves |

`strict` is the API contract: comma-separated values split, and an invalid
value is a 400. The web pages read repeated parameters only, and an invalid
value (a stale bookmark) means "not filtering". Relative date windows ("in the
last 7 days") resolve with `smart_rules.resolve_relative_date_windows` in both
parsers.

On the page side, `static/js/libraryFilterState.js` is the filter menu's state
(values, labels, clear) for every page that shows `filter_menu.html`. A page
hands it its current filters in the smart-rule vocabulary:
`MediaListFilters.menu_state()` for URL filters, the normalized rules for smart
lists.

The media list's Python-built paths (separate entries, time left) apply the
rating and date ranges through the engine too (`apply_range_filters`), and the
ranges are part of their cache keys.

## Adding a filter or sort

- **Filter:** add a `FilterDef` to `filters.FILTERS` in the form it can be
  evaluated in:
  - `row`: a condition on one tracker row. All row conditions share one
    subquery, so they hold on the same row.
  - `sql`: a condition on the item.
  - `predicate`: Python. Declare `needs` for what it reads.

  Then add the field to `spec.FilterValues` and map it in `adapters`. Parse
  it in `parse_media_list_filters` (URL surfaces) and `normalize_rule_payload`
  (saved rules), add it to `MediaListFilters.menu_state()`, and give the menu
  state a default in `libraryFilterState.js`.
- **Sort:** add a `SortDef` to `sorts.SORTS`, or `sorts.register(...)` it from
  the surface that owns it, as Home does for its upcoming, recent, completion
  and episodes-left orders.
  - Give it a `sql` expression, or `sql_order` plus `batch_values`. The two
    must order identically; see `users.tests.test_home_row_paging`.
  - `tracker=True` marks values derived from tracker rows.

`app.tests.test_library_query` checks that every SQL sort orders the same way
on the scan path. A new sort is covered automatically.

## Semantics that surfaces choose

| Option | Meaning | Used by |
|---|---|---|
| `FilterValues.status_match="latest"` | Status and rating read the item's most recent row by activity | Media list, API, Home, new smart lists |
| `FilterValues.status_match="any"` | Status and rating match any row | Saved smart lists, custom-list pages |
| `collection_attributes` | A collected copy's platform and format count | Everywhere except saved smart lists |
| `season_effective_status` | A season must also read as the status through its episode history. A season stored In Progress, Dropped or Paused always does, so only other statuses pay for the derivation | Home |
| `LibraryQuery.routing="library"` | Anime tracked on TV rows follows the user's anime-library preference | Everywhere except saved smart lists |
| `LibraryQuery.routing="model"` | Anime tracked on TV rows stays in TV | Saved smart lists |

Saved smart-list rules carry `semantics_version`. Rules saved before the
engine have no version, and they keep the semantics they were built with: any
row, the item's own platform and format, model routing. No list's membership
changed. This was verified against a copy of the real library, with every
smart list identical and 521 incremental checks identical.

## Behaviour changes in this pass

Each of these was measured with a differential harness before its surface
switched over. They are intentional:

- **Home now matches the media list its title links to:**
  - latest-row status;
  - a statusless tracker row (an imported rating) is not part of "All";
  - anime-library routing;
  - a collected copy's platform and format;
  - movie plays count completed viewings;
  - the platform sort sorts by platform (Home silently fell back to title).
- **Home "descending popularity" still means most popular first.** The row's
  link to the media list now passes the matching rank direction.
- **Platform sorts by the platform a card displays:** the collected copy's
  platform, else the one an active filter asked for, else the item's only
  platform. Items listing several platforms sort last. The API previously
  sorted by the first listed platform.
- **Runtime, time watched and time to beat sort a zero value last,** as
  unmeasured. Nulls sort last in both directions everywhere. A list page's
  rating sort used to put unrated items first when ascending.
- **Filters the media list ignored on types whose UI does not show them now
  apply to every type,** for example author on the movie API.
- **"No status" on its own means only statusless items** on every surface.

## Still O(n)

- Python predicates: provider availability, author, progress, and a season's
  effective status where it has to be derived.
- Python sorts: time to beat, next episode air date, time left, and Home's
  upcoming, completion and episodes-left orders. These scan the SQL-narrowed
  candidates.
- `ids()` for smart-list sync is O(n) by definition and runs in the
  background.
