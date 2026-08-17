import importlib

from django.test import SimpleTestCase

migration_0155 = importlib.import_module(
    "app.migrations.0155_rewrite_old_img_none_placeholder",
)
migration_0156 = importlib.import_module(
    "app.migrations.0156_alter_album_image_alter_artist_image_and_more",
)
migration_0157 = importlib.import_module(
    "app.migrations.0157_rewrite_old_img_none_placeholder_after_widening",
)

IMAGE_MODELS = ("Item", "Person", "Artist", "Album", "PodcastShow")


class _Field:
    def __init__(self, max_length):
        self.max_length = max_length


class _Meta:
    def __init__(self, max_length):
        self.field = _Field(max_length)

    def get_field(self, field_name):
        if field_name != "image":
            raise KeyError(field_name)
        return self.field


class _Manager:
    def __init__(self):
        self.filters = []
        self.updates = []

    def filter(self, **filters):
        self.filters.append(filters)
        return self

    def update(self, **values):
        self.updates.append(values)
        return 1


class _Apps:
    def __init__(self, max_length):
        self.max_length = max_length
        self.managers = {}

    def get_model(self, app_label, model_name):
        if app_label != "app" or model_name not in IMAGE_MODELS:
            raise KeyError((app_label, model_name))

        manager = _Manager()
        self.managers[model_name] = manager
        return type(
            f"Historical{model_name}",
            (),
            {"_meta": _Meta(self.max_length), "objects": manager},
        )


class ImagePlaceholderUpgradeMigrationTests(SimpleTestCase):
    """Protect the PostgreSQL upgrade path reported in issue #848."""

    def test_new_placeholder_exceeds_legacy_image_limit(self):
        self.assertGreater(len(migration_0155.NEW_IMG_NONE), 200)

    def test_0155_skips_rewrite_when_historical_field_is_too_short(self):
        apps = _Apps(max_length=200)

        migration_0155.rewrite_old_placeholder(apps, None)

        self.assertEqual(set(apps.managers), set(IMAGE_MODELS))
        for manager in apps.managers.values():
            self.assertEqual(manager.filters, [])
            self.assertEqual(manager.updates, [])

    def test_0155_can_rewrite_when_field_has_no_length_limit(self):
        apps = _Apps(max_length=None)

        migration_0155.rewrite_old_placeholder(apps, None)

        for manager in apps.managers.values():
            self.assertEqual(
                manager.filters,
                [{"image": migration_0155.OLD_IMG_NONE}],
            )
            self.assertEqual(
                manager.updates,
                [{"image": migration_0155.NEW_IMG_NONE}],
            )

    def test_0156_widens_every_image_model_that_0155_rewrites(self):
        widened_models = {
            operation.model_name
            for operation in migration_0156.Migration.operations
            if getattr(operation, "name", None) == "image"
        }

        self.assertEqual(
            widened_models,
            {model_name.lower() for model_name in IMAGE_MODELS},
        )

    def test_0157_retries_same_frozen_rewrite_after_0156(self):
        self.assertEqual(migration_0157.OLD_IMG_NONE, migration_0155.OLD_IMG_NONE)
        self.assertEqual(migration_0157.NEW_IMG_NONE, migration_0155.NEW_IMG_NONE)
        self.assertIn(
            ("app", "0156_alter_album_image_alter_artist_image_and_more"),
            migration_0157.Migration.dependencies,
        )

        apps = _Apps(max_length=None)
        migration_0157.rewrite_old_placeholder_after_widening(apps, None)

        for manager in apps.managers.values():
            self.assertEqual(
                manager.filters,
                [{"image": migration_0157.OLD_IMG_NONE}],
            )
            self.assertEqual(
                manager.updates,
                [{"image": migration_0157.NEW_IMG_NONE}],
            )
