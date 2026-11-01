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
            ("app", "0216_reliable_sync_contract")
        ]
        executor.migrate(before)
        try:
            show_model = executor.loader.project_state(before).apps.get_model(
                "app", "PodcastShow"
            )
            # What older GPodder imports stored when the feed had no title.
            derived = slugify(FEED.lower())
            leaked = show_model.objects.create(
                podcast_uuid="gp_leaked",
                title=derived.replace("-", " ")[:255],
                slug=derived[:255],
                rss_feed_url=FEED,
            )
            renamed = show_model.objects.create(
                podcast_uuid="gp_renamed",
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

            executor = MigrationExecutor(connection)
            executor.migrate(after)
            show_model = executor.loader.project_state(after).apps.get_model(
                "app", "PodcastShow"
            )

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
        finally:
            MigrationExecutor(connection).migrate(after)


class PodcastShowTitleMigrationAliasTests(SimpleTestCase):
    """The repair reads and writes through the migration's own connection."""

    def test_reads_and_writes_use_the_schema_editor_alias(self):
        migration = importlib.import_module(
            "app.migrations.0217_podcast_show_url_derived_titles"
        )
        derived = slugify(FEED.lower())
        show = SimpleNamespace(
            title=derived.replace("-", " ")[:255],
            slug=derived[:255],
            rss_feed_url=FEED,
            save=Mock(),
        )
        model = Mock()
        queryset = model.objects.using.return_value
        queryset.exclude.return_value.only.return_value.iterator.return_value = [show]
        apps = Mock(get_model=Mock(return_value=model))
        schema_editor = SimpleNamespace(connection=SimpleNamespace(alias="replica"))

        migration.clear_url_derived_titles(apps, schema_editor)

        model.objects.using.assert_called_once_with("replica")
        model.objects.exclude.assert_not_called()
        show.save.assert_called_once_with(
            using="replica", update_fields=["title", "slug"]
        )
        self.assertEqual(show.title, "Unknown Podcast")
