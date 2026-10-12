# FlexGet and download-tool integration

How an external download tool tells Floppy what you want and what you own, by
provider id, without Floppy running anything new. FlexGet's `floppy_list`
plugin is the reference client; the same calls work from `curl` or any script.

The runnable half of this document is
`src/api/tests/test_fork_media_collection.py`, plus the list-membership tests in
`src/api/tests/test_media_core.py`. If this page and those files disagree, the
files are right.

```bash
SECRET=test-only scripts/test.sh api.tests.test_fork_media_collection
```

## What it gives you

Two things in Floppy, kept separate on purpose:

| Concept | Meaning | Where it shows |
|---|---|---|
| A custom list (for example "To Download") | You want this | Lists; add-to-list button on cards and detail pages |
| Collection | You own this | Collection page; the collected / not collected library filter |

Status is a third, independent axis: `Planning` means "I intend to watch
this", not "I have not downloaded it". A title that is `Planning` and collected
is downloaded and waiting to be watched.

## Connect

Create a token in **Settings → Integrations → App tokens** and send it as
`Authorization: Bearer flp_xxx` (or `X-API-Key: flp_xxx`).

| To | Scope |
|---|---|
| Read lists and their items | `lists:read` |
| Add to or remove from a list | `lists:write` |
| Read the collection | `watchlist:read` |
| Add to or remove from the collection | `watchlist:write` |

See `docs/architecture/api-scopes.md` for the scope contract.

## Identifiers

Movies and shows are addressed as `{media_type}/{source}/{media_id}`, and the
API accepts `tmdb` as the provider source for both. A client holding only a
TVDB or IMDb id must resolve it to a TMDB id first (TMDB's `/find/{id}`
endpoint does this); FlexGet's plugin does so automatically, and falls back to
a TMDB search by name when an entry carries no id at all.

Episodes are addressed by their **show's** TMDB id plus season and episode
numbers. No episode-level id is needed.

A title Floppy has never seen is created from provider metadata on first use,
so a client does not have to track or search for it beforehand. A movie or show
created this way is stored with its release date and its IMDb and TVDB ids, so
list reads return them in `release_datetime` and `ids` straight away.

## Lists

| Operation | Call |
|---|---|
| Find a list's id by name | `GET /api/v1/lists/` |
| Read a list | `GET /api/v1/lists/{list_id}/items/` |
| Add a movie or show | `PUT /api/v1/media/{movie\|tv}/tmdb/{id}/lists/{list_id}/` |
| Remove a movie or show | `DELETE /api/v1/media/{movie\|tv}/tmdb/{id}/lists/{list_id}/` |
| Add or remove a season | `PUT` / `DELETE /api/v1/media/tv/tmdb/{id}/{season}/lists/{list_id}/` |

```bash
curl -X PUT -H "Authorization: Bearer $TOKEN" \
  "$FLOPPY/api/v1/media/movie/tmdb/603/lists/7/"
```

| Status | Meaning |
|---|---|
| `200` | Added; the body lists the item's list memberships |
| `409` | Already in the list |
| `404` | The list does not exist, or the provider does not know the id |
| `502` | The provider could not be reached; nothing was created, retry later |

List reads are paginated with `limit` (at most 200) and `offset`; follow
`pagination.next` until it is null. Each result carries an `item` with
`media_type`, `source`, `media_id`, `title`, `season_number`,
`episode_number`, `release_datetime`, and `ids`.

Limits:

- Lists do not hold single episodes.
- A season can only be added when Floppy already has that season; movies and
  shows are created on demand. Anime on the TMDB or TVDB route is not created
  on demand (it is stored as TV in the anime bucket); use `tv` for it.
- Smart lists are filled from their rules, so write to manual lists only. A
  smart list with a `Planning` status rule is the way to read "everything in
  Planning" through the list endpoint.

## Collection

| Operation | Call |
|---|---|
| Read the collection | `GET /api/v1/collection/` |
| Collect a movie | `PUT /api/v1/media/movie/tmdb/{id}/collection/` |
| Collect an episode | `PUT /api/v1/media/tv/tmdb/{show_id}/{season}/episodes/{episode}/collection/` |
| Remove either | `DELETE` on the same URL |

```bash
curl -X PUT -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"resolution": "1080p"}' \
  "$FLOPPY/api/v1/media/tv/tmdb/1396/2/episodes/5/collection/"
```

The body is optional. `resolution` is free text (at most 100 characters) and is
shown as the entry's quality.

| Status | Meaning |
|---|---|
| `201` | Collected; the body is the new collection entry |
| `200` | Already collected; the same entry is returned, with `resolution` updated if one was sent |
| `204` | Removed (`DELETE`) |
| `400` | Unsupported media type or source, a body that is not a JSON object, or a show without season and episode |
| `404` | The provider does not know the id, or (`DELETE`) there was nothing to remove |
| `502` | The provider could not be reached; nothing was created, retry later |

`PUT` is idempotent, so replaying a download event, or reporting a quality
upgrade, updates one entry instead of adding copies. Two calls arriving at the
same moment still produce one entry.

`DELETE` removes only the copy the API created. A copy added by hand in
Floppy (for example a disc with its own details) is left alone, and `DELETE`
answers `404` when only such copies exist. Add `?all=true` to remove every
copy of the title.

Limits:

- Shows are collected per episode. `PUT .../media/tv/tmdb/{id}/collection/`
  without a season and episode is rejected, because marking a whole show needs
  every episode to be known first.
- Entries created this way are ordinary collection entries, the same as ones
  added in the UI. They are not labelled with the tool that reported them.

## FlexGet

FlexGet's `floppy_list` plugin wraps the calls above as a managed list, so it
works as an input and with `list_add`, `list_remove`, `list_match`, and
`list_clear`.

Download what is on a Floppy list:

```yaml
tasks:
  queue-movies:
    floppy_list:
      base_url: http://localhost:8000
      api_key: flp_xxx
      list: To Download
      type: movies
    accept_all: yes
    list_add:
      - movie_list: wanted
```

Mark what was downloaded as collected, and take movies off the list:

```yaml
tasks:
  download:
    # ... your inputs, series/movie filters and download output ...
    tmdb_lookup: yes
    list_add:
      - floppy_list:
          base_url: http://localhost:8000
          api_key: flp_xxx
          list: collection
    list_remove:
      - floppy_list:
          base_url: http://localhost:8000
          api_key: flp_xxx
          list: To Download
          type: movies
```

Skip what is already owned:

```yaml
    list_match:
      from:
        - floppy_list:
            base_url: http://localhost:8000
            api_key: flp_xxx
            list: collection
      action: reject
      remove_on_match: no
```

The plugin's own option reference lives on the FlexGet wiki under
`Plugins/List/floppy_list`.
