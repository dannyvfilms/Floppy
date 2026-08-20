# Per-Release / Per-Edition Tracking Implementation Plan (#907)

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax for tracking. Work
> chunk-by-chunk in the order listed — each chunk is meant to land as its own PR.
> Chunks 3-6 (Music) touch live scrobble matching and should be tested against real
> MusicBrainz data and a real scrobble source before merging; don't ship them
> unverified.

**Goal:** Resolve [#907](https://github.com/dannyvfilms/Floppy/issues/907) — let
users pin a specific MusicBrainz **Release** (a particular pressing: 1977 vinyl vs.
2011 CD remaster, etc.) to a tracked album, with real tracking effects (tracklist,
format, and scrobble attribution reflect the pinned release), not just a cosmetic
cover-art swap. Along the way, upgrade the existing Hardcover "book edition" feature
from cosmetic-only to the same real-tracking-effect model, and extract shared
picker plumbing where the two domains overlap.

**Core design decision:** pin one release/edition **per tracked `Item`** (per user),
not per individual play/read event. `Music.album` already FKs to a single `Album`
row; a release-group can already carry more than one release id, so we widen `Album`
so a specific pressing can be its own row instead of collapsing back onto the
release-group's "representative" row. Books have no per-play concept, so pinning is
the only option there too — see `docs/agents/music_integration.md` for the existing
music domain model and `src/app/metadata_sync_views.py` for the current cosmetic
edition flow.

**Background reading before starting:** `docs/agents/music_integration.md`,
`src/app/models/music.py`, `src/app/services/music_scrobble.py`,
`src/app/providers/musicbrainz.py`, `src/app/metadata_sync_views.py`,
`src/app/providers/hardcover.py`.

---

## Chunk 1 — Books: cached edition fields drive real progress (land first, lowest risk)

**Why first:** self-contained, no constraint migration, validates the "cached pin
fields → real tracking behavior" pattern end-to-end before touching music.

**Files:**
- Modify: `src/app/models/credits.py` (`HardcoverEditionPreference`)
- New: `src/app/migrations/016X_hardcover_edition_preference_cache_fields.py`
- Modify: `src/app/providers/hardcover.py` (`_get_edition`, `editions`, `book`)
- Modify: `src/app/metadata_sync_views.py` (`set_hardcover_edition`)
- Modify: `src/app/services/tracking_hydration.py` (edition upsert at tracking time, ~line 420)
- Modify: `src/app/models/media.py` (`Book.formatted_progress`, `Book.progress_unit`)
- Modify: `src/app/models/media.py` / wherever `process_progress` calls
  `providers.services.get_media_metadata` for books (needs `edition_id` passed through)
- Tests: `src/app/tests/providers/test_hardcover_editions.py`,
  `src/app/tests/views/test_hardcover_edition_views.py`, `src/app/tests/test_credits.py`

- [ ] **Step 1: Add cached fields to `HardcoverEditionPreference`**
  - Add `format = models.CharField(max_length=32, blank=True, default="")`,
    `number_of_pages = models.IntegerField(null=True, blank=True)`,
    `isbn = models.CharField(max_length=32, blank=True, default="")`,
    `synced_at = models.DateTimeField(null=True, blank=True)`.
  - Additive migration only — no backfill, existing rows just get nulls/defaults
    until next resolve.

- [ ] **Step 2: Confirm/add per-edition `pages` in the Hardcover GraphQL queries**
  - In `_get_edition` (`hardcover.py:303`) and `editions` (`hardcover.py:352`), add
    `pages` to the `editions_by_pk { ... }` and `editions { ... }` field selections
    (Hardcover's schema exposes `pages` on the `editions` type — **verify against
    the live API/schema introspection at home**, since this session can't reach it).
  - If `pages` isn't available per-edition in the real schema, fall back to keeping
    `number_of_pages` sourced from the book level but still cache `format`/`isbn`
    per edition (format is the more common source of real per-edition variance:
    audiobook vs. physical vs. ebook).

- [ ] **Step 3: Use per-edition `pages` in `book()`'s `max_progress`**
  - `hardcover.book()` (`hardcover.py:164-300`) currently always sets
    `max_progress`/`details.number_of_pages` from `book_data.get("pages")`,
    ignoring the selected edition. Change to prefer
    `selected_edition.get("pages")` when present, falling back to book-level pages.

- [ ] **Step 4: Cache edition fields at pin time**
  - `set_hardcover_edition` (`metadata_sync_views.py:266-311`) already calls into
    edition resolution indirectly via cache-busting; add an explicit
    `hardcover._get_edition(edition_id)` call and populate
    `format`/`number_of_pages`/`isbn`/`synced_at` on the
    `HardcoverEditionPreference` row in the same `update_or_create`.
  - Do the same in `tracking_hydration.py` (~line 420-431) where an edition is
    chosen at initial-tracking time, so first-track and later-repin both populate
    the cache.

- [ ] **Step 5: Make `Book.formatted_progress`/`progress_unit` edition-aware**
  - In `src/app/models/media.py` (`Book` class, ~968-1000), look up the current
    user's `HardcoverEditionPreference` for `self.item` (when present and
    `format` is cached) and use its `format` instead of `self.item.format` to
    decide pages vs. audiobook-minutes display. Fall back to `item.format` when
    no pin exists or the cache is empty (graceful degradation — don't hard-fail
    on old un-cached preference rows).

- [ ] **Step 6: Make `process_progress`'s `max_progress` edition-aware for books**
  - Find the `providers.services.get_media_metadata(...)` call used for books'
    `max_progress` (`src/app/models/media.py`, in `process_progress`) and pass
    `edition_id=` from the user's `HardcoverEditionPreference` (if any) — mirrors
    how `get_media_metadata` already accepts `edition_id` for display purposes
    (`src/app/providers/services.py:568-575`, used at line ~698).

- [ ] **Step 7: Tests**
  - Extend `test_hardcover_editions.py` / `test_hardcover_edition_views.py` to
    cover: pinning an edition caches format/pages; `book()` returns edition-scoped
    `max_progress` when an edition with `pages` is selected; `set_hardcover_edition`
    populates the new fields.
  - Add a `Book.progress_unit`/`formatted_progress` test with a pinned
    audiobook-format edition vs. no pin vs. a pin with stale/null cache fields.
  - Run: `pytest src/app/tests/providers/test_hardcover_editions.py src/app/tests/views/test_hardcover_edition_views.py src/app/tests/test_credits.py`

**Verify at home:** confirm Hardcover's `editions` GraphQL type actually exposes
`pages` (introspect the live schema or check a real response) before relying on
per-edition page counts; if it doesn't, ship with format-only per-edition caching
and note pages as book-level-only in the model docstring.

---

## Chunk 2 — Shared variant-picker scaffolding

**Why now:** do this once Chunk 1 exists as a concrete caller, so the abstraction
isn't designed speculatively. Music (Chunk 6) becomes the second caller.

**Files:**
- New: `src/app/services/variant_tracking.py`
- Rename/generalize: `src/templates/app/components/hardcover_edition_results.html` →
  `src/templates/app/components/variant_results.html`
- Modify: `src/templates/app/components/media_metadata_panel.html` (~115-150)
- Modify: `src/app/track_modal_views.py` (~564-566, hardcoded gate)
- Modify: `src/app/metadata_sync_views.py` (route book edition endpoints through
  the shared dispatch, keep existing URLs working)

- [ ] **Step 1: Define the shared variant shape**
  - A plain list of dicts with common keys: `id`, `label`, `subtitle`, `image`,
    `format`, `is_selected`. Book editions and (later) music releases both map
    into this shape before rendering.

- [ ] **Step 2: `variant_tracking.py`**
  - `list_variants(media_type, source, media_id) -> list[dict]` — dispatches to
    `hardcover.editions()` (mapped into the shared shape) for books; raise/return
    empty for unsupported combos until music is added in Chunk 6.
  - `set_pinned_variant(user, item, variant_id) -> None` — dispatches to the
    book-specific `HardcoverEditionPreference` upsert (reuse the logic from
    `set_hardcover_edition`), sharing cache-busting and messaging.
  - `supports_variant_selection(media_type, source) -> bool` — returns `True` for
    `(BOOK, HARDCOVER)` only, for now.

- [ ] **Step 3: Generalize the template**
  - Rename `hardcover_edition_results.html` → `variant_results.html`, parameterize
    row labels (title/subtitle/format) off the shared dict shape instead of
    Hardcover-specific field names. Keep the existing POST/preview-link behavior.

- [ ] **Step 4: Replace the hardcoded gate**
  - `track_modal_views.py:564-566`: swap
    `media_type == BOOK and source == HARDCOVER` for
    `variant_tracking.supports_variant_selection(media_type, source)`.

- [ ] **Step 5: Tests**
  - Cover `list_variants`/`set_pinned_variant` dispatch for books, and that the
    generalized template renders identically to the old `hardcover_edition_results.html`
    for existing book fixtures (regression-check via
    `test_hardcover_edition_views.py`).
  - Run: `pytest src/app/tests/views/test_hardcover_edition_views.py`

---

## Chunk 3 — Music schema: widen `Album` to allow a pinned release per release-group

**Risk:** touches a live uniqueness constraint and a hot scrobble-matching path.
**Ship Chunk 3 and Chunk 4/5 together** — don't deploy the schema change without the
matching scrobble lookup-order fix, or old code can create duplicate `Album` rows
against the new schema.

**Files:**
- Modify: `src/app/models/music.py` (`Album`)
- New: `src/app/migrations/016X_album_release_uniqueness.py`
- New: `src/app/migrations/016X_album_release_preference.py` (new
  `AlbumReleasePreference` model)

- [ ] **Step 1: Change `Album` uniqueness**
  - Current: `unique_album_per_artist_release_group` on `(artist, musicbrainz_release_group_id)`.
  - New constraints:
    - `unique(artist, musicbrainz_release_id)` where `musicbrainz_release_id IS NOT NULL`
      (one row per pinned pressing).
    - `unique(artist, musicbrainz_release_group_id)` scoped to
      `musicbrainz_release_id IS NULL` (keeps exactly one "unpinned/representative"
      row per release-group — preserves today's behavior for the common case).
  - This is schema-only; no data migration needed since existing rows already
    satisfy both new constraints (at most one row per `(artist, release_group)`
    today).

- [ ] **Step 2: Add `AlbumReleasePreference`**
  - Mirrors `HardcoverEditionPreference`: `user` FK, `item` FK, `album` FK (to the
    specific pinned `Album` row), unique on `(user, item)`. Per-user rather than a
    boolean on `Album`, so two users tracking the same artist can pin different
    pressings without fighting over a shared flag.

- [ ] **Step 3: Tests**
  - Migration test / model test: two `Album` rows for the same `(artist,
    release_group)` with different non-null `musicbrainz_release_id` values are
    both allowed; a second null-release_id row for the same `(artist,
    release_group)` is rejected.
  - Run: `pytest src/app/tests/test_music*.py -k album`

---

## Chunk 4 — Music service layer: resolve and populate a pinned release

**Files:**
- Modify: `src/app/providers/musicbrainz.py` (add `get_releases_for_group`)
- Modify: `src/app/services/music.py` (`resolve_pinned_release`,
  `ensure_album_has_release_id`, `populate_album_tracks`)
- Modify: `src/app/tasks_music.py` (healing/backfill, ~314, 600-900)

- [ ] **Step 1: `get_releases_for_group(release_group_id)` in `musicbrainz.py`**
  - Query MB `release` endpoint filtered by `release-group`, `inc=media+labels`.
  - Return `[{release_id, title, date, country, status, packaging, barcode, label,
    catno, track_count, disambiguation}, ...]` — the fields the picker UI needs
    (Lidarr-style format/label/country display).
  - Cache aggressively (mirror the existing `musicbrainz_release_for_group_*`
    cache key pattern) — only fetch when a user opens the picker, not on every
    album page view. Respect the existing `_rate_limit()` in
    `musicbrainz.py:167` (MB's public limit is ~1 req/sec).

- [ ] **Step 2: `resolve_pinned_release(user, item, release_id)` in `services/music.py`**
  - Find-or-create the `Album` row for this specific `musicbrainz_release_id`
    (reusing artist/title from the existing release-group row).
  - Call `populate_album_tracks` against this specific release (see Step 4).
  - Upsert `AlbumReleasePreference(user, item, album)`.
  - Re-point the user's relevant `Music`/`Item` rows at the new `Album` row.

- [ ] **Step 3: Guard `ensure_album_has_release_id` against pinned rows**
  - `services/music.py` (~1458): no-op when the `Album` row already has a pin
    referencing it (check `AlbumReleasePreference` or an equivalent marker) —
    healing must never silently overwrite a user's chosen pressing.

- [ ] **Step 4: `populate_album_tracks` takes an explicit `release_id`**
  - `services/music.py` (~1524): currently derives a release id from the
    release-group; add a parameter so Chunk 4 Step 2 can force it to fetch tracks
    for the *specific* pinned release (tracklist/track count/duration can differ
    by pressing — this is the concrete non-cosmetic payoff for music).

- [ ] **Step 5: Audit `tasks_music.py` healing/backfill (~314, 600-900)**
  - Ensure backfill tasks skip or respect pinned `Album` rows rather than treating
    `musicbrainz_release_id` as always safe to overwrite.

- [ ] **Step 6: Tests**
  - `resolve_pinned_release` creates a distinct `Album` row and doesn't collide
    with the unpinned representative row.
  - `ensure_album_has_release_id`/backfill tasks leave pinned rows untouched.
  - Run: `pytest src/app/tests/providers/test_musicbrainz.py src/app/tests/test_music_scrobble_service.py`

**Verify at home:** real MusicBrainz release-group responses (multi-release
groups, releases with missing label/country data) — the picker UI needs to handle
sparse metadata gracefully.

---

## Chunk 5 — Scrobble healing respects pinned Album (ship with Chunk 3/4)

**Files:**
- Modify: `src/app/services/music_scrobble.py` (`_get_or_create_album`, ~line 615)

- [ ] **Step 1: Change lookup order**
  - If an incoming scrobble carries a release id matching a *pinned* `Album` for
    this artist/user, prefer that row. Otherwise fall back to today's behavior
    (the unpinned representative row for the release-group).
  - Must not create a second unpinned row when a pinned one already exists for
    the same release id — dedupe against `musicbrainz_release_id` first.

- [ ] **Step 2: Tests**
  - Scrobble resolution against a pinned vs. unpinned `Album` for the same
    release-group resolves correctly and doesn't duplicate rows.
  - Run: `pytest src/app/tests/test_music_scrobble_service.py`

**Verify at home:** run against a real scrobble source (Last.fm/ListenBrainz
import or live scrobble) with a manually pinned release to confirm plays land on
the pinned `Album`, not a fresh duplicate.

---

## Chunk 6 — Music views/URLs/templates for the release picker

**Files:**
- Modify: `src/app/metadata_sync_views.py` (add music dispatch alongside book's,
  or add `list_album_releases`/`set_album_release` and wire into
  `variant_tracking.py` from Chunk 2)
- Modify: `src/app/urls.py`
- Modify: `src/templates/app/music_album_detail.html`,
  `src/templates/app/components/detail_music_album.html`
- Modify: `src/app/music_album_views.py` (`album_detail` resolution order)
- Modify: `src/app/track_modal_views.py` (gating, if not already covered by Chunk 2)

- [ ] **Step 1: Extend `variant_tracking.py` for music**
  - `list_variants` dispatches to `musicbrainz.get_releases_for_group()` (mapped
    to the shared shape: `id=release_id`, `label=title`, `subtitle="{format} · {country} · {date}"`, etc.).
  - `set_pinned_variant` dispatches to `resolve_pinned_release` for music.
  - `supports_variant_selection` returns `True` for `(MUSIC, MUSICBRAINZ)` too.

- [ ] **Step 2: Views/URLs**
  - Add routes using the shared dispatch from Chunk 2 (or thin music-specific
    views calling into `variant_tracking.py`), wired in `urls.py` alongside the
    existing book edition routes.

- [ ] **Step 3: Templates**
  - Add a "Release" section to `music_album_detail.html` /
    `detail_music_album.html` (format/label/country/catalog#), reusing
    `variant_results.html` from Chunk 2 for the picker list.

- [ ] **Step 4: Album detail resolution order**
  - `music_album_views.py`'s `album_detail` view resolves which `Album` row to
    show using the same order as books: query-param preview > saved
    `AlbumReleasePreference` > default representative row.

- [ ] **Step 5: Tests + manual verification**
  - View tests for the new endpoints (list/set release), template smoke test.
  - Manual (via the `run-floppy` skill, or locally at home): open an album page,
    use the picker to select a different pressing, confirm tracklist/format
    update, then trigger a scrobble/play and confirm it resolves to the pinned
    `Album`.

---

## Chunk 7 — Backfill / cache-warm command (last, optional)

**Files:** New management command, e.g. `src/app/management/commands/warm_release_cache.py`

- [ ] Warm the MusicBrainz releases-for-group cache and Hardcover edition cache
  for active users' most-recently-viewed items, to avoid a burst of live API
  calls right after rollout. Not required for correctness — do this once real
  usage patterns from Chunks 1-6 are visible.

---

## Cross-cutting risks to keep in mind

- **MusicBrainz rate limits:** ~1 req/sec (`providers/musicbrainz.py:167`) — the
  releases-for-group list must be cached aggressively and fetched lazily
  (picker-open only).
- **Schema/scrobble deploy ordering:** Chunk 3 (constraint change) and Chunk 5
  (scrobble lookup-order fix) must ship in the same deploy — see Chunk 3 note.
- **Graceful degradation:** both `HardcoverEditionPreference` rows created before
  Chunk 1 and `Album` rows with no pin must keep working with today's behavior,
  not error, until they're naturally re-resolved.
- **Test coverage to add across chunks:** scrobble resolution pinned vs.
  unpinned; `Album` uniqueness edge cases (two users pinning the same release_id
  reuse one row); book progress-unit calc with/without a pin and with stale/null
  cache fields; shared variant picker renders both media types; gating helper
  excludes unsupported media types.
