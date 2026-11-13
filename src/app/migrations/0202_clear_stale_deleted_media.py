from django.db import migrations
from django.db.models import Exists, OuterRef

# Overwrite imports used to leave a "the user deleted this" tombstone on every
# show, movie, game and book they replaced. Later syncs then skipped items the
# user still tracks. A tombstone for an item that is tracked right now can only
# be one of those, so remove them.
TRACKED_MODELS = {
    "tv": "TV",
    "anime": "Anime",
    "movie": "Movie",
    "manga": "Manga",
    "book": "Book",
    "comic": "Comic",
    "game": "Game",
    "boardgame": "BoardGame",
    "music": "Music",
    "podcast": "Podcast",
}


def clear_stale_tombstones(apps, schema_editor):
    deleted_media = apps.get_model("app", "DeletedMedia")
    for media_type, model_name in TRACKED_MODELS.items():
        tracked = apps.get_model("app", model_name)._default_manager.filter(
            user_id=OuterRef("user_id"),
            item__media_type=media_type,
            item__source=OuterRef("source"),
            item__media_id=OuterRef("media_id"),
        )
        deleted_media.objects.filter(media_type=media_type).filter(
            Exists(tracked),
        ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0201_game_artwork"),
    ]

    operations = [
        migrations.RunPython(clear_stale_tombstones, migrations.RunPython.noop),
    ]
