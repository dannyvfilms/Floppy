"""Long-catalogue fixtures for the detail-page census (assignment 49).

Each ``build_*`` function creates one catalogue of a given length and, for the
``tracked`` user, a library that has watched or played every child with one
repeat. Rows are named from ``prefix`` and ``size`` so callers find them by
name, never by position. Inserts are bulk, so the extreme sizes stay quick.

``FakeTmdb`` answers ``services.api_request`` for TMDB show, season and person
URLs from a synthetic catalogue and counts every call, so pages go through the
real provider code without the network.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from django.conf import settings
from simple_history.utils import bulk_create_with_history

from app.models import (
    TV,
    Album,
    AlbumTracker,
    Anime,
    Artist,
    ArtistMember,
    ArtistTracker,
    BoardGame,
    Book,
    CollectionEntry,
    CollectionField,
    CollectionFieldGroup,
    Comic,
    ComicIssue,
    Episode,
    Game,
    Item,
    ItemTag,
    Manga,
    MediaTypes,
    Movie,
    Music,
    Podcast,
    PodcastEpisode,
    PodcastShow,
    PodcastShowTracker,
    Season,
    Sources,
    Status,
    Tag,
    Track,
    Video,
)
from app.models.discovery import CollectionFieldType
from lists.models import CustomList, CustomListItem

BASE = datetime(2020, 1, 1, 12, 0, tzinfo=UTC)
EPISODES_PER_SEASON = 10
TRACKS_PER_ALBUM = 5
# TMDB ids for synthetic shows, people and movies; far above anything the
# rest of the suite creates.
SHOW_ID_BASE = 9_100_000
PERSON_ID_BASE = 9_200_000
MOVIE_ID_BASE = 9_300_000


@dataclass
class FakeTmdb:
    """Answer TMDB requests for synthetic shows and people; count each call."""

    shows: dict[int, dict[int, int]] = field(default_factory=dict)
    people: dict[int, list[int]] = field(default_factory=dict)
    # Optional richer shapes per show (``build_sample_library``): cast
    # ``(person_id, name)`` pairs, guest stars per ``(season, episode)`` and
    # the ``(season, episode)`` pairs with no air date.
    casts: dict[int, list] = field(default_factory=dict)
    guests: dict[int, dict] = field(default_factory=dict)
    unaired: dict[int, set] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    # The real ``services.api_request``: answers every other provider the way
    # an offline host does (its network layer is patched to fail).
    passthrough: object = None

    def add_show(self, show_id, episodes_by_season, *, cast=(), guests=None, unaired=()):
        self.shows[int(show_id)] = dict(episodes_by_season)
        self.casts[int(show_id)] = list(cast)
        self.guests[int(show_id)] = dict(guests or {})
        self.unaired[int(show_id)] = set(unaired)

    def add_person(self, person_id, movie_ids):
        self.people[int(person_id)] = list(movie_ids)

    def __call__(self, provider, method, url, params=None, **kwargs):
        self.calls.append(url)
        if provider != Sources.TMDB.value:
            return self.passthrough(provider, method, url, params=params, **kwargs)
        if match := re.search(r"/tv/(\d+)/season/(\d+)/episode/(\d+)$", url):
            return self._episode(*(int(group) for group in match.groups()))
        if match := re.search(r"/tv/(\d+)/season/(\d+)$", url):
            show_id, number = (int(group) for group in match.groups())
            if number in self.shows.get(show_id, {}):
                return self._season(
                    number, self.shows[show_id][number], show_id=show_id
                ) | self.MEDIA_APPENDS
        if match := re.search(r"/movie/(\d+)$", url):
            return self._movie(int(match[1]))
        if match := re.search(r"/tv/(\d+)$", url):
            return self._tv(int(match[1]), (params or {}).get("append_to_response", ""))
        if match := re.search(r"/person/(\d+)$", url):
            return self._person(int(match[1]))
        return self.passthrough(provider, method, url, params=params, **kwargs)

    def _tv(self, show_id, appends):
        seasons = self.shows[show_id]
        total = sum(seasons.values())
        response = {
            "id": show_id,
            "name": f"Census Show {show_id}",
            "original_name": f"Census Show {show_id}",
            "poster_path": "/poster.jpg",
            "backdrop_path": "/backdrop.jpg",
            "overview": "A synthetic show.",
            "genres": [{"id": 18, "name": "Drama"}],
            "vote_average": 7.5,
            "vote_count": 100,
            "first_air_date": "2000-01-01",
            "last_air_date": "2020-01-01",
            "status": "Ended",
            "number_of_seasons": len(seasons),
            "number_of_episodes": total,
            "episode_run_time": [45],
            "production_companies": [],
            "production_countries": [],
            "spoken_languages": [],
            "created_by": [],
            "aggregate_credits": {
                "cast": [
                    {
                        "id": person_id,
                        "name": name,
                        "profile_path": None,
                        "known_for_department": "Acting",
                        "order": order,
                        "roles": [{"character": "Lead", "episode_count": total}],
                        "total_episode_count": total,
                    }
                    for order, (person_id, name) in enumerate(self.casts.get(show_id, []))
                ],
                "crew": [],
            },
            "external_ids": {"tvdb_id": show_id},
            "recommendations": {"results": []},
            "watch/providers": {"results": {}},
            **self.MEDIA_APPENDS,
            "last_episode_to_air": None,
            "next_episode_to_air": None,
            "seasons": [
                {
                    "season_number": number,
                    "name": f"Season {number}",
                    "poster_path": None,
                    "air_date": f"{2000 + number % 20}-01-01",
                    "episode_count": count,
                    "overview": "",
                    "vote_average": 7.0,
                    "vote_count": 10,
                }
                for number, count in seasons.items()
            ],
        }
        for append in appends.split(","):
            match = re.fullmatch(r"season/(\d+)", append)
            if match and int(match[1]) in seasons:
                number = int(match[1])
                response[append] = self._season(
                    number, seasons[number], show_id=show_id
                )
        return response

    def _season(self, number, count, *, show_id=None):
        return {
            "name": f"Season {number}",
            "poster_path": None,
            "season_number": number,
            "overview": "",
            "vote_average": 7.0,
            "air_date": "2000-01-01",
            "episodes": [
                self._episode_row(show_id, number, episode, count)
                for episode in range(1, count + 1)
            ],
        }

    def _episode_row(self, show_id, number, episode, count):
        unaired = (number, episode) in self.unaired.get(show_id, set())
        guests = self.guests.get(show_id, {}).get((number, episode), [])
        return {
            "id": number * 100_000 + episode,
            "episode_number": episode,
            "season_number": number,
            "name": f"Episode {episode}",
            "overview": "",
            "air_date": None if unaired else (
                BASE.date() - timedelta(days=count - episode)
            ).isoformat(),
            "runtime": 45,
            "vote_average": 7.0,
            "vote_count": 5,
            "still_path": None,
            "crew": [],
            "guest_stars": [
                {
                    "id": person_id,
                    "name": name,
                    "character": "Guest",
                    "profile_path": None,
                    "order": order,
                }
                for order, (person_id, name) in enumerate(guests)
            ],
        }

    def _episode(self, show_id, number, episode):
        count = self.shows[show_id][number]
        return self._episode_row(show_id, number, episode, count) | {
            "credits": {"cast": [], "crew": [], "guest_stars": []},
        }

    # The ``videos,images`` appends the detail carousel asks for: none.
    MEDIA_APPENDS = {
        "videos": {"results": []},
        "images": {"backdrops": [], "logos": [], "posters": []},
    }

    def _movie(self, movie_id):
        return {
            "id": movie_id,
            "title": f"Census Movie {movie_id}",
            "original_title": f"Census Movie {movie_id}",
            "poster_path": "/m.jpg",
            "backdrop_path": None,
            "overview": "",
            "genres": [{"id": 18, "name": "Drama"}],
            "release_date": "2010-01-01",
            "runtime": 100,
            "vote_average": 6.0,
            "vote_count": 50,
            "status": "Released",
            "production_companies": [],
            "production_countries": [],
            "spoken_languages": [],
            "credits": {"cast": [], "crew": []},
            "recommendations": {"results": []},
            "external_ids": {},
            "watch/providers": {"results": {}},
        } | self.MEDIA_APPENDS

    def _person(self, person_id):
        return {
            "id": person_id,
            "name": f"Census Person {person_id}",
            "profile_path": None,
            "biography": "",
            "known_for_department": "Acting",
            "gender": 2,
            "birthday": "1970-01-01",
            "deathday": None,
            "place_of_birth": "",
            "external_ids": {},
            "combined_credits": {
                "cast": [
                    {
                        "id": movie_id,
                        "media_type": "movie",
                        "title": f"Census Movie {movie_id}",
                        "poster_path": "/m.jpg",
                        "release_date": "2010-01-01",
                        "character": "Lead",
                        "vote_average": 6.0,
                        "vote_count": 50,
                        "popularity": 1.0,
                    }
                    for movie_id in self.people[person_id]
                ],
                "crew": [],
            },
        }


def _plays(user, model, items, *, repeats=2, **fields):
    """Bulk-create ``repeats`` completed entries per item, with history."""
    rows = [
        model(
            item=item,
            user=user,
            status=Status.COMPLETED.value,
            progress=1,
            end_date=BASE - timedelta(days=index * repeats + repeat),
            **fields,
        )
        for index, item in enumerate(items)
        for repeat in range(repeats)
    ]
    bulk_create_with_history(rows, model, default_user=user, batch_size=1000)


def movie_items(prefix, size):
    """Return ``size`` TMDB movie items named ``{prefix} Movie NNNNN``."""
    first = MOVIE_ID_BASE + zlib.crc32(prefix.encode()) % 10_000 * 100_000
    Item.objects.bulk_create(
        Item(
            media_id=str(first + index),
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title=f"{prefix} Movie {index:05d}",
            image="https://image.tmdb.org/t/p/w500/m.jpg",
            release_datetime=BASE - timedelta(days=index),
        )
        for index in range(size)
    )
    return list(
        Item.objects.filter(title__startswith=f"{prefix} Movie ").order_by("title")
    )


def build_tv_show(fake, tracked, *, seasons, episodes=EPISODES_PER_SEASON, prefix):
    """A TMDB show with ``seasons`` seasons; ``tracked`` watched all of it twice."""
    show_id = SHOW_ID_BASE + zlib.crc32(prefix.encode()) % 10_000 * 100
    fake.add_show(show_id, dict.fromkeys(range(1, seasons + 1), episodes))
    media_id = str(show_id)
    title = f"Census Show {show_id}"
    show = Item.objects.create(
        media_id=media_id,
        source=Sources.TMDB.value,
        media_type=MediaTypes.TV.value,
        title=title,
        image="https://image.tmdb.org/t/p/w500/poster.jpg",
    )
    Item.objects.bulk_create(
        Item(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title=title,
            season_number=number,
            image="https://image.tmdb.org/t/p/w500/poster.jpg",
        )
        for number in range(1, seasons + 1)
    )
    Item.objects.bulk_create(
        Item(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title=title,
            season_number=number,
            episode_number=episode,
            runtime_minutes=45,
            image="https://image.tmdb.org/t/p/w500/still.jpg",
        )
        for number in range(1, seasons + 1)
        for episode in range(1, episodes + 1)
    )
    if tracked is not None:
        tv = TV.objects.create(item=show, user=tracked, status=Status.COMPLETED.value)
        season_items = Item.objects.filter(
            media_id=media_id, media_type=MediaTypes.SEASON.value
        ).order_by("season_number")
        # Creating the show may already add its seasons; add the rest.
        existing = set(
            Season.objects.filter(related_tv=tv).values_list("item_id", flat=True)
        )
        bulk_create_with_history(
            [
                Season(
                    item=item,
                    user=tracked,
                    related_tv=tv,
                    status=Status.COMPLETED.value,
                )
                for item in season_items
                if item.id not in existing
            ],
            Season,
            default_user=tracked,
        )
        Season.objects.filter(related_tv=tv).update(status=Status.COMPLETED.value)
        season_by_number = {
            season.item.season_number: season
            for season in Season.objects.filter(related_tv=tv).select_related("item")
        }
        episode_items = Item.objects.filter(
            media_id=media_id, media_type=MediaTypes.EPISODE.value
        ).order_by("season_number", "episode_number")
        rows = [
            Episode(
                related_season=season_by_number[item.season_number],
                item=item,
                status=Status.COMPLETED.value,
                end_date=BASE - timedelta(days=index * 2 + repeat),
            )
            for index, item in enumerate(episode_items)
            for repeat in range(2)
        ]
        bulk_create_with_history(rows, Episode, default_user=tracked, batch_size=1000)
    return show


def build_artist(tracked, *, albums, prefix):
    """An artist with ``albums`` albums of five tracks; ``tracked`` played each twice."""
    artist = Artist.objects.create(name=f"{prefix} Artist")
    Album.objects.bulk_create(
        Album(
            title=f"{prefix} Album {index:04d}",
            artist=artist,
            tracks_populated=True,
            release_type="Album",
            release_date=(BASE - timedelta(days=index * 30)).date(),
        )
        for index in range(albums)
    )
    album_rows = list(Album.objects.filter(artist=artist).order_by("title"))
    Track.objects.bulk_create(
        Track(
            album=album,
            title=f"{album.title} Track {number}",
            track_number=number,
            disc_number=1,
            duration_ms=200_000,
            musicbrainz_recording_id=f"{prefix}-{album.id}-{number}",
        )
        for album in album_rows
        for number in range(1, TRACKS_PER_ALBUM + 1)
    )
    if tracked is None:
        return artist
    ArtistTracker.objects.create(user=tracked, artist=artist)
    tracks = list(Track.objects.filter(album__artist=artist).order_by("id"))
    Item.objects.bulk_create(
        Item(
            media_id=track.musicbrainz_recording_id,
            source=Sources.MUSICBRAINZ.value,
            media_type=MediaTypes.MUSIC.value,
            title=track.title,
        )
        for track in tracks
    )
    items = {
        item.media_id: item
        for item in Item.objects.filter(
            media_type=MediaTypes.MUSIC.value, media_id__startswith=f"{prefix}-"
        )
    }
    rows = [
        Music(
            item=items[track.musicbrainz_recording_id],
            user=tracked,
            artist=artist,
            album_id=track.album_id,
            track=track,
            status=Status.COMPLETED.value,
            progress=2,
            end_date=BASE - timedelta(minutes=index),
        )
        for index, track in enumerate(tracks)
    ]
    bulk_create_with_history(rows, Music, default_user=tracked, batch_size=1000)
    # The second play of each track, as an extra history row.
    entries = Music.objects.filter(user=tracked, artist=artist)
    historical = Music.history.model
    historical.objects.bulk_create(
        [
            historical(
                id=entry.id,
                artist_id=artist.id,
                album_id=entry.album_id,
                track_id=entry.track_id,
                status=entry.status,
                progress=entry.progress,
                end_date=entry.end_date + timedelta(days=1),
                history_date=entry.end_date + timedelta(days=1),
                history_type="~",
                history_user=tracked,
            )
            for entry in entries
        ],
        batch_size=1000,
    )
    return artist


def build_person(fake, tracked, *, credit_count, prefix):
    """A TMDB person with ``credit_count`` movie credits; ``tracked`` watched each twice."""
    person_id = PERSON_ID_BASE + zlib.crc32(prefix.encode()) % 10_000
    items = movie_items(prefix, credit_count)
    fake.add_person(person_id, [int(item.media_id) for item in items])
    if tracked is not None:
        _plays(tracked, Movie, items)
    return person_id


def build_list(owner, tracked, *, items, prefix):
    """A list of ``items`` movies owned by ``owner``; ``tracked`` watched each twice."""
    movies = movie_items(prefix, items)
    custom_list = CustomList.objects.create(name=f"{prefix} List", owner=owner)
    CustomListItem.objects.bulk_create(
        [
            CustomListItem(custom_list=custom_list, item=item, added_by=owner)
            for item in movies
        ],
        batch_size=1000,
    )
    if tracked is not None:
        _plays(tracked, Movie, movies)
    return custom_list


def build_collection(owner, tracked, *, entries, prefix):
    """``entries`` collected movies for ``owner``; ``tracked`` also watched each twice."""
    movies = movie_items(prefix, entries)
    CollectionEntry.objects.bulk_create(
        [
            CollectionEntry(
                user=owner,
                item=item,
                media_type="bluray",
                resolution="1080p",
            )
            for item in movies
        ],
        batch_size=1000,
    )
    if tracked is not None:
        _plays(tracked, Movie, movies)
    return movies


def build_tag(owner, tracked, *, entries, prefix):
    """One tag on ``entries`` movies for ``owner``; ``tracked`` also watched each twice."""
    movies = movie_items(prefix, entries)
    tag = Tag.objects.create(user=owner, name=f"{prefix} tag")
    ItemTag.objects.bulk_create(
        [ItemTag(tag=tag, item=item) for item in movies], batch_size=1000
    )
    if tracked is not None:
        _plays(tracked, Movie, movies)
    return tag


# ---------------------------------------------------------------------------
# One realistic library (assignment 73)
# ---------------------------------------------------------------------------
#
# ``build_sample_library`` gives one user at least one tracked item of every
# ``MediaTypes`` value, plus the awkward shapes that have broken pages before:
# a cast member whose card has no ``source`` (#1953), an episode with no air
# date (#1717), a numeric collection choice (#1700), a podcast show with
# episodes in three states (#1828), an album with tracks and a rating, a
# grouped anime stored on TV rows, a manual item, an item with no image and an
# empty second user. Provider answers come from ``SampleLibrary.payloads``
# (processed metadata, served by ``stored_metadata``) and from ``FakeTmdb``
# (raw TMDB answers, so TV, season, episode and person pages run the real
# provider code). Nothing reaches the network.
#
# Used by ``app.tests.test_every_page_opens`` and by the PR screenshot seed
# (``scripts/pr_screenshots_seed.py``). Add a shape here when a page breaks
# on data no fixture had, and every page test that uses it picks it up.

SAMPLE_SHOW_ID = 9_400_001
SAMPLE_ANIME_SHOW_ID = 9_400_002
SAMPLE_PERSON_ID = 9_400_101
SAMPLE_GUEST_ID = 9_400_102
SAMPLE_MOVIE_ID = "9400201"
SAMPLE_UNAIRED_EPISODE = (1, 3)
SAMPLE_UNTRACKED_EPISODE = (1, 4)


def _sample_payload(media_type, source, media_id, title, **extra):
    """Processed provider metadata in the shape ``get_media_metadata`` returns."""
    payload = {
        "media_id": str(media_id),
        "source": source,
        "media_type": media_type,
        "title": title,
        "original_title": title,
        "localized_title": title,
        "image": f"https://example.com/{media_type}.jpg",
        "synopsis": f"A sample {media_type}.",
        "genres": ["Drama"],
        "score": 7.5,
        "score_count": 100,
        "max_progress": 1,
        "details": {"format": media_type.title(), "release_date": "2010-01-01"},
        # A cast card with no ``source``: the page must supply it (#1953).
        "cast": [
            {
                "person_id": str(SAMPLE_PERSON_ID),
                "name": "Sample Person",
                "role": "Lead",
                "image": settings.IMG_NONE,
            },
        ],
        "crew": [],
        "related": {"recommendations": []},
        "provider_external_ids": {},
    }
    payload.update(extra)
    return payload


@dataclass
class SampleLibrary:
    """Handles to everything ``build_sample_library`` created."""

    user: object
    empty_user: object
    fake: FakeTmdb
    # One item per media type whose pages a test opens, keyed by MediaTypes value.
    items: dict = field(default_factory=dict)
    # (media_type, source, media_id) -> processed metadata.
    payloads: dict = field(default_factory=dict)
    grouped_anime: object = None
    manual_item: object = None
    no_image_item: object = None
    custom_list: object = None
    podcast_show: object = None
    podcast_list: object = None
    artist: object = None
    album: object = None
    track: object = None
    person_id: int = SAMPLE_PERSON_ID
    season_number: int = 1
    episode_number: int = 1

    def stored_metadata(self, real):
        """Return a ``get_media_metadata`` that answers from ``payloads``.

        Anything not stored (manual, video and TMDB TV routes) goes to
        ``real``, which reaches ``FakeTmdb`` or the database.
        """
        import copy

        def get_media_metadata(media_type, media_id, source, *args, **kwargs):
            key = (media_type, source, str(media_id))
            if key in self.payloads:
                return copy.deepcopy(self.payloads[key])
            return real(media_type, media_id, source, *args, **kwargs)

        return get_media_metadata

    def search_results(self, media_type, *_args, **_kwargs):
        """A ``services.search`` answer listing the library's item of that type."""
        item = self.items.get(media_type)
        results = []
        if item is not None:
            results.append(
                {
                    "media_id": item.media_id,
                    "source": item.source,
                    "media_type": media_type,
                    "title": item.title,
                    "image": item.image or settings.IMG_NONE,
                    "year": 2010,
                },
            )
        return {
            "page": 1,
            "total_results": len(results),
            "total_pages": 1,
            "results": results,
        }

    def patchers(self):
        """Patches that keep every provider call offline and answered.

        Start them before requesting pages (``setUpClass``). TMDB goes to
        ``FakeTmdb``, stored payloads answer ``get_media_metadata``, and any
        other HTTP request fails as on an offline host.
        """
        from unittest.mock import patch

        import requests

        from app.providers import services

        self.fake.passthrough = services.api_request

        def offline(_session, method, url, *args, **kwargs):
            raise requests.ConnectionError(f"offline in tests: {url}")

        return [
            patch("app.providers.services.api_request", side_effect=self.fake),
            patch(
                "app.providers.services.get_media_metadata",
                side_effect=self.stored_metadata(services.get_media_metadata),
            ),
            patch(
                "app.providers.services.search",
                side_effect=lambda media_type, *args, **kwargs: self.search_results(
                    media_type
                ),
            ),
            patch("requests.sessions.Session.request", offline),
        ]


def build_sample_library(user, *, empty_user=None, fake=None, now=None):
    """Create the sample library for ``user`` and return a ``SampleLibrary``.

    Cheap enough for ``setUpTestData``. ``empty_user``, when given, is left
    with nothing tracked. ``fake`` is the ``FakeTmdb`` to register shows and
    people on; a new one is made when omitted. ``now`` fixes the instant the
    play dates count back from (the recorded native answers need a fixed one).
    """
    fake = fake or FakeTmdb()
    library = SampleLibrary(user=user, empty_user=empty_user, fake=fake)
    now = now or datetime.now(UTC)
    _sample_tv(library)
    _sample_grouped_anime(library)
    _sample_provider_types(library, now)
    _sample_manual_and_no_image(library, now)
    _sample_podcast(library)
    _sample_music(library, now)
    _sample_video(library, now)
    _sample_collection_field(library)
    fake.add_person(SAMPLE_PERSON_ID, [int(SAMPLE_MOVIE_ID)])
    fake.add_person(SAMPLE_GUEST_ID, [int(SAMPLE_MOVIE_ID)])
    custom_list = CustomList.objects.create(name="Every type", owner=user)
    for item in library.items.values():
        CustomListItem.objects.create(custom_list=custom_list, item=item, added_by=user)
    library.custom_list = custom_list
    return library


def _sample_tv(library):
    """A TMDB show, two seasons, a guest star and one episode with no air date."""
    show_id = SAMPLE_SHOW_ID
    library.fake.add_show(
        show_id,
        {1: 4, 2: 2},
        cast=[(SAMPLE_PERSON_ID, "Sample Person")],
        # Episode 1 is watched; episode 4 is not, so its page has no tracker
        # row (``media``) beside the guest star, the #1953 shape.
        guests={
            (1, 1): [(SAMPLE_GUEST_ID, "Sample Guest")],
            SAMPLE_UNTRACKED_EPISODE: [(SAMPLE_GUEST_ID, "Sample Guest")],
        },
        unaired={SAMPLE_UNAIRED_EPISODE},
    )
    media_id = str(show_id)
    title = f"Census Show {show_id}"
    show = Item.objects.create(
        media_id=media_id,
        source=Sources.TMDB.value,
        media_type=MediaTypes.TV.value,
        title=title,
        image="https://image.tmdb.org/t/p/w500/poster.jpg",
    )
    season_item = Item.objects.create(
        media_id=media_id,
        source=Sources.TMDB.value,
        media_type=MediaTypes.SEASON.value,
        title=title,
        season_number=1,
        image="https://image.tmdb.org/t/p/w500/poster.jpg",
    )
    episode_items = [
        Item.objects.create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title=title,
            season_number=1,
            episode_number=number,
            runtime_minutes=45,
            # The unaired episode has no date at all (#1717).
            release_datetime=(
                None
                if (1, number) == SAMPLE_UNAIRED_EPISODE
                else BASE - timedelta(days=10 - number)
            ),
            image="https://image.tmdb.org/t/p/w500/still.jpg",
        )
        for number in range(1, 5)
    ]
    tv = TV.objects.create(
        item=show, user=library.user, status=Status.IN_PROGRESS.value, score=8
    )
    season = Season.objects.filter(related_tv=tv, item=season_item).first()
    if season is None:
        season = Season.objects.create(
            item=season_item,
            user=library.user,
            related_tv=tv,
            status=Status.IN_PROGRESS.value,
        )
    for index, item in enumerate(episode_items[:2]):
        Episode.objects.create(
            related_season=season,
            item=item,
            status=Status.COMPLETED.value,
            end_date=BASE + timedelta(days=index),
        )
    library.items[MediaTypes.TV.value] = show
    library.items[MediaTypes.SEASON.value] = season_item
    library.items[MediaTypes.EPISODE.value] = episode_items[0]


def _sample_grouped_anime(library):
    """A TMDB anime grouped on TV rows (``library_media_type`` anime)."""
    show_id = SAMPLE_ANIME_SHOW_ID
    library.fake.add_show(show_id, {1: 3})
    item = Item.objects.create(
        media_id=str(show_id),
        source=Sources.TMDB.value,
        media_type=MediaTypes.TV.value,
        library_media_type=MediaTypes.ANIME.value,
        title=f"Census Show {show_id}",
        image="https://image.tmdb.org/t/p/w500/poster.jpg",
    )
    TV.objects.create(item=item, user=library.user, status=Status.IN_PROGRESS.value)
    library.grouped_anime = item


# media type -> (model, source, media_id, extra payload fields)
_PROVIDER_TYPES = {
    MediaTypes.MOVIE.value: (Movie, Sources.TMDB.value, SAMPLE_MOVIE_ID, {"max_progress": 1}),
    MediaTypes.ANIME.value: (Anime, Sources.MAL.value, "9400301", {"max_progress": 12}),
    MediaTypes.MANGA.value: (Manga, Sources.MAL.value, "9400401", {"max_progress": 40}),
    MediaTypes.GAME.value: (Game, Sources.IGDB.value, "9400501", {"max_progress": None}),
    MediaTypes.BOOK.value: (Book, Sources.OPENLIBRARY.value, "OL9400601M", {"max_progress": 320}),
    MediaTypes.COMIC.value: (Comic, Sources.COMICVINE.value, "9400701", {"max_progress": 12}),
    MediaTypes.COMIC_ISSUE.value: (
        ComicIssue, Sources.COMICVINE.value, "9400702", {"max_progress": 1},
    ),
    MediaTypes.BOARDGAME.value: (BoardGame, Sources.BGG.value, "9400801", {"max_progress": None}),
}


def _sample_provider_types(library, now):
    """One tracked, rated item per provider-backed type, with a stored payload."""
    for index, (media_type, (model, source, media_id, extra)) in enumerate(
        _PROVIDER_TYPES.items()
    ):
        title = f"Sample {MediaTypes(media_type).label}"
        item = Item.objects.create(
            media_id=media_id,
            source=source,
            media_type=media_type,
            title=title,
            image=f"https://example.com/{media_type}.jpg",
            genres=["Drama"],
            release_datetime=BASE - timedelta(days=365 * index),
        )
        model.objects.create(
            item=item,
            user=library.user,
            status=Status.COMPLETED.value if index % 2 else Status.IN_PROGRESS.value,
            score=7 + index % 3,
            progress=1,
            start_date=now - timedelta(days=30 + index),
            end_date=now - timedelta(days=index),
        )
        library.payloads[(media_type, source, media_id)] = _sample_payload(
            media_type, source, media_id, title, **extra
        )
        library.items[media_type] = item


def _sample_manual_and_no_image(library, now):
    """A manual movie, and a movie with no artwork at all."""
    manual = Item.objects.create(
        media_id="sample-manual-movie",
        source=Sources.MANUAL.value,
        media_type=MediaTypes.MOVIE.value,
        title="The Long Title That Wraps Across Several Lines",
        genres=["Drama", "Sci-Fi"],
    )
    Movie.objects.create(
        item=manual,
        user=library.user,
        status=Status.COMPLETED.value,
        score=8,
        end_date=now - timedelta(days=1),
    )
    bare = Item.objects.create(
        media_id="9400202",
        source=Sources.TMDB.value,
        media_type=MediaTypes.MOVIE.value,
        title="No Artwork",
        image=settings.IMG_NONE,
    )
    Movie.objects.create(
        item=bare, user=library.user, status=Status.PLANNING.value
    )
    library.payloads[(MediaTypes.MOVIE.value, Sources.TMDB.value, "9400202")] = (
        _sample_payload(
            MediaTypes.MOVIE.value,
            Sources.TMDB.value,
            "9400202",
            "No Artwork",
            image=settings.IMG_NONE,
            cast=[],
            genres=[],
            details={},
        )
    )
    library.manual_item = manual
    library.no_image_item = bare


def _sample_podcast(library):
    """A rated show whose episodes are in progress, played and untracked."""
    show = PodcastShow.objects.create(
        podcast_uuid="sample-podcast-show",
        source=Sources.POCKETCASTS.value,
        title="Example Podcast",
        image=settings.IMG_NONE,
    )
    show_item = Item.objects.create(
        media_id=show.podcast_uuid,
        source=show.source,
        media_type=MediaTypes.PODCAST.value,
        title=show.title,
        image=settings.IMG_NONE,
        release_datetime=datetime(2025, 1, 1, tzinfo=UTC),
    )
    PodcastShowTracker.objects.create(
        user=library.user, show=show, status=Status.IN_PROGRESS.value, score=8
    )
    podcast_list = CustomList.objects.create(
        name="Podcast status review", owner=library.user
    )
    CustomListItem.objects.create(custom_list=podcast_list, item=show_item)
    for number, (identity, title, status) in enumerate(
        (
            ("sample-podcast-playing", "Episode in progress", Status.IN_PROGRESS.value),
            ("sample-podcast-played", "Completed episode", Status.COMPLETED.value),
            ("sample-podcast-untracked", "Untracked episode", None),
        ),
        start=1,
    ):
        episode = PodcastEpisode.objects.create(
            show=show,
            episode_uuid=identity,
            title=title,
            published=datetime(2025, 1, number, tzinfo=UTC),
            duration=1800,
            episode_number=number,
        )
        item = Item.objects.create(
            media_id=identity,
            source=show.source,
            media_type=MediaTypes.PODCAST.value,
            title=title,
            image=settings.IMG_NONE,
            release_datetime=datetime(2025, 1, number, tzinfo=UTC),
        )
        CustomListItem.objects.create(custom_list=podcast_list, item=item)
        if status:
            Podcast.objects.create(
                user=library.user,
                item=item,
                show=show,
                episode=episode,
                status=status,
                end_date=(
                    datetime(2025, 2, number, tzinfo=UTC)
                    if status == Status.COMPLETED.value
                    else None
                ),
            )
    library.podcast_show = show
    library.podcast_list = podcast_list
    library.items[MediaTypes.PODCAST.value] = show_item


def _sample_music(library, now):
    """A band with members, and a rated album whose tracks were played."""
    band = Artist.objects.create(name="Shot Band", genres=["Rock"])
    for name, role, current in (("Ada", "guitar", True), ("Bo", "drums", False)):
        ArtistMember.objects.create(
            band=band,
            member=Artist.objects.create(name=name),
            role=role,
            is_current=current,
        )
    ArtistTracker.objects.create(user=library.user, artist=band)
    album = Album.objects.create(
        title="Shot Album",
        artist=band,
        genres=["Rock"],
        tracks_populated=True,
        release_date=BASE.date(),
    )
    AlbumTracker.objects.create(
        user=library.user, album=album, status=Status.COMPLETED.value, score=9
    )
    origins = ["https://soundcloud.com/shot/one", "https://open.spotify.com/track/two", ""]
    first = None
    for number, origin in enumerate(origins, start=1):
        track = Track.objects.create(
            album=album,
            title=f"Track {number}",
            track_number=number,
            duration_ms=200_000,
        )
        first = first or track
        item = Item.objects.create(
            media_id=f"sample-track-{number}",
            source=Sources.MUSICBRAINZ.value,
            media_type=MediaTypes.MUSIC.value,
            title=track.title,
        )
        Music.objects.create(
            item=item,
            user=library.user,
            artist=band,
            album=album,
            track=track,
            status=Status.COMPLETED.value,
            end_date=now - timedelta(hours=number),
            origin_url=origin,
        )
        if number == 1:
            library.items[MediaTypes.MUSIC.value] = item
    library.artist, library.album, library.track = band, album, first


def _sample_video(library, now):
    """A YouTube video with one play."""
    item = Item.objects.create(
        media_id="sample-video-1",
        source=Sources.YOUTUBE.value,
        media_type=MediaTypes.VIDEO.value,
        title="Sample Video",
        image="https://example.com/video.jpg",
        release_datetime=BASE,
    )
    Video.objects.create(
        item=item,
        user=library.user,
        status=Status.COMPLETED.value,
        channel="Sample Channel",
        watch_url="https://www.youtube.com/watch?v=sample-video-1",
        length_seconds=600,
        end_date=now - timedelta(hours=2),
    )
    library.items[MediaTypes.VIDEO.value] = item


def _sample_collection_field(library):
    """A collection drop-down whose choices are numbers (#1700)."""
    group = CollectionFieldGroup.objects.create(user=library.user, name="Shelf")
    CollectionField.objects.create(
        group=group,
        label="Disc count",
        field_type=CollectionFieldType.SELECT,
        options=[1, 2, 4],
        media_types=list(MediaTypes.values),
    )
