from django.db import migrations


def normalize_tag_names(apps, schema_editor):
    """Collapse stray whitespace in tag names, merging tags that become equal.

    ``Tag.save`` has always done this, but a name stored with a trailing space
    could never be matched by the media list's tag filter (#1351).
    """
    Tag = apps.get_model("app", "Tag")
    ItemTag = apps.get_model("app", "ItemTag")

    for tag in Tag.objects.order_by("id"):
        name = " ".join(tag.name.split())
        if name == tag.name:
            continue
        keeper = (
            Tag.objects.filter(user_id=tag.user_id, name__iexact=name)
            .exclude(pk=tag.pk)
            .order_by("id")
            .first()
        )
        if keeper is None:
            Tag.objects.filter(pk=tag.pk).update(name=name)
            continue
        already_tagged = ItemTag.objects.filter(tag=keeper).values("item_id")
        ItemTag.objects.filter(tag=tag).exclude(item_id__in=already_tagged).update(
            tag=keeper,
        )
        tag.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0199_episode_rating_only"),
    ]

    operations = [
        migrations.RunPython(normalize_tag_names, migrations.RunPython.noop),
    ]
