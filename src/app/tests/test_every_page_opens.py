"""Every page a signed-in user can reach opens for every kind of media (assignment 73).

One realistic library (``catalogue_fixtures.build_sample_library``) and a
table of rows, each one (page, media type, URL). A web row must answer 200
(after redirects), contain the page's landmark and the item's own title, and
none of the template failures that have shipped before: ``NoReverseMatch``,
``VariableDoesNotExist``, an empty card link, or a link to a library list
that does not exist. A JSON row (the twin the Expo app reads) must answer
200 and carry the top-level keys its native reader uses.

Rows come from ``MediaTypes``, the sort registry and ``LayoutChoices``, so a
new media type, sort or layout is opened without anyone editing this file.
A (page, media type) pair that cannot exist is listed in ``EXEMPT`` with its
reason; any other pair without a row fails ``test_every_pair_is_covered``.

A smoke test: it checks pages open, not their layout, copy or numbers. The
library list grid (every type, sort and layout) runs as one test class per
media type so the parallel runner spreads it.

    scripts/test.sh app.tests.test_every_page_opens
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils.text import slugify

from app.library_query.sorts import SORTS
from app.media_list_entry_grouping_views import LISTED_UNDER
from app.models import MediaTypes, Sources
from app.podcast_views import podcast_show_url
from app.signals import suppress_media_change_side_effects
from app.tests import catalogue_fixtures as fx
from users.models import LayoutChoices, User

ALL_TYPES = tuple(MediaTypes.values)
SEASONED = (MediaTypes.SEASON.value, MediaTypes.EPISODE.value)
# One key per sort definition: aliases resolve to the same definition.
SORT_KEYS = tuple(definition.keys[0] for definition in SORTS)
ALL_SORT_KEYS = frozenset(key for definition in SORTS for key in definition.keys)
LAYOUTS = tuple(LayoutChoices.values)

# Pages opened once per media type. ``test_every_pair_is_covered`` checks each
# has a row or an ``EXEMPT`` reason for every media type.
PER_TYPE_PAGES = (
    "detail",
    "track_form",
    "media_list",
    "search",
    "api_detail",
    "api_library",
)

# (page, media type) pairs that cannot exist, with the reason.
EXEMPT = {
    (
        "search",
        MediaTypes.SEASON.value,
    ): "Search finds shows; seasons open from the show.",
    (
        "search",
        MediaTypes.EPISODE.value,
    ): "Search finds shows; episodes open from the show.",
    (
        "api_library",
        MediaTypes.SEASON.value,
    ): "The app lists seasons inside their show.",
    (
        "api_library",
        MediaTypes.EPISODE.value,
    ): "The app lists episodes inside their season.",
}

# The native reader for the detail page JSON. Its top-level keys are read
# from the reader itself, so a key the app starts reading is checked here.
DETAIL_READER = (
    Path(settings.BASE_DIR).parent
    / "native-proof"
    / "app"
    / "surfaces"
    / "DetailSlot.jsx"
)
DETAIL_READER_FUNCTION = "detailFromProviderPayload"
# The sorts the Expo library offers; its JSON rows request each one.
LIBRARY_SCREEN = DETAIL_READER.parent.parent / "screens" / "LibraryScreen.jsx"

# Text a rendered page must never contain.
TEMPLATE_FAULTS = ("NoReverseMatch", "VariableDoesNotExist")
EMPTY_CARD_LINK = re.compile(
    r'<a\b[^>]*\bhref=""[^>]*class="[^"]*media-card|'
    r'<a\b[^>]*class="[^"]*media-card[^"]*"[^>]*\bhref=""'
)
LIST_LINK = re.compile(r'href="/medialist/([a-z]+)')
# A tag that loads part of the page by itself once the page is shown.
DEFERRED_TAG = re.compile(r"<[a-z][^>]*\bhx-get=\"([^\"]+)\"[^>]*>")
DEFERRED_TRIGGER = re.compile(r'hx-trigger="[^"]*\b(load|revealed|intersect)\b')
MAIN = "<main"


def detail_reader_keys():
    """Top-level keys ``detailFromProviderPayload`` reads from the detail JSON."""
    source = DETAIL_READER.read_text()
    start = source.index(f"function {DETAIL_READER_FUNCTION}(")
    end = source.find("\nfunction ", start + 1)
    body = source[start : end if end != -1 else None]
    return tuple(sorted(set(re.findall(r"payload\??\.([a-z_]+)", body))))


def app_library_sorts():
    """The sort values the Expo library screen offers (its ``SORTS``)."""
    source = LIBRARY_SCREEN.read_text()
    start = source.index("const SORTS = [")
    block = source[start : source.index("];", start)]
    return tuple(re.findall(r"value: '([a-z_]+)'", block))


@dataclass(frozen=True)
class Row:
    """One page to open."""

    page: str
    media_type: str
    url: str
    # Text the response must contain: the main landmark for a full page, the
    # form for a dialog fragment. Empty for JSON.
    landmark: str = MAIN
    # The item's title, when the page is about one item.
    expect: str = ""
    # Top-level JSON keys the native reader uses (JSON rows only).
    keys: tuple[str, ...] = ()
    # For list JSON: the ``results`` must not be empty.
    nonempty: bool = False

    @property
    def is_json(self):
        return self.page.startswith("api_")

    @property
    def label(self):
        return f"{self.page} [{self.media_type}] {self.url}"


def _slug(item):
    return slugify(item.title) or "item"


def _with_query(path, query):
    return f"{path}?{urlencode(query)}" if query else path


def _media_details(item, media_type=None):
    return reverse(
        "media_details",
        kwargs={
            "source": item.source,
            "media_type": media_type or item.media_type,
            "media_id": item.media_id,
            "title": _slug(item),
        },
    )


def _music_kwargs(library, *, track=False):
    kwargs = {
        "artist_id": library.artist.id,
        "artist_slug": slugify(library.artist.name),
        "album_id": library.album.id,
        "album_slug": slugify(library.album.title),
    }
    if track:
        kwargs |= {
            "track_id": library.track.id,
            "track_slug": slugify(library.track.title),
        }
    return kwargs


def detail_url(library, media_type):
    """The web page that shows one item of ``media_type``."""
    item = library.items[media_type]
    tv = {"source": item.source, "media_id": item.media_id, "title": _slug(item)}
    if media_type == MediaTypes.SEASON.value:
        return reverse(
            "season_details", kwargs=tv | {"season_number": item.season_number}
        )
    if media_type == MediaTypes.EPISODE.value:
        return reverse(
            "episode_details",
            kwargs=tv
            | {
                "season_number": item.season_number,
                "episode_number": item.episode_number,
            },
        )
    if media_type == MediaTypes.MUSIC.value:
        return reverse("music_track_details", kwargs=_music_kwargs(library, track=True))
    if media_type == MediaTypes.PODCAST.value:
        return podcast_show_url(library.podcast_show)
    return _media_details(item)


def track_form_url(library, media_type):
    """The Track dialog for one item of ``media_type``."""
    item = library.items[media_type]
    if media_type == MediaTypes.MUSIC.value:
        return reverse("album_track_modal", kwargs={"album_id": library.album.id})
    if media_type == MediaTypes.PODCAST.value:
        return reverse(
            "podcast_show_track_modal", kwargs={"show_id": library.podcast_show.id}
        )
    kwargs = {
        "source": item.source,
        "media_type": media_type,
        "media_id": item.media_id,
    }
    query = {}
    if media_type in SEASONED:
        kwargs |= {
            "media_type": MediaTypes.SEASON.value,
            "season_number": item.season_number,
        }
    if media_type == MediaTypes.EPISODE.value:
        query["episode_number"] = item.episode_number
    return _with_query(reverse("track_modal", kwargs=kwargs), query)


def api_detail_rows(library, media_type):
    """The JSON the Expo detail page reads for one item of ``media_type``."""
    item = library.items[media_type]
    if media_type == MediaTypes.MUSIC.value:
        album = library.album.id
        return [
            Row(
                "api_detail",
                media_type,
                reverse("api_music_album_detail", args=[album]),
                landmark="",
                keys=("title", "artist_name", "tracker"),
            ),
            Row(
                "api_detail",
                media_type,
                reverse("api_music_album_tracks", args=[album]),
                landmark="",
                keys=("results",),
                nonempty=True,
            ),
        ]
    if media_type == MediaTypes.PODCAST.value:
        show = library.podcast_show.id
        return [
            Row(
                "api_detail",
                media_type,
                reverse("api_podcast_show_detail", args=[show]),
                landmark="",
                keys=("title", "description", "image", "tracker"),
            ),
            Row(
                "api_detail",
                media_type,
                _with_query(
                    reverse("api_podcast_show_episodes", args=[show]),
                    {"limit": 30, "offset": 0},
                ),
                landmark="",
                keys=("results",),
                nonempty=True,
            ),
        ]
    query = {}
    if media_type in SEASONED:
        query = {"detail_type": media_type, "season_number": item.season_number}
    if media_type == MediaTypes.EPISODE.value:
        query["episode_number"] = item.episode_number
    path = reverse(
        "api_media_detail_page",
        kwargs={
            "media_type": MediaTypes.TV.value if media_type in SEASONED else media_type,
            "source": item.source,
            "media_id": item.media_id,
        },
    )
    # An episode's JSON is titled by the episode, not the show.
    title = "Episode 1" if media_type == MediaTypes.EPISODE.value else item.title
    return [
        Row(
            "api_detail",
            media_type,
            _with_query(path, query),
            landmark="",
            expect=title,
            keys=detail_reader_keys(),
        ),
    ]


def api_library_path(media_type):
    """The path the Expo library reads for ``media_type`` (``libraryPath``)."""
    if media_type == MediaTypes.MUSIC.value:
        return reverse("api_music_albums")
    if media_type == MediaTypes.PODCAST.value:
        return reverse("api_podcast_shows")
    return reverse("api_media_type_list", kwargs={"media_type": media_type})


def list_title(library, media_type):
    """The title a library list for ``media_type`` must show."""
    if media_type == MediaTypes.MUSIC.value:
        return library.artist.name
    if media_type == MediaTypes.EPISODE.value:
        return library.items[MediaTypes.TV.value].title
    return library.items[media_type].title


def media_list_rows(library, media_type):
    """The library list for one type, for every sort key and layout."""
    base = reverse("medialist", kwargs={"media_type": media_type})
    expect = list_title(library, media_type)
    rows = [
        Row(
            "media_list",
            media_type,
            _with_query(base, {"layout": layout, "sort": sort}),
            expect=expect,
        )
        for layout in LAYOUTS
        for sort in SORT_KEYS
    ]
    if media_type not in SEASONED:
        rows += [
            Row(
                "api_library",
                media_type,
                _with_query(api_library_path(media_type), {"sort": sort}),
                landmark="",
                keys=("results",),
                nonempty=True,
            )
            for sort in app_library_sorts()
        ]
    return rows


def page_rows(library):
    """Every row except the library list grid."""
    rows = []
    for media_type in ALL_TYPES:
        if media_type not in library.items:
            continue  # test_every_type_has_a_sample names it
        item = library.items[media_type]
        title = item.title
        if media_type == MediaTypes.MUSIC.value:
            title = library.track.title
        rows.append(
            Row("detail", media_type, detail_url(library, media_type), expect=title)
        )
        rows.append(
            Row(
                "track_form",
                media_type,
                track_form_url(library, media_type),
                landmark="<form",
            )
        )
        rows += api_detail_rows(library, media_type)
        if media_type not in SEASONED:
            rows.append(
                Row(
                    "search",
                    media_type,
                    _with_query(
                        reverse("search"), {"q": "Sample", "media_type": media_type}
                    ),
                )
            )
    grouped = library.grouped_anime
    grouped_tv = {
        "source": grouped.source,
        "media_id": grouped.media_id,
        "title": _slug(grouped),
    }
    shown = library.items[MediaTypes.TV.value]
    rows += [
        Row(
            "detail",
            "anime grouped on TV rows",
            _media_details(grouped, MediaTypes.ANIME.value),
            expect=grouped.title,
        ),
        Row(
            "season",
            "anime grouped on TV rows",
            reverse("anime_season_details", kwargs=grouped_tv | {"season_number": 1}),
            expect=grouped.title,
        ),
        Row(
            "episode",
            "anime grouped on TV rows",
            reverse(
                "anime_episode_details",
                kwargs=grouped_tv | {"season_number": 1, "episode_number": 1},
            ),
            expect=grouped.title,
        ),
        Row(
            "episode",
            "episode with no air date",
            reverse(
                "episode_details",
                kwargs={
                    "source": shown.source,
                    "media_id": shown.media_id,
                    "title": _slug(shown),
                    "season_number": fx.SAMPLE_UNAIRED_EPISODE[0],
                    "episode_number": fx.SAMPLE_UNAIRED_EPISODE[1],
                },
            ),
            expect=shown.title,
        ),
        Row(
            "episode",
            "untracked episode with a guest star",
            reverse(
                "episode_details",
                kwargs={
                    "source": shown.source,
                    "media_id": shown.media_id,
                    "title": _slug(shown),
                    "season_number": fx.SAMPLE_UNTRACKED_EPISODE[0],
                    "episode_number": fx.SAMPLE_UNTRACKED_EPISODE[1],
                },
            ),
            expect="Sample Guest",
        ),
        Row(
            "detail",
            "manual movie",
            _media_details(library.manual_item),
            expect=library.manual_item.title,
        ),
        Row(
            "detail",
            "movie with no image",
            _media_details(library.no_image_item),
            expect=library.no_image_item.title,
        ),
        Row(
            "artist",
            MediaTypes.MUSIC.value,
            reverse(
                "music_artist_details",
                kwargs={
                    "artist_id": library.artist.id,
                    "artist_slug": slugify(library.artist.name),
                },
            ),
            expect=library.artist.name,
        ),
        Row(
            "album",
            MediaTypes.MUSIC.value,
            reverse("music_album_details", kwargs=_music_kwargs(library)),
            expect=library.album.title,
        ),
        Row(
            "api_artist",
            MediaTypes.MUSIC.value,
            reverse("api_music_artist_detail", args=[library.artist.id]),
            landmark="",
            keys=("name", "albums", "tracker"),
        ),
        Row(
            "person",
            "all",
            reverse(
                "person_detail",
                kwargs={
                    "source": Sources.TMDB.value,
                    "person_id": str(library.person_id),
                    "name": "sample-person",
                },
            ),
        ),
        Row(
            "api_person",
            "all",
            reverse(
                "api_person",
                kwargs={
                    "source": Sources.TMDB.value,
                    "person_id": str(library.person_id),
                },
            ),
            landmark="",
        ),
        Row("home", "all", reverse("home")),
        Row("api_home", "all", reverse("api_home"), landmark=""),
        Row("history", "all", reverse("history")),
        Row("api_history", "all", reverse("api_history"), landmark=""),
        Row("statistics", "all", reverse("statistics")),
        Row("api_statistics", "all", reverse("api_statistics_overview"), landmark=""),
        Row("calendar", "all", reverse("calendar")),
        Row("api_calendar", "all", reverse("api_calendar"), landmark=""),
        Row(
            "custom_list",
            "every type",
            reverse("list_detail", kwargs={"list_reference": library.custom_list.pk}),
        ),
        Row(
            "api_custom_list",
            "every type",
            reverse("api_list_detail", kwargs={"list_id": library.custom_list.pk}),
            landmark="",
        ),
        Row(
            "custom_list",
            "podcast show and episodes",
            reverse("list_detail", kwargs={"list_reference": library.podcast_list.pk}),
            expect=library.podcast_show.title,
        ),
        Row("lists", "all", reverse("lists")),
        Row("collection", "all", reverse("collection_list")),
        Row("tags", "all", reverse("tag_index")),
    ]
    return rows


def deferred_parts(row, body):
    """URLs a page loads by itself after it is shown (fragments, lazy rows).

    The detail pages render their cast, crew and side panels this way, so a
    row that skipped them would miss the faults they hold (#1953).
    """
    path = row.url.split("?", 1)[0]
    urls = []
    for match in DEFERRED_TAG.finditer(body):
        url = html.unescape(match[1])
        if not url.startswith("/") or "{" in url:
            continue
        same_page = url.split("?", 1)[0] == path and "fragment=" in url
        if same_page or DEFERRED_TRIGGER.search(match[0]):
            urls.append(url)
    return list(dict.fromkeys(urls))


def faults(row, response):
    """Return what is wrong with one response, or an empty list."""
    if response.status_code != 200:
        snippet = ""
        if response.get("Content-Type", "").startswith("application/json"):
            snippet = " " + response.content.decode(errors="replace")[:300]
        return [f"status {response.status_code}{snippet}"]
    if row.is_json:
        payload = response.json()
        if not isinstance(payload, dict):
            return [f"answered {type(payload).__name__}, not an object"]
        found = [f"missing key {key!r}" for key in row.keys if key not in payload]
        if row.nonempty and not payload.get("results"):
            found.append("no results")
        if row.expect and row.expect not in response.content.decode():
            found.append(f"no {row.expect!r}")
        return found
    body = response.content.decode(errors="replace")
    found = [f"contains {fault}" for fault in TEMPLATE_FAULTS if fault in body]
    if row.landmark and row.landmark not in body:
        found.append(f"no {row.landmark!r}")
    if row.expect and row.expect not in body:
        found.append(f"no {row.expect!r}")
    if EMPTY_CARD_LINK.search(body):
        found.append('a card link with href=""')
    dead = sorted(
        {link for link in LIST_LINK.findall(body) if link not in MediaTypes.values}
    )
    if dead:
        found.append(f"links to library lists that do not exist: {dead}")
    return found


class SampleLibraryTestCase(TestCase):
    """One sample library per class, opened as a signed-in user."""

    @classmethod
    def setUpClass(cls):
        logging.disable(logging.CRITICAL)
        cls.addClassCleanup(logging.disable, logging.NOTSET)
        super().setUpClass()

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="every-page", password="x")
        empty = User.objects.create_user(username="every-page-empty", password="x")
        with (
            patch("app.models.Item.fetch_releases", return_value=None),
            suppress_media_change_side_effects(),
        ):
            cls.library = fx.build_sample_library(cls.user, empty_user=empty)

    def setUp(self):
        for patcher in self.library.patchers():
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client.force_login(self.user)

    def open_rows(self, rows):
        """Open each row; fail once, naming every row that went wrong."""
        failures = []
        for row in rows:
            headers = {"X-Api-Key": self.user.token} if row.is_json else {}
            try:
                response = self.client.get(
                    row.url, headers=headers, follow=not row.is_json
                )
            except Exception as error:
                failures.append(f"{row.label}: raised {type(error).__name__}: {error}")
                continue
            found = faults(row, response)
            failures += [f"{row.label}: {fault}" for fault in found]
            if found or row.is_json:
                continue
            for url in deferred_parts(row, response.content.decode(errors="replace")):
                part = Row(f"{row.page} part", row.media_type, url, landmark="")
                try:
                    fragment = self.client.get(url, headers={"HX-Request": "true"})
                except Exception as error:
                    failures.append(
                        f"{part.label}: raised {type(error).__name__}: {error}"
                    )
                    continue
                if fragment.status_code == 204:
                    continue
                failures += [
                    f"{part.label}: {fault}" for fault in faults(part, fragment)
                ]
        self.assertEqual(failures, [], "\n" + "\n".join(failures))


class EveryPageOpensTests(SampleLibraryTestCase):
    """Detail, Track, search, person and the all-types pages, web and JSON."""

    def test_every_type_has_a_sample(self):
        missing = [t for t in ALL_TYPES if t not in self.library.items]
        self.assertEqual(
            missing, [], "Add a tracked item of each type to build_sample_library."
        )

    def test_every_pair_is_covered(self):
        rows = page_rows(self.library) + [
            row
            for media_type in ALL_TYPES
            if media_type in self.library.items
            for row in media_list_rows(self.library, media_type)
        ]
        covered = {(row.page, row.media_type) for row in rows}
        missing = [
            (page, media_type)
            for page in PER_TYPE_PAGES
            for media_type in ALL_TYPES
            if (page, media_type) not in covered and (page, media_type) not in EXEMPT
        ]
        self.assertEqual(missing, [], "Add a row or an EXEMPT reason for each pair.")
        stale = [pair for pair in EXEMPT if pair in covered]
        self.assertEqual(stale, [], "These pairs now have rows; drop their exemption.")

    def test_types_without_a_list_redirect_to_the_list_that_holds_them(self):
        for media_type, (parent, extra) in LISTED_UNDER.items():
            response = self.client.get(
                reverse("medialist", kwargs={"media_type": media_type}) + "?genre=Drama"
            )
            self.assertRedirects(
                response,
                _with_query(
                    reverse("medialist", kwargs={"media_type": parent}),
                    {"genre": "Drama", **extra},
                ),
                fetch_redirect_response=False,
            )

    def test_the_native_readers_are_found(self):
        self.assertIn("title", detail_reader_keys())
        sorts = app_library_sorts()
        self.assertIn("title", sorts)
        unknown = [sort for sort in sorts if sort not in ALL_SORT_KEYS]
        self.assertEqual(
            unknown, [], "The app offers sorts the server does not define."
        )

    def test_every_page_opens(self):
        self.open_rows(page_rows(self.library))


class _LibraryListGrid:
    """Every sort key and layout of one media type's library list."""

    media_type = None

    def test_every_sort_and_layout_opens(self):
        if self.media_type not in self.library.items:
            self.fail(f"Add a tracked {self.media_type} to build_sample_library.")
        self.open_rows(media_list_rows(self.library, self.media_type))


# One class per media type, generated so a new type gets its own.
for _media_type in ALL_TYPES:
    _name = f"LibraryList{_media_type.title().replace('_', '')}Tests"
    globals()[_name] = type(
        _name,
        (_LibraryListGrid, SampleLibraryTestCase),
        {"media_type": _media_type, "__doc__": f"Library list grid for {_media_type}."},
    )
del _media_type, _name
