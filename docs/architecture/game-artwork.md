# Game artwork

IGDB stays Floppy's game metadata source. Its screenshots and trailer are joined
by SteamGridDB heroes, TheGamesDB fanart and ScreenScraper fanart/screenshots in the
details-page gallery. Other artwork sources contribute their backdrop when available. The **logo** and the **backdrop** shown over the gallery
are resolved separately, by `app.game_artwork`, so each can come from the
provider that does it best.

## Providers

| Provider | Needs | Gives | Asked for |
|---|---|---|---|
| Steam (`steam.py`) | nothing | Library Logo, Library Hero (`/steam/apps/<appid>/logo.png`, `library_hero.jpg`) | games with a Steam AppID |
| Libretro (`libretro.py`) | nothing | Title screen or screenshot as backdrop, a logo only if `Named_Logos` has one | retro games |
| SteamGridDB (`steamgriddb.py`) | member or instance API key | logos, heroes | every game |
| TheGamesDB (`thegamesdb.py`) | member or instance API key | `clearlogo`, `fanart` | every game |
| ScreenScraper (`screenscraper.py`) | Floppy developer credentials in the environment | `wheel` (logo), `fanart` | retro games |

Libretro is a safety net, not a logo collection: its own documentation says the
online collections are not dependable for logos.

## Order

* Steam AppID known: Steam, SteamGridDB, TheGamesDB (then ScreenScraper if the game is also on a retro platform).
* Retro platform: ScreenScraper, TheGamesDB, SteamGridDB, Libretro.
* Anything else: SteamGridDB, TheGamesDB.

Each asset is resolved on its own: a provider is only asked for what an earlier
one did not find. If IGDB is unavailable, a stored game's title, platforms, release date and external
ids still let the artwork providers search. IGDB's own artwork is the backdrop
fallback and is recorded as
provider `igdb`. There is no IGDB logo, so a game with no provider logo shows
the details page without the overview logo.

## What is stored

`GameArtwork` holds one row per IGDB game: `logo_url`, `logo_provider`,
`logo_provider_id`, and the same three for the backdrop. The provider id is the
provider's own id for the image or game, so a later "Refresh artwork" or "Pick
another" does not need a new model.

A row with both assets from real providers is kept 30 days. A row with a gap is
looked up again after 6 hours, so adding a key takes effect without any reset.
A lookup where a provider *errored* and found nothing stores nothing and backs
off for 5 minutes; a row never records an outage as "no artwork".

Two things reopen a stored row before its time limit. A manual **Refresh metadata**
(web or API) calls `app.game_artwork.expire`, which makes that game due whatever it
holds. Saving a SteamGridDB, TheGamesDB or ScreenScraper key calls `keys_saved`,
which notes the time in the cache; a row with a gap saved before that is due for
requests the key applies to (the member who saved a personal key, or everyone for an
instance key). Nothing is rewritten in the database for a key, so a member without
the key cannot search, find nothing and settle the row before its owner visits. A
saved key also starts a fresh error backoff. The lookup runs on the next game page
view, in the viewer's request, because a personal key applies only there. Whatever
was stored stays until a lookup finds something better. During an error backoff a
view searches nothing and stores nothing. A found image whose URL is too long for the
column is treated as not found.

## ScreenScraper credentials

ScreenScraper identifies the application with `devid`, `devpassword` and
`softname`, and optionally a member with `ssid` and `sspassword`. Its media URLs
carry those as query parameters, so:

* the URL stored in `GameArtwork` and sent to the browser has them stripped;
* `app.image_cache` always proxies ScreenScraper URLs (whatever the caching
  toggle says) and calls `screenscraper.authenticate` only on the server-side
  fetch.

The developer credentials come only from `SCREENSCRAPER_DEV_ID`,
`SCREENSCRAPER_DEV_PASSWORD` and `SCREENSCRAPER_SOFTNAME` (or `_FILE` secrets).
They are not in `SHARED_DEFAULT_CREDENTIALS` and must never be committed.
Until they exist ScreenScraper is inactive.

## Adding a provider

Add a module with `PROVIDER` and `find(query, wanted)` returning
`{"logo": Art, "backdrop": Art}` for what it has, add it to
`provider_order`, approve its image host in `app.image_cache`, and add a
registry entry in `app.providers.credentials` if it takes a key.

Media details render a fresh cached gallery and stored artwork in the initial response, including the logo and hero layout. Missing or expired artwork stays on the deferred carousel path; the initial response never calls artwork providers. Seasons use the cached parent show artwork as well.

The additional gallery is capped at 24 unique images and cached for six hours.
Provider errors use a five-minute retry cache. Saving artwork credentials or
refreshing the game reopens the gallery. Fetching stays in the deferred carousel
request; repeat visits read the cached images without calling providers.
