"""Detection and repair of anime tracked in both libraries (discussion #967)."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from app.models import (
    TV,
    Anime,
    Item,
    ItemProviderLink,
    MediaTypes,
    Sources,
    Status,
)
from app.tasks_anime_library_repair import (
    duplicate_pair_count,
    duplicate_pairs,
    repair_duplicated_anime_libraries_task,
)


class DuplicateAnimeDetectionTests(TestCase):
    """Detection is pure database work and must not need any provider."""

    def setUp(self):
        """Track one show as flat MAL anime, linked to a TMDB series."""
        self.user = get_user_model().objects.create_user(
            username="anime-repair-user",
            password="password",
        )
        self.anime_item = Item.objects.create(
            media_id="52991",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Frieren: Beyond Journey's End",
            image="",
        )
        ItemProviderLink.objects.create(
            item=self.anime_item,
            provider=Sources.TMDB.value,
            provider_media_type=MediaTypes.TV.value,
            provider_media_id="209867",
            season_number=1,
            episode_offset=0,
        )
        self.anime = Anime.objects.create(
            item=self.anime_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
            progress=12,
        )

    def _add_plain_tv_row(self, bucket=""):
        tv_item = Item.objects.create(
            media_id="209867",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=bucket,
            title="Frieren: Beyond Journey's End",
            image="",
        )
        return TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

    def test_detects_the_flat_and_plain_tv_pair(self):
        """The exact shape the old routing produced is found."""
        tv = self._add_plain_tv_row()

        pairs = list(duplicate_pairs())

        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0][0].pk, self.anime.pk)
        self.assertEqual(pairs[0][1].pk, tv.pk)

    def test_detects_a_tv_bucket_duplicate_too(self):
        """A settled `tv` verdict is still a duplicate of the anime row."""
        self._add_plain_tv_row(bucket=MediaTypes.TV.value)

        self.assertEqual(len(list(duplicate_pairs())), 1)

    def test_duplicate_count_matches_pairs_and_is_user_scoped(self):
        """The settings count uses one query but must agree with detection."""
        self._add_plain_tv_row()

        self.assertEqual(duplicate_pair_count(user_id=self.user.id), 1)
        self.assertEqual(duplicate_pair_count(), 1)
        self.assertEqual(duplicate_pair_count(user_id=self.user.id + 1), 0)

    def test_grouped_anime_is_not_a_duplicate(self):
        """A TV row already in the anime bucket is the same library, not a dupe."""
        self._add_plain_tv_row(bucket=MediaTypes.ANIME.value)

        self.assertEqual(list(duplicate_pairs()), [])

    def test_user_scoped_detection_ignores_other_accounts(self):
        """The settings-page repair only sees the signed-in user's pairs."""
        other = get_user_model().objects.create_user(
            username="scoped-other",
            password="password",
        )
        other_anime_item = Item.objects.create(
            media_id="28171",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Other Show",
            image="",
        )
        ItemProviderLink.objects.create(
            item=other_anime_item,
            provider=Sources.TMDB.value,
            provider_media_type=MediaTypes.TV.value,
            provider_media_id="88888",
        )
        Anime.objects.create(
            item=other_anime_item,
            user=other,
            status=Status.IN_PROGRESS.value,
        )
        self._add_plain_tv_row()

        self.assertEqual(
            [pair[0].user_id for pair in duplicate_pairs(user_id=self.user.id)],
            [self.user.id],
        )
        self.assertEqual(
            list(duplicate_pairs(user_id=other.id)),
            [],
        )

    def test_another_users_tv_row_is_not_a_duplicate(self):
        """Duplicates are per user; another account's row is its own business."""
        other = get_user_model().objects.create_user(
            username="other-anime-user",
            password="password",
        )
        tv_item = Item.objects.create(
            media_id="209867",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type="",
            title="Frieren: Beyond Journey's End",
            image="",
        )
        TV.objects.create(
            item=tv_item,
            user=other,
            status=Status.IN_PROGRESS.value,
        )

        self.assertEqual(list(duplicate_pairs()), [])

    def test_anime_without_a_tv_identity_is_not_a_duplicate(self):
        """A MAL-only title has nothing to collide with."""
        ItemProviderLink.objects.filter(item=self.anime_item).delete()
        self._add_plain_tv_row()

        self.assertEqual(list(duplicate_pairs()), [])

    def test_unresolvable_pair_is_reported_and_left_untouched(self):
        """A pair that cannot be merged safely must never be guessed at."""
        from app.services.anime_migration import AnimeMigrationError

        tv = self._add_plain_tv_row()

        with patch(
            "app.services.library_migration.migrate_library_item",
            side_effect=AnimeMigrationError("ambiguous mapping"),
        ):
            result = repair_duplicated_anime_libraries_task()

        self.assertEqual(result["repaired"], 0)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(
            result["unresolved"],
            ["Frieren: Beyond Journey's End"],
        )
        self.assertTrue(Anime.objects.filter(pk=self.anime.pk).exists())
        self.assertTrue(TV.objects.filter(pk=tv.pk).exists())

    def test_clean_library_is_a_no_op(self):
        """With no duplicates the task does nothing and reports nothing."""
        result = repair_duplicated_anime_libraries_task()

        self.assertEqual(
            result,
            {"repaired": 0, "skipped": 0, "unresolved": []},
        )


class DuplicateAnimeMergeTests(TestCase):
    """The repair folds a duplicate pair into a single tracked row.

    The conversion services are exercised by their own tests; what is verified
    here is the composition: which row is converted, which is folded in, and
    that exactly one survives.
    """

    def setUp(self):
        """Track one show twice: flat MAL anime plus a plain TV row."""
        self.user = get_user_model().objects.create_user(
            username="anime-merge-user",
            password="password",
        )
        self.user.anime_metadata_source_default = Sources.TMDB.value
        self.user.save(update_fields=["anime_metadata_source_default"])

        self.anime_item = Item.objects.create(
            media_id="52991",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Frieren: Beyond Journey's End",
            image="",
        )
        ItemProviderLink.objects.create(
            item=self.anime_item,
            provider=Sources.TMDB.value,
            provider_media_type=MediaTypes.TV.value,
            provider_media_id="209867",
            season_number=1,
            episode_offset=0,
        )
        Anime.objects.create(
            item=self.anime_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
            progress=12,
        )

        self.plain_tv_item = Item.objects.create(
            media_id="209867",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type="",
            title="Frieren: Beyond Journey's End",
            image="",
        )
        TV.objects.create(
            item=self.plain_tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

        # What the flat->grouped conversion produces.
        self.grouped_item = Item.objects.create(
            media_id="209867",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.ANIME.value,
            title="Frieren: Beyond Journey's End",
            image="",
        )

    def test_flat_row_is_converted_then_the_tv_row_is_folded_in(self):
        """The flat row converts first, then the stray TV row merges into it."""
        grouped_tv = TV.objects.create(
            item=self.grouped_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

        with patch(
            "app.services.library_migration.migrate_library_item",
            return_value=self.grouped_item,
        ) as mock_migrate:
            result = repair_duplicated_anime_libraries_task()

        self.assertEqual(result["repaired"], 1)
        self.assertEqual(result["skipped"], 0)

        # The flat anime row is what gets converted, not the TV row.
        migrated_item = mock_migrate.call_args.args[1]
        self.assertEqual(migrated_item.pk, self.anime_item.pk)

        # The stray TV row is gone and the grouped one survives.
        self.assertFalse(Item.objects.filter(pk=self.plain_tv_item.pk).exists())
        self.assertTrue(TV.objects.filter(pk=grouped_tv.pk).exists())
        self.assertEqual(
            TV.objects.filter(user=self.user).count(),
            1,
        )
        self.assertEqual(
            TV.objects.get(user=self.user).item.library_media_type,
            MediaTypes.ANIME.value,
        )

    def test_mal_preference_moves_the_stray_tv_row_instead(self):
        """A MAL-preferring user keeps the flat row; only the TV row moves."""
        self.user.anime_metadata_source_default = Sources.MAL.value
        self.user.save(update_fields=["anime_metadata_source_default"])

        with patch(
            "app.services.library_migration.migrate_library_item",
            return_value=self.anime_item,
        ) as mock_migrate:
            result = repair_duplicated_anime_libraries_task()

        self.assertEqual(result["repaired"], 1)
        moved_item = mock_migrate.call_args.args[1]
        self.assertEqual(moved_item.pk, self.plain_tv_item.pk)
        self.assertEqual(mock_migrate.call_args.args[3], Sources.MAL.value)


class MultiCourDuplicateTests(TestCase):
    """MAL identity is per cour, so several Anime rows share one TV show."""

    def setUp(self):
        """Track two MAL cours that both map to a single TMDB series."""
        self.user = get_user_model().objects.create_user(
            username="multi-cour-user",
            password="password",
        )
        for mal_id, title in (
            ("28171", "Food Wars! Shokugeki no Soma"),
            ("32282", "Food Wars! The Second Plate"),
        ):
            anime_item = Item.objects.create(
                media_id=mal_id,
                source=Sources.MAL.value,
                media_type=MediaTypes.ANIME.value,
                title=title,
                image="",
            )
            ItemProviderLink.objects.create(
                item=anime_item,
                provider=Sources.TMDB.value,
                provider_media_type=MediaTypes.TV.value,
                provider_media_id="62273",
                episode_offset=0,
            )
            Anime.objects.create(
                item=anime_item,
                user=self.user,
                status=Status.COMPLETED.value,
                progress=24,
            )

        self.plain_tv_item = Item.objects.create(
            media_id="62273",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.TV.value,
            title="Food Wars! Shokugeki no Soma",
            image="",
        )
        TV.objects.create(
            item=self.plain_tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

    def test_one_stray_tv_row_yields_one_pair(self):
        """The TV row can only be folded in once, however many cours exist.

        Yielding it per MAL entry would make the second repair operate on an
        already-merged row.
        """
        pairs = list(duplicate_pairs())

        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0][1].item.pk, self.plain_tv_item.pk)


class AnimeShapeConversionPromptTests(TestCase):
    """Switching provider offers a conversion instead of performing one."""

    def setUp(self):
        """Track one flat MAL anime linked to a TMDB series."""
        self.user = get_user_model().objects.create_user(
            username="shape-prompt-user",
            password="password",
        )
        self.user.anime_metadata_source_default = Sources.MAL.value
        self.user.save(update_fields=["anime_metadata_source_default"])
        self.client.force_login(self.user)

        anime_item = Item.objects.create(
            media_id="52991",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Frieren: Beyond Journey's End",
            image="",
        )
        ItemProviderLink.objects.create(
            item=anime_item,
            provider=Sources.TMDB.value,
            provider_media_type=MediaTypes.TV.value,
            provider_media_id="209867",
            episode_offset=0,
        )
        Anime.objects.create(
            item=anime_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
            progress=12,
        )

    def test_switching_provider_does_not_convert_anything_on_its_own(self):
        """The existing library is untouched until the user asks."""
        from app.tasks_anime_library_repair import anime_rows_needing_conversion

        self.user.anime_metadata_source_default = Sources.TMDB.value
        self.user.save(update_fields=["anime_metadata_source_default"])

        self.assertEqual(len(anime_rows_needing_conversion(self.user)), 1)
        self.assertEqual(Anime.objects.filter(user=self.user).count(), 1)

    def test_conversion_endpoint_queues_the_task(self):
        """The modal's confirm button starts the conversion, nothing sooner."""
        from django.urls import reverse

        with patch(
            "app.tasks_anime_library_repair.convert_anime_library_shape_task.delay",
        ) as mock_delay:
            response = self.client.post(reverse("convert_anime_library"))

        self.assertEqual(response.status_code, 302)
        mock_delay.assert_called_once_with(self.user.id)

    def test_review_surface_stays_visible_after_the_provider_changes(self):
        """The optional conversion is described persistently, not as a modal."""
        from django.urls import reverse

        response = self.client.post(
            reverse("set_media_type_provider", args=[MediaTypes.ANIME.value]),
            {
                "source": Sources.TMDB.value,
                "next": reverse("provider_detail", args=["tmdb"]) + "?tab=metadata",
            },
            follow=True,
        )

        anime_source = next(
            source for source in response.context["provider_page"]["metadata"]["sources"]
            if source["key"] == "anime"
        )
        self.assertEqual(anime_source["existingCount"], 1)
        self.assertEqual(anime_source["moveAction"], reverse("convert_anime_library"))
        self.assertContains(response, "Convert existing anime")
        self.assertContains(response, reverse("convert_anime_library"))

        again = self.client.get(
            reverse("provider_detail", args=["tmdb"]) + "?tab=metadata",
        )
        anime_source = next(
            source for source in again.context["provider_page"]["metadata"]["sources"]
            if source["key"] == "anime"
        )
        self.assertEqual(anime_source["existingCount"], 1)
        self.assertEqual(anime_source["moveAction"], reverse("convert_anime_library"))

    def test_no_conversion_notice_when_the_library_matches_the_provider(self):
        """A library already in the preferred shape needs no action."""
        from django.urls import reverse

        response = self.client.post(
            reverse("set_media_type_provider", args=[MediaTypes.ANIME.value]),
            {
                "source": Sources.MAL.value,
                "next": reverse("provider_detail", args=["tmdb"]) + "?tab=metadata",
            },
            follow=True,
        )

        self.assertNotContains(response, "still in the other format")

    def test_duplicate_repair_endpoint_queues_a_user_scoped_task(self):
        """The duplicate card repairs only the signed-in account."""
        from django.urls import reverse

        with patch(
            "app.tasks_anime_library_repair.repair_duplicated_anime_libraries_task.delay",
        ) as mock_delay:
            response = self.client.post(
                reverse("repair_duplicate_anime_libraries"),
            )

        self.assertEqual(response.status_code, 302)
        mock_delay.assert_called_once_with(user_id=self.user.id)

    def test_duplicate_card_appears_with_a_repair_action(self):
        """An affected user sees the repair option in Data Management."""
        from django.urls import reverse

        tv_item = Item.objects.create(
            media_id="209867",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.TV.value,
            title="Frieren: Beyond Journey's End",
            image="",
        )
        TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

        response = self.client.get(reverse("data_management"))

        self.assertContains(response, "Duplicate anime libraries")
        self.assertContains(response, reverse("repair_duplicate_anime_libraries"))


class DuplicateDetectionQueryCountTests(TestCase):
    """Detection cost must not grow with the number of anime rows."""

    def _anime(self, user, n, with_twin):
        item = Item.objects.create(
            media_id=str(n),
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title=f"Show {n}",
            image="",
        )
        ItemProviderLink.objects.create(
            item=item,
            provider=Sources.TMDB.value,
            provider_media_type=MediaTypes.TV.value,
            provider_media_id=str(1000 + n),
        )
        Anime.objects.create(item=item, user=user, status=Status.IN_PROGRESS.value)
        if with_twin:
            tv_item = Item.objects.create(
                media_id=str(1000 + n),
                source=Sources.TMDB.value,
                media_type=MediaTypes.TV.value,
                library_media_type="",
                title=f"Show {n}",
                image="",
            )
            TV.objects.create(item=tv_item, user=user, status=Status.IN_PROGRESS.value)

    def test_clean_library_costs_one_query_and_duplicates_still_found(self):
        """No-duplicate libraries are one query; real pairs are still yielded."""
        user = get_user_model().objects.create_user(username="qc", password="x")
        for n in range(30):
            self._anime(user, n, with_twin=False)
        with CaptureQueriesContext(connection) as clean:
            self.assertEqual(list(duplicate_pairs()), [])
        self.assertEqual(len(clean), 1)

        for n in (100, 101):
            self._anime(user, n, with_twin=True)
        with CaptureQueriesContext(connection) as sparse:
            pairs = list(duplicate_pairs())
        self.assertEqual(len(pairs), 2)
        self.assertLessEqual(len(sparse), 1 + 2 * 2)
        self.assertEqual(len(list(duplicate_pairs(batch_size=1))), 1)
