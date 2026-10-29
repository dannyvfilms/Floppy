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

## Video artwork

Video-only library grids and video Home shelves use 16:9 cards. Mixed Home
shelves and other mixed card surfaces retain the poster-sized card, containing
rather than cropping video artwork. History groups video plays in a separate
16:9 row after its poster and square rows. These dedicated video rows use wider
cards than posters and the comfortable phone card size even in compact mode.
All three use the existing card interactions and lazy artwork loading.

For standard YouTube `hqdefault.jpg`, `mqdefault.jpg`, or `sddefault.jpg`
artwork, these cards display YouTube's
high-resolution `maxresdefault.jpg` variant and fall back to the stored image
if the high-resolution thumbnail is missing. The
stored image is unchanged, including client-supplied or user-selected artwork.
Thumbnail dimensions do not classify a video as a Short.

## Rating from the card

A tracked card's rating is a button (`media_card_rate_button.html`): the filled star and score,
or, when unrated, an empty star that shows while the card is hovered. It opens the same picker
as the details pages, `rating_picker.html`, which is the one copy of the star row. The popup is
teleported to `<body>` because the card clips its overflow. Public pages, modal search cards
and untracked items keep the plain read-only rating. `update_media_score` returns
`media_card_rating_oob.html`, which swaps the card's rating after a change.

## Surfaces

| Surface | Differs from the default | Why |
|---|---|---|
| `library`, `collection`, `related`, `seasons`, `list_recommendations` | Nothing | |
| `home` | Next-event chip and subtitle | Upcoming shelves lead with the next release |
| `up_next` | Queue chip and always-visible subtitle | Next episode and backlog/countdown must be readable without hover, including on touch screens |
| `list` | S01E02 subtitle on episodes | A list can hold single episodes |
| `credit` | Role line and watched-runtime chip from the `credit` value | A person's or studio's titles show what that person did on each one |
| `tier` | No status chip, no hover actions, no release-year placeholder | A tile on a list's tier board: the board owns clicks and drags |
| `group` | No status chip, no hover actions, no release-year placeholder | A game franchise/series tile shows a group, not one tracked game |
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

These cards are built separately, on purpose, because they show a different kind of
thing or use a different layout: list cards (`lists/components/list_grid.html`),
history day cards, the Now Playing card, person and cast cards, and statistics highlights.
A person's or studio's list of titles is not one of them: it uses the `credit` surface, with
`people_views.attach_card_media` loading the viewer's tracking row for each title. The Statistics
repeat-player strip is still the older hand-built `person_filmography_card.html`.
Do not copy the `media-card-*` classes into a new card for a media item; use the tag.

The library's album and artist grids (`artist_grid_items.html`,
`album_list_grid_items.html`) are also separate. The card needs an `Item`, and albums
and artists only get one through Home's placeholder rows, which are written to the
database. The library does not write while it reads, so these cards stay separate. They
use the shared rating partial, `media_card_rating.html`, so a rating reads the same.

Known remaining duplication:

- Home builds its tracking rows in `users/home_screen._media_lookup_for_items`, which has
  season-status and artwork fix-ups the shared lookup lacks.
- Lists build theirs in `lists/views_helpers._attach_media_with_aggregation`, which also
  loads episodes' seasons and annotates `max_progress`, and serves the owner's data on
  public lists.
- Moving either onto the shared lookup needs its own change, with query-count checks.

## Artwork loading

Poster cards put the artwork URL directly in `src` and use native `loading="lazy"`.
This lets the browser reuse cached artwork without waiting for JavaScript to replace
a placeholder on each navigation, including HTMX swaps. Keep the aspect ratio so
offscreen cards can stay deferred without shifting the grid.

`artwork-loading.js`, loaded by both base templates, remembers up to 256 successfully
loaded poster URLs and prepares them during HTMX swaps.
Returning artwork uses eager loading and synchronous decoding so a cached image does
not wait for another lazy-load visibility pass. URLs survive normal document
navigation in session storage; a parser observer promotes them before the initial
visibility pass and disconnects at DOMContentLoaded. The first eight images in each
document or response load eagerly; unseen artwork beyond them stays lazy. Table
thumbnails and other hand-built artwork use `data-media-artwork` to share this policy.
Recently used URLs stay at the end of the bounded history rather than being evicted
just because they were first encountered early in the session.

Warm images carry `data-artwork-ready="true"`, which suppresses the containing page's
and grid card's entrance animations. Otherwise an already-cached poster still fades
in with a stagger on every navigation or appended page. No image fetch or decode is
awaited before swapping the page. The login-response guard
checks an actual meta element; matching raw response text would match the guard's
own script and turn each boosted navigation into a second full page request.

The list index has a separate cold-cover lookup for provider backdrops. Resolved URLs
are cached for one hour and rendered directly on repeat visits. The key includes the
first item's ID and image, so changing that item or its artwork bypasses the old entry.
Only a cold cover uses the per-card HTMX request; page rendering never fetches providers.
The first eight resolved index covers are eager even on a full document load.

## Card profiles

Subtitle lines come from `User.card_metadata`, one profile per media type plus `person`.
`src/users/card_metadata.py` is the registry. `card_context` resolves the profile for the
shared card. The picker's properties are generated per type: a card-only field declares
its types, and a field that reads item metadata is offered for every type whose
`app.custom_metadata.MEDIA_TYPE_FIELD_ORDER` entry contains that metadata field. Platform
is therefore a game card property without a second per-type list to maintain.
Hand-rolled cards call `{% card_lines %}`. `display` is `hover` or `always`.
Rows (episode rows, calendar rows) have no hover state, so their hover lines are always
visible. Hand-rolled poster cards add the saved title treatment with `{% card_title_classes %}`,
and only once the user has changed a title option, so unchanged cards keep their own clamps.
The poster progress bar follows the `progress` field. A zero score is hidden per type
via `options.rating.hide_zero`.

Cards that read the profile: the shared card, history, music grids, search music results,
`media_card_list`, episode rows, person and cast cards, stats highlights, active playback,
and calendar rows. `list_grid.html` is a list index. It always shows the item count and
does not read a profile.

`GET /api/v1/user/preferences/` still accepts the old names `media_card_subtitle_display`,
`progress_bar`, and `hide_zero_rating`. A name is omitted when types disagree. `PATCH`
of one name writes every type. The columns are gone.
