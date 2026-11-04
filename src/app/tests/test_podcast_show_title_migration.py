"""Upgrade replaces show titles and slugs derived from private feed URLs."""

import importlib
import os
from types import SimpleNamespace
from unittest import skipIf
from unittest.mock import Mock

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TransactionTestCase
from django.utils.text import slugify

FEED = "https://feeds.example.com/private/path-secret-abc123/feed.xml?token=query-secret-xyz789"


@skipIf(os.environ.get("FLOPPY_TEST_FAST_DB") == "1", "Requires migration replay")
class PodcastShowTitleMigrationTests(TransactionTestCase):
    """Only exact URL-derived values are replaced; genuine metadata survives."""

    def test_upgrade_replaces_only_url_derived_values(self):
        executor = MigrationExecutor(connection)
        after = executor.loader.graph.leaf_nodes()
        before = [node for node in after if node[0] != "app"] + [
            ("app", "0222_playbackprogress_last_event_at")
        ]
        executor.migrate(before)
        try:
            before_apps = executor.loader.project_state(before).apps
            show_model = before_apps.get_model("app", "PodcastShow")
            item_model = before_apps.get_model("app", "Item")
            # What older GPodder imports stored when the feed had no title.
            derived = slugify(FEED.lower())
            derived_title = derived.replace("-", " ")[:255]
            leaked = show_model.objects.create(
                podcast_uuid="gp_leaked",
                source="gpodder",
                title=derived.replace("-", " ")[:255],
                slug=derived[:255],
                rss_feed_url=FEED,
            )
            renamed = show_model.objects.create(
                podcast_uuid="gp_renamed",
                source="gpodder",
                title="Real Show",
                slug=derived[:255],
                rss_feed_url=FEED,
            )
            genuine = show_model.objects.create(
                podcast_uuid="pc_genuine",
                title="Another Show",
                slug="another-show",
                rss_feed_url=FEED,
            )
            # Tracked shows' Items copied the show title when they were created.
            items = {
                key: item_model.objects.create(
                    media_type="podcast", source=source, media_id=media_id, **titles
                ).pk
                for key, source, media_id, titles in (
                    (
                        "leaked",
                        "gpodder",
                        "gp_leaked",
                        {"title": derived_title, "original_title": derived_title},
                    ),
                    ("renamed", "gpodder", "gp_renamed", {"title": derived_title}),
                    ("genuine", "pocketcasts", "pc_genuine", {"title": "Another Show"}),
                    (
                        "other_source",
                        "pocketcasts",
                        "gp_leaked",
                        {"title": derived_title},
                    ),
                    ("no_show", "gpodder", "gp_unknown", {"title": derived_title}),
                )
            }

            executor = MigrationExecutor(connection)
            executor.migrate(after)
            after_apps = executor.loader.project_state(after).apps
            show_model = after_apps.get_model("app", "PodcastShow")
            item_model = after_apps.get_model("app", "Item")

            leaked = show_model.objects.get(pk=leaked.pk)
            self.assertEqual(
                (leaked.title, leaked.slug), ("Unknown Podcast", "unknown-podcast")
            )
            renamed = show_model.objects.get(pk=renamed.pk)
            self.assertEqual((renamed.title, renamed.slug), ("Real Show", "real-show"))
            genuine = show_model.objects.get(pk=genuine.pk)
            self.assertEqual(
                (genuine.title, genuine.slug), ("Another Show", "another-show")
            )

            def item(key):
                row = item_model.objects.get(pk=items[key])
                return row.title, row.original_title

            self.assertEqual(item("leaked"), ("Unknown Podcast", "Unknown Podcast"))
            self.assertEqual(item("renamed"), ("Real Show", None))
            self.assertEqual(item("genuine"), ("Another Show", None))
            # Only the show's own Item, matched by media_id and source, changes.
            self.assertEqual(item("other_source"), (derived_title, None))
            self.assertEqual(item("no_show"), (derived_title, None))
        finally:
            MigrationExecutor(connection).migrate(after)


class PodcastShowTitleMigrationAliasTests(SimpleTestCase):
    """The repair reads and writes through the migration's own connection."""

    def test_reads_and_writes_use_the_schema_editor_alias(self):
        migration = importlib.import_module(
            "app.migrations.0223_podcast_show_url_derived_titles"
        )
        derived = slugify(FEED.lower())
        show = SimpleNamespace(
            podcast_uuid="gp_leaked",
            source="gpodder",
            title=derived.replace("-", " ")[:255],
            slug=derived[:255],
            rss_feed_url=FEED,
            save=Mock(),
        )
        item = SimpleNamespace(
            media_id="gp_leaked",
            source="gpodder",
            title=show.title,
            original_title=None,
            localized_title=None,
        )
        model = Mock()
        queryset = model.objects.using.return_value
        queryset.exclude.return_value.only.return_value.iterator.return_value = [show]
        item_model = Mock()
        item_queryset = item_model.objects.using.return_value
        item_queryset.filter.return_value.only.return_value = [item]
        apps = Mock(
            get_model=Mock(
                side_effect=lambda _app, name: (
                    model if name == "PodcastShow" else item_model
                )
            )
        )
        schema_editor = SimpleNamespace(connection=SimpleNamespace(alias="replica"))

        migration.clear_url_derived_titles(apps, schema_editor)

        model.objects.using.assert_called_once_with("replica")
        model.objects.exclude.assert_not_called()
        show.save.assert_called_once_with(
            using="replica", update_fields=["title", "slug"]
        )
        self.assertEqual(show.title, "Unknown Podcast")
        item_model.objects.using.assert_called_with("replica")
        item_model.objects.filter.assert_not_called()
        item_queryset.bulk_update.assert_called_once()
        self.assertEqual(item.title, "Unknown Podcast")
