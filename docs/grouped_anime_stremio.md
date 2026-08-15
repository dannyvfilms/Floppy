# Grouped anime from Stremio

Floppy stores TV-shaped anime as grouped anime: the parent remains an `Item`
with `media_type="tv"`, while the parent, seasons, and episodes use
`library_media_type="anime"`. This preserves Floppy's TV season/episode
history model and keeps the title in the Anime library.

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
