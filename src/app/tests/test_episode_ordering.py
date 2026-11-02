from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from app.models import TV, Episode, Item, MediaTypes, Season, Sources, Status
from app.models.episode_order import EpisodeOrderChange
from app.services.episode_ordering import (
    apply_change,
    can_revert,
    latest_reversible_change,
    persist_order,
    preview_change,
    revert_change,
)
from app.services.order_resolution import resolve_incoming_episode
from app.templatetags.app_tags import media_url


class EpisodeOrderingTests(TestCase):
    """Verify stable-identity previews and transactional order changes."""

    def setUp(self):
        """Create one show with a legacy episode watch."""
        self.user = get_user_model().objects.create_user(username="order-user")
        self.show = Item.objects.create(
            media_id="1396", source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value, title="Breaking Bad",
        )
        self.tv = TV.objects.create(
            item=self.show, user=self.user, status=Status.IN_PROGRESS.value,
        )
        self.season_item = Item.objects.create(
            media_id="1396", source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value, season_number=1,
            title="Breaking Bad",
        )
        self.season = Season.objects.create(
            item=self.season_item, related_tv=self.tv, user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        self.episode_item = Item.objects.create(
            media_id="1396", source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value, season_number=1,
            episode_number=1, title="Pilot", provider_episode_id="legacy-1",
        )
        self.watch = Episode.objects.create(
            item=self.episode_item, related_season=self.season,
            end_date=timezone.now(),
        )
        self.order = persist_order(
            self.show, Sources.TMDB.value, "1396", "aired", "TMDB (Aired)",
            {"episodes": [{
                "provider_episode_id": "new-1", "season_number": 1,
                "episode_number": 1, "title": "Pilot", "image": "",
            }]},
        )

    def test_preview_does_not_match_equal_coordinates(self):
        """Coordinates alone remain unresolved when provider identity differs."""
        preview = preview_change(self.tv, self.order)

        self.assertEqual(preview["resolutions"][0]["episode_ids"], [])

    def test_apply_requires_explicit_resolution_and_switches_active_order(self):
        """An explicit stable identity moves the watch and archives old rows."""
        preview = preview_change(self.tv, self.order)

        with self.assertRaises(ValueError):
            apply_change(
                self.tv, self.order, token=preview["token"], resolutions=[],
            )

        journal = apply_change(
            self.tv, self.order, token=preview["token"], resolutions=[{
                "watch_ids": [self.watch.pk], "episode_ids": ["new-1"],
                "archive": False,
            }],
        )

        self.assertEqual(journal.order_id, self.order.pk)
        self.tv.refresh_from_db()
        self.assertEqual(self.tv.active_episode_order_id, self.order.pk)
        self.watch.refresh_from_db()
        self.assertFalse(self.watch.order_archived)
        self.assertEqual(self.watch.item.provider_episode_id, "new-1")
        self.assertTrue(Season.all_objects.get(pk=self.season.pk).order_archived)
        self.assertTrue(
            Season.objects.filter(
                item__episode_order=self.order,
                item__season_number=1,
            ).exists(),
        )


def _voyager(test):
    """Seed a show whose legacy numbering merges a two-part episode."""
    test.user = get_user_model().objects.create_user(username="voyager-user")
    test.show = Item.objects.create(
        media_id="1855", source=Sources.TMDB.value,
        media_type=MediaTypes.TV.value, title="Star Trek: Voyager",
    )
    test.tv = TV.objects.create(
        item=test.show, user=test.user, status=Status.IN_PROGRESS.value,
    )
    test.season_item = Item.objects.create(
        media_id="1855", source=Sources.TMDB.value,
        media_type=MediaTypes.SEASON.value, season_number=5, title="Voyager",
    )
    test.season = Season.objects.create(
        item=test.season_item, related_tv=test.tv, user=test.user,
        status=Status.IN_PROGRESS.value,
    )
    test.watches = {}
    base = timezone.now()
    # Watched out of order, as a Trakt import would leave them.
    for offset, (number, title) in zip(
        (3, 1, 2), ((16, "Survival Instinct"), (15, "Equinox"), (17, "Barge of the Dead")),
        strict=True,
    ):
        item = Item.objects.create(
            media_id="1855", source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value, season_number=5,
            episode_number=number, title=title, provider_episode_id=f"legacy-{number}",
        )
        test.watches[number] = Episode.objects.create(
            item=item, related_season=test.season, end_date=base + timedelta(days=offset),
        )
    rows = [
        ("t15", 15, "Equinox", "1999-05-26"),
        ("t16", 16, "Equinox, Part II", "1999-09-22"),
        ("t17", 17, "Survival Instinct", "1999-10-06"),
        ("t18", 18, "Barge of the Dead", "1999-11-03"),
    ]
    test.order = persist_order(
        test.show, Sources.TVDB.value, "74205", "default", "TVDB (Aired order)",
        {"episodes": [
            {"provider_episode_id": pid, "season_number": 5, "episode_number": number,
             "title": title, "image": "", "air_date": aired}
            for pid, number, title, aired in rows
        ]},
    )


class EpisodeOrderSuggestionTests(TestCase):
    """Verify the review screen pre-selects only evidence-backed destinations."""

    def setUp(self):
        """Create a show whose old numbering merged a two-part episode."""
        _voyager(self)

    def test_title_beats_equal_coordinates_for_a_split_two_parter(self):
        """Survival Instinct is old S5E16 but S5E17 after the split."""
        suggestions = preview_change(self.tv, self.order)["suggestions"]

        self.assertEqual(
            suggestions[self.watches[16].pk], {"episode_id": "t17", "basis": "title"},
        )
        self.assertEqual(
            suggestions[self.watches[15].pk], {"episode_id": "t15", "basis": "title"},
        )

    def test_air_date_beats_title_and_coordinate(self):
        """A unique air date wins over a title that matches another episode."""
        item = self.watches[17].item
        item.title = "Survival Instinct"  # would match t17 by title
        item.release_datetime = datetime(1999, 11, 3, tzinfo=UTC)
        item.save()

        suggestion = preview_change(self.tv, self.order)["suggestions"][self.watches[17].pk]

        self.assertEqual(suggestion, {"episode_id": "t18", "basis": "air_date"})

    def test_coordinate_is_the_last_resort_and_stays_unproven(self):
        """With no date or title evidence, equal coordinates are only suggested."""
        item = self.watches[17].item
        item.title = "Different name"
        item.save()

        preview = preview_change(self.tv, self.order)

        self.assertEqual(
            preview["suggestions"][self.watches[17].pk],
            {"episode_id": "t17", "basis": "coordinate"},
        )
        self.assertTrue(all(not row["episode_ids"] for row in preview["resolutions"]))

    def test_watches_are_listed_by_old_episode_with_old_coordinates(self):
        """Rows follow season and episode number, not viewing order."""
        rows = preview_change(self.tv, self.order)["watches"]

        self.assertEqual([row["episode_number"] for row in rows], [15, 16, 17])
        self.assertEqual({row["season_number"] for row in rows}, {5})

    def test_proven_identity_is_not_repeated_as_a_suggestion(self):
        """A stable-ID match stays in resolutions only."""
        self.watches[15].item.__class__.objects.filter(pk=self.watches[15].item.pk).update(
            source=Sources.TVDB.value, provider_episode_id="t15",
        )

        preview = preview_change(self.tv, self.order)

        self.assertNotIn(self.watches[15].pk, preview["suggestions"])
        proven = [row for row in preview["resolutions"] if row["episode_ids"]]
        self.assertEqual([row["episode_ids"] for row in proven], [["t15"]])


class EpisodeOrderRevertTests(TestCase):
    """Verify an order change can be undone while nothing depends on it."""

    def setUp(self):
        """Create a show and apply an order with one split viewing."""
        _voyager(self)
        preview = preview_change(self.tv, self.order)
        resolutions = [
            {"watch_ids": [self.watches[15].pk], "episode_ids": ["t15", "t16"], "archive": False},
            {"watch_ids": [self.watches[16].pk], "episode_ids": ["t17"], "archive": False},
            {"watch_ids": [self.watches[17].pk], "episode_ids": [], "archive": True},
        ]
        apply_change(self.tv, self.order, token=preview["token"], resolutions=resolutions)
        self.tv.refresh_from_db()

    def test_revert_restores_watches_seasons_and_active_order(self):
        """Undo puts every viewing back on its original episode."""
        self.assertEqual(Episode.objects.filter(related_season__related_tv=self.tv).count(), 3)

        revert_change(self.tv)

        self.tv.refresh_from_db()
        self.assertIsNone(self.tv.active_episode_order_id)
        rows = Episode.objects.filter(related_season__related_tv=self.tv).order_by("item__episode_number")
        self.assertEqual(
            [(row.item.episode_number, row.item.title) for row in rows],
            [(15, "Equinox"), (16, "Survival Instinct"), (17, "Barge of the Dead")],
        )
        self.assertEqual(
            list(Season.objects.filter(related_tv=self.tv).values_list("pk", flat=True)),
            [self.season.pk],
        )
        self.assertIsNone(latest_reversible_change(self.tv))

    def test_revert_refuses_once_a_newer_viewing_exists(self):
        """A viewing added under the new order cannot be mapped back."""
        item = Item.objects.create(
            media_id=self.order.media_id, source=Sources.TVDB.value,
            media_type=MediaTypes.EPISODE.value, season_number=5, episode_number=18,
            provider_episode_id="t18", title="Barge of the Dead", episode_order=self.order,
        )
        season = Season.objects.get(related_tv=self.tv, order_archived=False)
        Episode.objects.create(item=item, related_season=season, end_date=timezone.now())

        with self.assertRaises(ValueError):
            revert_change(self.tv)

        self.tv.refresh_from_db()
        self.assertEqual(self.tv.active_episode_order_id, self.order.pk)

    def test_revert_refuses_after_a_viewing_was_edited(self):
        """Edited notes, scores or dates on a moved viewing are never overwritten."""
        row = Episode.objects.filter(related_season__related_tv=self.tv).first()
        Episode.objects.filter(pk=row.pk).update(notes="rewatched with friends")

        self.assertFalse(can_revert(self.tv))
        with self.assertRaises(ValueError):
            revert_change(self.tv)

        row.refresh_from_db()
        self.assertEqual(row.notes, "rewatched with friends")

    def test_can_revert_follows_the_same_rules_as_revert(self):
        """The flag clients read is false as soon as a newer viewing exists."""
        self.assertTrue(can_revert(self.tv))
        item = Item.objects.create(
            media_id=self.order.media_id, source=Sources.TVDB.value,
            media_type=MediaTypes.EPISODE.value, season_number=5, episode_number=18,
            provider_episode_id="t18", title="Barge of the Dead", episode_order=self.order,
        )
        season = Season.objects.get(related_tv=self.tv, order_archived=False)
        Episode.objects.create(item=item, related_season=season, end_date=timezone.now())

        self.assertFalse(can_revert(self.tv))

    def test_the_active_change_is_found_behind_many_undone_ones(self):
        """Undone journals never hide the change that is still active."""
        change = latest_reversible_change(self.tv)
        for _ in range(25):
            EpisodeOrderChange.objects.create(
                user=self.user, tv=self.tv, order=self.order,
                before_state={"reverted": True},
            )

        self.assertEqual(latest_reversible_change(self.tv), change)

    def test_revert_needs_a_change_to_undo(self):
        """A show still on its original numbering has nothing to undo."""
        revert_change(self.tv)

        with self.assertRaises(ValueError):
            revert_change(self.tv)


class EpisodeOrderWebhookTests(TestCase):
    """Verify incoming plays land on the episode the active order names."""

    def setUp(self):
        """Activate the TVDB order for a show."""
        _voyager(self)
        preview = preview_change(self.tv, self.order)
        apply_change(self.tv, self.order, token=preview["token"], resolutions=[
            {"watch_ids": [self.watches[15].pk], "episode_ids": ["t15"], "archive": False},
            {"watch_ids": [self.watches[16].pk], "episode_ids": ["t17"], "archive": False},
            {"watch_ids": [self.watches[17].pk], "episode_ids": ["t18"], "archive": False},
        ])

    def test_plex_tvdb_episode_17_resolves_to_survival_instinct(self):
        """A play numbered S5E17 lands on the same-titled episode, not the next one."""
        catalogue = {"episodes": self.order.catalogue["episodes"]}
        with patch("app.providers.episode_orders.fetch_order", return_value=catalogue):
            targets = resolve_incoming_episode(
                self.user, "74205", Sources.TVDB.value, 5, 17,
            )

        self.assertEqual([item.title for item in targets], ["Survival Instinct"])


class EpisodeOrderingPageTests(TestCase):
    """Verify the review page shows what to check and ends back on the show."""

    def setUp(self):
        """Seed a show and a logged-in user; provider calls are replaced."""
        _voyager(self)
        self.client.force_login(self.user)
        self.url = reverse("episode_ordering_settings", args=[self.tv.pk])
        orders = [{"provider": "tvdb", "key": "default", "label": "TVDB (Aired order)", "series_id": "74205"}]
        for name, value in (
            ("available_orders", (orders, [])),
            ("selected_order", self.order),
        ):
            patcher = patch(f"app.episode_order_views.{name}", return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _preview(self):
        return self.client.post(self.url, {"provider": "tvdb", "key": "default"})

    def test_chooser_lists_orders_under_their_provider(self):
        """The first step groups orders by provider and links back to the show."""
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["order_groups"][0][0], "TVDB")
        self.assertContains(response, "TVDB (Aired order)")
        self.assertContains(response, "Review changes")

    def test_review_preselects_evidence_and_holds_back_coordinates(self):
        """Title matches are filled in; a coordinate-only match waits for a click."""
        item = self.watches[17].item
        item.title = "Different name"
        item.save()

        rows = {row["id"]: row for row in self._preview().context["watches"]}

        self.assertEqual(rows[self.watches[16].pk]["selected"], ["t17"])
        self.assertEqual(rows[self.watches[16].pk]["kind"], "suggested")
        self.assertEqual(rows[self.watches[17].pk]["selected"], [])
        self.assertEqual(rows[self.watches[17].pk]["pending"], "t17")
        self.assertEqual(
            [row["episode_number"] for row in self._preview().context["watches"]],
            [15, 16, 17],
        )

    def test_apply_returns_to_the_show_with_a_message(self):
        """A successful apply leaves the review and reports it on the show page."""
        preview = self._preview().context
        data = {"action": "apply", "order_id": self.order.pk, "token": preview["preview"]["token"]}
        for row in preview["watches"]:
            data[f"episodes_{row['id']}"] = row["selected"] or ["t15"]

        response = self.client.post(self.url, data)

        self.assertRedirects(response, media_url(self.show), fetch_redirect_response=False)
        self.tv.refresh_from_db()
        self.assertEqual(self.tv.active_episode_order_id, self.order.pk)

    def test_failed_apply_stays_in_the_review(self):
        """An unresolved viewing keeps the user in the review with an error."""
        preview = self._preview().context
        data = {"action": "apply", "order_id": self.order.pk, "token": preview["preview"]["token"]}

        response = self.client.post(self.url, data)

        self.assertEqual(response.status_code, 400)
        self.assertIn("watches", response.context)
        self.assertTrue(list(response.context["messages"]))

    def test_revert_returns_to_the_show(self):
        """Undo from the chooser restores the original numbering."""
        preview = self._preview().context
        data = {"action": "apply", "order_id": self.order.pk, "token": preview["preview"]["token"]}
        for row in preview["watches"]:
            data[f"episodes_{row['id']}"] = row["selected"] or ["t15"]
        self.client.post(self.url, data)

        self.assertTrue(self.client.get(self.url).context["can_revert"])
        response = self.client.post(self.url, {"action": "revert"})

        self.assertRedirects(response, media_url(self.show), fetch_redirect_response=False)
        self.tv.refresh_from_db()
        self.assertIsNone(self.tv.active_episode_order_id)

    def test_archiving_a_combined_viewing_is_rejected(self):
        """A viewing cannot be both archived and combined into another."""
        preview = self._preview().context
        first, second = preview["watches"][0]["id"], preview["watches"][1]["id"]
        data = {"action": "apply", "order_id": self.order.pk, "token": preview["preview"]["token"]}
        for row in preview["watches"]:
            data[f"episodes_{row['id']}"] = row["selected"] or ["t15"]
        data[f"combine_{second}"] = str(first)
        data[f"archive_{second}"] = "on"

        response = self.client.post(self.url, data)

        self.assertEqual(response.status_code, 400)
        self.tv.refresh_from_db()
        self.assertIsNone(self.tv.active_episode_order_id)

    def test_archiving_the_target_of_a_combination_is_rejected(self):
        """Archiving a viewing others are folded into would archive them silently."""
        preview = self._preview().context
        first, second = preview["watches"][0]["id"], preview["watches"][1]["id"]
        data = {"action": "apply", "order_id": self.order.pk, "token": preview["preview"]["token"]}
        for row in preview["watches"]:
            data[f"episodes_{row['id']}"] = row["selected"] or ["t15"]
        data[f"combine_{second}"] = str(first)
        data[f"archive_{first}"] = "on"

        self.assertEqual(self.client.post(self.url, data).status_code, 400)

    def test_undo_names_the_order_it_returns_to(self):
        """After two changes, undo says it restores the first order, not the original."""
        preview = self._preview().context
        data = {"action": "apply", "order_id": self.order.pk, "token": preview["preview"]["token"]}
        for row in preview["watches"]:
            data[f"episodes_{row['id']}"] = row["selected"] or ["t15"]
        self.client.post(self.url, data)

        self.assertEqual(self.client.get(self.url).context["revert_label"], "Original numbering")

        second = persist_order(
            self.show, Sources.TVDB.value, "74205", "dvd", "TVDB (DVD order)",
            self.order.catalogue,
        )
        self.tv.refresh_from_db()
        second_preview = preview_change(self.tv, second)
        apply_change(self.tv, second, token=second_preview["token"], resolutions=[
            {"watch_ids": [row["id"]], "episode_ids": ["t15"], "archive": False}
            for row in second_preview["watches"]
        ])

        context = self.client.get(self.url).context
        self.assertEqual(context["revert_label"], "TVDB (Aired order)")
        self.assertTrue(context["can_revert"])
