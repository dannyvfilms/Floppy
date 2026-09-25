# Media card

Every poster grid of media items is one card, `src/templates/app/components/media_card.html`.
The page it appears on is its *surface*, and the only differences between surfaces are
declared in `src/app/card_surfaces.py`. This page explains the contract; if the two
disagree, the module wins.

## The rule

A template renders the card with the tag, never with `{% include %}`:

```django
{% media_card "collection" item=entry.item media=entry.media collection_completeness=entry.completeness %}
```

- **`surface`** picks a row of `SURFACES`. The row sets the card's flags (status chip,
  hover actions, next-event subtitle, and so on).
- **Card values** (`item`, `media`, `title`, `subtitle_override`, ...) belong to this one
  card. Any you do not pass are cleared, so a value from the page (the detail page's own
  item, another card in the loop) cannot leak in.
- **Page values** (`public_view`, `enable_bulk_select`, `home_row_id`, ...) belong to the
  page. Any you do not pass are inherited from it. This is how a public detail page hides
  the hover actions on its related cards.
- A value not declared in either list raises `TypeError`, and an undeclared surface raises
  `ValueError`. A new flag goes into the module with its reason, not onto one call site.

## What `media` must be

`media` is the viewer's tracking row for the item, or `None` when they do not track it.
The rating and the status chip read from it, and they are never a per-surface choice: a
tracked item shows its rating on every surface. Load it with
`app.media_list_filters.media_list_entries_for_items(user, items)`, the library's own
lookup, which aggregates repeat viewings. It costs one query per media type on the page.

#1271 was a surface that passed `media=None` for items the user tracks. Collection and
the list recommendations queue now use the shared lookup.

## Surfaces

| Surface | Differs from the default | Why |
|---|---|---|
| `library`, `collection`, `related`, `seasons`, `list_recommendations` | Nothing | |
| `home` | Next-event chip and subtitle | Upcoming shelves lead with the next release |
| `list` | S01E02 subtitle on episodes | A list can hold single episodes |
| `search` | No release-year placeholder | Provider results are not saved items |
| `search_modal` | Click previews, no hover actions, darker surface | Picking an item inside a modal |
| `discover` | No status chip, Discover hover actions | Candidates are untracked by definition |
| `discover_hidden` | No status chip | The subtitle is the date it was hidden |

The library alone shows a "No Status" chip on untracked entries. That comes from its
own entry wrapper (`media_list_views.MediaListEntry.is_statusless`), which serves the
library's status filter. Every other surface shows no chip for an untracked item.

## Adding a surface

1. Add a row to `SURFACES`, with a comment for each difference from the default.
2. Load `media` with `media_list_entries_for_items`.
3. Render with `{% media_card "<surface>" ... %}`.

`app.tests.test_media_card_contract` renders every surface. It fails if a template
includes the card directly, names an undeclared surface, or loses a rating or status
chip that the table says should show.

## Not this card

These tiles are built separately, on purpose, because they show a different kind of
thing or use a different layout: list tiles (`lists/components/list_grid.html`),
history day cards, the Now Playing card, person and cast cards, and statistics highlights.
Do not copy the `media-card-*` classes into a new tile for a media item; use the tag.

The library's album and artist grids (`artist_grid_items.html`,
`album_list_grid_items.html`) are also separate. The card needs an `Item`, and albums
and artists only get one through Home's placeholder rows, which are written to the
database. The library does not write while it reads, so these tiles stay separate. They
use the shared rating partial, `media_card_rating.html`, so a rating reads the same.

Known remaining duplication:

- Home builds its tracking rows in `users/home_screen._media_lookup_for_items`, which has
  season-status and artwork fix-ups the shared lookup lacks.
- Lists build theirs in `lists/views_helpers._attach_media_with_aggregation`, which also
  loads episodes' seasons and annotates `max_progress`, and serves the owner's data on
  public lists.
- Moving either onto the shared lookup needs its own change, with query-count checks.
