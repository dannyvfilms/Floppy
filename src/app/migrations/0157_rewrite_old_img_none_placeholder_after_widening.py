from django.db import migrations

# Keep these values frozen in the migration. Do not read the runtime IMG_NONE
# setting because installations can override that setting after this migration.
OLD_IMG_NONE = (
    "https://www.themoviedb.org/assets/2/v4/glyphicons/basic/"
    "glyphicons-basic-38-picture-grey-c2ebdbb057f2a7614185931650f8cee23fa137b93812ccb132b9df511df1cfac.svg"
)
NEW_IMG_NONE = (
    "data:image/svg+xml;base64,"
    "PHN2ZyBpZD0iZ2x5cGhpY29ucy1iYXNpYyIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiB2aWV3Qm94PSIwIDAgMzIgMzIiPgogIDxwYXRoIGZpbGw9IiNiNWI1YjUiIGlkPSJwaWN0dXJlIiBkPSJNMjcuNSw1SDQuNUExLjUwMDA4LDEuNTAwMDgsMCwwLDAsMyw2LjV2MTlBMS41MDAwOCwxLjUwMDA4LDAsMCwwLDQuNSwyN2gyM0ExLjUwMDA4LDEuNTAwMDgsMCwwLDAsMjksMjUuNVY2LjVBMS41MDAwOCwxLjUwMDA4LDAsMCwwLDI3LjUsNVpNMjYsMTguNWwtNC43OTQyNS01LjIzMDFhLjk5MzgzLjk5MzgzLDAsMCAwLTEuNDQ0MjgtLjAzMTM3bC01LjM0NzQxLDUuMzQ3NDFMMTkuODI4MTIsMjRIMTdsLTQuNzkyOTEtNC43OTNhMS4wMDAyMiwxLjAwMDIyLDAsMCAwLTEuNDE0MTgsMEw2LDI0VjhIMjZabS0xNy45LTZhMi40LDIuNCwwLDEsMSwyLjQsMi40QTIuNDAwMDUsMi40MDAwNSwwLDAsMSw4LjEsMTIuNVoiLz4KPC9zdmc+Cg=="
)


def rewrite_old_placeholder_after_widening(apps, schema_editor):
    """Rewrite the old placeholder after image fields can store the data URI."""
    if NEW_IMG_NONE == OLD_IMG_NONE:
        return

    for model_name in ("Item", "Person", "Artist", "Album", "PodcastShow"):
        model = apps.get_model("app", model_name)
        model.objects.filter(image=OLD_IMG_NONE).update(image=NEW_IMG_NONE)


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0156_alter_album_image_alter_artist_image_and_more"),
    ]

    operations = [
        migrations.RunPython(
            rewrite_old_placeholder_after_widening,
            migrations.RunPython.noop,
        ),
    ]
