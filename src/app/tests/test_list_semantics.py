"""A sort, a filter and "select all" mean the same thing everywhere (assignment 76).

One library of sixty movies (more than a page on every surface) plus small
sets of games, books, shows and one list (``list_semantics_fixtures``). Three
tables state what the library should look like:

- ``ORDERS``: for every key in ``library_query.sorts.SORTS``, the first six
  and last three titles in each direction, with a one-line reason. Each row
  is read on every surface that offers it: the web media list (every page),
  the media API the Expo library reads (every page), and a Home shelf with
  that sort. A key without a row fails ``test_every_sort_key_has_a_row``.
- ``FILTERS``: for each filter in ``library_query.filters.FILTERS``, the
  titles it keeps, computed from the fixture's rules. The web list, the API,
  and "select all" on both (``?bulk_ids=1`` and ``item-ids``) must return
  exactly that set.
- ``EXEMPT``: the places a surface legitimately differs, with the reason.

Adding a sort or filter: state the order (or the matching titles) in the
table. ``test_library_query`` proves SQL and Python agree; this file states
what the order means and that every surface shows it.

    scripts/test.sh app.tests.test_list_semantics
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import patch

import requests
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from app.library_query.filters import FILTERS as FILTER_DEFS
from app.library_query.sorts import SORTS
from app.models import Item, Status
from app.signals import suppress_media_change_side_effects
from app.tests import list_semantics_fixtures as fx
from users import home_screen
from users.models import HomeScreenRow, HomeScreenRowTypeChoices, User

WEB, API, HOME, LIST = "web", "api", "home", "list"
ALL_SURFACES = (WEB, API, HOME)
API_PAGE = 30  # what the Expo library asks for (libraryTransportCore.js)
HOME_PAGE = 14
MOVIE, GAME, BOOK, TV = "movie", "game", "book", "tv"


@dataclass(frozen=True)
class Order:
    """What one sort key means, as titles a person could check."""

    library: str
    reason: str
    asc: tuple[tuple[str, ...], tuple[str, ...]]
    desc: tuple[tuple[str, ...], tuple[str, ...]]
    surfaces: tuple[str, ...] = ALL_SURFACES
    # The value the surface's own control sends, when it is not the key.
    param: str = ""
    # {surface: (asc, desc)} where EXEMPT says that surface orders differently.
    overrides: dict = field(default_factory=dict)


# fmt: off
ORDERS: dict[str, Order | None] = {
    "title": Order(
        MOVIE, "A to Z, ignoring case.",
        (("Acorn", "Amber", "Anchor", "Arrow", "Aspen", "Badger"), ("Velvet", "Willow", "Zephyr")),
        (("Zephyr", "Willow", "Velvet", "Umber", "Tundra", "Thistle"), ("Anchor", "Amber", "Acorn")),
    ),
    "release_date": Order(
        MOVIE, "Oldest release first; titles with no release date last both ways.",
        (("Indigo", "Willow", "Hazel", "Umber", "Glacier", "Thistle"), ("Cinder", "Comet", "Delta")),
        (("Jasper", "Anchor", "Kestrel", "Aspen", "Larch", "Lotus"), ("Basil", "Arrow", "Acorn")),
    ),
    "critic_rating": Order(
        MOVIE, "Lowest critic rating first; unrated last both ways.",
        (("Ripple", "Pine", "Nectar", "Maple", "Glacier", "Larch"), ("Quartz", "Sage", "Umber")),
        (("Arrow", "Basil", "Bramble", "Cinder", "Comet", "Heron"), ("Linden", "Juniper", "Acorn")),
    ),
    "popularity": Order(
        MOVIE, "Ascending is most popular (rank 1) first; unranked last both ways.",
        (("Cedar", "Fern", "Kestrel", "Onyx", "Tundra", "Basil"), ("Iris", "Meadow", "Ripple")),
        (("Raven", "Maple", "Hazel", "Coral", "Badger", "Thistle"), ("Ember", "Canyon", "Acorn")),
    ),
    "id": Order(
        MOVIE, "By the provider's id. API only.",
        (("Acorn", "Beacon", "Cobalt", "Falcon", "Heron", "Larch"), ("Glacier", "Juniper", "Marble")),
        (("Marble", "Juniper", "Glacier", "Delta", "Cedar", "Aspen"), ("Cobalt", "Beacon", "Acorn")),
        surfaces=(API,),
    ),
    "source": Order(
        MOVIE, "By provider; one provider here, so titles break the tie. API only.",
        (("Acorn", "Amber", "Anchor", "Arrow", "Aspen", "Badger"), ("Velvet", "Willow", "Zephyr")),
        (("Zephyr", "Willow", "Velvet", "Umber", "Tundra", "Thistle"), ("Anchor", "Amber", "Acorn")),
        surfaces=(API,),
    ),
    "type": Order(
        MOVIE, "By media type; all movies here, so titles break the tie. API, and a list's Media Type.",
        (("Acorn", "Amber", "Anchor", "Arrow", "Aspen", "Badger"), ("Velvet", "Willow", "Zephyr")),
        (("Zephyr", "Willow", "Velvet", "Umber", "Tundra", "Thistle"), ("Anchor", "Amber", "Acorn")),
        surfaces=(API,),
    ),
    "date_added": Order(
        MOVIE, "When first tracked; a rewatch (Maple) keeps its first date (#1859); same-day titles A to Z.",
        (("Acorn", "Beacon", "Cobalt", "Falcon", "Heron", "Larch"), ("Glacier", "Juniper", "Marble")),
        (("Marble", "Juniper", "Glacier", "Delta", "Cedar", "Aspen"), ("Cobalt", "Beacon", "Acorn")),
    ),
    "start_date": Order(
        MOVIE, "Earliest start first; planned titles (no start) last both ways.",
        (("Beacon", "Cobalt", "Falcon", "Heron", "Larch", "Raven"), ("Nimbus", "Quartz", "Thistle")),
        (("Marble", "Juniper", "Glacier", "Cedar", "Aspen", "Velvet"), ("Cinder", "Basil", "Acorn")),
    ),
    "end_date": Order(
        MOVIE,
        "Labelled Last Watched: the last play, or for unfinished titles the last progress; "
        "titles finished without a date (Ember, Umber) last both ways (#1718).",
        (("Acorn", "Falcon", "Nimbus", "Arrow", "Garnet", "Orchid"), ("Bramble", "Ember", "Umber")),
        (("Bramble", "Maple", "Glacier", "Oak", "Amber", "Drift"), ("Acorn", "Umber", "Ember")),
    ),
    "last_watched": Order(
        MOVIE, "The API's name for the Last Watched order above.",
        (("Acorn", "Falcon", "Nimbus", "Arrow", "Garnet", "Orchid"), ("Bramble", "Ember", "Umber")),
        (("Bramble", "Maple", "Glacier", "Oak", "Amber", "Drift"), ("Acorn", "Umber", "Ember")),
        surfaces=(API,),
    ),
    "score": Order(
        MOVIE, "Lowest rating first; unrated last both ways.",
        (("Canyon", "Ember", "Iris", "Meadow", "Ripple", "Bramble"), ("Oak", "Raven", "Thistle")),
        (("Saffron", "Nectar", "Jasper", "Falcon", "Cedar", "Amber"), ("Coral", "Badger", "Acorn")),
    ),
    "progress": Order(
        MOVIE,
        "Plays: a row counts when it has an end date or is Completed; Maple was watched twice.",
        (("Acorn", "Amber", "Arrow", "Basil", "Beacon", "Bramble"), ("Willow", "Zephyr", "Maple")),
        (("Maple", "Zephyr", "Willow", "Umber", "Sage", "Ripple"), ("Arrow", "Amber", "Acorn")),
    ),
    "random": None,  # Shuffled: see test_random_is_stable_and_complete.
    "list_added": Order(
        "list", "When the title joined the list.",
        (("Acorn", "Cricket", "Lantern", "Arrow", "Ember", "Raven"), ("Orchid", "Cobalt", "Jasper")),
        (("Jasper", "Cobalt", "Orchid", "Heron", "Zephyr", "Nimbus"), ("Lantern", "Cricket", "Acorn")),
        surfaces=(LIST,), param="date_added",
    ),
    "list_tier": Order(
        "list",
        "S, A, B, C, D, F, then Unranked; the list's own order inside a tier. "
        "Descending is the exact reverse, so Unranked comes first.",
        (("Acorn", "Raven", "Larch", "Maple", "Garnet", "Hazel"), ("Cricket", "Basil", "Heron")),
        (("Heron", "Basil", "Cricket", "Jasper", "Nimbus", "Ember"), ("Larch", "Raven", "Acorn")),
        surfaces=(LIST,), param="tier",
    ),
    "status": Order(
        "list", "Planning first, then in progress, completed, paused, dropped.",
        (("Acorn", "Basil", "Garnet", "Nimbus", "Beacon", "Clover"), ("Heron", "Lantern", "Sage")),
        (("Sage", "Lantern", "Heron", "Canyon", "Orchid", "Hazel"), ("Garnet", "Basil", "Acorn")),
        surfaces=(LIST,),
    ),
    "platform": Order(
        GAME, "By platform name; a game with no platform (Brine) last both ways.",
        (("Glass Key", "Moss Run", "Dust Lamp", "Echo Vale", "Iron Tide", "Brine"),
         ("Echo Vale", "Iron Tide", "Brine")),
        (("Iron Tide", "Echo Vale", "Dust Lamp", "Moss Run", "Glass Key", "Brine"),
         ("Moss Run", "Glass Key", "Brine")),
    ),
    "runtime": Order(
        MOVIE, "Shortest first; unknown runtime last both ways.",
        (("Clover", "Harbor", "Marble", "Sage", "Badger", "Delta"), ("Glacier", "Lantern", "Saffron")),
        (("Pine", "Falcon", "Tundra", "Nimbus", "Indigo", "Coral"), ("Cricket", "Birch", "Acorn")),
    ),
    "time_watched": Order(
        MOVIE, "Least time spent watching first; Maple, watched twice, has the most.",
        (("Harbor", "Badger", "Onyx", "Flint", "Anchor", "Nectar"), ("Tundra", "Velvet", "Willow")),
        (("Maple", "Pine", "Indigo", "Ripple", "Cedar", "Juniper"), ("Arrow", "Amber", "Acorn")),
    ),
    "time_to_beat": Order(
        GAME, "Shortest to finish first; equal times A to Z; unknown (Dust Lamp) last both ways.",
        (("Brine", "Iron Tide", "Echo Vale", "Moss Run", "Glass Key", "Dust Lamp"),
         ("Moss Run", "Glass Key", "Dust Lamp")),
        (("Glass Key", "Moss Run", "Echo Vale", "Iron Tide", "Brine", "Dust Lamp"),
         ("Iron Tide", "Brine", "Dust Lamp")),
    ),
    "author": Order(
        BOOK, "By first author, ignoring case; a book with no author (Quiet Hours) last both ways.",
        (("Kite Weather", "Low Tide", "Paper Moon", "Salt Roads", "Quiet Hours"),
         ("Paper Moon", "Salt Roads", "Quiet Hours")),
        (("Salt Roads", "Paper Moon", "Low Tide", "Kite Weather", "Quiet Hours"),
         ("Low Tide", "Kite Weather", "Quiet Hours")),
    ),
    "updated": Order(
        MOVIE, "When the newest row last moved: Bramble (restarted), then Maple (rewatched). API only.",
        (("Acorn", "Cobalt", "Falcon", "Heron", "Larch", "Nimbus"), ("Glacier", "Maple", "Bramble")),
        (("Bramble", "Maple", "Glacier", "Oak", "Amber", "Drift"), ("Falcon", "Cobalt", "Acorn")),
        surfaces=(API,),
    ),
    "time_left": Order(
        TV,
        "Fewest aired episodes left to watch first (Copper Line has watched all of them); "
        "a show with nothing known (Unknown Coast) last both ways. The web differs: see EXEMPT.",
        (("Copper Line", "Nightjar", "Fable Street", "Westward", "Harbor Lights", "Unknown Coast"),
         ("Westward", "Harbor Lights", "Unknown Coast")),
        (("Harbor Lights", "Westward", "Fable Street", "Nightjar", "Copper Line", "Unknown Coast"),
         ("Nightjar", "Copper Line", "Unknown Coast")),
        overrides={WEB: (
            (("Nightjar", "Fable Street", "Westward", "Harbor Lights", "Copper Line", "Unknown Coast"),
             ("Harbor Lights", "Copper Line", "Unknown Coast")),
            (("Copper Line", "Harbor Lights", "Westward", "Fable Street", "Nightjar", "Unknown Coast"),
             ("Fable Street", "Nightjar", "Unknown Coast")),
        )},
    ),
    "next_episode_air_date": Order(
        TV, "When the next unwatched episode airs; equal dates A to Z; nothing scheduled last both ways.",
        (("Fable Street", "Westward", "Harbor Lights", "Nightjar", "Copper Line", "Unknown Coast"),
         ("Nightjar", "Copper Line", "Unknown Coast")),
        (("Copper Line", "Nightjar", "Harbor Lights", "Westward", "Fable Street", "Unknown Coast"),
         ("Westward", "Fable Street", "Unknown Coast")),
    ),
}
# fmt: on

# Where a surface legitimately differs, and what the test does about it.
EXEMPT = {
    ("end_date", API): (
        "The media API keeps end_date as the literal completion date (its documented "
        "contract). The Expo library labels the sort Last watched and asks for last_watched "
        "(libraryTransportCore.test.mjs), so the API reader sends that."
    ),
    ("end_date", LIST): (
        "A list page labels the sort End Date and orders by the literal completion date "
        "(library-query.md); pinned in test_literal_end_date_where_the_label_says_end_date."
    ),
    ("popularity", HOME): (
        "Home saved 'descending popularity' to mean most popular first; the reader flips "
        "the saved direction (adapters.home_engine_direction)."
    ),
    ("time_left", WEB): (
        "The web list ranks shows in groups (app.tv_sort): those with something left by "
        "minutes left, then caught-up shows newest first, then completed, then dropped. The "
        "API (the Expo library) and Home rank by episodes left, so a caught-up show comes "
        "first there and after the shows in progress on the web. A decision, not a bug: "
        "both orders are pinned in ORDERS['time_left']."
    ),
    (LIST, API): (
        "The list API orders in its own code (api.helpers.paginate_list_items), not the "
        "shared engine, and the Expo list screen re-sorts on the device."
    ),
    ("select all", WEB): (
        "Offered only where the web list pages in SQL: not for podcasts, music albums and "
        "artists, TV by time left or separate entries (media_list_views, select_all_url)."
    ),
}

# The value the Expo library sends for a sort, where it is not the key.
API_PARAM = {"end_date": "last_watched"}


def _tracked(index):
    """In the library's "All": a statusless row (a bare rating) is not."""
    return fx.status(index) is not None


def _movies(predicate):
    return frozenset(
        fx.title(index)
        for index in range(fx.MOVIES)
        if _tracked(index) and predicate(index)
    )


def _current_status(index):
    return Status.IN_PROGRESS.value if index == fx.TRACKED_TWICE else fx.status(index)


def _end_day(index):
    end = fx.end_date(index)
    return None if end is None else (end - fx.BASE).days


def _released_in(index, year):
    released = fx.release(index)
    return released is not None and released.year == year


@dataclass(frozen=True)
class FilterCase:
    """One filter, the parameters a surface sends, and the titles it keeps."""

    key: str
    library: str
    params: dict
    expected: frozenset[str]
    reason: str
    surfaces: tuple[str, ...] = (WEB, API)
    exempt: dict = field(default_factory=dict)


# fmt: off
FILTERS = (
    FilterCase("status", MOVIE, {"status": "Paused"},
               _movies(lambda i: _current_status(i) == Status.PAUSED.value),
               "Paused now; Bramble was paused and then restarted, so it is not."),
    FilterCase("status", MOVIE, {"status": "no_status"},
               frozenset(fx.title(index) for index in fx.NO_STATUS),
               "Only the two titles with a rating and no status."),
    FilterCase("date_added", MOVIE, {"date_added_from": "2024-01-11", "date_added_to": "2024-01-20"},
               _movies(lambda i: 10 <= (fx.created(i) - fx.BASE).days <= 19),
               "Added on those ten days; the rewatched Maple was first added on one of them."),
    FilterCase("updated_since", MOVIE, {"updated_since": "2024-02-20T00:00:00Z"},
               _movies(lambda i: i >= 50 or i in (fx.REWATCHED, fx.TRACKED_TWICE)),
               "Rows that changed since then, including a rewatch and a restart."),
    FilterCase("completed_date", MOVIE, {"completed_date_from": "2024-04-10", "completed_date_to": "2024-04-29"},
               _movies(lambda i: _end_day(i) is not None and 100 <= _end_day(i) <= 119),
               "Finished on those twenty days."),
    FilterCase("search", MOVIE, {"search": "AN"},
               _movies(lambda i: "an" in fx.title(i).lower()),
               "Titles containing the text, ignoring case."),
    FilterCase("initial", MOVIE, {"initial": "b"},
               _movies(lambda i: fx.title(i).startswith("B")),
               "Titles starting with B (the A to Z rail)."),
    FilterCase("rating", MOVIE, {"rating_min": "8"},
               _movies(lambda i: fx.score(i) is not None and fx.score(i) >= 8),
               "Rated 8 or more."),
    FilterCase("rating", MOVIE, {"rating": "not_rated"},
               _movies(lambda i: fx.score(i) is None),
               "Not rated."),
    FilterCase("collection", MOVIE, {"collection": "collected"},
               _movies(lambda i: i % 4 == 1),
               "Collected by this person; the other person's copies do not count."),
    FilterCase("genre", MOVIE, {"genre": "Drama"},
               _movies(lambda i: i % 3 == 0), "Drama, by the provider."),
    FilterCase("implied_genre", MOVIE, {"implied_genre": "Noir"},
               _movies(lambda i: i % 6 == 1), "Implied genre Noir.",
               surfaces=(API,),
               exempt={WEB: "The web list offers implied genres for music only and ignores the parameter elsewhere."}),
    FilterCase("year", MOVIE, {"year": "2022"},
               _movies(lambda i: _released_in(i, 2022)), "Released in 2022."),
    FilterCase("year", MOVIE, {"year": "unknown"},
               _movies(lambda i: fx.release(i) is None), "No release date."),
    FilterCase("release", MOVIE, {"release": "not_released"},
               _movies(lambda i: fx.release(i) is None),
               "Not released: every dated title is in the past, so only the undated ones."),
    FilterCase("release_date", MOVIE, {"release_date_from": "2022-01-01", "release_date_to": "2022-12-31"},
               _movies(lambda i: _released_in(i, 2022)), "Released inside the window; undated never match."),
    FilterCase("source", MOVIE, {"source": "TMDB"},
               _movies(lambda i: True), "Every movie comes from TMDB; the match ignores case."),
    FilterCase("media_status", MOVIE, {"media_status": "Post Production"},
               _movies(lambda i: i % 5 == 2), "The provider's production status."),
    FilterCase("language", MOVIE, {"language": "fr"},
               _movies(lambda i: i % 4 == 0), "Spoken in French."),
    FilterCase("country", MOVIE, {"country": "fr"},
               _movies(lambda i: i % 4 == 0), "From France, ignoring case."),
    FilterCase("origin", MOVIE, {"origin": "FR"},
               _movies(lambda i: i % 4 == 0), "Origin France."),
    FilterCase("platforms", GAME, {"platform": "PC"},
               frozenset({"Moss Run", "Glass Key"}), "Games listing PC."),
    FilterCase("format", MOVIE, {"format": "bluray"},
               _movies(lambda i: i % 4 == 1), "Collected on Blu-ray by this person."),
    FilterCase("tags", MOVIE, {"tag": fx.TAGGED},
               _movies(lambda i: i % 5 == 0), "Tagged Favourite by this person."),
    FilterCase("tags", MOVIE, {"tag": fx.TAGGED, "tag_mode": "not"},
               _movies(lambda i: i % 5 != 0), "Not tagged Favourite."),
    FilterCase("author", BOOK, {"author": "ADA BROOK"},
               frozenset({"Low Tide", "Kite Weather"}), "Books by that author, ignoring case."),
    FilterCase("progress", TV, {"progress": "caught_up"},
               frozenset({"Copper Line"}), "Watched everything aired so far."),
)

EXEMPT_FILTERS = {
    "game_group": (
        "A drill-down into one game series or franchise: the web opens it through its own "
        "grouping view (the engine path is forced to group_by=item); the API serves it "
        "from library/game-groups."
    ),
    "season_status": "Home's season shelves only; not offered on the media list or API.",
    "provider": "Reads streaming availability from TMDB at request time, which tests cannot reach.",
}
# fmt: on


def _offline(_session, method, url, *args, **kwargs):
    raise requests.ConnectionError(f"offline in tests: {url}")


def _first_out_of_place(actual, expected):
    for position, (got, wanted) in enumerate(zip(actual, expected, strict=False)):
        if got != wanted:
            return f"position {position + 1} is {got!r}, expected {wanted!r}"
    return f"{len(actual)} titles where {len(expected)} belong"


class ListSemanticsTestCase(TestCase):
    """The fixture, built once, and one reader per surface."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="semantics", password="x")
        cls.other = User.objects.create_user(username="semantics-other", password="x")
        with (
            patch("app.models.Item.fetch_releases", return_value=None),
            suppress_media_change_side_effects(),
        ):
            items = fx.build_movie_library(cls.user, cls.other)
            fx.build_small_libraries(cls.user, cls.other)
            cls.custom_list = fx.build_list(cls.user, items)

    def setUp(self):
        cache.clear()
        for patcher in (
            patch("requests.sessions.Session.request", _offline),
            patch(
                "app.providers.services.get_media_metadata",
                side_effect=requests.ConnectionError("offline in tests"),
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client.force_login(self.user)

    # Readers. Each walks every page and returns (titles, the count shown).

    def read_web(self, media_type, params):
        titles, page = [], 1
        while True:
            response = self.client.get(
                reverse("medialist", args=[media_type]),
                {"layout": "grid", "status": "", **params, "page": page},
                # The fragment the page asks for when it filters or pages:
                # the same context without the page shell.
                headers={"HX-Request": "true"},
            )
            self.assertEqual(response.status_code, 200)
            media_page = response.context["media_list"]
            titles += [entry.item.title for entry in media_page.object_list]
            if not media_page.has_next():
                return titles, media_page.paginator.count
            page += 1

    def read_api(self, media_type, params):
        titles, offset = [], 0
        while True:
            response = self.client.get(
                f"/api/v1/media/{media_type}/",
                {**params, "limit": API_PAGE, "offset": offset},
                headers={"X-Api-Key": self.user.token},
            )
            self.assertEqual(response.status_code, 200, response.content[:300])
            body = response.json()
            titles += [row["item"]["title"] for row in body["results"]]
            offset += API_PAGE
            if offset >= body["pagination"]["total"]:
                return titles, body["pagination"]["total"]

    def read_home(self, media_type, sort, direction, seed=0):
        row = HomeScreenRow.objects.create(
            user=self.user,
            media_type=media_type,
            position=0,
            enabled=True,
            row_type=HomeScreenRowTypeChoices.LIBRARY_QUERY,
            sort_by=sort,
            direction=direction,
            # Every status: a new shelf defaults to In Progress only.
            filters={"status": []},
        )
        titles, offset = [], 0
        while True:
            section = home_screen._build_row_section(
                self.user, row, media_type, HOME_PAGE, batch_start=offset, seed=seed,
            )
            if section is None:
                return titles, 0
            titles += [entry.item.title for entry in section["items"]]
            offset += HOME_PAGE
            if offset >= section["total"]:
                return titles, section["total"]

    def read_list(self, params):
        titles, page = [], 1
        while True:
            response = self.client.get(
                reverse("list_detail", args=[self.custom_list.id]),
                {**params, "page": page},
            )
            self.assertEqual(response.status_code, 200)
            items = response.context["items"]
            titles += [item.title for item in items.object_list]
            if not items.has_next():
                return titles, items.paginator.count
            page += 1

    def select_all_web(self, media_type, params):
        response = self.client.get(
            reverse("medialist", args=[media_type]),
            {"status": "", **params, "bulk_ids": "1"},
        )
        self.assertEqual(response.status_code, 200)
        return self._titles_of(response.json()["item_ids"])

    def select_all_api(self, media_type, params):
        response = self.client.get(
            f"/api/v1/media/{media_type}/item-ids/",
            params,
            headers={"X-Api-Key": self.user.token},
        )
        self.assertEqual(response.status_code, 200, response.content[:300])
        return self._titles_of(response.json()["item_ids"])

    def _titles_of(self, ids):
        self.assertEqual(len(set(ids)), len(ids), "select all returned an id twice")
        return list(Item.objects.filter(pk__in=ids).values_list("title", flat=True))

    def library_titles(self, library):
        """Every title the person has in ``library``, as its "All" view shows it."""
        if library == MOVIE:
            return _movies(lambda index: True)
        if library == LIST:
            return frozenset(fx.title(index) for index in fx.LIST_MEMBERS)
        rows = {GAME: fx.GAMES, BOOK: fx.BOOKS, TV: fx.SHOWS}[library]
        return frozenset(row[0] for row in rows)

    def paging_faults(self, label, titles, shown, library):
        """No title twice, none missing or foreign, the count shown is the count walked."""
        faults = []
        repeats = sorted({title for title in titles if titles.count(title) > 1})
        if repeats:
            faults.append(f"{label}: on two pages: {repeats[:3]}")
        expected = self.library_titles(library)
        missing, foreign = sorted(expected - set(titles)), sorted(set(titles) - expected)
        if missing:
            faults.append(f"{label}: missing {missing[:3]}")
        if foreign:
            faults.append(f"{label}: not this person's library: {foreign[:3]}")
        if shown != len(titles):
            faults.append(f"{label}: shows a count of {shown}, walked {len(titles)}")
        return faults


class SortMeaningTests(ListSemanticsTestCase):
    """Every sort key orders as its row says, on every surface that offers it."""

    def test_every_sort_key_has_a_row(self):
        keys = [definition.keys[0] for definition in SORTS]
        missing = [key for key in keys if key not in ORDERS]
        self.assertEqual(
            missing, [],
            f"State the order in the table: add a row for {missing} to ORDERS in "
            "app/tests/test_list_semantics.py.",
        )
        self.assertEqual(sorted(set(ORDERS) - set(keys)), [], "ORDERS names a key the registry lost")

    def test_every_surface_shows_the_stated_order(self):
        failures = []
        for key, order in ORDERS.items():
            if order is None:
                continue
            for direction in ("asc", "desc"):
                for surface in order.surfaces:
                    first, last = (
                        order.overrides[surface][direction == "desc"]
                        if surface in order.overrides
                        else getattr(order, direction)
                    )
                    label = f"sort {key} {direction} on {surface}"
                    titles, shown = self.read(surface, key, order, direction)
                    failures += self.paging_faults(label, titles, shown, order.library)
                    head, tail = titles[: len(first)], titles[-len(last):]
                    if tuple(head) != first:
                        failures.append(
                            f"{label}, first titles: {_first_out_of_place(head, first)}. "
                            f"Meaning: {order.reason}",
                        )
                    if tuple(tail) != last:
                        failures.append(
                            f"{label}, last titles: {_first_out_of_place(tail, last)}. "
                            f"Meaning: {order.reason}",
                        )
        self.assertEqual(failures, [], "\n" + "\n".join(failures))

    def read(self, surface, key, order, direction):
        if surface == WEB:
            return self.read_web(order.library, {"sort": order.param or key, "direction": direction})
        if surface == API:
            sort = API_PARAM.get(key, key)  # EXEMPT[("end_date", API)]
            return self.read_api(order.library, {"sort": sort, "direction": direction})
        if surface == HOME:
            if key == "popularity":  # EXEMPT[("popularity", HOME)]
                direction = "asc" if direction == "desc" else "desc"
            return self.read_home(order.library, key, direction)
        return self.read_list({"sort": order.param or key, "direction": direction})

    def test_random_is_stable_and_complete(self):
        """A shuffled shelf holds one order for one seed, every title once."""
        first, shown = self.read_home(MOVIE, "random", "asc", seed=12345)
        self.assertEqual(self.paging_faults("random on home", first, shown, MOVIE), [])
        again, _ = self.read_home(MOVIE, "random", "asc", seed=12345)
        self.assertEqual(again, first)

    def test_literal_end_date_where_the_label_says_end_date(self):
        """The API's end_date and a list's End Date read the completion date only."""
        api, _ = self.read_api(MOVIE, {"sort": "end_date", "direction": "desc"})
        # Bramble was restarted and has no completion date, so it is not first
        # as it is under Last Watched.
        self.assertEqual(api[:3], ["Maple", "Nectar", "Fern"])
        listed, _ = self.read_list({"sort": "end_date", "direction": "asc"})
        self.assertEqual(listed[:3], ["Larch", "Canyon", "Cricket"])
        self.assertEqual(listed[-1], "Umber")  # finished without a date: last


class FilterMeaningTests(ListSemanticsTestCase):
    """A filter keeps the same titles on every surface and in "select all"."""

    def test_every_filter_has_a_row(self):
        covered = {case.key for case in FILTERS} | set(EXEMPT_FILTERS)
        missing = [definition.key for definition in FILTER_DEFS if definition.key not in covered]
        self.assertEqual(
            missing, [],
            f"State what {missing} keeps: add a FilterCase to app/tests/test_list_semantics.py.",
        )
        known = {definition.key for definition in FILTER_DEFS}
        self.assertEqual(sorted(covered - known), [], "a row names a filter the registry lost")

    def test_every_surface_and_select_all_keep_the_same_titles(self):
        failures = []
        for case in FILTERS:
            label = f"filter {case.key} {case.params}"
            results = {}
            if WEB in case.surfaces:
                results["web list"] = self.read_web(case.library, case.params)
                results["web select all"] = (self.select_all_web(case.library, case.params), None)
            if API in case.surfaces:
                results["API"] = self.read_api(case.library, case.params)
                results["API select all"] = (self.select_all_api(case.library, case.params), None)
            for surface, (titles, shown) in results.items():
                got = set(titles)
                if len(got) != len(titles):
                    failures.append(f"{label} on {surface}: a title twice")
                if shown is not None and shown != len(titles):
                    failures.append(f"{label} on {surface}: shows {shown}, walked {len(titles)}")
                extra, missing = sorted(got - case.expected), sorted(case.expected - got)
                if extra or missing:
                    failures.append(
                        f"{label} on {surface}: extra {extra[:3]}, missing {missing[:3]} "
                        f"({len(got)} of {len(case.expected)}). Meaning: {case.reason}",
                    )
        self.assertEqual(failures, [], "\n" + "\n".join(failures))

    def test_select_all_spans_every_page(self):
        """Select all with no filter is the whole library, not the first page."""
        everything = _movies(lambda index: True)
        self.assertGreater(len(everything), 32)  # more than one web page
        self.assertEqual(set(self.select_all_web(MOVIE, {})), everything)
        self.assertEqual(set(self.select_all_api(MOVIE, {})), everything)

    def test_select_all_is_offered_only_where_the_list_pages_in_sql(self):
        """EXEMPT[("select all", WEB)]: written down, not changed."""
        offered = self.client.get(reverse("medialist", args=[MOVIE]), {"status": ""})
        self.assertTrue(offered.context["bulk_action_data"]["selectAllUrl"])
        grouped = self.client.get(
            reverse("medialist", args=[TV]), {"status": "", "sort": "time_left"},
        )
        self.assertEqual(grouped.context["bulk_action_data"]["selectAllUrl"], "")
