"""Refuse an item without a library bucket.

0230 gave every item a bucket. The old check allowed the empty string, which
let one title be stored twice; the new one only accepts a media type. It is a
separate migration so PostgreSQL never alters ``app_item`` in the transaction
that deleted 0230's folded rows.
"""

from django.db import migrations, models

from app.migration_operations import AddConstraintIfNotExists, RemoveConstraintIfExists

MEDIA_TYPES = [
    "tv",
    "season",
    "episode",
    "movie",
    "anime",
    "manga",
    "game",
    "book",
    "comic",
    "comicissue",
    "boardgame",
    "music",
    "podcast",
    "video",
]


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0230_fill_empty_item_buckets"),
    ]

    operations = [
        RemoveConstraintIfExists(
            model_name="item",
            name="app_item_library_media_type_valid",
        ),
        AddConstraintIfNotExists(
            model_name="item",
            constraint=models.CheckConstraint(
                condition=models.Q(library_media_type__in=MEDIA_TYPES),
                name="app_item_library_media_type_set",
            ),
        ),
    ]
