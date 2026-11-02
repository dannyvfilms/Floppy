# Recommendations for external clients

What a media-server plugin or other library builder needs to turn a user's Floppy
history into a recommendation list, using IMDb/TMDB/TVDB ids rather than Floppy's
own item ids. Written for plugins such as JellyNext, which today read the same
shapes from Trakt.

`api.tests.test_fork_discover.RecommendationsTests` is the runnable half. If this
page and that file disagree, the file is right.

```bash
SECRET=test-only scripts/test.sh api.tests.test_fork_discover
```

## Connect

Use an app token as described in `docs/integrations/nuvio-client-guide.md`. The
default token preset already holds the scopes below.

| Need | Endpoint | Scope |
|---|---|---|
| Personalized picks | `GET /api/v1/recommendations/` | `catalog:read` |
| Watch history with ids | `GET /api/v1/history/?flat=1&media_type=tv` | `watchlist:read` |

## Recommendations

`GET /api/v1/recommendations/?media_type=movie|tv&limit=20&offset=0`

Returns the user's "Top Picks For You" Discover row as a flat, paginated list.
What is in it differs by type:

- `movie`: the user's Planning list plus new titles that match their taste.
  Anything completed, dropped or in progress is left out, so a movie they
  watched stays out even after the file is deleted from the media server.
- `tv`: the user's Planning list, ranked by taste. Floppy has no row of new,
  untracked TV recommendations, so a client wanting those must look elsewhere.

```json
{
  "pagination": {"total": 12, "limit": 20, "offset": 0, "next": null, "previous": null},
  "results": [
    {
      "media_type": "tv",
      "source": "tmdb",
      "media_id": "1396",
      "title": "Breaking Bad",
      "release_date": "2008-01-20",
      "genres": ["Drama", "Crime"],
      "rating": 8.9,
      "image": "https://...",
      "ids": {"tmdb": "1396", "imdb": "tt0903747", "tvdb": "81189"}
    }
  ]
}
```

Things a client must handle:

- `ids` keys are present only when Floppy resolved them. A TV pick can lack
  `tvdb`. Skip or look it up yourself; Floppy does not guess.
- The first call can be slow or return an empty list while Floppy builds the
  user's Discover rows. Call again later; `POST /api/v1/discover/refresh/` forces a rebuild.
- `404` means the user turned Discover off in Floppy. `400` means `media_type`
  is not `movie` or `tv`.
- Ids missing from Floppy's own records are fetched from TMDB per pick, then
  cached, so a cold first page is slower than later ones. Keep `limit` modest.

## Watch history

`GET /api/v1/history/?flat=1&media_type=tv&start_date=...` lists watched entries.
Each entry carries `provider_external_ids` (`tmdb_id`, `imdb_id`, `tvdb_id`) when
known, plus the watch date. Use `limit` and `offset` to page.

## What Floppy does not provide

Floppy has no Trakt-compatible server, no Trakt device-code login, and no
trending list of its own (its trending rows come from Trakt). A client written
for Trakt needs a Floppy provider; it cannot just change a base URL.
