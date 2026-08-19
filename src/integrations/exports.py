import csv
import json
import logging
from collections import defaultdict
from io import StringIO

from django.apps import apps
from django.conf import settings
from django.db.models import Field

from app import helpers
from app.models import (
    AlbumTracker,
    ArtistTracker,
    CollectionEntry,
    Item,
    ItemTag,
    MediaTypes,
    Sources,
)
from lists.models import CustomList

logger = logging.getLogger(__name__)


class Echo:
    """An object that implements just the write method of the file-like interface."""

    def write(self, value):
        """Write the value by returning it, instead of storing in a buffer."""
        return value


def _get_media_types_to_export(media_types=None):
    """Return the list of media type values to export.

    If *media_types* is ``None`` every type is included (original behaviour).
    Otherwise only the explicitly requested types **plus** their implicit
    children (season → episode, tv → season+episode) are returned.
    """
    if media_types is None:
        return [*list(MediaTypes.values), "music_artist", "music_album"]

    out = list(media_types)
    # If TV is selected, ensure season & episode are included
    if MediaTypes.TV.value in out:
        for child in (MediaTypes.SEASON.value, MediaTypes.EPISODE.value):
            if child not in out:
                out.append(child)
    # If season is selected, ensure episode is included
    if MediaTypes.SEASON.value in out and MediaTypes.EPISODE.value not in out:
        out.append(MediaTypes.EPISODE.value)
    # If music is selected, include artist and album trackers too
    if MediaTypes.MUSIC.value in out:
        if "music_artist" not in out:
            out.append("music_artist")
        if "music_album" not in out:
            out.append("music_album")
    return out


def generate_rows(user, media_types=None, include_lists=True, include_collection=True):
    """Generate CSV rows.

    Parameters
    ----------
    user : User
        The user whose data is being exported.
    media_types : list[str] | None
        Restrict export to these media types.  ``None`` means *all*.
        An empty list exports no media rows but, mirroring lists, still
        exports all collection entries when *include_collection* is on
        (enables a collection-only export).
    include_lists : bool
        Whether to include custom lists in the export.
    include_collection : bool
        Whether to include collection (owned media) entries in the export.
    """
    pseudo_buffer = Echo()
    writer = csv.writer(pseudo_buffer, quoting=csv.QUOTE_ALL)

    # Get fields
    fields = {
        # watch_providers scales with ~60 TMDB regions, is never read back on
        # import, and is fully re-fetchable via the provider backfill task.
        "item": get_model_fields(Item, exclude={"watch_providers"}),
        "track": get_track_fields(),
        "list": get_list_fields(),
        "collection": get_collection_fields(),
        "tags": get_tag_fields(),
    }

    # Yield header row
    yield writer.writerow(
        ["row_type"]
        + fields["item"]
        + fields["track"]
        + fields["list"]
        + fields["collection"]
        + fields["tags"],
    )

    item_tags_map = _build_item_tags_map(user)

    types_to_export = _get_media_types_to_export(media_types)

    # Yield data rows
    for media_type in MediaTypes.values:
        if media_type not in types_to_export:
            continue

        model = apps.get_model("app", media_type)

        filter_kwargs = (
            {"related_season__user": user}
            if media_type == MediaTypes.EPISODE.value
            else {"user": user}
        )

        # Only ``item`` is read per row below - no season/episode nesting is
        # ever touched here, so no further select_related/prefetch_related is
        # needed. A prior version eagerly prefetched every season and episode
        # for each tv/season row despite never using them, tripling the
        # episode load for large libraries and causing exports to time out
        # partway through (issue #618).
        queryset = model.objects.filter(**filter_kwargs).select_related("item")

        logger.debug("Streaming %ss to CSV", media_type)

        row_count = 0
        for media in queryset.iterator(chunk_size=500):
            if media.item is None:
                logger.warning(
                    "Skipping %s id=%s for user %s: no linked item",
                    media_type,
                    media.pk,
                    user.username,
                )
                continue
            row_count += 1
            row = (
                ["media"]
                + [getattr(media.item, field, "") for field in fields["item"]]
                + [getattr(media, field, "") for field in fields["track"]]
                + [""] * len(fields["list"])
                + [""] * len(fields["collection"])
                + [json.dumps(item_tags_map.get(media.item_id, []))]
            )

            if media_type == MediaTypes.GAME.value:
                # calculate index of progress field
                progress_index = fields["track"].index("progress")
                row[progress_index + 1 + len(fields["item"])] = helpers.minutes_to_hhmm(
                    media.progress,
                )

            yield writer.writerow(row)

        logger.debug("Finished streaming %d %s row(s) to CSV", row_count, media_type)

    if "music_artist" in types_to_export:
        logger.debug("Streaming music_artists to CSV")
        for tracker in ArtistTracker.objects.filter(user=user).select_related("artist"):
            artist = tracker.artist
            item_vals = {
                "media_id": artist.musicbrainz_id or "",
                "source": "musicbrainz",
                "media_type": "music_artist",
                "title": artist.name,
                "image": artist.image or "",
                "library_media_type": "",
                "season_number": "",
                "episode_number": "",
            }
            track_vals = {
                "status": tracker.status,
                "score": tracker.score if tracker.score is not None else "",
                "notes": tracker.notes,
                "start_date": tracker.start_date.isoformat()
                if tracker.start_date
                else "",
                "end_date": tracker.end_date.isoformat() if tracker.end_date else "",
                "created_at": tracker.created_at.isoformat()
                if tracker.created_at
                else "",
            }
            row = (
                ["media"]
                + [item_vals.get(f, "") for f in fields["item"]]
                + [track_vals.get(f, "") for f in fields["track"]]
                + [""] * len(fields["list"])
                + [""] * len(fields["collection"])
                + [""] * len(fields["tags"])
            )
            yield writer.writerow(row)
        logger.debug("Finished streaming music_artists to CSV")

    if "music_album" in types_to_export:
        logger.debug("Streaming music_albums to CSV")
        for tracker in AlbumTracker.objects.filter(user=user).select_related("album"):
            album = tracker.album
            item_vals = {
                "media_id": album.musicbrainz_release_group_id or "",
                "source": "musicbrainz",
                "media_type": "music_album",
                "title": album.title,
                "image": album.image or "",
                "library_media_type": "",
                "season_number": "",
                "episode_number": "",
            }
            track_vals = {
                "status": tracker.status,
                "score": tracker.score if tracker.score is not None else "",
                "notes": tracker.notes,
                "start_date": tracker.start_date.isoformat()
                if tracker.start_date
                else "",
                "end_date": tracker.end_date.isoformat() if tracker.end_date else "",
                "created_at": tracker.created_at.isoformat()
                if tracker.created_at
                else "",
            }
            row = (
                ["media"]
                + [item_vals.get(f, "") for f in fields["item"]]
                + [track_vals.get(f, "") for f in fields["track"]]
                + [""] * len(fields["list"])
                + [""] * len(fields["collection"])
                + [""] * len(fields["tags"])
            )
            yield writer.writerow(row)
        logger.debug("Finished streaming music_albums to CSV")

    if include_lists:
        yield from _generate_list_rows(user, writer, fields, item_tags_map)

    if include_collection:
        yield from _generate_collection_rows(
            user, writer, fields, media_types, item_tags_map
        )


def _generate_list_rows(user, writer, fields, item_tags_map):
    """Yield ``list`` and ``list_item`` rows for the user's custom lists."""
    custom_lists = CustomList.objects.filter(owner=user).order_by("name")

    for custom_list in custom_lists:
        yield from _generate_single_list_rows(
            custom_list, writer, fields, item_tags_map
        )


def _generate_single_list_rows(custom_list, writer, fields, item_tags_map):
    """Yield the ``list`` row and its ``list_item`` rows for one custom list."""
    list_row = (
        ["list"]
        + [""] * len(fields["item"])
        + [""] * len(fields["track"])
        + [
            custom_list.id,
            custom_list.name,
            custom_list.description,
            json.dumps(custom_list.tags or []),
            custom_list.visibility,
            custom_list.allow_recommendations,
            custom_list.source,
            custom_list.source_id,
            custom_list.is_smart,
            json.dumps(custom_list.smart_media_types or []),
            json.dumps(custom_list.smart_excluded_media_types or []),
            json.dumps(custom_list.smart_filters or {}),
            "",
        ]
        + [""] * len(fields["collection"])
        + [""] * len(fields["tags"])
    )
    yield writer.writerow(list_row)

    list_items = custom_list.customlistitem_set.select_related("item").order_by(
        "date_added", "pk"
    )
    for list_item in list_items:
        item = list_item.item
        list_item_row = (
            ["list_item"]
            + [getattr(item, field, "") for field in fields["item"]]
            + [""] * len(fields["track"])
            + [
                custom_list.id,
                custom_list.name,
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                list_item.date_added.isoformat() if list_item.date_added else "",
            ]
            + [""] * len(fields["collection"])
            + [json.dumps(item_tags_map.get(item.id, []))]
        )
        yield writer.writerow(list_item_row)


def generate_list_csv(custom_list):
    """Generate CSV rows for a single custom list (definition + item snapshot).

    Uses the same header/column layout as ``generate_rows`` so the output is
    directly importable via the full-backup ``YamtrackImporter``.
    """
    pseudo_buffer = Echo()
    writer = csv.writer(pseudo_buffer, quoting=csv.QUOTE_ALL)

    fields = {
        # watch_providers scales with ~60 TMDB regions, is never read back on
        # import, and is fully re-fetchable via the provider backfill task.
        "item": get_model_fields(Item, exclude={"watch_providers"}),
        "track": get_track_fields(),
        "list": get_list_fields(),
        "collection": get_collection_fields(),
        "tags": get_tag_fields(),
    }

    yield writer.writerow(
        ["row_type"]
        + fields["item"]
        + fields["track"]
        + fields["list"]
        + fields["collection"]
        + fields["tags"],
    )

    item_tags_map = _build_item_tags_map(custom_list.owner)
    yield from _generate_single_list_rows(custom_list, writer, fields, item_tags_map)


def _generate_collection_rows(user, writer, fields, media_types, item_tags_map):
    """Yield ``collection`` rows for the user's collection entries.

    When *media_types* is a non-empty list, only entries whose item matches
    the requested types (plus implicit children) are exported; ``None`` and
    ``[]`` both export every entry.
    """
    logger.debug("Streaming collection entries to CSV")
    queryset = CollectionEntry.objects.filter(user=user).select_related("item")
    if media_types:
        types_to_export = _get_media_types_to_export(media_types)
        queryset = queryset.filter(item__media_type__in=types_to_export)
    queryset = queryset.order_by("item__media_type", "collected_at", "pk")

    for entry in queryset.iterator(chunk_size=500):
        collection_vals = []
        for attr in COLLECTION_EXPORT_FIELDS.values():
            value = getattr(entry, attr)
            if attr == "collected_at":
                value = value.isoformat() if value else ""
            elif value is None:
                value = ""
            collection_vals.append(value)
        row = (
            ["collection"]
            + [getattr(entry.item, field, "") for field in fields["item"]]
            + [""] * len(fields["track"])
            + [""] * len(fields["list"])
            + collection_vals
            + [json.dumps(item_tags_map.get(entry.item_id, []))]
        )
        yield writer.writerow(row)
    logger.debug("Finished streaming collection entries to CSV")


def write_backup(user, media_types=None, include_lists=True, include_collection=True):
    """Write a CSV backup to the configured backup directory.

    Returns the path to the created file.
    """
    from pathlib import Path

    from django.conf import settings
    from django.utils import timezone

    backup_dir = Path(settings.BACKUP_DIR) / str(user.username)
    backup_dir.mkdir(parents=True, exist_ok=True)

    now = timezone.localtime()
    filename = f"floppy_{now.strftime('%Y-%m-%d_%H%M%S')}.csv"
    filepath = backup_dir / filename

    with filepath.open("w", newline="", encoding="utf-8") as f:
        f.writelines(
            generate_rows(
                user,
                media_types=media_types,
                include_lists=include_lists,
                include_collection=include_collection,
            )
        )

    logger.info("Backup written to %s for user %s", filepath, user.username)
    return str(filepath)


def get_model_fields(model, exclude=frozenset()):
    """Get a list of fields names from a model."""
    return [
        field.name
        for field in model._meta.get_fields()
        if isinstance(field, Field)
        and not field.auto_created
        and not field.is_relation
        and field.name not in exclude
    ]


def get_track_fields():
    """Get a list of all track fields from all media models."""
    all_fields = []

    for media_type in MediaTypes.values:
        model = apps.get_model("app", media_type)
        for field in get_model_fields(model, exclude={"watch_operation_id"}):
            if field not in all_fields:
                all_fields.append(field)

    # Put start_date and end_date next to each other.
    if "start_date" in all_fields and "end_date" in all_fields:
        end_idx = all_fields.index("end_date")

        # Remove both dates
        all_fields.remove("start_date")
        all_fields.remove("end_date")
        # Insert them in the correct order at the earlier index
        all_fields.insert(end_idx, "end_date")
        all_fields.insert(end_idx, "start_date")

    for timestamp_field in ("created_at", "progressed_at"):
        if timestamp_field in all_fields:
            all_fields.remove(timestamp_field)
            all_fields.append(timestamp_field)

    return list(all_fields)


def get_list_fields():
    """Get list-specific export fields."""
    return [
        "list_uid",
        "list_name",
        "list_description",
        "list_tags",
        "list_visibility",
        "list_allow_recommendations",
        "list_source",
        "list_source_id",
        "list_is_smart",
        "list_smart_media_types",
        "list_smart_excluded_media_types",
        "list_smart_filters",
        "list_item_date_added",
    ]


# CSV column name -> CollectionEntry attribute. ``collection_format`` maps to
# CollectionEntry.media_type, renamed to avoid clashing with the Item
# media_type column. Plex cache fields and updated_at are deliberately
# excluded (instance-local state).
COLLECTION_EXPORT_FIELDS = {
    "collection_format": "media_type",
    "collection_resolution": "resolution",
    "collection_hdr": "hdr",
    "collection_is_3d": "is_3d",
    "collection_audio_codec": "audio_codec",
    "collection_audio_channels": "audio_channels",
    "collection_bitrate": "bitrate",
    "collection_collected_at": "collected_at",
}


def get_collection_fields():
    """Get collection-specific export fields."""
    return list(COLLECTION_EXPORT_FIELDS)


def get_tag_fields():
    """Get item-tag export fields."""
    return ["item_tags"]


def _build_item_tags_map(user):
    """Map Item id -> tag names, for the CSV item_tags column."""
    tag_map = defaultdict(list)
    for item_id, tag_name in ItemTag.objects.filter(tag__user=user).values_list(
        "item_id",
        "tag__name",
    ):
        tag_map[item_id].append(tag_name)
    return tag_map


TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500/"

SAMPLE_MOVIES = [
    ("680", "Pulp Fiction", "vQWk5YBFWF4bZaofAbv0tShwBvQ.jpg"),
    ("10494", "Perfect Blue", "6WTiOCfDPP8XV4jqfloiVWf7KHq.jpg"),
    ("27205", "Inception", "xlaY2zyzMfkhk0HSC5VUwzoZPU1.jpg"),
    ("155", "The Dark Knight", "qJ2tW6WMUDux911r6m7haRef0WH.jpg"),
    ("238", "The Godfather", "3bhkrj58Vtu7enYsRolD1fZdja1.jpg"),
]

# (media_id, title, show poster path, season poster path)
SAMPLE_TV_SHOWS = [
    (
        "1668",
        "Friends",
        "2koX1xLkpTQM4IZebYvKysFW1Nh.jpg",
        "odCW88Cq5hAF0ZFVOkeJmeQv1nV.jpg",
    ),
    (
        "1396",
        "Breaking Bad",
        "ztkUQFLlC19CCMYHW9o1zWhJRNq.jpg",
        "ztkUQFLlC19CCMYHW9o1zWhJRNq.jpg",
    ),
    (
        "1399",
        "Game of Thrones",
        "1XS1oqL89opfnbLl8WnZY1O1uJx.jpg",
        "1XS1oqL89opfnbLl8WnZY1O1uJx.jpg",
    ),
    (
        "2316",
        "The Office",
        "7DJKHzAi83BmQrWLrYYOqcoKfhR.jpg",
        "7DJKHzAi83BmQrWLrYYOqcoKfhR.jpg",
    ),
    (
        "60625",
        "Rick and Morty",
        "owhkU6KRqdXoUQpjV8uyZGPtX58.jpg",
        "owhkU6KRqdXoUQpjV8uyZGPtX58.jpg",
    ),
]

SAMPLE_ANIME = [
    ("227", "FLCL", "https://cdn.myanimelist.net/images/anime/7/77356l.jpg"),
    (
        "44511",
        "Chainsaw Man",
        "https://cdn.myanimelist.net/images/anime/1806/126216l.jpg",
    ),
    ("12189", "Hyouka", "https://cdn.myanimelist.net/images/anime/13/50521l.jpg"),
    ("31043", "Erased", "https://cdn.myanimelist.net/images/anime/1555/106759l.jpg"),
    ("1535", "Death Note", "https://cdn.myanimelist.net/images/anime/1079/138100.jpg"),
]

SAMPLE_MANGA = [
    ("2", "Berserk", "https://cdn.myanimelist.net/images/manga/1/157897l.jpg"),
    ("98270", "Fire Punch", "https://cdn.myanimelist.net/images/manga/2/180430l.jpg"),
    ("44347", "One Punch-Man", "https://cdn.myanimelist.net/images/manga/3/80661l.jpg"),
    ("13", "One Piece", "https://cdn.myanimelist.net/images/manga/2/253146.jpg"),
    ("656", "Vagabond", "https://cdn.myanimelist.net/images/manga/1/259070.jpg"),
]

SAMPLE_GAMES = [
    (
        "19562",
        "Resident Evil 7: Biohazard",
        "https://images.igdb.com/igdb/image/upload/t_original/co545w.jpg",
    ),
    ("72", "Portal 2", ""),
    ("233", "Half-Life 2", ""),
    ("7346", "The Legend of Zelda: Breath of the Wild", ""),
    ("119133", "Elden Ring", ""),
]

SAMPLE_BOOKS = [
    (
        "OL21733390M",
        "Nineteen Eighty-Four",
        "https://covers.openlibrary.org/b/id/9267242-L.jpg",
    ),
    ("OL51711263M", "The Hobbit", "https://covers.openlibrary.org/b/id/14627509-L.jpg"),
    (
        "OL40236195M",
        "Fahrenheit 451",
        "https://covers.openlibrary.org/b/id/12993656-L.jpg",
    ),
    ("OL32848840M", "Dune", "https://covers.openlibrary.org/b/id/11481354-L.jpg"),
    (
        "OL22570129M",
        "The Great Gatsby",
        "https://covers.openlibrary.org/b/id/10590366-L.jpg",
    ),
]

SAMPLE_COMICS = [
    ("796", "Batman"),
    ("46568", "Saga"),
    ("18166", "The Walking Dead"),
    ("3622", "Watchmen"),
    ("2127", "The Amazing Spider-Man"),
]

SAMPLE_BOARDGAMES = [
    ("13", "Catan"),
    ("30549", "Pandemic"),
    ("174430", "Gloomhaven"),
    ("266192", "Wingspan"),
    ("9209", "Ticket to Ride"),
]

SAMPLE_PODCASTS = [
    (
        "1200361736",
        "The Daily",
        "https://is1-ssl.mzstatic.com/image/thumb/Podcasts221/v4/ab/64/66/"
        "ab6466a9-9a7d-e20e-7a3d-bc5be37d29ce/mza_15084852813176276273.jpg/600x600bb.jpg",
    ),
    (
        "1150510297",
        "How I Built This with Guy Raz",
        "https://is1-ssl.mzstatic.com/image/thumb/Podcasts126/v4/64/45/06/"
        "644506b5-c44f-f661-f74e-f63a4b2511bc/mza_14892199991035639268.jpeg/600x600bb.jpg",
    ),
    (
        "173001861",
        "Dan Carlin's Hardcore History",
        "https://is1-ssl.mzstatic.com/image/thumb/Podcasts115/v4/49/b7/eb/"
        "49b7eb32-8f08-6fac-aadb-2f002131fe5f/mza_15196161972010256532.jpg/600x600bb.jpg",
    ),
    (
        "917918570",
        "Serial",
        "https://is1-ssl.mzstatic.com/image/thumb/Podcasts221/v4/9a/fb/87/"
        "9afb8760-0e05-2b3e-24a2-7e14cce74570/mza_14816055607064169808.jpg/600x600bb.jpg",
    ),
    (
        "1441923632",
        "Batman University",
        "https://is1-ssl.mzstatic.com/image/thumb/Podcasts122/v4/2d/3c/5e/"
        "2d3c5e31-ff23-2531-be0c-3f54dbeb2b0c/mza_4814953863670326339.jpg/600x600bb.jpg",
    ),
]

# (artist musicbrainz_id, artist name, album release-group id, album title)
SAMPLE_MUSIC = [
    (
        "ff95eb47-41c4-4f7f-a104-cdc30f02e872",
        "Brian Eno",
        "5fdd6ba8-83c1-3a87-b378-d5f61dec5ddd",
        "Ambient 1: Music for Airports",
    ),
    (
        "a74b1b7f-71a5-4011-9441-d0b5e4122711",
        "Radiohead",
        "b1392450-e666-3926-a536-22c65f834433",
        "OK Computer",
    ),
    (
        "bd13909f-1c29-4c27-a874-d4aaf27c5b1a",
        "Fleetwood Mac",
        "416bb5e5-c7d1-3977-8fd7-7c9daf6c2be6",
        "Rumours",
    ),
    (
        "381086ea-f511-4aba-bdf9-71c753dc5077",
        "Kendrick Lamar",
        "499c19c8-0dab-4824-884b-6191d145e95b",
        "good kid, m.A.A.d city",
    ),
    (
        "056e4f3e-d505-4dad-8ec1-d04f521cbb56",
        "Daft Punk",
        "48117b90-a16e-34ca-a514-19c702df1158",
        "Discovery",
    ),
]


def generate_sample_template():
    """Build a sample CSV demonstrating the Floppy/Yamtrack CSV format.

    Uses real, verifiable catalog entries (real TMDB/MAL/IGDB/OpenLibrary/
    ComicVine/BGG/Pocket Casts/MusicBrainz IDs) instead of placeholder data,
    so re-importing the downloaded file unmodified brings in real,
    recognizable titles rather than fake "sample" ones. Five items per
    trackable media type, a regular list per media type, and one smart list
    querying Completed+highly-rated items across every type.
    """
    output = StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)

    fields = {
        # watch_providers scales with ~60 TMDB regions, is never read back on
        # import, and is fully re-fetchable via the provider backfill task.
        "item": get_model_fields(Item, exclude={"watch_providers"}),
        "track": get_track_fields(),
        "list": get_list_fields(),
        "collection": get_collection_fields(),
        "tags": get_tag_fields(),
    }
    writer.writerow(
        ["row_type"]
        + fields["item"]
        + fields["track"]
        + fields["list"]
        + fields["collection"]
        + fields["tags"],
    )

    placeholder_image = settings.IMG_NONE

    def write_media_row(item_vals, track_vals=None):
        item_vals = {
            "source": Sources.MANUAL.value,
            "image": placeholder_image,
            **item_vals,
        }
        track_vals = track_vals or {}
        writer.writerow(
            ["media"]
            + [item_vals.get(field, "") for field in fields["item"]]
            + [track_vals.get(field, "") for field in fields["track"]]
            + [""] * len(fields["list"])
            + [""] * len(fields["collection"])
            + [""] * len(fields["tags"]),
        )

    def write_list_row(list_vals):
        writer.writerow(
            ["list"]
            + [""] * len(fields["item"])
            + [""] * len(fields["track"])
            + [list_vals.get(field, "") for field in fields["list"]]
            + [""] * len(fields["collection"])
            + [""] * len(fields["tags"]),
        )

    def write_list_item_row(item_vals, list_vals):
        item_vals = {
            "source": Sources.MANUAL.value,
            "image": placeholder_image,
            **item_vals,
        }
        writer.writerow(
            ["list_item"]
            + [item_vals.get(field, "") for field in fields["item"]]
            + [""] * len(fields["track"])
            + [list_vals.get(field, "") for field in fields["list"]]
            + [""] * len(fields["collection"])
            + [""] * len(fields["tags"]),
        )

    def write_collection_row(item_vals, collection_vals):
        item_vals = {
            "source": Sources.MANUAL.value,
            "image": placeholder_image,
            **item_vals,
        }
        writer.writerow(
            ["collection"]
            + [item_vals.get(field, "") for field in fields["item"]]
            + [""] * len(fields["track"])
            + [""] * len(fields["list"])
            + [collection_vals.get(field, "") for field in fields["collection"]]
            + [""] * len(fields["tags"]),
        )

    # Every category gets the same 5-item status/score spread, so each one
    # contributes exactly one item to the smart list below (the first slot:
    # Completed with a score of 9.0).
    status_score_sequence = [
        ("Completed", "9.0"),
        ("Completed", "6.0"),
        ("In progress", ""),
        ("Planning", ""),
        ("Dropped", ""),
    ]

    def tmdb_image(path):
        return f"{TMDB_IMAGE_BASE}{path}" if path else ""

    def write_category_list(
        media_type, source, list_name, entries, image_fn=lambda x: x
    ):
        list_uid = f"sample-list-{media_type}"
        write_list_row(
            {
                "list_uid": list_uid,
                "list_name": list_name,
                "list_description": f"All five sample {list_name.lower()}",
                "list_visibility": "private",
            },
        )
        for (media_id, title, *rest), (status, score) in zip(
            entries, status_score_sequence, strict=False
        ):
            track_vals = {"status": status}
            if score:
                track_vals["score"] = score
            if media_type == "game" and status == "Completed":
                track_vals["progress"] = "5:30"
            image = (image_fn(rest[0]) if rest else "") or placeholder_image
            item_vals = {
                "media_id": media_id,
                "source": source,
                "media_type": media_type,
                "title": title,
                "image": image,
            }
            write_media_row(item_vals, track_vals)
            write_list_item_row(
                item_vals, {"list_uid": list_uid, "list_name": list_name}
            )

    write_category_list("movie", "tmdb", "Sample Movies", SAMPLE_MOVIES, tmdb_image)

    # One owned copy of the first sample movie, demonstrating the
    # collection row format.
    sample_movie_id, sample_movie_title, sample_movie_poster = SAMPLE_MOVIES[0]
    write_collection_row(
        {
            "media_id": sample_movie_id,
            "source": "tmdb",
            "media_type": "movie",
            "title": sample_movie_title,
            "image": tmdb_image(sample_movie_poster),
        },
        {
            "collection_format": "4K Blu-ray",
            "collection_resolution": "4K",
            "collection_hdr": "Dolby Vision",
            "collection_audio_codec": "Dolby Atmos",
            "collection_audio_channels": "7.1",
        },
    )
    write_category_list("anime", "mal", "Sample Anime", SAMPLE_ANIME, lambda url: url)
    write_category_list("manga", "mal", "Sample Manga", SAMPLE_MANGA, lambda url: url)
    write_category_list("game", "igdb", "Sample Games", SAMPLE_GAMES, lambda url: url)
    write_category_list(
        "book", "openlibrary", "Sample Books", SAMPLE_BOOKS, lambda url: url
    )
    write_category_list("comic", "comicvine", "Sample Comics", SAMPLE_COMICS)
    write_category_list("boardgame", "bgg", "Sample Board Games", SAMPLE_BOARDGAMES)
    write_category_list(
        "podcast", "pocketcasts", "Sample Podcasts", SAMPLE_PODCASTS, lambda url: url
    )

    # TV shows also get a linked season (season_number=1) per show.
    tv_list_uid = "sample-list-tv"
    tv_list_name = "Sample TV Shows"
    season_list_uid = "sample-list-season"
    season_list_name = "Sample TV Seasons"
    write_list_row(
        {
            "list_uid": tv_list_uid,
            "list_name": tv_list_name,
            "list_description": "All five sample TV shows",
            "list_visibility": "private",
        },
    )
    write_list_row(
        {
            "list_uid": season_list_uid,
            "list_name": season_list_name,
            "list_description": "Season 1 of each sample TV show",
            "list_visibility": "private",
        },
    )
    for (media_id, title, show_path, season_path), (status, score) in zip(
        SAMPLE_TV_SHOWS,
        status_score_sequence,
        strict=False,
    ):
        tv_track_vals = {"status": status}
        if score:
            tv_track_vals["score"] = score
        tv_item_vals = {
            "media_id": media_id,
            "source": "tmdb",
            "media_type": "tv",
            "title": title,
            "image": tmdb_image(show_path),
        }
        season_item_vals = {
            **tv_item_vals,
            "media_type": "season",
            "season_number": "1",
            "image": tmdb_image(season_path),
        }
        write_media_row(tv_item_vals, tv_track_vals)
        write_media_row(season_item_vals, tv_track_vals)
        write_list_item_row(
            tv_item_vals, {"list_uid": tv_list_uid, "list_name": tv_list_name}
        )
        write_list_item_row(
            season_item_vals,
            {"list_uid": season_list_uid, "list_name": season_list_name},
        )

    # Music artists and their most iconic album. ArtistTracker/AlbumTracker
    # aren't Item-backed, so they can't belong to a CustomList or the smart
    # list below -- that's a structural constraint of the data model, not an
    # omission.
    for (artist_mbid, artist_name, release_group_id, album_title), (
        status,
        score,
    ) in zip(
        SAMPLE_MUSIC,
        status_score_sequence,
        strict=False,
    ):
        track_vals = {"status": status}
        if score:
            track_vals["score"] = score
        write_media_row(
            {
                "media_id": artist_mbid,
                "source": "musicbrainz",
                "media_type": "music_artist",
                "title": artist_name,
            },
            track_vals,
        )
        write_media_row(
            {
                "media_id": release_group_id,
                "source": "musicbrainz",
                "media_type": "music_album",
                "title": album_title,
                "image": f"https://coverartarchive.org/release-group/{release_group_id}/front",
            },
            track_vals,
        )

    # A single smart list that queries across every list-eligible media type
    # at once: the top-rated Completed pick from each, kept in sync
    # automatically as the user's library changes.
    write_list_row(
        {
            "list_uid": "sample-list-smart",
            "list_name": "Top-Rated Completed (All Types)",
            "list_description": (
                "Auto-updates with every Completed item scored 8 or higher, across all media types"
            ),
            "list_visibility": "private",
            "list_is_smart": "true",
            "list_smart_filters": json.dumps(
                {"status": "Completed", "rating_min": "8"}
            ),
        },
    )

    return output.getvalue()
