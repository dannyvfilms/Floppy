from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

import app.helpers
from app import home_presentation
from app.media_card_model import progress_changer_model
from app.models import Game, Item, MediaTypes, Sources, Status


class GameTotalPlaytimeTests(SimpleTestCase):
    """A game tracked in several sessions shows its total, not the last session."""

    def game(self, progress, aggregated=None):
        game = SimpleNamespace(
            id=3,
            item=SimpleNamespace(media_type=MediaTypes.GAME.value),
            progress=progress,
            max_progress=None,
            formatted_progress=app.helpers.minutes_to_hhmm(progress),
            progress_is_percentage=False,
            progress_unit="minutes",
        )
        if aggregated is not None:
            game.aggregated_progress = aggregated
        return game

    def test_total_replaces_the_latest_session(self):
        props = progress_changer_model(self.game(170, aggregated=3000))
        self.assertEqual(props["value"], app.helpers.minutes_to_hhmm(3000))

    def test_single_entry_is_unchanged(self):
        props = progress_changer_model(self.game(170))
        self.assertEqual(props["value"], app.helpers.minutes_to_hhmm(170))


class HomeButtonsPreferenceTests(SimpleTestCase):
    """"Next Episode button only" leaves no +/- buttons or counts on Home cards."""

    def progress_for(self, preference):
        user = SimpleNamespace(quick_season_update_mobile=preference)
        entry = SimpleNamespace(
            item=SimpleNamespace(media_type="tv", id=1),
            media=SimpleNamespace(
                id=1, item=SimpleNamespace(media_type="tv"), progress=1,
                max_progress=10, formatted_progress="1", formatted_max_progress="10",
                progress_unit="episodes", progress_is_percentage=False,
            ),
            next_episode=False, subtitle_override=None, use_podcast_show=False,
            podcast_show=None, show_progress_controls=True,
        )
        ctx = {"react_props": {"model": {"cardKey": "tv-1"}}}
        with mock.patch.object(home_presentation, "card_context", return_value=ctx), \
                mock.patch.object(home_presentation, "_base_context", return_value={}), \
                mock.patch.object(home_presentation, "_request_csrf", return_value=""):
            return home_presentation._entry_model(entry, {}, user, None)["progress"]

    def test_next_episode_only_hides_progress(self):
        self.assertIsNone(self.progress_for("next_episode"))

    def test_other_choices_keep_progress(self):
        for choice in ("none", "season_update", "both"):
            self.assertIsNotNone(self.progress_for(choice), choice)


class ProgressEditGameTotalTests(TestCase):
    def test_response_shows_total_playtime_across_sessions(self):
        user = get_user_model().objects.create_user(username="gamer", password="x")
        self.client.force_login(user)
        item = Item.objects.create(
            media_id="gta6", source=Sources.MANUAL.value,
            media_type=MediaTypes.GAME.value, title="GTA 6",
        )
        Game.objects.create(item=item, user=user, status=Status.IN_PROGRESS.value, progress=1000)
        latest = Game.objects.create(item=item, user=user, status=Status.IN_PROGRESS.value, progress=170)
        response = self.client.post(
            reverse("progress_edit", args=[MediaTypes.GAME.value, latest.id]),
            {"operation": "increase"},
        )
        self.assertContains(response, app.helpers.minutes_to_hhmm(1200))
