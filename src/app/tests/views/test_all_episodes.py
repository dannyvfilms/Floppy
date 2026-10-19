"""The TV overview shares season metadata and the existing episode actions."""

from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from app.detail_related import enrich_detail_seasons
from app.models import TV, Episode, Item, MediaTypes, Season, Sources, Status
from app.services.episode_coordinates import InvalidEpisodeCoordinateError
from lists.models import CustomList, CustomListItem


class AllEpisodesTests(TestCase):
    """Keep all seasons available with personal watch state and safe actions."""

    def setUp(self):
        rating_fetch = patch(
            "app.tasks_trakt.populate_trakt_episode_ratings_for_season.delay"
        )
        rating_fetch.start()
        self.addCleanup(rating_fetch.stop)
        self.user = get_user_model().objects.create_user(username="episodes")
        self.client.force_login(self.user)
        self.url = reverse(
            "media_details",
            kwargs={
                "source": "tmdb",
                "media_type": "tv",
                "media_id": "42",
                "title": "a-show",
            },
        )
        self.base = {
            "source": "tmdb",
            "media_type": "tv",
            "media_id": "42",
            "title": "A Show",
            "image": "https://example.com/show.jpg",
            "details": {"runtime": "30m"},
            "related": {
                "seasons": [
                    {
                        "source": "tmdb",
                        "media_type": "season",
                        "media_id": "42",
                        "title": "A Show",
                        "season_number": number,
                        "image": "",
                    }
                    for number in (2, 0, 1)
                ]
            },
        }
        self.grouped = {
            f"season/{number}": {
                "source": "tmdb",
                "media_id": "42",
                "season_number": number,
                "season_title": f"Season {number}",
                "media_type": "season",
                "title": "A Show",
                "image": "https://example.com/show.jpg",
                "max_progress": 1,
                "details": {"episodes": 1},
                "episodes": [
                    {
                        "episode_number": 1,
                        "name": f"Episode in season {number}",
                        "air_date": (
                            timezone.now() + timedelta(days=30 if number == 2 else -30)
                        )
                        .date()
                        .isoformat(),
                    }
                ],
            }
            for number in (0, 1, 2)
        }

    def metadata(self, media_type, *_args, **_kwargs):
        if media_type == "season":
            return deepcopy(self.grouped[f"season/{_args[2][0]}"])
        return deepcopy(self.grouped if media_type == "tv_with_seasons" else self.base)

    @patch("app.providers.services.get_media_metadata")
    def test_saved_language_localizes_episode_list_and_actions(self, metadata):
        metadata.side_effect = self.metadata
        for language, heading, progress, action, accessible_action in (
            ("de", "Alle Folgen", "0 / 3 gesehen", "Staffel erfassen", "Folge 1 als gesehen markieren"),
            ("es", "Todos los episodios", "0 / 3 vistos", "Registrar temporada", "Marcar el episodio 1 como visto"),
            ("fr", "Tous les épisodes", "0 / 3 vus", "Suivre la saison", "Marquer l\u2019épisode 1 comme vu"),
        ):
            with self.subTest(language=language):
                self.user.ui_language = language
                self.user.save(update_fields=["ui_language"])
                response = self.client.get(self.url, {"fragment": "secondary"})
                for text in (heading, progress, action, accessible_action):
                    self.assertContains(response, text)
                self.assertNotContains(response, "Mark episode 1 watched")

    @patch("app.providers.services.get_media_metadata")
    def test_all_seasons_share_page_and_future_episode_has_no_watch_action(
        self, metadata
    ):
        metadata.side_effect = self.metadata
        response = self.client.get(self.url, {"fragment": "secondary"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [
                season["season_number"]
                for season in response.context["all_episode_seasons"]
            ],
            [0, 1, 2],
        )
        soup = BeautifulSoup(response.content, "html.parser")
        section = soup.select_one("#all-episodes")
        self.assertIn("0 / 3 watched", section.get_text())
        self.assertEqual(len(section.select("details[open]")), 3)
        self.assertEqual(
            section.select_one('[data-unwatched="true"]')["data-episode"], "1-1"
        )
        self.assertIsNotNone(section.select_one('[data-episode="1-1"] form'))
        self.assertIsNone(section.select_one('[data-episode="2-1"] form'))
        self.assertEqual(
            sum(call.args[0] == "tv_with_seasons" for call in metadata.call_args_list),
            1,
        )

    @patch("app.providers.services.get_media_metadata")
    def test_row_forms_add_and_remove_a_watch_using_existing_actions(self, metadata):
        metadata.side_effect = self.metadata
        response = self.client.get(self.url, {"fragment": "secondary"})
        soup = BeautifulSoup(response.content, "html.parser")
        form = soup.select_one('#all-episodes [data-episode="1-1"] form')
        fields = {
            field["name"]: field.get("value", "") for field in form.select("input")
        }
        saved = self.client.post(form["action"], fields)
        self.assertEqual(saved.status_code, 302)
        self.assertEqual(saved.url, f"{self.url}#all-episodes")
        self.assertEqual(
            Episode.objects.filter(related_season__user=self.user).count(), 1
        )
        self.assertTrue(
            Season.objects.filter(
                user=self.user,
                item__season_number=2,
                status=Status.IN_PROGRESS.value,
            ).exists()
        )

        response = self.client.get(self.url, {"fragment": "secondary"})
        soup = BeautifulSoup(response.content, "html.parser")
        form = soup.select_one('#all-episodes [data-episode="1-1"] form')
        fields = {
            field["name"]: field.get("value", "") for field in form.select("input")
        }
        deleted = self.client.post(form["action"], fields)
        self.assertEqual(deleted.status_code, 302)
        self.assertEqual(
            Episode.objects.filter(related_season__user=self.user).count(), 0
        )

    @patch("app.providers.services.get_media_metadata")
    def test_watch_state_uses_owner_and_excludes_ratings_and_archived_plays(
        self, metadata
    ):
        metadata.side_effect = self.metadata
        show_item = Item.objects.create(
            media_id="42", source="tmdb", media_type="tv", title="A Show"
        )
        show = TV.objects.create(
            item=show_item, user=self.user, status=Status.IN_PROGRESS.value
        )
        season_item = Item.objects.create(
            media_id="42",
            source="tmdb",
            media_type="season",
            season_number=1,
            title="A Show",
        )
        season = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=show,
            status=Status.IN_PROGRESS.value,
        )
        episode_item = Item.objects.create(
            media_id="42",
            source="tmdb",
            media_type="episode",
            season_number=1,
            episode_number=1,
            title="One",
        )
        watch = Episode.objects.create(
            item=episode_item, related_season=season, end_date=timezone.now()
        )
        response = self.client.get(self.url, {"fragment": "secondary"})
        self.assertEqual(response.context["all_episode_watched"], 1)
        soup = BeautifulSoup(response.content, "html.parser")
        row = soup.select_one('#all-episodes [data-episode="1-1"]')
        self.assertNotIn("data-unwatched", row.attrs)
        self.assertEqual(
            row.select_one('input[name="instance_id"]')["value"], str(watch.pk)
        )
        self.assertIn("Mark unwatched", row.get_text())
        self.assertIn("%23all-episodes", row.select_one("form")["action"])

        owner = get_user_model().objects.create_user(username="public-owner")
        public_list = CustomList.objects.create(
            name="Public shows",
            owner=owner,
            visibility="public",
        )
        CustomListItem.objects.create(custom_list=public_list, item=show_item)
        public_response = self.client.get(
            self.url,
            {
                "fragment": "secondary",
                "public_view": "1",
                "public_list": public_list.public_reference,
            },
        )
        self.assertEqual(public_response.context["all_episode_watched"], 0)
        public_soup = BeautifulSoup(public_response.content, "html.parser")
        self.assertIsNone(public_soup.select_one("#all-episodes form"))
        self.assertIsNone(public_soup.select_one("#all-episodes button"))

        watch.order_archived = True
        watch.save(update_fields=["order_archived"])
        Episode.ratings.create(
            item=episode_item, related_season=season, rating_only=True, score=7
        )
        response = self.client.get(self.url, {"fragment": "secondary"})
        self.assertEqual(response.context["all_episode_watched"], 0)

    @patch("app.providers.services.get_media_metadata")
    def test_pinned_catalogue_does_not_refetch_provider_coordinates(self, metadata):
        pinned = deepcopy(self.base)
        pinned.update(deepcopy(self.grouped))
        for number in (0, 1, 2):
            pinned[f"season/{number}"]["media_id"] = "order_123"
        _, seasons = enrich_detail_seasons(
            pinned,
            media_id="42",
            source=Sources.TMDB.value,
            user=self.user,
            detail_item=None,
            render_secondary_only=True,
        )
        metadata.assert_not_called()
        self.assertTrue(
            all(season["episode_media_id"] == "order_123" for season in seasons)
        )
        self.assertTrue(all(season["episodes"] for season in seasons))

    @patch("app.save_views.resolve_episode_coordinate")
    def test_pinned_episode_keeps_its_provider_when_returning_to_other_provider_show(
        self, resolve_coordinate
    ):
        resolve_coordinate.side_effect = InvalidEpisodeCoordinateError
        return_url = reverse(
            "media_details",
            kwargs={
                "source": "tvdb",
                "media_type": "tv",
                "media_id": "84",
                "title": "a-show",
            },
        )
        response = self.client.post(
            f"{reverse('episode_save')}?next={return_url}",
            {
                "media_id": "order_123",
                "source": "tmdb",
                "season_number": 1,
                "episode_number": 1,
                "status": Status.COMPLETED.value,
            },
        )
        self.assertEqual(response.status_code, 404)
        resolve_coordinate.assert_called_once_with(
            "order_123",
            Sources.TMDB.value,
            1,
            1,
            language="en",
        )
        self.assertFalse(Episode.objects.exists())
