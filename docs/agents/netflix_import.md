# Netflix viewing-history import

Covers the Netflix importer and its interactive review page. Read this before
changing `src/integrations/imports/netflix.py`,
`src/templates/integrations/netflix_pending.html`, or the `NetflixPendingRow`
model.

## What the input is

Netflix's "viewing activity" export is a two-column CSV in the account's
local language — `Title,Date` (German: `Titel,Datum`). There is no media
type, no provider IDs, and no season/episode columns: episodes encode both
in the title text. A German export looks like:

```csv
Title,Date
Arrival,11/20/26
Weeds – Kleine Deals unter Nachbarn: Staffel 8: Es ist Zeit: Teil 2,10/7/18
Some Show: Miniserie: Folge 3,10/7/18
 ,10/7/18
```

An English export uses the same shape with `Season` / `Episode` /
`Limited Series` / `Part`:

```csv
Title,Date
Arrival,11/20/26
Weeds: Season 8: It's Time: Part 2,10/7/18
Disenchantment: Part 5: Goodbye Bean,11/20/26
Some Show: Limited Series: Episode 3,11/20/26
```

The last German shape is common: Netflix writes a blank title when it has no
name for the entry (usually a kids' show or an unlicensed title).

## Decoding and dates

`_decode_csv` reads UTF-8 with BOM tolerance and falls back to Latin-1, so
non-UTF-8 exports (older Windows exports) do not crash the import.
`_normalize_rows` maps the localized headers onto `Title`/`Date`.

Dates are `M/D/YY` or `D/M/YY` depending on the account locale. Because a
single-digit date like `10/7/18` is ambiguous, `_detect_date_layout` scans
the whole file: any first component above 12 means `D/M/Y`, any second
component above 12 means `M/D/Y`, and an all-ambiguous file defaults to
`M/D/Y` (Netflix's US default). Two-digit years roll at 70. A row whose date
still does not parse is parked as a pending row with its raw date kept in
`raw_date`.

## Media type and S/E from the title

`_split_title` is a bilingual-label heuristic (Netflix localizes the
markers with the UI, so both German and English exports occur in one
account's history — a single German file in testing contained 22 English
`Season` rows):

- `Staffel N`/`Season N`, `Folge K`/`Episode K` or a `Miniserie` /
  `Limited Series` segment → TV; the series name is the text before the
  first labelled segment, so a show whose own name contains a colon keeps
  it (`Tour de France: Unchained: Season 3: …` queries
  `Tour de France: Unchained`), and the labels supply the coordinates.
  `Miniserie`/`Limited Series` rows have no season label and are recorded
  in season 1.
- A standalone `Part N`/`Teil N` or `Volume N` segment directly after the
  series name names a season (`Disenchantment: Part 5: Goodbye Bean` → S5,
  `Love, Death & Robots: Volume 3: Jibaro` → S3); the row needs at least
  one more segment, so a two-part movie title stays a movie.
- `Part N`/`Teil N` *after* a known season names a part of one episode
  (`Weeds: Season 8: It's Time: Part 2`) and is ignored — never an episode
  number.
- A limited series that labels its episodes `Part 1` … `Part N`
  (`Wild Wild Country: Limited Series: Part 6`) carries the episode number
  there, in season 1.
- Dash-form parts (`Die Tribute von Panam - Teil 3: Vögel`) are movie
  titles and stay movies.
- anything without a marker is a movie.

A TV row without a season and without an episode number cannot be recorded
and goes to the review page, pre-filled with whatever was parsed. A row
that has an episode number but no season is still resolvable: see
`resolve_row` below.

## Resolution and idempotency

Every row is resolved through `NetflixResolver.resolve_row` on top of the
TMDB title search (the same path TV Time's import uses, via
`TraktMetadataResolverMixin`) — there are no provider IDs in the file to
lean on. `NetflixResolver` is a thin subclass: it carries no
`external_reference_integration`, so every lookup is a plain title search,
and it adds `search_results` (the review page's pick list), `resolve_row`
and `record_play`.

A row resolves when the title search has exactly one exact normalized-title
match. Otherwise four non-guessing shortcuts apply, each requiring a unique
hit; anything ambiguous stays pending:

- **Known season filters same-title shows.** Netflix exports several shows
  under one name (two shows named `The Rookie`). When the row carries a
  season, only candidates that actually have that season (TMDB `related.seasons`)
  survive; a single survivor resolves the row.
- **Part-suffix continuation.** TMDB keeps a movie's part label that Netflix
  drops (`Mission: Impossible - Dead Reckoning` is listed as `… Dead
  Reckoning Part One`). A movie row with no exact match resolves when
  exactly one result continues the title with nothing but a
  `Part N`/`Teil N` label.
- **Season by episode number.** A series row with an episode number but no
  season (`Delicious in Dungeon: Episode 12`) resolves when exactly one of
  the show's seasons carries that many episodes; with several candidates the
  row's episode title (when it has one) must additionally match exactly one
  season's episode name.
- **Unlabelled anthology episode.** Anthology docuseries export their parts
  as `Show: Part title` without season or episode labels. A colon-titled row
  no movie search can find may resolve when the title before the last
  segment is a unique TV show and the last segment names exactly one
  episode across all of the show's seasons.

All searches and show/season lookups are memoized per import run.

`record_play` writes one `Movie` row (status `COMPLETED`, `progress=1`) or
one `Episode` row per watch, with `TV`/`Season` rows created on demand, and
re-verifies the episode against the TMDB season before writing. A
re-record of the same `(item, day)` is a no-op, which is what makes
re-importing the same file safe: plays are additive and idempotent, so the
import mode is accepted but never acted on (the `youtube_takeout`
precedent). There is deliberately no `to_delete`/bulk machinery.

### Episode title matching

Many rows carry the season and the episode title but no number (`Weeds:
Season 8: It's Time`). For those, `match_episode_number` compares the row's
trailing episode title (labels and a trailing `: Part N`/`: Teil N`
stripped by `_episode_title`) against the season's episode names from the
same TMDB season lookup — normalized to alphanumerics, so case and
punctuation never block a match. A unique hit is recorded; zero or
ambiguous hits stay pending with the season pre-filled. English episode
titles match TMDB's English names; localized (e.g. German) episode titles
generally do not and land on the review page.

## Provenance and undo

The importer stamps every row it **creates** with the ambient
`ImportRun` (`import_progress.tracking` threads the id, exactly like the
shared bulk importers): new `Movie`/`TV`/`Season`/`Episode` rows via
`import_run`, and parked `NetflixPendingRow`s the same way. Existing rows
are never re-tagged, so re-imports keep the original provenance. Plays
recorded later on the review page are stamped with the **row's**
`import_run_id` (`netflix_pending_resolve` passes it to the resolver), so
undoing a run also removes the plays its unresolved rows produced.

Two undo paths, both keyed on those stamps:

- **Per-run** (`rollback_import_run`, "Recent Import Runs"): the generic
  loop deletes the run's tagged `Movie`/`TV`/`Season` rows (deleting a
  `TV` cascades to its seasons and episodes — the same semantics the Trakt
  rollback has since #579, so a show the run created disappears with it),
  and a Netflix branch additionally deletes the run's tagged `Episode`
  rows (via the `bulk_media_delete` context, so the usual post-delete
  cleanup runs) and its `NetflixPendingRow`s. The message reports the
  counts. `Episode` stays excluded from the generic loop for other
  sources.
- **All of a source** (Data Management, `bulk_delete_by_import_source`):
  works from the same stamps — `_import_source_media_summary` lists the
  run's movie/tv/season counts under `netflix`, and deleting them cascades
  as above. `ImportRun` rows that are left with zero rows are swept away,
  taking any remaining pending rows with them.

Rows written before the stamping existed carry no `import_run` and are
deliberately not back-filled: their plays are not distinguishable from
other sources' plays, and deleting untagged rows would risk unrelated
history. On the test deployment the DB is rebuilt and re-imported after
the fix.

## The pending rows

Rows the importer cannot resolve — no unique TMDB title match, an
unparseable date, or a series row missing S/E — are saved as
`NetflixPendingRow` instead of dropped. The model is per-user, keyed
`one_pending_netflix_row` on `(user, title, watched_at)` **while pending**,
so re-imports stay quiet. It holds the parsed media type and S/E so the
review page can pre-fill them.

The review page (`/import/netflix/pending`,
`src/templates/integrations/netflix_pending.html`) is a standalone page
with a React island for the row list: `data-netflix-review-root` carries
the server-rendered rows as the no-JavaScript fallback, and
`netflix-review-props` (JSON) feeds the shared presentation
`frontend/pages/NetflixReviewView.jsx`, mounted by
`frontend/pages/mountNetflixReview.jsx` (search via the view's
`?format=json` branch, resolve/dismiss via form POSTs through
`transport.web.js`). Each row card has a per-row TMDB search (top 8,
movie/TV toggle), the resolve form (which posts back to the shared
`NetflixResolver.record_play`), and a dismiss button. Resolved/dismissed
rows stay visible under `?show=all` with their outcome; nothing is ever
deleted. Rows are scoped to the logged-in user in every view.

The list is server-paged (`?page=`, 100 rows via Django's `Paginator`)
and globally filtered by title (`?filter=`, `title__icontains`). The
filter input, the Prev/Next links, the row count and the Pending/All tabs
are plain server-rendered chrome around the island — they work in the
no-JavaScript fallback and the React island renders only the current
page's cards (the island's props carry one page's rows). Resolve/dismiss
redirect back through the same list, preserving `show`/`filter`/`page`
(`_netflix_review_return`), and the per-row TMDB search form carries them
as hidden inputs. A filter that matches nothing offers a "Clear filter"
reset link.

## Deliberate boundaries

- German and English labels are the supported marker set. Any other
  Netflix UI locale produces different markers; rows from such an export
  land on the review page instead of being parsed.
- `Teil N`/`Part N` is never an episode number; as a standalone segment it
  is a season only when it follows the series name and another segment.
- Localized episode titles that do not match the season's TMDB names stay
  pending; the shortcuts above only ever resolve a row that exactly one
  candidate can hold — the importer never guesses between candidates, and
  never uses the watch date or the release year to break a title tie
  (rewatches make the date a guess).
- A title with no unique TMDB match stays pending until a human picks one.
- Rows whose TMDB season genuinely does not exist (`season_missing`) or
  whose episode name TMDB does not know stay pending; those are provider
  data gaps, not importer failures.

## Tests

`src/integrations/tests/imports/test_netflix.py` covers the title/date
heuristics (including the English markers, `Part`/`Teil`/`Volume`
semantics, colon show names, `_episode_title`), movie and episode
recording (including title matching and `Part`-as-season rows), the
`resolve_row` shortcuts (season narrowing, part continuation, season-by-
episode, unlabelled anthology episode, and the ambiguity cases that must
stay pending), the pending paths, re-import idempotency, the review views
(server search, the island's JSON search, the island props, resolve,
dismiss, user scoping, 100-row paging, the `?filter=` narrowing, and
resolve/dismiss preserving `show`/`filter`/`page`), the import-run
provenance (stamping of new movie/show/episode/pending rows, no re-tagging
on re-import, and the review-page resolve stamping plays with the row's
run), the Celery task wiring, and the TMDB precondition. The undo paths
live in `src/users/tests/views/test_rollback_import_run.py` (the Netflix
branch: plays under pre-existing shows, the cascade of run-created shows,
other sources keeping episode history) and
`src/users/tests/views/test_bulk_delete_by_import_source.py` (tagged rows
listed under their source, TV delete cascading to episode plays).
