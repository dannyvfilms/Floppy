"""The card model reads the same answers the media card template renders."""

from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.card_surfaces import card_context
from app.media_card_model import _corner_chips, _progress_bar, card_model, card_shape
from app.models import Item, MediaTypes, Movie, Sources, Status
from users.card_metadata import parse_card_metadata


class MediaCardModelTest(TestCase):
    """One tracked movie and a podcast, through the library surface."""

    def setUp(self):
        """Create a user and a completed movie."""
        self.user = get_user_model().objects.create_user("model-user", password="x")
        self.item = Item.objects.create(
            media_id="model-1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Model Movie",
        )
        self.movie = Movie.objects.create(
            item=self.item, user=self.user, status=Status.COMPLETED.value, progress=2,
        )

    def test_shapes(self):
        """Podcasts and music are square, library video is landscape."""
        self.assertEqual(card_shape("movie"), "poster")
        self.assertEqual(card_shape("podcast"), "square")
        self.assertEqual(card_shape("video", video_landscape=True), "landscape")

    def test_movie_model(self):
        """A completed movie has a status chip, its title and a play count."""
        ctx = card_context({"user": self.user}, "library", {"item": self.item, "media": self.movie})
        model = card_model(ctx)
        self.assertEqual(model["title"], "Model Movie")
        self.assertEqual(model["shape"], "poster")
        self.assertEqual(model["statusChip"]["kind"], "status")
        self.assertEqual(model["statusChip"]["status"], Status.COMPLETED.value)
        self.assertIn("model-1", model["href"])

    def test_credit_age_line_uses_the_person_setting(self):
        """A credit age is present by default and removable without removing role."""
        credit = {"age_label": "29 yo at release · died 1993", "role": "Eric Draven"}
        context = {"user": self.user}
        values = {"item": self.item, "media": self.movie, "credit": credit}
        model = card_model(card_context(context, "credit", values))
        age_line = next(line for line in model["lines"] if line.get("variant") == "credit-age")
        self.assertEqual(age_line["parts"][0]["text"], credit["age_label"])

        self.user.card_metadata = parse_card_metadata({
            "types": {
                "person": {
                    "fields": ["role"],
                    "options": {"show_credit_age": False},
                },
            },
        })
        hidden_model = card_model(card_context(context, "credit", values))
        self.assertFalse(any(line.get("variant") == "credit-age" for line in hidden_model["lines"]))

    def test_hover_actions(self):
        """The hover buttons track, list and link to history, and hide on public pages."""
        ctx = card_context({"user": self.user}, "library", {"item": self.item, "media": self.movie})
        actions = card_model(ctx)["actions"]
        self.assertEqual(
            [item["title"] for item in actions["items"]],
            ["Add to tracker", "Add to custom lists", "View your activity history"],
        )
        self.assertFalse(actions["clickable"])
        track = actions["items"][0]
        self.assertEqual(track["modal"], "track")
        self.assertTrue(track["target"].startswith("#track-movie-model-1"))
        self.assertEqual(track["vals"]["instance_id"], str(self.movie.id))
        public = card_context({"user": self.user, "public_view": True}, "library", {"item": self.item, "media": self.movie})
        self.assertIsNone(card_model(public)["actions"])
        self.user.clickable_media_cards = True
        self.assertTrue(card_model(ctx)["actions"]["clickable"])

    def test_quick_status_identity_tracks_permissions_and_existing_row(self):
        """Quick actions use the existing tracker and never appear on public cards."""
        ctx = card_context({"user": self.user}, "library", {"item": self.item, "media": self.movie})
        quick = card_model(ctx)["quickStatus"]
        self.assertTrue(quick["tracked"])
        self.assertEqual(quick["status"], Status.COMPLETED.value)
        self.assertEqual(quick["identity"]["instanceId"], self.movie.id)
        self.assertEqual(quick["identity"]["mediaId"], "model-1")
        untracked = card_context({"user": self.user}, "search", {"item": self.item, "media": None})
        self.assertFalse(card_model(untracked)["quickStatus"]["tracked"])
        self.item.source = Sources.MANUAL.value
        self.assertIsNone(card_model(untracked)["quickStatus"])
        self.item.source = Sources.TMDB.value
        public = card_context({"user": self.user, "public_view": True}, "library", {"item": self.item, "media": self.movie})
        self.assertIsNone(card_model(public)["quickStatus"])

    def test_next_episode_chip_has_compact_label(self):
        """The next-episode action exposes a short localized label for phones."""
        media = SimpleNamespace(next_episode_queue=False)
        ctx = {
            "item": self.item,
            "media": media,
            "user": SimpleNamespace(is_authenticated=True, quick_season_update_mobile="next_episode"),
        }
        with patch("app.media_card_model.app_tags.next_episode_url", return_value="/episode/next/"):
            chips = _corner_chips(ctx, "tv")

        self.assertEqual(chips, [{
            "kind": "next-episode",
            "text": "Next ep",
            "compactText": "Next",
            "href": "/episode/next/",
        }])

    def test_next_episode_chip_names_the_episode_for_hover(self):
        """The episode code comes from the link, so hover can say which one is next."""
        media = SimpleNamespace(next_episode_queue=False)
        ctx = {
            "item": self.item,
            "media": media,
            "user": SimpleNamespace(is_authenticated=True, quick_season_update_mobile="next_episode"),
        }
        href = "/details/tmdb/tv/1/show/season/3/episode/5"
        with patch("app.media_card_model.app_tags.next_episode_url", return_value=href):
            chip = _corner_chips(ctx, "tv")[0]

        self.assertEqual(chip["expandedText"], "Next episode: S03E05")
        self.assertEqual(chip["expandedShortText"], "Next ep: S03E05")

    def test_replacement_subtitle_lines_follow_the_saved_display(self):
        """An episode code or release date is as visible at rest as the user's first line."""
        from app.media_card_model import _item_lines

        item = SimpleNamespace(season_number=1, episode_number=14)
        ctx = {"item": item, "user": None, "show_episode_identity": True}
        for use_lines, profile, expected in (
            (True, {"lines": [{"display": "dormant"}], "display": "hover"}, True),
            (True, {"lines": [{"display": "hover"}, {"display": "dormant"}], "display": "hover"}, False),
            (False, {"lines": [], "display": "always"}, True),
            (False, {"lines": [], "display": "hover"}, False),
        ):
            with patch("users.card_metadata.resolve_profile", return_value=profile):
                lines = _item_lines({**ctx, "card_use_lines": use_lines}, "tv")
            self.assertEqual(lines[0]["parts"][0]["text"], "S01 E14")
            self.assertEqual(lines[0]["dormant"], expected, (use_lines, profile))

    def test_discover_actions(self):
        """Discover cards plan or hide a candidate with a POST that targets its row."""
        ctx = card_context(
            {"user": self.user},
            "discover",
            {"item": self.item, "discover_row_key": "trending"},
        )
        plan, hide, lists = card_model(ctx)["actions"]["items"]
        self.assertEqual((plan["kind"], plan["vals"]["action"]), ("post", "planning"))
        self.assertEqual(hide["vals"]["action"], "dismiss")
        self.assertEqual(plan["target"], "#discover-row-trending")
        self.assertEqual(plan["swap"], "outerHTML")
        self.assertEqual(lists["modal"], "lists")

    def test_status_chip_carries_its_color_class(self):
        """The chip's icon keeps the status colour the release card gave it."""
        ctx = card_context({"user": self.user}, "library", {"item": self.item, "media": self.movie})
        chip = card_model(ctx)["statusChip"]
        self.assertEqual(chip["kind"], "status")
        self.assertTrue(chip["colorClass"].startswith("text-"))

    def test_progress_bar_reports_whether_it_stays_visible_at_rest(self):
        """A dormant display keeps the bar on the poster instead of only on hover."""
        media = SimpleNamespace(
            status=Status.IN_PROGRESS.value,
            aggregated_status=None,
            progress=5,
            max_progress=10,
            progress_percentage=50,
        )
        base = {"media": media, "card_show_progress": True}
        shown = _progress_bar({**base, "card_progress_display": "dormant"}, MediaTypes.TV.value)
        hover = _progress_bar({**base, "card_progress_display": "hover"}, MediaTypes.TV.value)
        self.assertEqual(shown, {"percent": 50, "paused": False, "dormant": True})
        self.assertFalse(hover["dormant"])
        self.assertIsNone(_progress_bar({**base, "card_show_progress": False}, MediaTypes.TV.value))
