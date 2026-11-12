"""Date existing tracking rows by their last known change, not by this deploy."""

from django.db import migrations
from django.db.models import F
from django.db.models.functions import Coalesce, Greatest

MODELS = (
    "Anime", "BasicMedia", "BoardGame", "Book", "Comic", "ComicIssue", "Game",
    "Manga", "Movie", "Music", "Podcast", "Season", "TV", "Video",
)


def backfill(apps, schema_editor):
    """Set updated_at to the newest of created/progressed/scored that exist."""
    for name in MODELS:
        model = apps.get_model("app", name)
        names = {field.name for field in model._meta.get_fields()}
        stamps = [F("created_at")]
        stamps += [
            Coalesce(F(field), F("created_at"))
            for field in ("progressed_at", "scored_at")
            if field in names
        ]
        model.objects.update(
            updated_at=Greatest(*stamps) if len(stamps) > 1 else stamps[0],
        )


class Migration(migrations.Migration):
    dependencies = [("app", "0226_media_updated_at")]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
