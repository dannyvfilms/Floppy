"""The libraries ``test_list_semantics`` reads (assignment 76).

Sixty movies for one person, more than one page on every surface: every
status, titles without a date, score or runtime, equal sort values, one
rewatch, one title tracked twice, tags, collected copies and a second person
whose rows must never appear. Each movie's values follow a rule of its index
(``MOVIE_RULES``) so an expected order can be checked by reading the rules.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.models import (
    CollectionEntry,
    Item,
    ItemTag,
    MediaTypes,
    Movie,
    Sources,
    Status,
    Tag,
)

BASE = datetime(2024, 1, 1, 12, tzinfo=UTC)
MOVIES = 60

# Sixty titles in alphabetical order; movie ``i`` is called
# ``TITLES[(7 * i) % 60]`` so title order and index order differ.
TITLES = (
    "Acorn", "Amber", "Anchor", "Arrow", "Aspen", "Badger", "Basil", "Beacon",
    "Birch", "Bramble", "Canyon", "Cedar", "Cinder", "Clover", "Cobalt", "Comet",
    "Coral", "Cricket", "Delta", "Drift", "Ember", "Falcon", "Fern", "Flint",
    "Garnet", "Glacier", "Harbor", "Hazel", "Heron", "Indigo", "Iris", "Jasper",
    "Juniper", "Kestrel", "Lantern", "Larch", "Linden", "Lotus", "Maple", "Marble",
    "Meadow", "Nectar", "Nimbus", "Oak", "Onyx", "Orchid", "Pebble", "Pine",
    "Quartz", "Raven", "Ripple", "Saffron", "Sage", "Sparrow", "Thistle", "Tundra",
    "Umber", "Velvet", "Willow", "Zephyr",
)

# Status by ``i % 6``; the last two movies have only a rating (no status).
STATUS_CYCLE = (
    Status.PLANNING.value,
    Status.IN_PROGRESS.value,
    Status.COMPLETED.value,
    Status.PAUSED.value,
    Status.DROPPED.value,
    Status.COMPLETED.value,
)
NO_STATUS = (58, 59)
# Completed without a watch date (#1718): they must not lead Last Watched.
UNDATED_COMPLETED = (8, 20)
# Watched again later on a second row (#1859): Date Added keeps the first.
REWATCHED = 14
# Paused, then started again on a newer row: the newer row's status counts.
TRACKED_TWICE = 27
# Date Added equal to the movie before it, so the title breaks the tie.
SAME_DAY_AS_PREVIOUS = (11, 41)
TAGGED = "Favourite"
OTHER_USER_TITLES = ("Intruder One", "Intruder Two", "Intruder Three")


def title(index: int) -> str:
    """Return movie ``index``'s title."""
    return TITLES[(7 * index) % MOVIES]


def status(index: int) -> str | None:
    """Return the status of movie ``index``'s first row."""
    if index in NO_STATUS:
        return None
    return STATUS_CYCLE[index % 6]


def created(index: int) -> datetime:
    """Return when movie ``index`` was first tracked: one a day."""
    day = index - 1 if index in SAME_DAY_AS_PREVIOUS else index
    return BASE + timedelta(days=day)


def end_date(index: int) -> datetime | None:
    """Completed and dropped movies end on a scrambled day; two have no date."""
    if status(index) not in (Status.COMPLETED.value, Status.DROPPED.value):
        return None
    if index in UNDATED_COMPLETED:
        return None
    return BASE + timedelta(days=100 + (13 * index) % 60)


def start_date(index: int) -> datetime | None:
    """Anything begun starts the day after it was added; planned has none."""
    if status(index) in (None, Status.PLANNING.value):
        return None
    return created(index) + timedelta(days=1)


def progressed(index: int) -> datetime:
    """When the row last moved: late for in-progress, else when added."""
    if status(index) == Status.IN_PROGRESS.value:
        return BASE + timedelta(days=200 + index)
    return created(index)


def score(index: int) -> Decimal | None:
    """A score of 1 to 10, none for every seventh movie; ties are common."""
    if index % 7 == 0:
        return None
    return Decimal((3 * index) % 10 + 1)


def release(index: int) -> datetime | None:
    """Release a scrambled number of months back; every ninth is unknown."""
    if index % 9 == 0:
        return None
    return BASE - timedelta(days=30 * ((37 * index) % 60))


def critic_rating(index: int) -> float | None:
    """0 to 9.8 in steps of 0.2; every eighth has none."""
    if index % 8 == 0:
        return None
    return ((11 * index) % 50) / 5


def popularity(index: int) -> int | None:
    """Rank 1 (most popular) to 60; every tenth is unranked."""
    if index % 10 == 0:
        return None
    return (17 * index) % 60 + 1


def runtime(index: int) -> int | None:
    """80 to 139 minutes; every eleventh is unknown."""
    if index % 11 == 0:
        return None
    return 80 + (19 * index) % 60


def build_movie_library(user, other_user):
    """Create the sixty movies for ``user`` and the noise for ``other_user``.

    Returns ``{title: item}``. Rows are bulk-created, so no save signal or
    provider call runs; the dates are written afterwards because
    ``created_at`` and ``progressed_at`` are set automatically on insert.
    """
    items = Item.objects.bulk_create(
        [
            Item(
                media_id=str(76_000 + index),
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title=title(index),
                image="https://example.com/poster.jpg",
                release_datetime=release(index),
                provider_rating=critic_rating(index),
                trakt_popularity_rank=popularity(index),
                runtime_minutes=runtime(index),
                genres=["Drama"] if index % 3 == 0 else ["Comedy"],
                implied_genres=["Noir"] if index % 6 == 1 else [],
                status="Post Production" if index % 5 == 2 else "Released",
                languages=["fr"] if index % 4 == 0 else ["en"],
                country="FR" if index % 4 == 0 else "US",
            )
            for index in range(MOVIES)
        ],
    )
    rows = Movie.objects.bulk_create(
        [
            Movie(
                item=item,
                user=user,
                status=status(index),
                score=score(index),
                progress=1 if status(index) == Status.COMPLETED.value else 0,
                start_date=start_date(index),
                end_date=end_date(index),
            )
            for index, item in enumerate(items)
        ],
    )
    for index, row in enumerate(rows):
        Movie.objects.filter(pk=row.pk).update(
            created_at=created(index),
            progressed_at=progressed(index),
            updated_at=created(index),
        )

    rewatch = Movie.objects.create(
        item=items[REWATCHED],
        user=user,
        status=Status.COMPLETED.value,
        progress=1,
        start_date=BASE + timedelta(days=300),
        end_date=BASE + timedelta(days=301),
    )
    Movie.objects.filter(pk=rewatch.pk).update(
        created_at=BASE + timedelta(days=300),
        progressed_at=BASE + timedelta(days=300),
        updated_at=BASE + timedelta(days=300),
    )
    restarted = Movie.objects.create(
        item=items[TRACKED_TWICE],
        user=user,
        status=Status.IN_PROGRESS.value,
        start_date=BASE + timedelta(days=310),
    )
    Movie.objects.filter(pk=restarted.pk).update(
        created_at=BASE + timedelta(days=310),
        progressed_at=BASE + timedelta(days=310),
        updated_at=BASE + timedelta(days=310),
    )

    tag = Tag.objects.create(user=user, name=TAGGED)
    ItemTag.objects.bulk_create(
        [ItemTag(tag=tag, item=item) for index, item in enumerate(items) if index % 5 == 0],
    )
    CollectionEntry.objects.bulk_create(
        [
            CollectionEntry(user=user, item=item, resolution="1080p", media_type="bluray")
            for index, item in enumerate(items)
            if index % 4 == 1
        ],
    )

    # The other person tracks ten of the same titles with values that would
    # lead every order, tags and collects them, and owns three titles of
    # their own. None of it may reach the first person's lists.
    other_items = Item.objects.bulk_create(
        [
            Item(
                media_id=str(77_000 + index),
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title=name,
                image="https://example.com/poster.jpg",
            )
            for index, name in enumerate(OTHER_USER_TITLES)
        ],
    )
    Movie.objects.bulk_create(
        [
            Movie(
                item=item,
                user=other_user,
                status=Status.COMPLETED.value,
                score=Decimal(10),
                progress=1,
                end_date=BASE + timedelta(days=999),
            )
            for item in [*items[:10], *other_items]
        ],
    )
    other_tag = Tag.objects.create(user=other_user, name=TAGGED)
    ItemTag.objects.bulk_create([ItemTag(tag=other_tag, item=item) for item in other_items])
    CollectionEntry.objects.bulk_create(
        [
            CollectionEntry(user=other_user, item=item, media_type="bluray")
            for item in [*items[:10], *other_items]
        ],
    )
    return {item.title: item for item in items}


# The smaller sets: sorts whose values exist only for one kind of media.
# Each is ``(title, values...)`` read by the builder below and by the tables.
GAMES = (
    # title, time to beat in minutes (None: unknown), platform
    ("Moss Run", 300, "PC"),
    ("Iron Tide", 60, "Switch"),
    ("Glass Key", 900, "PC"),
    ("Dust Lamp", None, "PlayStation 5"),
    ("Brine", 60, None),
    ("Echo Vale", 120, "Switch"),
)
BOOKS = (
    # title, first author (None: no author)
    ("Salt Roads", "Ursula Penn"),
    ("Low Tide", "Ada Brook"),
    ("Paper Moon", "Mo Chen"),
    ("Quiet Hours", None),
    ("Kite Weather", "ada brook"),
)
SHOWS = (
    # title, episodes aired (in the past), episodes watched,
    # episodes still to air (in the future), status
    ("Harbor Lights", 10, 2, 0, Status.IN_PROGRESS.value),
    ("Nightjar", 10, 9, 0, Status.IN_PROGRESS.value),
    ("Copper Line", 10, 10, 2, Status.IN_PROGRESS.value),
    ("Westward", 6, 0, 0, Status.PLANNING.value),
    ("Fable Street", 8, 4, 0, Status.PAUSED.value),
    ("Unknown Coast", 0, 0, 0, Status.PLANNING.value),
)


def _game_lengths(minutes):
    if minutes is None:
        return {}
    return {"hltb": {"summary": {"all_styles_minutes": minutes}}}


def build_small_libraries(user, other_user):
    """Create the game, book and TV sets for ``user`` (and noise for ``other_user``)."""
    from django.utils import timezone

    from app.models import TV, Book, Episode, Game, Season
    from events.models import Event

    # Air dates are relative to now, so "aired" and "still to air" stay true.
    today = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)

    games = Item.objects.bulk_create(
        [
            Item(
                media_id=f"g{index}",
                source=Sources.IGDB.value,
                media_type=MediaTypes.GAME.value,
                title=name,
                image="https://example.com/cover.jpg",
                provider_game_lengths=_game_lengths(minutes),
                platforms=[platform] if platform else [],
            )
            for index, (name, minutes, platform) in enumerate(GAMES)
        ],
    )
    Game.objects.bulk_create(
        [Game(item=item, user=user, status=Status.IN_PROGRESS.value) for item in games],
    )
    books = Item.objects.bulk_create(
        [
            Item(
                media_id=f"b{index}",
                source=Sources.OPENLIBRARY.value,
                media_type=MediaTypes.BOOK.value,
                title=name,
                image="https://example.com/cover.jpg",
                authors=[author] if author else [],
                format="audiobook" if index % 2 == 0 else "paperback",
            )
            for index, (name, author) in enumerate(BOOKS)
        ],
    )
    Book.objects.bulk_create(
        [Book(item=item, user=user, status=Status.IN_PROGRESS.value) for item in books],
    )
    # Noise: the other person's game and book would lead each order.
    noise = Item.objects.bulk_create(
        [
            Item(
                media_id="g-other", source=Sources.IGDB.value,
                media_type=MediaTypes.GAME.value, title="Intruder Game",
                image="x", provider_game_lengths=_game_lengths(1), platforms=["Atari"],
            ),
            Item(
                media_id="b-other", source=Sources.OPENLIBRARY.value,
                media_type=MediaTypes.BOOK.value, title="Intruder Book",
                image="x", authors=["Aaron Aardvark"],
            ),
        ],
    )
    Game.objects.create(item=noise[0], user=other_user, status=Status.IN_PROGRESS.value)
    Book.objects.create(item=noise[1], user=other_user, status=Status.IN_PROGRESS.value)

    for index, (name, aired, watched, upcoming, show_status) in enumerate(SHOWS):
        show = Item.objects.create(
            media_id=f"t{index}", source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value, title=name, image="x", runtime_minutes=30,
        )
        tv = TV.objects.bulk_create([TV(item=show, user=user, status=show_status)])[0]
        if not aired and not upcoming:
            continue
        season_item = Item.objects.create(
            media_id=show.media_id, source=show.source,
            media_type=MediaTypes.SEASON.value, season_number=1, title=name, image="x",
        )
        season = Season.objects.bulk_create(
            [Season(item=season_item, related_tv=tv, user=user, status=show_status)],
        )[0]
        # Episode n of the aired ones aired n days before today minus the
        # show's index weeks, so each show's next episode has its own date.
        dates = [
            today - timedelta(days=7 * index + aired - number)
            for number in range(1, aired + 1)
        ] + [today + timedelta(days=30 * (number + 1)) for number in range(upcoming)]
        Event.objects.bulk_create(
            [
                Event(item=season_item, content_number=number, datetime=when)
                for number, when in enumerate(dates, start=1)
            ],
        )
        episode_items = Item.objects.bulk_create(
            [
                Item(
                    media_id=show.media_id, source=show.source,
                    media_type=MediaTypes.EPISODE.value, season_number=1,
                    episode_number=number, title=name, image="x",
                )
                for number in range(1, watched + 1)
            ],
        )
        Episode.objects.bulk_create(
            [
                Episode(
                    item=episode_item, related_season=season,
                    end_date=today - timedelta(days=60 - number),
                )
                for number, episode_item in enumerate(episode_items, start=1)
            ],
        )


# The list: the first 24 movies (every status), added in a scrambled order, most
# placed in a tier. ``LIST_MEMBERS[k]`` is the k-th member by movie index.
LIST_MEMBERS = tuple(range(24))
LIST_TIERS = ("s", "a", "b", "c", "", "s", "f")


def list_added(position: int) -> datetime:
    """When member ``position`` joined the list: a scrambled day."""
    return BASE + timedelta(days=(11 * position) % len(LIST_MEMBERS))


def list_tier(position: int) -> str:
    """Member ``position``'s tier id; every fifth of seven is unranked."""
    return LIST_TIERS[position % len(LIST_TIERS)]


def build_list(user, items_by_title):
    """Create the list over ``LIST_MEMBERS`` and return it."""
    from lists.models import CustomList, CustomListItem

    custom_list = CustomList.objects.create(name="Semantics", owner=user)
    CustomListItem.objects.bulk_create(
        [
            CustomListItem(
                custom_list=custom_list,
                item=items_by_title[title(index)],
                added_by=user,
                tier=list_tier(position),
            )
            for position, index in enumerate(LIST_MEMBERS)
        ],
    )
    for position, index in enumerate(LIST_MEMBERS):
        CustomListItem.objects.filter(
            custom_list=custom_list, item=items_by_title[title(index)],
        ).update(date_added=list_added(position))
    return custom_list
