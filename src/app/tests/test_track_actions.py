from types import SimpleNamespace
from unittest.mock import patch

from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase

from app import checkin
from app.models import MediaTypes, Status
from app.track_actions import track_actions

ADD, EDIT = "create", "edit"


class TrackActionsTests(SimpleTestCase):
    """The main button leads with the forward action where the media type has one."""

    def keys(self, media_type, status):
        return [action["key"] for action in track_actions(media_type, status)]

    def test_games_and_board_games_always_lead_with_add_entry(self):
        for media_type in (MediaTypes.GAME.value, MediaTypes.BOARDGAME.value):
            for status in Status.values:
                with self.subTest(media_type=media_type, status=status):
                    self.assertEqual(self.keys(media_type, status), [ADD, EDIT])

    def test_finished_items_lead_with_add_entry(self):
        for media_type in (
            MediaTypes.MOVIE.value,
            MediaTypes.ANIME.value,
            MediaTypes.BOOK.value,
            MediaTypes.COMIC.value,
        ):
            with self.subTest(media_type=media_type):
                self.assertEqual(
                    self.keys(media_type, Status.COMPLETED.value),
                    [ADD, EDIT],
                )

    def test_videos_keep_one_row_so_they_never_offer_a_new_entry(self):
        self.assertEqual(
            self.keys(MediaTypes.VIDEO.value, Status.COMPLETED.value),
            [EDIT],
        )

    def test_unfinished_items_only_edit(self):
        for status in (
            Status.IN_PROGRESS.value,
            Status.PLANNING.value,
            Status.PAUSED.value,
            Status.DROPPED.value,
        ):
            with self.subTest(status=status):
                self.assertEqual(self.keys(MediaTypes.MOVIE.value, status), [EDIT])

    def test_manga_only_edits(self):
        for status in Status.values:
            with self.subTest(status=status):
                self.assertEqual(self.keys(MediaTypes.MANGA.value, status), [EDIT])


class CheckInActionsTests(SimpleTestCase):
    """A movie that can be checked in leads with the check-in action for its phase."""

    def keys(self, phase, status):
        return [
            action["key"]
            for action in track_actions(
                MediaTypes.MOVIE.value,
                status,
                {"phase": phase, "reload_in": None},
            )
        ]

    def test_idle_unfinished_movie_leads_with_check_in(self):
        for status in (
            Status.PLANNING.value,
            Status.IN_PROGRESS.value,
            Status.PAUSED.value,
            Status.DROPPED.value,
        ):
            with self.subTest(status=status):
                self.assertEqual(self.keys(checkin.PHASE_IDLE, status), ["start", EDIT])

    def test_idle_completed_movie_leads_with_check_in(self):
        self.assertEqual(
            self.keys(checkin.PHASE_IDLE, Status.COMPLETED.value),
            ["start", ADD, EDIT],
        )

    def test_running_check_in_leads_with_pause_then_finish(self):
        self.assertEqual(
            self.keys(checkin.PHASE_ACTIVE, Status.IN_PROGRESS.value),
            ["pause", "cancel", EDIT],
        )
        self.assertEqual(
            self.keys(checkin.PHASE_FINISHABLE, Status.IN_PROGRESS.value),
            ["finish", "pause", "cancel", EDIT],
        )

    def test_paused_check_in_leads_with_resume(self):
        self.assertEqual(
            self.keys(checkin.PHASE_PAUSED, Status.IN_PROGRESS.value),
            ["resume", EDIT],
        )


class ShowCheckInActionsTests(SimpleTestCase):
    """A show's Check-in names the episode it would start."""

    def labels(self, phase, status=Status.IN_PROGRESS.value):
        return [
            action["label"]
            for action in track_actions(
                MediaTypes.TV.value,
                status,
                {"phase": phase, "reload_in": None, "code": "S02E05"},
            )
        ]

    def test_idle_show_checks_in_to_the_next_episode(self):
        self.assertEqual(
            self.labels(checkin.PHASE_IDLE),
            ["Check-in S02E05", "Edit"],
        )

    def test_a_completed_show_with_a_new_episode_never_offers_add_entry(self):
        self.assertEqual(
            self.labels(checkin.PHASE_IDLE, Status.COMPLETED.value),
            ["Check-in S02E05", "Edit"],
        )

    def test_paused_show_resumes_its_episode(self):
        self.assertEqual(
            self.labels(checkin.PHASE_PAUSED),
            ["Resume S02E05", "Edit"],
        )

    def test_a_caught_up_show_keeps_the_plain_edit_button(self):
        self.assertEqual(
            [
                a["key"]
                for a in track_actions(MediaTypes.TV.value, Status.COMPLETED.value)
            ],
            [EDIT],
        )


class ShowTrackActionTemplateTests(SimpleTestCase):
    """The TV status pill gains a Check-in split only when there is an episode to start."""

    def render(self, phase):
        request = RequestFactory().get("/details/")
        request.user = SimpleNamespace(id=1)
        media = {"source": "tmdb", "media_type": "tv", "media_id": "1668"}
        with patch("app.checkin.phase", return_value=phase):
            return render_to_string(
                "app/components/detail_track_action.html",
                {
                    "request": request,
                    "media": media,
                    "return_url": "%2Fdetails%2F",
                    "current_instance": SimpleNamespace(
                        id=7,
                        status=Status.IN_PROGRESS.value,
                    ),
                },
            )

    def test_check_in_leads_with_a_pencil_for_edit(self):
        html = self.render(
            {"phase": checkin.PHASE_IDLE, "reload_in": None, "code": "S02E05"},
        )
        self.assertIn("Check-in S02E05", html)
        self.assertIn('hx-vals=\'{"action": "start"}\'', html)
        self.assertIn('aria-label="Edit entry, In Progress"', html)
        self.assertNotIn("More tracking actions", html)

    def test_running_check_in_puts_edit_in_a_menu(self):
        html = self.render(
            {"phase": checkin.PHASE_ACTIVE, "reload_in": 60, "code": "S02E05"},
        )
        self.assertIn("Pause", html)
        self.assertIn("Cancel check-in", html)
        self.assertIn('aria-label="More tracking actions"', html)
        self.assertIn("location.reload()", html)

    def test_no_episode_left_keeps_the_status_pill(self):
        html = self.render(None)
        self.assertNotIn("Check-in", html)
        self.assertNotIn("Edit entry,", html)
        self.assertIn("In Progress", html)


class TrackSplitTemplateTests(SimpleTestCase):
    """One action is a plain button, two a pencil segment, three or more a menu."""

    def render(self, actions, status=Status.COMPLETED.value):
        request = RequestFactory().get("/details/")
        request.user = SimpleNamespace(id=1)
        media = {"source": "tmdb", "media_type": "movie", "media_id": "238"}
        with (
            patch("app.track_actions.track_actions", return_value=actions),
            patch("app.checkin.phase", return_value=None),
        ):
            return render_to_string(
                "app/components/detail_track_split.html",
                {
                    "request": request,
                    "media": media,
                    "media_type": "movie",
                    "current_instance": SimpleNamespace(id=7, status=status),
                },
            )

    @staticmethod
    def action(key):
        return {
            "key": key,
            "label": "Add new entry" if key == "create" else "Edit",
            "icon": "plus" if key == "create" else "edit",
        }

    def test_single_action_is_a_plain_edit_button_with_no_menu(self):
        html = self.render([self.action("edit")])
        self.assertIn("Completed", html)
        self.assertNotIn("More tracking actions", html)
        self.assertNotIn("Edit entry,", html)
        self.assertNotIn('x-show="trackMenuOpen"', html)

    def test_two_actions_add_an_icon_only_edit_segment(self):
        html = self.render([self.action("create"), self.action("edit")])
        self.assertIn("Add new entry", html)
        self.assertEqual(html.count('aria-label="Edit entry, Completed"'), 1)
        self.assertIn('title="Edit entry, Completed"', html)
        self.assertNotIn("More tracking actions", html)
        self.assertNotIn('x-show="trackMenuOpen"', html)

    def test_three_actions_open_a_menu(self):
        extra = {"key": "create", "label": "Another action", "icon": "plus"}
        html = self.render([self.action("create"), self.action("edit"), extra])
        self.assertIn('aria-label="More tracking actions"', html)
        self.assertIn(':aria-expanded="trackMenuOpen"', html)
        self.assertIn('@keydown.escape.window="trackMenuOpen = false"', html)
        self.assertIn("Another action", html)
        self.assertNotIn("Edit entry,", html)

    def test_modal_actions_override_the_checkin_swap_mode(self):
        html = self.render([self.action("create"), self.action("edit")])
        self.assertEqual(html.count('hx-swap="innerHTML"'), 2)

    def test_saving_a_movie_keeps_the_checkin_split_button(self):
        request = RequestFactory().post("/save/")
        request.user = SimpleNamespace(id=1)
        with patch("app.checkin.phase", return_value={"phase": "idle", "reload_in": None}):
            html = render_to_string("app/components/detail_track_action.html", {
                "request": request,
                "media": {"source": "tmdb", "media_type": "movie", "media_id": "238"},
                "current_instance": SimpleNamespace(id=7, status=Status.COMPLETED.value),
                "return_url": "%2Fdetails%2Ftmdb%2Fmovie%2F238%2Fmovie",
                "swap_oob": True,
            })
        self.assertIn("Check-in</span>", html)
        self.assertIn("Add new entry</button>", html)
        self.assertIn('hx-swap-oob="outerHTML"', html)
        self.assertNotIn('"return_url": "/save/"', html)

    def test_grouped_anime_is_decided_by_its_stored_type(self):
        """A TMDB anime is one TV tracker, so a new entry would collide with it."""
        request = RequestFactory().get("/details/")
        request.user = SimpleNamespace(id=1)
        media = {"source": "tmdb", "media_type": "anime", "media_id": "1"}
        for stored, expected in (("tv", False), ("anime", True)):
            with (
                self.subTest(stored=stored),
                patch(
                    "app.checkin.phase",
                    return_value=None,
                ),
            ):
                html = render_to_string(
                    "app/components/detail_track_split.html",
                    {
                        "request": request,
                        "media": media,
                        "media_type": "anime",
                        "current_instance": SimpleNamespace(
                            id=7,
                            status=Status.COMPLETED.value,
                            item=SimpleNamespace(media_type=stored),
                        ),
                    },
                )
                self.assertEqual("Add new entry" in html, expected)
