# Metadata & provider tokens: current architecture inventory

This document has one responsibility: inventory the current instance-provider
credential loading and consumer boundaries, then record the compatibility
contract a future resolver must satisfy. It does not define a model, resolver
implementation, form, or migration.

## Reviewed base

| Item | Reviewed value |
|---|---|
| Earlier planning baseline | `80844026` |
| Current base | `414c6530` (`origin/latest` when reviewed) |
| Delta | 30 commits |

The credential declarations and their defaults did not change in that delta.
The relevant changes were:

- PR #729 added boosted-navigation feedback in `src/templates/base.html`.
  `src/users/urls.py`, `src/users/views.py`, `src/templates/users/base.html`, and
  `src/templates/users/integrations.html` remained byte-unchanged.
- PR #730 added API/MCP progress fields and IGDB search output. It changed an
  IGDB search cache version, but not IGDB credential loading.
- PR #735 separated Redis roles: the Django cache uses `REDIS_CACHE_URL`, the
  Celery broker and result backend can use their own URLs, and `REDIS_URL`
  remains the fallback.
- PR #737 and its stack added configurable data paths and hardened generated
  `SECRET` handling. The provider `secret()` helper and provider declarations
  were not changed.
- PR #685 isolated browser/date-picker and CSV export tests from live provider
  behavior and wall-clock timing. It changed tests only.
- PR #738 normalized provider episode calendar dates to UTC midnight, leaves
  invalid years `<=1900` and `9999` null, and conditionally fills only a null
  stored date so an existing or concurrently written trusted date survives.

PRs #685 and #738 did not change provider credential declarations, Django
settings behavior, or migrations. The Settings route/view/template files named
above remain byte-unchanged from `80844026`.

## Credential declarations and precedence

All declarations are in `src/config/settings.py`. A relative `_FILE` value is
read below `/run/secrets`; an absolute value is read directly. File contents are
stripped. Last.fm is the only family below without a `_FILE` input.

| Family | Django setting / primary environment | File environment | Built-in fallback |
|---|---|---|---|
| TMDB | `TMDB_API` | `TMDB_API_FILE` | non-empty shared key |
| TVDB | `TVDB_API_KEY` | `TVDB_API_KEY_FILE` | empty |
| TVDB | `TVDB_PIN` | `TVDB_PIN_FILE` | empty |
| MyAnimeList | `MAL_API` | `MAL_API_FILE` | non-empty shared client ID |
| IGDB | `IGDB_ID` | `IGDB_ID_FILE` | non-empty shared client ID |
| IGDB | `IGDB_SECRET` | `IGDB_SECRET_FILE` | non-empty shared client secret |
| Steam | `STEAM_API_KEY` | `STEAM_API_KEY_FILE` | empty |
| BoardGameGeek | `BGG_API_TOKEN` | `BGG_API_TOKEN_FILE` | non-empty shared token |
| Hardcover | `HARDCOVER_API` | `HARDCOVER_API_FILE` | non-empty shared `Bearer` token |
| Comic Vine | `COMICVINE_API` | `COMICVINE_API_FILE` | non-empty shared key |
| Last.fm | `LASTFM_API_KEY` | none | empty |
| Trakt | `TRAKT_API` | `TRAKT_API_FILE` | empty |
| Trakt | `TRAKT_API_SECRET` | `TRAKT_API_SECRET_FILE` | empty |
| AniList | `ANILIST_ID` | `ANILIST_ID_FILE` | empty |
| AniList | `ANILIST_SECRET` | `ANILIST_SECRET_FILE` | empty |
| SIMKL | `SIMKL_ID` | `SIMKL_ID_FILE` | non-empty shared client ID |
| SIMKL | `SIMKL_SECRET` | `SIMKL_SECRET_FILE` | non-empty shared client secret |

The current value order is explicit primary environment, `_FILE` contents, then
built-in fallback. The expression is `config(PRIMARY,
default=secret(FILE, fallback))`. Python evaluates `secret(...)` before calling
`config(...)`, so a configured primary value does **not** protect startup from
a configured but unreadable `_FILE`; the file read can raise first.

The future value order is **explicit environment -> `_FILE` -> app-managed ->
built-in/default**. Compatibility also requires preserving the current eager
startup failure exactly: initialization must read and validate a configured
`_FILE` even when an explicit environment value will win value resolution.

## Direct consumers

These are the production symbols found by the current direct-read scan,
including `getattr(settings, ...)` reads. Each field is independent; paired
fields may resolve from different sources. The operation column is the boundary
the later resolver and direct-read contract test must preserve.

| Field | Exact direct symbols | Operation boundary |
|---|---|---|
| `TMDB_API` | `app.providers.tmdb.base_params`; `app.discover.providers.tmdb_adapter.TMDB_BASE_PARAMS` (module scope); `app.management.commands.backfill_discover_metadata.Command._tmdb_fetch` | TMDB request parameters for normal metadata/search, Discover, and the backfill command |
| `TVDB_API_KEY` | `app.providers.tvdb.enabled`; `app.providers.tvdb._get_token`; `app.services.metadata_resolution.provider_is_enabled` | configured-state inference and TVDB login `apikey` |
| `TVDB_PIN` | `app.providers.tvdb._get_token` | optional TVDB login `pin` only; it does not determine `enabled()` |
| `MAL_API` | `app.providers.mal.search`, `.anime`, `.manga`; `app.discover.provider_candidates._mal_manga_ranking_candidates.fetcher`; `integrations.imports.mal.MyAnimeListImporter._get_whole_response` | MAL client-ID header for metadata, Discover, and imports |
| `IGDB_ID` | `app.providers.igdb.get_access_token`, `.external_game`, `.search`, `.game`, `.company_profile`, `._fetch_games_by_ids`; `app.discover.provider_candidates._igdb_games_candidates.fetcher`; `app.services.game_lengths.fetch_igdb_time_to_beat`; `lists.models.CustomList._get_igdb_backdrop` | Twitch token client ID and IGDB `Client-ID` request header |
| `IGDB_SECRET` | `app.providers.igdb.get_access_token` | Twitch client-credentials token acquisition only |
| `STEAM_API_KEY` | `integrations.imports.steam.SteamImporter.__init__` | Steam importer API key captured per importer instance |
| `BGG_API_TOKEN` | `app.providers.bgg.search`, `._fetch_thumbnails`, `.boardgame`; `app.discover.provider_candidates._bgg_hot_candidates` | BGG bearer header for metadata and Discover |
| `HARDCOVER_API` | `app.providers.hardcover._authorization_header` | normalized Hardcover authorization header used by provider calls |
| `COMICVINE_API` | `app.providers.comicvine.search`, `.comic`, `.get_volume_issues`, `.get_publisher_comics`, `.search_issues`, `.comic_issue`, `.issue`, `.person_profile`; `app.discover.provider_candidates._comicvine_volume_candidates`, `._comicvine_coming_soon_volume_candidates` | Comic Vine API parameter for metadata, people, issue, and Discover requests |
| `LASTFM_API_KEY` | `integrations.lastfm_api._make_api_request`; `app.discover.provider_candidates._lastfm_top_tracks_candidates` | Last.fm integration calls and Discover top tracks; configured-state check is part of each symbol |
| `TRAKT_API` | `app.providers.trakt.is_configured`, `._headers`; `app.discover.providers.trakt_adapter.TraktDiscoverAdapter._cache_request`; `integrations.views.trakt_oauth`; `integrations.imports.trakt.handle_oauth_callback`, `.get_username_from_oauth`, `.get_access_token`, `.TraktImporter._make_api_request`; `lists.imports.trakt._make_trakt_request`; `users.views.import_data`; `users.onboarding_views.onboarding_service_setup` | instance Trakt configured state, metadata/Discover headers, OAuth start/exchange/refresh, profile/list imports, and UI inference |
| `TRAKT_API_SECRET` | `integrations.imports.trakt.handle_oauth_callback`, `.get_access_token`; `users.views.import_data`; `users.onboarding_views.onboarding_service_setup` | instance OAuth code/refresh exchange and paired configured-state inference; no metadata header use |
| `ANILIST_ID` | `integrations.views.anilist_oauth`; `integrations.imports.anilist.get_token` | OAuth authorization redirect and token exchange client ID |
| `ANILIST_SECRET` | `integrations.imports.anilist.get_token` | OAuth token exchange client secret only |
| `SIMKL_ID` | `integrations.views.simkl_oauth`; `integrations.imports.simkl.get_token`, `.get_username`, `.SimklImporter._get_user_list` | OAuth redirect/exchange and SIMKL API-key headers |
| `SIMKL_SECRET` | `integrations.imports.simkl.get_token` | OAuth token exchange client secret only |

`src/config/test_settings.py` supplies test-only Steam and Trakt overrides; it
is not a production source.

### Module-scope capture

`src/app/discover/providers/tmdb_adapter.py` builds `TMDB_BASE_PARAMS` at module
import with `settings.TMDB_API` and `settings.TMDB_LANG`. Every other direct
credential read above occurs inside a function, method, or instance
initializer. A runtime-editable credential cannot take effect in that TMDB
adapter until this module-scope capture is removed or rebuilt.

### Verified indirect operation boundaries

This category map records the contexts that must be exercised when consumers
move to the resolver. It names concrete verified edges without claiming that
every possible dynamic provider call is statically enumerable.

| Context | Verified indirect consumers and behavior |
|---|---|
| Interactive routing | `src/app/providers/services.py` dispatches search and metadata work to TMDB, TVDB, MAL, IGDB, BGG, Hardcover, and Comic Vine. `src/app/services/metadata_resolution.py` filters TVDB availability. Verified callers include `src/app/search_views.py`, metadata/detail/people views, `src/api/views.py`, `src/lists/views_recommendations.py`, and `src/lists/views_add_reorder.py`. |
| Discover and statistics | `src/app/discover/provider_candidates.py` and the TMDB/Trakt adapters fetch credentialed rows. `src/app/statistics_views.py` calls `tvdb.enabled()` for its page contexts. |
| TVDB background work | `src/app/tasks_genre.py` gates genre backfill on `tvdb.enabled()` and calls TVDB lookup/genre helpers. `src/app/tasks_metadata_cache.py` derives TVDB metadata cache keys. `src/app/tasks_tv_provider_migration.py` and `src/app/services/tv_provider_migration.py` gate and fetch TVDB migration data. |
| Other background work | `src/app/tasks_trakt.py` calls the Trakt provider for popularity and episode ratings. `src/app/tasks_providers.py`, `src/app/tasks_episode.py`, and `src/app/tasks_metadata_cache.py` fetch through provider services. Calendar modules under `src/events/calendar/` use provider services and direct TMDB, TVDB, MAL, and Comic Vine modules. Last.fm tasks in `src/integrations/tasks/_lastfm.py` call `src/integrations/lastfm_api.py`. |
| OAuth and imports | Trakt, AniList, and SIMKL redirects in `src/integrations/views.py` use instance client IDs; matching modules under `src/integrations/imports/` exchange tokens with instance secrets. MAL, Steam, Trakt, AniList, and SIMKL Celery entry points in `src/integrations/tasks/_media_imports.py` call their importers. Plex, SIMKL, and Trakt importers also call TVDB where source mapping requires it. |
| Webhooks and API ingestion | `src/integrations/webhooks/base.py` uses TVDB for anime/source resolution. `src/integrations/webhooks/plex.py`, `src/integrations/webhooks/stremio.py`, `src/api/fork_views_playback.py`, and `src/api/fork_views_scrobble.py` call TMDB directly or through provider services. |
| Cache and migration operations | `src/app/metadata_sync_views.py` derives TVDB invalidation keys. `src/app/management/commands/merge_duplicate_provider_items.py` checks TVDB availability before provider-item work. |
| Management backfills | `backfill_discover_metadata` reads TMDB directly. `backfill_trakt_popularity` calls the Trakt provider, which reads the instance Trakt client ID. |

Configuration inference is also observable UI behavior:

- `src/users/views.py` computes `tvdb_enabled` through metadata resolution for
  `src/templates/users/preferences.html`.
- `src/app/statistics_views.py` computes `tvdb_enabled` through
  `tvdb.enabled()` for `src/templates/app/statistics.html`.
- `src/users/views.py` and `src/users/onboarding_views.py` compute
  `trakt_configured` from the instance Trakt pair for
  `src/templates/users/import_data.html` and
  `src/templates/users/onboarding/components/connect_trakt.html`.
- `src/lists/views_list_browse.py` computes `trakt_has_credentials` from the
  per-user `TraktAccount` for `src/templates/lists/custom_lists.html`. This is
  the per-user exception below, not instance resolver state.

### Existing per-user Trakt exception

`src/integrations/models.py::TraktAccount` already stores an encrypted Trakt
client ID and secret per user for custom-list imports. The write/OAuth path is
`src/lists/views_trakt.py`; decryption is centralized in
`src/lists/views_helpers.py::_get_trakt_credentials`; the resulting client ID
is passed to `src/lists/tasks.py` and `src/lists/imports/trakt.py`.

This is separate from the instance `TRAKT_API` / `TRAKT_API_SECRET` used by
private-profile imports and provider metadata. A future instance resolver must
not replace, migrate, or reinterpret `TraktAccount` ciphertext.

## Cache and token invalidation boundaries

Current behavior uses static bearer-token keys:

- IGDB caches its client-credentials bearer token under
  `igdb_access_token`. It deletes that key after an unauthorized response and
  otherwise retains it until the provider-reported expiry minus 60 seconds.
- TVDB caches its bearer token under `tvdb_v4_access_token` for 12 hours. It
  deletes that key on an unauthorized response before one retry. TVDB metadata
  uses separate `tvdb_v4_*` keys.
- TMDB discovery captures the API key at module import as described above.
- Other provider response caches are not credential stores. Changing a
  credential should not imply a global cache clear.

Since PR #735, these static keys live in Django's default cache at
`REDIS_CACHE_URL` (falling back to `REDIS_URL`). Celery queue state uses
`CELERY_BROKER_URL`, and Celery results use `CELERY_RESULT_BACKEND`, each
falling back to `REDIS_URL`. Cache, broker, and result storage cannot be assumed
to share a URL.

Future IGDB and TVDB bearer caches must be namespaced by the resolver's
`configuration_version`; the current static key names are not the future
contract. A successful credential change captures the old
`configuration_version`, commits the new configuration, invalidates only the
old version's affected bearer-token namespace, and invalidates non-secret
resolver state across workers so they observe the new version. It must never
globally clear Django's cache or flush Redis.

## Current Settings boundary

- `django.contrib.auth.middleware.LoginRequiredMiddleware` protects Settings.
  The existing Settings views have no staff or superuser requirement.
- Provider credentials are currently instance-wide process configuration and
  are not writable through Settings. There is therefore no current
  application-level permission for changing them.
- Preferences rejects writes by demo users. The Integrations page and several
  of its POST endpoints do not establish an instance-administration boundary.
  A credential editor must define and test its own narrow permission instead
  of treating ordinary Settings access as authority over shared secrets.

## Settings and Integrations compatibility constraints

The reviewed domain label is **Metadata & provider tokens**.

- Keep `/settings/integrations`, URL name `integrations`,
  `users.views.integrations`, and `users/integrations.html` unchanged.
- Keep the Integrations page's API token, media-server/webhook content, copy,
  forms, and POST destinations. Preserve `?onboarding=...` and the
  `?open=<integration>` deep-link filter. Preserve redirects to `integrations`,
  submitted `next`, and the existing `/settings/integrations` referer fallback.
- Metadata language, watch-provider region, and TV/anime metadata-source
  defaults remain user Preferences. They are not instance credentials.
- `src/templates/users/base.html` marks items active by exact path. A new route
  needs its own exact-path entry.
- The shared Settings link in `src/templates/base.html` currently recognizes
  Account, Notifications, Sidebar/UI, Preferences, Home Screen, Integrations,
  Import, and Export. It does not include RSS, Advanced, or About. Add the new
  page deliberately; do not use this omission to relabel or fold existing
  pages together.
- Boosted navigation from PR #729 is part of the current shared shell and must
  continue to receive a full visible page response.

## Documentation and generated surfaces for later work

| Surface | Current state / later obligation |
|---|---|
| `AGENTS.md` | Only AGENTS file in the checkout; update repository map, validation, and Settings rules when implementation exists. No nested `AGENTS.md` was found. |
| `CLAUDE.md` | None was found. Do not add one only for this feature. |
| `CONTRIBUTING.md` | Contributor validation and UI screenshot rules apply; add a feature-specific rule only if implementation needs one. |
| `README.md` | Current operator credential list, `_FILE` examples, and Trakt OAuth guide must describe the final precedence and UI without removing environment compatibility. |
| `mcp_server/README.md` | Currently documents user `manage_settings` and the API token location. Update only if the MCP contract or token location changes. |
| `src/api/schema.py`, `src/api/serializers.py`, `src/api/views.py`, `src/config/urls.py` | OpenAPI is generated at `/api/schema/`; there is no checked-in generated schema file. Update source annotations only if a credential API is intentionally exposed. |
| `docs/agents/metadata-backfill.md`, `docs/agents/media_type_integration.md`, `docs/agents/lastfm_integration.md` | Provider/backfill guidance must use the resolver once it exists. |
| `docs/agents/dev_release_diff_report.md` | Temporary release/wiki staging document contains provider configuration references; reconcile it only if it remains active when the feature lands. |
| Project wiki | The local `wiki/` checkout is empty here. The README links external configuration and API pages; update the separate wiki repository during release work. |

## Future resolver contract

One provider-credential resolver must serve every instance consumer above. Its
observable invariants are:

| Concern | Required invariant |
|---|---|
| Field independence | Resolve each of the 17 fields independently. A pair may be mixed-source: for example `IGDB_ID` may come from environment while `IGDB_SECRET` is app-managed. Do not choose one source for an entire family. |
| Value precedence | For each field: explicit environment -> `_FILE` -> app-managed -> built-in/default. Preserve every current environment name, `_FILE` path rule, whitespace handling, and built-in/default value. |
| Eager file compatibility | During settings initialization, read and validate every configured `_FILE` before selecting the effective value. A bad configured file must keep failing startup even when explicit environment wins. |
| Startup snapshot | Settings initialization captures only non-secret source-presence booleans for every field, not process values. Resolver/status requests use that snapshot and do not reread `os.environ`, Decouple, or secret files. Environment or `_FILE` changes require process restart; app-managed version changes do not. |
| Resolver purity | Resolution performs zero provider/network calls. An explicit **Test** action may call a provider after resolution; ordinary status, render, and save paths may not. Saving must not mutate Django settings or process environment. |
| Query boundary | Normal operator/provider hot paths perform zero credential-table queries when their version-bound consumer state is warm. An explicit operator status read may make one bounded query for all app-managed field states, never one query per field or family. |
| Non-secret shared state | Cross-worker/Django cache may contain only `configured`, effective `source`, `configuration_version`, and `editability` per field. It must contain no plaintext credential and no ciphertext. Source/editability status comes from the startup snapshot plus bounded database state, not by rereading process values. |
| Decryption | Decrypt an app-managed value only on a credential consumer's version-bound process-local miss or an explicit **Test** action. Never decrypt to render source/configured/editability status. Plaintext and ciphertext must never enter shared cache, logs, templates, API output, Celery arguments, or persisted status snapshots. |
| Concurrent change | A consumer cheaply rechecks non-secret source/version before using resolved material. If it changed during resolution or token acquisition, discard the stale result and retry a bounded number of times; do not loop without limit. |
| Bearer tokens | IGDB and TVDB bearer keys are namespaced by the captured `configuration_version`. After a successful change, invalidate only the captured old version's affected namespace and non-secret resolver state across workers. Never globally clear Django cache or flush Redis. |
| Direct reads | Direct credential access is allowed only during `src/config/settings.py` initialization and inside resolver internals. There are no current operator-only runtime exceptions. Any future exception must be recorded here by exact module, symbol, and field and added to the direct-read contract test before merge. |
| Existing data | Do not rewrite existing ciphertext or persisted data, including `TraktAccount` and encrypted OAuth/task values. Do not mutate environment/settings to simulate a write. |

The direct-read contract test must cover the exact field/symbol inventory above,
including `getattr(settings, ...)` and module-scope reads, and fail on an
unlisted runtime read.
