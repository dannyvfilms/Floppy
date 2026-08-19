# Fix the 0135 backfill (issue #496): it treated a null end_date as
# "not completed", but before 0135 every non-dropped episode was a
# completed watch, and end_date could legitimately be null (a watch
# logged without a date). That flipped dateless completed episodes to
# "In progress". Only correct rows untouched by the new fields, so a
# genuinely new in-progress entry created after upgrading is left alone.

from django.db import migrations


def fix_incorrectly_flipped_episodes(apps, schema_editor):
    Episode = apps.get_model("app", "Episode")
    Episode.objects.filter(
        dropped=False,
        status="In progress",
        end_date__isnull=True,
        start_date__isnull=True,
        notes="",
    ).update(status="Completed")


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0142_historicalpodcast_position_updated_at_and_more"),
    ]

    operations = [
        migrations.RunPython(
            fix_incorrectly_flipped_episodes,
            migrations.RunPython.noop,
        ),
    ]
