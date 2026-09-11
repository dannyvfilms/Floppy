# API token scopes

Scopes constrain what an `IntegrationToken` may reach. This is the contract a
third-party client (Nuvio, Stremio, Kodi, a scrobbler) is written against.

## Where the rules live

| Concern | Location |
|---|---|
| Scope vocabulary and descriptions | `src/api/scopes.py` (`SCOPE_DESCRIPTIONS`) |
| Which scope each endpoint needs | `src/api/scopes.py` (`VIEW_SCOPES`) |
| Enforcement | `api.authentication.HasScope`, installed globally in `REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"]` |
| Published per-operation scope | `x-required-scope` in `src/api/contracts/openapi.yaml` |
| Coverage guarantee | `api.tests.test_fork_scope_enforcement.ScopeMapCoverageTests` |

The coverage test has already paid for itself: the watched-state sync endpoints
landed unmapped, and unmapped means denied, so the change feed was unreachable
by exactly the clients it exists for until they were added here.

## The three credential kinds

| Credential | `request.auth` | Access |
|---|---|---|
| Session login | `None` | Everything the user can reach |
| Legacy `User.token` | `None` | Everything the user can reach |
| `IntegrationToken` | the token | Only what its scopes name |

Legacy account tokens are deliberately unrestricted. They predate scopes, they
are the credential every existing integration was set up with, and narrowing
them would break working installs. Scoping is what the named tokens are for.

## Enforcement rules

1. An endpoint is denied unless `VIEW_SCOPES` names it for that HTTP method.
   Unmapped means denied, not allowed — a new route cannot silently become
   reachable by every scoped token.
2. `ANY_SCOPE` means any valid token passes. It is for endpoints that carry no
   user data of their own, or that a client needs before it knows its grants
   (health, info, task status, ListenBrainz token validation).
3. `NEVER` means no scoped token passes, whatever it holds — including `"*"`.
   It guards account-token rotation, which would otherwise let a scoped token
   mint an unscoped one.
4. `"*"` in a token's scopes is a full grant over every mapped endpoint. It does
   not defeat `NEVER`.

`ScopeMapCoverageTests` fails the build when a routed view or method is missing
from the map, when a map entry no longer matches a route, or when a mapped scope
is not in the vocabulary. Adding an endpoint therefore requires deciding its
scope; forgetting is not one of the outcomes.

## What the map does not cover

Scopes apply to the DRF API (`/api/v1/`, `/apis/listenbrainz/1/`). They do not
apply to the non-DRF integration surfaces, which authenticate differently:

| Surface | Credential | Status |
|---|---|---|
| Stremio addon (`/stremio-addon/<token>/...`) | legacy `User.token` in the URL path | Replaced by catalog grants in Nuvio programme B1 |
| Webhooks (Plex, Jellyfin, Emby, Kodi, ...) | per-integration shared secret | Out of scope; each owns its own check |
| gPodder API | account credentials | Out of scope |

Do not describe Floppy as fully scope-gated until those are addressed.

## Vocabulary

| Scope | Grants |
|---|---|
| `scrobble:write` | Submit playback events |
| `progress:read` | Read resume positions and now-playing |
| `progress:write` | Create, update, and clear resume positions |
| `watchlist:read` | Read saved items, watched state, consumption history |
| `watchlist:write` | Change saved items, watched state, tags, history |
| `catalog:read` | Discover, home, search, calendar |
| `catalog:write` | Refresh Discover and the calendar; hide Discover items |
| `metadata:read` | Provider preferences and item metadata |
| `metadata:write` | Change item metadata, artwork, provider preferences; provider sync |
| `lists:read` | Lists, list items, collaborators, activity |
| `lists:write` | Change lists, membership, ordering, recommendations |
| `music:read` / `music:write` | Artists, albums, tracks, plays |
| `podcasts:read` / `podcasts:write` | Shows, episodes, play state |
| `statistics:read` / `statistics:write` | Read statistics; trigger a recompute |
| `sync:read` / `sync:write` | Read sync connections, the change feed, and conflicts; resolve a conflict |
| `imports:read` / `imports:write` | Import activity; start imports |
| `exports:read` | Download exports |
| `user:read` / `user:write` | Preferences, sidebar, notification settings |

## Creating a token

Settings → Integrations → **App tokens** → *Create an app token*.

The form takes a name, an optional expiry, and a permission set pre-ticked with
the tracking preset. The secret is shown once on the redirect and never again —
Floppy stores only the SHA-256 digest, so there is nothing to show later. The
list afterwards identifies each token by its `flp_` prefix, its permissions,
when it was created, and when it was last used.

Revoking one token leaves the others working. That is the point of named
tokens: the account token at the top of the same page is all-or-nothing, and
rotating it breaks every webhook and integration at once.

An expired token stays in the list, labelled `Expired`, rather than
disappearing — otherwise an app stops working with no visible reason.

## The tracking preset

A token minted without an explicit scope list gets
`scopes.TRACKING_PRESET`, which is what a tracking client needs and no more:

```text
scrobble:write
progress:read
progress:write
watchlist:read
watchlist:write
catalog:read
sync:read
```

That preset can scrobble, sync resume positions, read and change saved items and
watched state, and browse Discover. It cannot touch lists, music, podcasts,
imports, exports, user settings, or metadata. `TRACKING_PRESET` and
`integrations.models.DEFAULT_INTEGRATION_SCOPES` are asserted equal by test, so
the documented preset and the minted default cannot drift apart.

## List write bindings

`lists:write` lets a token change lists. `IntegrationToken.writable_list_ids`
narrows that further:

- empty means every list the user owns, which is what `lists:write` meant
  before bindings existed
- a populated list is an exact allowlist of `CustomList` ids

Smart lists are read-only to every external token, bound or not: a computed
list's contents come from its rules, so an external write would be silently
recomputed away.

Enforced centrally by `api.authentication.CanWriteBoundList`, installed in
`DEFAULT_PERMISSION_CLASSES` alongside `HasScope`. Thirteen endpoints write
lists across two modules; a per-view opt-in is a control that gets forgotten.

## Last use

`IntegrationToken.last_used_at` is written at most once per
`api.authentication.LAST_USED_WRITE_INTERVAL` (5 minutes), via a filtered
`UPDATE` rather than `save()`. A scrobbling client would otherwise write a row
on every request, and concurrent requests would race on the same row.

Treat it as "seen recently", not as a request log.

## Adding an endpoint

1. Add the route and view as usual.
2. Add the `module.ClassName` entry to `VIEW_SCOPES` with a scope per method.
3. Run `scripts/test.sh api.tests.test_fork_scope_enforcement`.
4. Regenerate the verified OpenAPI artifact if the endpoint is in the verified
   subset. The command is in `AGENTS.md`.

If no existing scope fits, add one to `SCOPE_DESCRIPTIONS` and document it here.
Do not reach for `ANY_SCOPE` to avoid the decision.
