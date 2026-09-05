# Grouped anime

Floppy stores TV-shaped anime as grouped anime: the parent remains an `Item`
with `media_type="tv"`, while the parent, seasons, and episodes use
`library_media_type="anime"`. This preserves Floppy's TV season/episode
history model and keeps the title in the Anime library.

## Which shape the Anime library uses

The Anime library's storage shape follows each user's **Anime Provider**:

- **TMDB or TVDB** (the default) stores anime as grouped anime - a TV-shaped
  row with a real season and episode tree, exactly like TV Shows.
- **MyAnimeList** stores flat `Anime` rows, one per cour, with progress but no
  per-episode history.

The shape is decided once, when a show is first tracked, and then stays put.
Changing the Anime Provider only affects newly added shows: MAL identity is per
cour while TMDB/TVDB identity is per show, so the mapping is N:1 and cannot be
re-derived in bulk without guessing at or dropping history. When the preference
changes and existing anime is in the other shape, Floppy offers a conversion
instead of performing one, and leaves anything it cannot convert safely alone.

## Where a scrobble lands

Routing is sticky. Once a show has a home in the Anime library - in either
shape - every later episode goes there, whether or not the Anime-IDs snapshot
happens to load on that request and whether or not the per-season mapping
covers that episode. An episode that no MAL entry can accept is dropped with a
warning rather than opening a row in TV Shows.

Before this rule existed, a show could land in Anime on one episode and in TV
Shows on the next and accrue progress in both. The scheduled **Repair
duplicated anime libraries** task folds any such pairs back into one row; a
pair it cannot resolve safely is reported and left untouched.

An anime-native id in the payload - an AniDB id from Plex/HAMA or from a
scrobble client - selects *which entry* the episode belongs to. It never selects
the shape. When such a payload carries no TMDB or TVDB id, the franchise
identity is derived from the pinned mapping first, so the rule above still
decides where the episode lands. The one case that has no choice is a MAL entry
the mapping gives no TMDB or TVDB identity for: nothing can be resolved or
classified, so the flat row is the only shape available and the reason is
logged.

`anime_library_mode` is a display setting on top of this. It decides which
library surfaces grouped anime - Anime, TV Shows, or both - and never changes
where a scrobble is stored.

## Which paths follow this rule

Every path that can create a show now shares one decision, so a title lands in
the same library whichever way it arrived. The shared pieces are
`metadata_resolution.prefers_grouped_anime`,
`metadata_resolution.find_existing_anime_home` and `grouped_anime.classify`;
importers compose them through `grouped_anime.AnimeRouteResolver`, which caches
per run because importers buffer their rows and flush at the end.

| Path | Follows the rule |
|---|---|
| Webhooks (Plex, Jellyfin, Emby, Kodi, Stremio) | Yes |
| Trakt import | Yes, decided once per show and inherited by season and episode rows |
| Plex import | Yes. A section named "Anime" still routes a title the classifier has no verdict on, but cannot override a positive "not animation" verdict |
| Stremio import | Yes |
| Simkl import | Yes. Anime always lands in the Anime library; the old per-import destination option is gone |
| Sonarr | No, deliberately. Its `seriesType` is a downloader release-parsing mode, not a claim about the title |
| MyAnimeList, AniList, Kitsu | No, deliberately. These are MAL-identity-native and carry no TMDB/TVDB identity to key the lookup on |
| Yamtrack CSV | No, deliberately. A CSV import is a restore; the exported bucket is honoured verbatim |

A show whose Anime home is a flat MAL row is skipped by importers that can only
resolve TMDB identities, rather than being imported as TV: importing it would
track the same show in both libraries.

To move existing shows between shapes, use the per-show Move action or the
"Convert anime library shape" task, both of which ask first.

## Classification policy

The shared classifier is intentionally fail-closed. A title is routed to
grouped anime only when:

1. TMDB resolves the series and reports the `Animation` genre; and
2. an exact TMDB, TVDB, or IMDb identifier is present in Kometa's Anime-IDs
   mapping and has a MAL identity.

Titles that only share a name, are merely animated, or cannot be resolved stay
in TV. TVDB remains optional; TMDB plus exact Anime-IDs matches are sufficient.

The mapping is pinned to an Anime-IDs commit and canonical JSON digest in
`integrations/anime_mapping.py`. Workers compile that revision once and cache
the raw payload, reverse indexes, identity groups, revision, and digest. The
snapshot is immutable at the classifier boundary. A refresh validates the
payload before writing a versioned cache entry and last-known-good pointer:

```bash
python manage.py refresh_anime_mapping \
  --revision <40-character-commit-sha> \
  --expected-digest <64-character-sha256>
```

`--activate` may be used after review to mark a validated snapshot as the
fallback; changing the production pin still requires a code review and deploy.
If the pinned source is unavailable, the last-known-good snapshot is used. If
no valid snapshot exists, grouping is skipped and the item remains TV.

## Integration points

- Stremio library import classifies the resolved TMDB show before creating its
  TV, season, and episode rows.
- The Stremio playback-start webhook uses the same classifier before creating
  the in-progress episode structure.
- The importer loads one snapshot per run instead of rebuilding indexes for
  each series. Webhook tasks do the same for their eligible TV event.
- Exact IDs that resolve to separate connected-provider groups are reported as
  `conflicting_exact_external_ids` and left in TV. Multiple MAL seasons are
  combined only inside one stable `mapping_group_key`.
- Promotion locks the parent and descendants in primary-key order, checks
  target collisions inside the transaction, preserves row IDs and user-owned
  state, and uses the shared race-safe provider-link upsert.
- Playback-start admission is per-user and Redis-backed: duplicate events are
  deduplicated, at most eight pending items are admitted, entries expire after
  ten minutes, and Redis failure returns the normal empty subtitles response
  without direct dispatch. The 30-minute per-item throttle remains in place.
- Existing TV trees can be reviewed and promoted in place with:

```bash
python manage.py classify_grouped_anime --user <username>
python manage.py classify_grouped_anime --user <username> --apply
```

The command never changes primary keys or watch-history rows. It aborts an
individual title when the target anime bucket is already occupied by another
item, so a collision cannot create duplicate history.

## Validation

The normal application suite remains the source of truth. PostgreSQL row-lock
coverage is tagged `postgres` and can be run reproducibly with:

```bash
scripts/test_postgres.sh
```

The script starts an ephemeral PostgreSQL 16 container and removes only that
test container on exit. The upstream PR intentionally does not modify CI
workflow files because this repository rejects workflow changes from fork PRs;
the maintainer should enable the trusted PostgreSQL service job for the tagged
test.

## Upstream contribution boundary

The classifier, Stremio integrations, tests, and this document are product
changes suitable for an upstream pull request. Deployment image workflows,
private compose files, credentials, and host-specific migration reports stay
in the downstream fork/deployment branch.
