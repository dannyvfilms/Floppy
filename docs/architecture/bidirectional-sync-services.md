# Bidirectional sync: which services can do it

This is the lookup page for "can Floppy sync X back to service Y, and why not?"
Read it before planning a new sync-back destination, and add to it when a
service is investigated, whether the answer is yes or no. The engine itself is
described in [Watched-state sync](watched-state-sync.md) and
[Rating sync-back](rating-sync.md); this page is about the services.

## What a service needs

Floppy can only push to a service that has all of these:

1. A documented, public API that accepts writes (a rating, a status or a play)
   for the user's own account, not just reads of site-wide averages.
2. An authorization model a third party can use on a user's behalf: OAuth, a
   device flow, or a personal key the user pastes in. Floppy does not ship
   shared keys for sync and does not copy browser cookies to call a site's
   private endpoints.
3. A way to find the same item on both sides (an exact external id).

If a service fails any of these, the answer is no until the service changes.
Calling undocumented website endpoints with a copied cookie is ruled out:
it breaks without warning and puts the user's login at risk.

Adding a destination that does qualify is one adapter module plus a line in
`integrations/state/registry.py`.

## Current destinations

| Service | Media | Pushes | Notes |
|---|---|---|---|
| TMDb | movies, TV | ratings | Uses the user's own TMDb session. |
| WeTrakr | movies, TV | plays, statuses, ratings | The user supplies their own app key. |
| Jellyfin | movies, TV | watched / unwatched | Opt-in per direction. |
| Emby, Kodi | movies, TV | none (read only) | Watched state is read, never written back. |
| MAL | anime, manga | status, progress, score | Separate system; see "Sync to Trackers". |

## Investigated and ruled out

Checked 2026-11-01. "Not found" means no documented public write API was
found, not proof that the service has no internal endpoints. Several service
sites were unreachable from the research sandbox, so a service changing this
later is possible; re-check before building.

### Games

| Service | Result |
|---|---|
| IGDB | Read-only game database. Its `rating` fields are site-wide averages. There is no per-user login: the Twitch key only produces an app token that cannot act as a user, and no endpoint reads or writes a user's own ratings. Importing a personal score is impossible for the same reason. |
| RAWG | API key and read endpoints only. No documented write for user ratings. |
| Steam | Reads user reviews (recommend / not recommend, not a numeric score). No documented way for a third party to publish one. |
| PlayStation | Store ratings exist for purchases, but there is no public API to write them. |
| Xbox | No public API for Store ratings. PlayFab `ReviewItem` rates items in a developer's own catalog, not Xbox Store games. |
| Backloggd | No official public API; only scrapers exist. |
| Grouvee | No documented public write API. |
| itch.io | OAuth exists, but the documented API has no rating write. |
| HowLongToBeat | No official public API. |
| RetroAchievements | API reads achievements, users and rating statistics; no rating submission. |
| GOG | The Galaxy SDK is for games integrating with Galaxy; it has no call to update a Store rating. |

The one workable path is local: Playnite's SDK exposes a writable `UserScore` on
game records. Syncing scores would mean a small extension that runs inside
Playnite, a separate project from the cloud adapters above. It has not been
started.

Ratings that Floppy only displays (IGDB, OpenCritic critic scores) are
metadata, not sync; see [Game artwork](game-artwork.md) and the provider
settings for those.

## Adding other media types

Add a section for each media type as it is investigated (books, comics, music,
podcasts, video) using the same table: service, result, and the reason. Record
negative results too. They are the ones people ask about again.
