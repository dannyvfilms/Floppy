from django.db import migrations


def copy_channel_to_authors(apps, schema_editor):
    """Give every video item the channel of the first video row that has one."""
    Video = apps.get_model("app", "Video")
    Item = apps.get_model("app", "Item")
    seen = set()
    rows = (
        Video.objects.exclude(channel="")
        .order_by("id")
        .values_list("item_id", "channel")
    )
    for item_id, channel in rows.iterator():
        if item_id in seen:
            continue
        seen.add(item_id)
        item = Item.objects.filter(pk=item_id).only("authors").first()
        if item is not None and not item.authors:
            Item.objects.filter(pk=item_id).update(authors=[channel])


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0213_item_type_lookup_index"),
    ]

    operations = [
        migrations.RunPython(copy_channel_to_authors, migrations.RunPython.noop),
    ]
