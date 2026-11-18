"""0230 and 0231: every item gets a library bucket, and twins fold without loss.

Replays the real migrations from 0229, so the fixture can hold the empty
buckets the new constraint refuses.
"""

import importlib
import os
from unittest import skipIf

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = ("app", "0229_podcast_show_url_derived_titles")
fill_migration = importlib.import_module("app.migrations.0230_fill_empty_item_buckets")


def _item_relation_counts(apps):
    """Rows in every table that points at an item, by table."""
    item_model = apps.get_model("app", "Item")
    counts = {}
    for relation in item_model._meta.related_objects:
        model = relation.through if relation.many_to_many else relation.related_model
        counts[model._meta.db_table] = model._base_manager.count()
    return counts


@skipIf(os.environ.get("FLOPPY_TEST_FAST_DB") == "1", "Requires migration replay")
class FillEmptyItemBucketsMigrationTests(TransactionTestCase):
    """Empty buckets are filled or folded; nothing a user recorded is lost."""

    def setUp(self):
        self.executor = MigrationExecutor(connection)
        self.after = self.executor.loader.graph.leaf_nodes()
        self.before = [node for node in self.after if node[0] != "app"] + [BEFORE]
        self.executor.migrate(self.before)
        self.executor.loader.build_graph()

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.after)

    def _migrate_forward(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.after)
        return executor.loader.project_state(self.after).apps

    def _seed(self, apps):
        user_model = apps.get_model("users", "User")
        item = apps.get_model("app", "Item")
        tv = apps.get_model("app", "TV")
        season = apps.get_model("app", "Season")
        episode = apps.get_model("app", "Episode")
        movie = apps.get_model("app", "Movie")
        tag = apps.get_model("app", "Tag")
        item_tag = apps.get_model("app", "ItemTag")
        custom_list = apps.get_model("lists", "CustomList")
        custom_list_item = apps.get_model("lists", "CustomListItem")
        collection_entry = apps.get_model("app", "CollectionEntry")

        alice = user_model.objects.create(username="alice")
        bob = user_model.objects.create(username="bob")

        def make(media_type, bucket, media_id="100", source="tmdb", **extra):
            return item.objects.create(
                media_id=media_id,
                source=source,
                media_type=media_type,
                library_media_type=bucket,
                title=f"{media_type} {bucket or 'empty'}",
                **extra,
            )

        ids = {}
        # A lone empty bucket (what the home screen's music shelf stored).
        ids["lone_music"] = make("music", "", media_id="m1", source="manual").pk

        # A show stored twice; Alice tracks both copies, Bob only the empty one.
        show_empty = make("tv", "")
        show_filled = make("tv", "tv")
        season_empty = make("season", "", season_number=1)
        season_filled = make("season", "season", season_number=1)
        episode_empty = make("episode", "", season_number=1, episode_number=1)
        episode_filled = make("episode", "tv", season_number=1, episode_number=1)
        ids.update(
            show_empty=show_empty.pk,
            show_filled=show_filled.pk,
            season_empty=season_empty.pk,
            season_filled=season_filled.pk,
            episode_empty=episode_empty.pk,
            episode_filled=episode_filled.pk,
        )
        alice_tv_empty = tv.objects.create(
            user=alice,
            item=show_empty,
            status="In progress",
            score=9,
            notes="Rewatching with friends",
        )
        alice_tv_filled = tv.objects.create(user=alice, item=show_filled, status="Planning")
        alice_season_empty = season.objects.create(
            user=alice,
            item=season_empty,
            related_tv=alice_tv_empty,
            status="In progress",
        )
        alice_season_filled = season.objects.create(
            user=alice,
            item=season_filled,
            related_tv=alice_tv_filled,
            status="Planning",
        )
        episode.objects.create(item=episode_empty, related_season=alice_season_empty)
        episode.objects.create(item=episode_filled, related_season=alice_season_filled)
        bob_tv = tv.objects.create(user=bob, item=show_empty, status="Completed", score=7)
        bob_season = season.objects.create(
            user=bob,
            item=season_empty,
            related_tv=bob_tv,
            status="Completed",
        )
        episode.objects.create(item=episode_empty, related_season=bob_season)
        ids.update(alice_tv_empty=alice_tv_empty.pk, alice_tv_filled=alice_tv_filled.pk)
        ids["bob_tv"] = bob_tv.pk

        # A movie stored twice, watched once on each copy, tagged and listed.
        movie_empty = make("movie", "", media_id="200")
        movie_filled = make("movie", "movie", media_id="200")
        ids.update(movie_empty=movie_empty.pk, movie_filled=movie_filled.pk)
        movie.objects.create(user=alice, item=movie_empty, status="Completed", score=8)
        movie.objects.create(user=alice, item=movie_filled, status="Completed")
        favourite = tag.objects.create(user=alice, name="favourite")
        item_tag.objects.create(tag=favourite, item=movie_empty)
        item_tag.objects.create(tag=favourite, item=movie_filled)
        watched = tag.objects.create(user=alice, name="cinema")
        item_tag.objects.create(tag=watched, item=movie_empty)
        weekend = custom_list.objects.create(owner=alice, name="Weekend")
        custom_list_item.objects.create(custom_list=weekend, item=movie_empty)
        collection_entry.objects.create(user=alice, item=movie_empty, media_type="digital")

        # Grouped anime on a TV item, in two filled buckets: left alone.
        ids["anime_bucket"] = make("tv", "anime", media_id="300").pk
        ids["tv_bucket"] = make("tv", "tv", media_id="300").pk
        return ids

    def test_fills_and_folds_without_losing_user_data(self):
        before_apps = self.executor.loader.project_state(self.before).apps
        ids = self._seed(before_apps)
        before_counts = _item_relation_counts(before_apps)

        apps = self._migrate_forward()
        item = apps.get_model("app", "Item")
        tv = apps.get_model("app", "TV")
        season = apps.get_model("app", "Season")
        episode = apps.get_model("app", "Episode")
        movie = apps.get_model("app", "Movie")
        item_tag = apps.get_model("app", "ItemTag")
        custom_list_item = apps.get_model("lists", "CustomListItem")
        collection_entry = apps.get_model("app", "CollectionEntry")
        deleted_media = apps.get_model("app", "DeletedMedia")
        historical_tv = apps.get_model("app", "HistoricalTV")

        self.assertFalse(item.objects.filter(library_media_type="").exists())
        self.assertEqual(item.objects.get(pk=ids["lone_music"]).library_media_type, "music")
        for key in ("show_empty", "season_empty", "episode_empty", "movie_empty"):
            self.assertFalse(item.objects.filter(pk=ids[key]).exists(), key)

        # Every play survives, on the surviving copy.
        self.assertEqual(episode.objects.count(), 3)
        self.assertEqual(
            set(episode.objects.values_list("item_id", flat=True)),
            {ids["episode_filled"]},
        )
        # Alice's two show rows became one, holding what she wrote on either.
        alice_tv = tv.objects.get(pk=ids["alice_tv_filled"])
        self.assertFalse(tv.objects.filter(pk=ids["alice_tv_empty"]).exists())
        self.assertEqual(
            (alice_tv.status, alice_tv.score, alice_tv.notes),
            ("In progress", 9, "Rewatching with friends"),
        )
        self.assertEqual(season.objects.filter(related_tv=alice_tv).count(), 1)
        self.assertEqual(
            episode.objects.filter(related_season__related_tv=alice_tv).count(),
            2,
        )
        self.assertTrue(
            historical_tv.objects.filter(
                id=alice_tv.pk,
                history_change_reason__startswith="Merged duplicate entry",
            ).exists(),
        )
        # Bob only tracked the empty copy: his rows moved, untouched.
        bob_tv = tv.objects.get(pk=ids["bob_tv"])
        self.assertEqual(
            (bob_tv.item_id, bob_tv.status, bob_tv.score),
            (ids["show_filled"], "Completed", 7),
        )
        self.assertEqual(
            season.objects.get(related_tv=bob_tv).item_id,
            ids["season_filled"],
        )
        # Movie repeats are rows: both stay, on the surviving copy.
        self.assertEqual(
            sorted(
                movie.objects.values_list("item_id", "score"),
                key=lambda row: (row[0], row[1] is not None),
            ),
            [(ids["movie_filled"], None), (ids["movie_filled"], 8)],
        )
        self.assertEqual(
            sorted(item_tag.objects.values_list("tag__name", "item_id")),
            [("cinema", ids["movie_filled"]), ("favourite", ids["movie_filled"])],
        )
        self.assertEqual(custom_list_item.objects.get().item_id, ids["movie_filled"])
        self.assertEqual(collection_entry.objects.get().item_id, ids["movie_filled"])
        # A merge is not a deletion: no tombstone that would block imports.
        self.assertFalse(deleted_media.objects.exists())
        # Grouped anime keeps its own bucket.
        self.assertEqual(
            sorted(
                item.objects.filter(media_id="300").values_list(
                    "library_media_type",
                    flat=True,
                ),
            ),
            ["anime", "tv"],
        )

        # Table by table, the only rows gone are the folded duplicates:
        # Alice's second show and season rows, and the tag already on the keeper.
        after_counts = _item_relation_counts(apps)
        expected = dict(before_counts)
        expected["app_tv"] -= 1
        expected["app_season"] -= 1
        expected["app_itemtag"] -= 1
        self.assertEqual(after_counts, expected)

    def test_database_refuses_an_empty_bucket_after_migrating(self):
        apps = self._migrate_forward()
        item = apps.get_model("app", "Item")
        with self.assertRaises(IntegrityError), transaction.atomic():
            item.objects.create(
                media_id="1",
                source="manual",
                media_type="music",
                library_media_type="",
                title="Empty",
            )

    def test_is_a_no_op_on_a_clean_database_and_when_run_again(self):
        before_apps = self.executor.loader.project_state(self.before).apps
        before_apps.get_model("app", "Item").objects.create(
            media_id="1",
            source="manual",
            media_type="music",
            library_media_type="music",
            title="Clean",
        )
        apps = self._migrate_forward()
        item = apps.get_model("app", "Item")
        snapshot = list(item.objects.values_list("pk", "library_media_type"))
        with self.assertNumQueries(1):
            fill_migration.fill_empty_item_buckets(apps, None)
        self.assertEqual(list(item.objects.values_list("pk", "library_media_type")), snapshot)
