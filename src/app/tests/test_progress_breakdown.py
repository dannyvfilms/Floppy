import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from app.models import TV, Episode, Item, MediaTypes, Season, Sources, Status
from app.providers.services import ProviderAPIError
from app.services.episode_ordering import persist_order
from app.services.progress_breakdown import (
    UNWATCHED,
    UPCOMING,
    WATCHED,
    build_progress_breakdown,
    format_minutes,
)

PAST = "2020-01-01"
FUTURE = (timezone.now() + timedelta(days=90)).strftime("%Y-%m-%d")


def _episode(number, air_date=PAST, runtime=40):
    return {
        "episode_number": number,
        "name": f"Episode {number} title",
        "air_date": air_date,
        "runtime": runtime,
    }


def _catalogue(**seasons):
    """Return a fake provider: seasons are given as s0=[...], s1=[...]."""
    payloads = {
        int(key.removeprefix("s")): {
            "season_title": "Specials" if key == "s0" else f"Season {key[1:]}",
            "episodes": episodes,
        }
        for key, episodes in seasons.items()
    }

    def fake(media_type, media_id, source, season_numbers=None, **kwargs):
        if media_type == "tv":
            return {
                "related": {
                    "seasons": [{"season_number": number} for number in payloads],
                },
            }
        return {f"season/{number}": payloads[number] for number in season_numbers if number in payloads}

    return fake


class BreakdownTestCase(TestCase):
    """Seed one tracked show and offer helpers to watch episodes."""

    def setUp(self):
        """Create a user with a tracked show."""
        self.user = get_user_model().objects.create_user(username="progress-user")
        self.show = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
        )
        self.tv = TV.objects.create(
            item=self.show,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

    def season(self, number, status=Status.IN_PROGRESS.value, **extra):
        """Track a season of the show."""
        item = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=number,
            title="Breaking Bad",
        )
        return Season.objects.create(
            item=item,
            related_tv=self.tv,
            user=self.user,
            status=status,
            **extra,
        )

    def watch(self, season, *numbers, when=None):
        """Complete the given episode numbers of a tracked season."""
        for number in numbers:
            item, _ = Item.objects.get_or_create(
                media_id="1396",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                season_number=season.item.season_number,
                episode_number=number,
                defaults={"title": f"Episode {number} title"},
            )
            Episode.objects.create(
                item=item,
                related_season=season,
                end_date=when or timezone.now(),
            )

    def breakdown(self, fake, **kwargs):
        """Build the breakdown against a fake provider."""
        with patch("app.providers.services.get_media_metadata", side_effect=fake):
            return build_progress_breakdown(**(kwargs or {"tv": self.tv}))


class BuildProgressBreakdownTests(BreakdownTestCase):
    """The numbers and episode states a breakdown reports."""

    def test_totals_count_aired_episodes_and_skip_specials(self):
        """Specials and unaired episodes stay out of the overall figures."""
        season_one = self.season(1)
        season_two = self.season(2)
        self.watch(season_one, 1, 2)
        self.watch(season_two, 1)

        result = self.breakdown(
            _catalogue(
                s0=[_episode(1)],
                s1=[_episode(1), _episode(2), _episode(3)],
                s2=[_episode(1), _episode(2), _episode(3, air_date=FUTURE)],
            ),
        )

        self.assertEqual((result.watched, result.total, result.left), (3, 5, 2))
        self.assertEqual(result.percent, 60)
        self.assertEqual(result.watched, self.tv.watched_once_count)
        self.assertEqual([season.number for season in result.seasons], [0, 1, 2])
        self.assertEqual(result.seasons[2].total, 2)
        self.assertEqual(
            [episode["state"] for episode in result.seasons[2].episodes],
            [WATCHED, UNWATCHED, UPCOMING],
        )
        self.assertEqual(result.first_open_season, 1)
        self.assertEqual(
            json.loads(result.open_state_json),
            {"s0": False, "s1": True, "s2": False},
        )

    def test_untracked_seasons_show_as_unwatched(self):
        """A catalogue season the user never tracked is all unwatched."""
        self.watch(self.season(1), 1)

        result = self.breakdown(_catalogue(s1=[_episode(1), _episode(2)], s2=[_episode(1)]))

        self.assertEqual(result.seasons[1].watched, 0)
        self.assertEqual(result.seasons[1].percent, 0)
        self.assertEqual((result.watched, result.total), (1, 3))

    def test_dropped_season_is_excluded_from_overall(self):
        """A dropped season is listed but does not feed the totals."""
        season_one = self.season(1)
        self.watch(season_one, 1)
        self.season(2, status=Status.DROPPED.value)

        result = self.breakdown(_catalogue(s1=[_episode(1), _episode(2)], s2=[_episode(1)]))

        self.assertTrue(result.seasons[1].dropped)
        self.assertEqual(result.total, 2)

    def test_plays_before_a_rewatch_still_count_as_watched(self):
        """Watched means finished once in any pass; the rewatch is reported on top."""
        started = timezone.now() - timedelta(days=1)
        season = self.season(1, rewatch_started_at=started)
        self.watch(season, 1, when=started - timedelta(days=30))
        self.watch(season, 2)
        self.tv.max_progress = 2

        result = self.breakdown(_catalogue(s1=[_episode(1), _episode(2)]))

        self.assertEqual(
            [episode["state"] for episode in result.seasons[0].episodes],
            [WATCHED, WATCHED],
        )
        self.assertEqual(
            [episode["rewatched"] for episode in result.seasons[0].episodes],
            [False, True],
        )
        self.assertEqual((result.watched, result.total, result.percent), (2, 2, 100))
        self.assertEqual(result.watched, self.tv.watched_once_count)
        self.assertTrue(result.rewatching)
        self.assertEqual((result.rewatch_watched, result.rewatch_percent), (1, 50))
        self.assertEqual(result.seasons[0].rewatch_percent, 50)
        self.assertEqual(result.rewatch_percent, self.tv.rewatch_percentage)

    def test_rewatch_just_started_glows_at_zero(self):
        """A fresh pass reports 0% on top of a complete first watch."""
        started = timezone.now() - timedelta(days=1)
        season = self.season(1, rewatch_started_at=started)
        self.watch(season, 1, 2, when=started - timedelta(days=30))

        result = self.breakdown(_catalogue(s1=[_episode(1), _episode(2)]))

        self.assertEqual(result.percent, 100)
        self.assertEqual(result.rewatch_percent, 0)

    def test_finished_rewatch_goes_back_to_a_plain_completed_line(self):
        """Once the pass is closed there is no rewatch line, only completion."""
        started = timezone.now() - timedelta(days=1)
        season = self.season(1, rewatch_started_at=started)
        self.watch(season, 1, 2)
        season.stop_rewatch()

        result = self.breakdown(_catalogue(s1=[_episode(1), _episode(2)]))

        self.assertFalse(result.rewatching)
        self.assertIsNone(result.rewatch_percent)
        self.assertEqual(result.percent, 100)

    def test_no_rewatch_line_without_a_pass(self):
        """A show never rewatched has no rewatch figures."""
        self.watch(self.season(1), 1)

        result = self.breakdown(_catalogue(s1=[_episode(1), _episode(2)]))

        self.assertFalse(result.rewatching)
        self.assertIsNone(result.rewatch_percent)
        self.assertIsNone(result.seasons[0].rewatch_percent)

    def test_rewatch_in_one_season_leaves_the_others_plain(self):
        """Only the season being rewatched carries a rewatch percentage."""
        started = timezone.now() - timedelta(days=1)
        season_one = self.season(1, rewatch_started_at=started)
        season_two = self.season(2)
        self.watch(season_one, 1, 2, when=started - timedelta(days=30))
        self.watch(season_one, 1)
        self.watch(season_two, 1, 2)
        self.tv.max_progress = 4

        result = self.breakdown(_catalogue(s1=[_episode(1), _episode(2)], s2=[_episode(1), _episode(2)]))

        self.assertEqual(result.percent, 100)
        self.assertEqual(result.seasons[0].rewatch_percent, 50)
        self.assertIsNone(result.seasons[1].rewatch_percent)
        # The other season's plays are not part of the open pass.
        self.assertEqual(result.rewatch_percent, 25)
        self.assertEqual(self.tv.rewatch_percentage, 25)

    def test_dropped_season_rewatch_is_left_out_of_overall(self):
        """A dropped season being rewatched does not move the show's rewatch line."""
        started = timezone.now() - timedelta(days=1)
        season_one = self.season(1)
        season_two = self.season(2, status=Status.DROPPED.value, rewatch_started_at=started)
        self.watch(season_one, 1)
        self.watch(season_two, 1)

        result = self.breakdown(_catalogue(s1=[_episode(1)], s2=[_episode(1)]))

        self.assertFalse(result.rewatching)
        self.assertIsNone(result.rewatch_percent)

    def test_unfinished_first_watch_shows_while_rewatching_another_season(self):
        """Season one still has an unwatched episode, so the show is not complete."""
        started = timezone.now() - timedelta(days=1)
        season_one = self.season(1)
        season_two = self.season(2, rewatch_started_at=started)
        self.watch(season_one, 1)
        self.watch(season_two, 1, when=started - timedelta(days=30))

        result = self.breakdown(_catalogue(s1=[_episode(1), _episode(2)], s2=[_episode(1)]))

        self.assertEqual((result.watched, result.total, result.percent), (2, 3, 67))
        self.assertEqual(result.rewatch_percent, 0)

    def test_watched_episode_missing_from_catalogue_still_counts(self):
        """The card counts every completed play, so the breakdown must too."""
        season = self.season(1)
        self.watch(season, 1, 9)

        result = self.breakdown(_catalogue(s1=[_episode(1), _episode(2)]))

        self.assertEqual((result.watched, result.total), (2, 3))
        self.assertEqual(result.seasons[0].episodes[-1]["number"], 9)

    def test_episode_without_air_date_waits_until_watched(self):
        """An undated episode is not counted unless it has been watched."""
        season = self.season(1)
        self.watch(season, 2)

        result = self.breakdown(_catalogue(s1=[_episode(1, air_date=None), _episode(2, air_date=None)]))

        self.assertEqual(
            [episode["state"] for episode in result.seasons[0].episodes],
            [UPCOMING, WATCHED],
        )
        self.assertEqual((result.watched, result.total), (1, 1))

    def test_season_with_nothing_aired_has_no_percent(self):
        """A season that has not started does not claim 0%."""
        self.season(1)

        result = self.breakdown(_catalogue(s1=[_episode(1, air_date=FUTURE)]))

        self.assertIsNone(result.seasons[0].percent)
        self.assertIsNone(result.percent)

    def test_minutes_left_needs_every_runtime(self):
        """The time left is only offered when every unwatched runtime is known."""
        self.watch(self.season(1), 1)

        known = self.breakdown(_catalogue(s1=[_episode(1), _episode(2, runtime=45), _episode(3, runtime=30)]))
        unknown = self.breakdown(_catalogue(s1=[_episode(1), _episode(2, runtime=None)]))

        self.assertEqual(known.minutes_left, 75)
        self.assertEqual(known.minutes_left_label, "1h 15m")
        self.assertIsNone(unknown.minutes_left)
        self.assertEqual(unknown.minutes_left_label, "")

    def test_provider_failure_falls_back_to_watched_episodes(self):
        """When the catalogue is down the modal still lists what was watched."""
        self.watch(self.season(1), 1, 2)

        with patch(
            "app.providers.services.get_media_metadata",
            side_effect=ProviderAPIError("tmdb", "boom"),
        ):
            result = build_progress_breakdown(tv=self.tv)

        self.assertTrue(result.catalogue_unavailable)
        self.assertIsNone(result.percent)
        self.assertEqual(result.seasons[0].watched, 2)
        self.assertTrue(result.seasons[0].catalogue_missing)

    def test_season_missing_from_catalogue_lists_only_watched(self):
        """A tracked season the provider no longer has keeps its watched list."""
        self.watch(self.season(1), 1)
        self.watch(self.season(7), 3)

        result = self.breakdown(_catalogue(s1=[_episode(1), _episode(2)]))

        missing = result.seasons[1]
        self.assertEqual(missing.number, 7)
        self.assertTrue(missing.catalogue_missing)
        self.assertIsNone(missing.percent)
        self.assertEqual((result.watched, result.total), (1, 2))

    def test_single_season_mode_counts_that_season_only(self):
        """The season page's breakdown covers just its season, specials included."""
        season = self.season(0)
        self.watch(season, 1)

        result = self.breakdown(_catalogue(s0=[_episode(1), _episode(2)]), season=season)

        self.assertEqual([s.number for s in result.seasons], [0])
        self.assertEqual((result.watched, result.total, result.percent), (1, 2, 50))
        self.assertEqual(json.loads(result.open_state_json), {"s0": True})

    def test_season_page_counts_unaired_episodes_like_its_card(self):
        """On a season page the card divides by every episode, so the modal does too."""
        season = self.season(1)
        self.watch(season, 1)
        season.max_progress = 3
        catalogue = _catalogue(
            s1=[_episode(1), _episode(2, air_date=FUTURE), _episode(3, air_date=None)],
        )

        season_view = self.breakdown(catalogue, season=season)
        show_view = self.breakdown(catalogue)

        self.assertEqual(season_view.percent, season.watched_once_percentage)
        self.assertEqual((season_view.watched, season_view.total), (1, 3))
        # The show page's card uses released episodes only, so its modal does too.
        self.assertEqual((show_view.watched, show_view.total, show_view.percent), (1, 1, 100))

    def test_links_point_at_episode_and_season_pages(self):
        """Every season and episode links to its own details page."""
        self.watch(self.season(1), 1)

        result = self.breakdown(_catalogue(s1=[_episode(1)]))

        self.assertEqual(
            result.seasons[0].url,
            "/details/tmdb/tv/1396/breaking-bad/season/1",
        )
        self.assertEqual(
            result.seasons[0].episodes[0]["url"],
            "/details/tmdb/tv/1396/breaking-bad/season/1/episode/1",
        )

    def test_selected_episode_order_supplies_the_catalogue(self):
        """A show on a personal episode order lists that order's episodes."""
        season = self.season(1)
        self.watch(season, 1)
        self.tv.active_episode_order = persist_order(
            self.show,
            Sources.TMDB.value,
            "1396",
            "aired",
            "TMDB (Aired)",
            {
                "episodes": [
                    {
                        "provider_episode_id": f"e{number}",
                        "season_number": 1,
                        "episode_number": number,
                        "title": f"Ordered {number}",
                        "air_date": PAST,
                    }
                    for number in (1, 2, 3)
                ],
            },
        )
        self.tv.save()

        result = build_progress_breakdown(tv=self.tv)

        self.assertEqual((result.watched, result.total), (1, 3))
        self.assertIn("order_", result.seasons[0].url)

    def test_exactly_one_target_is_required(self):
        """Passing both or neither is a programming error."""
        with self.assertRaises(ValueError):
            build_progress_breakdown()

    def test_format_minutes(self):
        """Minutes read as hours and minutes."""
        self.assertEqual(format_minutes(40), "40m")
        self.assertEqual(format_minutes(60), "1h 0m")
        self.assertEqual(format_minutes(125), "2h 5m")


class CaughtUpTests(BreakdownTestCase):
    """Caught Up is a display label: every aired episode watched, more to come (R5)."""

    def test_all_aired_watched_with_an_upcoming_episode_is_caught_up(self):
        season = self.season(1)
        self.watch(season, 1, 2)

        result = self.breakdown(
            _catalogue(s1=[_episode(1), _episode(2), _episode(3, air_date=FUTURE)]),
        )

        self.assertTrue(result.caught_up)

    def test_nothing_left_to_air_is_complete_not_caught_up(self):
        season = self.season(1)
        self.watch(season, 1, 2)

        result = self.breakdown(_catalogue(s1=[_episode(1), _episode(2)]))

        self.assertFalse(result.caught_up)

    def test_an_unwatched_aired_episode_is_not_caught_up(self):
        season = self.season(1)
        self.watch(season, 1)

        result = self.breakdown(
            _catalogue(s1=[_episode(1), _episode(2), _episode(3, air_date=FUTURE)]),
        )

        self.assertFalse(result.caught_up)

    def test_nothing_aired_yet_is_not_caught_up(self):
        self.season(1)

        result = self.breakdown(_catalogue(s1=[_episode(1, air_date=FUTURE)]))

        self.assertFalse(result.caught_up)

    def test_an_announced_season_with_no_episode_list_keeps_the_show_caught_up(self):
        season = self.season(1, status=Status.COMPLETED.value)
        self.season(2, status=Status.PLANNING.value)
        self.watch(season, 1, 2)

        result = self.breakdown(_catalogue(s1=[_episode(1), _episode(2)], s2=[]))

        self.assertTrue(result.caught_up)

    def test_a_season_page_is_judged_on_its_own_episodes(self):
        """Season 1 is finished even though the show has a season still to come."""
        season_one = self.season(1, status=Status.COMPLETED.value)
        self.season(2, status=Status.PLANNING.value)
        self.watch(season_one, 1, 2)
        fake = _catalogue(s1=[_episode(1), _episode(2)], s2=[_episode(1, air_date=FUTURE)])

        self.assertFalse(self.breakdown(fake, season=season_one).caught_up)
        self.assertTrue(self.breakdown(fake, tv=self.tv).caught_up)

    def test_a_tracked_season_missing_from_the_catalogue_is_not_caught_up(self):
        """A partial provider answer cannot prove an omitted season is watched."""
        season_one = self.season(1, status=Status.COMPLETED.value)
        self.season(2, status=Status.IN_PROGRESS.value)
        self.watch(season_one, 1, 2)

        result = self.breakdown(
            _catalogue(
                s1=[_episode(1), _episode(2)],
                s3=[_episode(1, air_date=FUTURE)],
            ),
        )

        self.assertFalse(result.caught_up)

    def test_unavailable_catalogue_is_not_caught_up(self):
        self.watch(self.season(1), 1)

        def broken(*_args, **_kwargs):
            raise ProviderAPIError("tmdb", None)

        self.assertFalse(self.breakdown(broken).caught_up)

    def test_progress_card_shows_the_label_only_when_caught_up(self):
        season = self.season(1)
        self.watch(season, 1, 2)
        self.tv.max_progress = 2
        context = {
            "media": self.tv.item,
            "media_type": "tv",
            "current_instance": self.tv,
            "public_view": False,
        }

        def card(fake):
            with patch("app.providers.services.get_media_metadata", side_effect=fake):
                return render_to_string("app/components/detail_progress_card_slot.html", context)

        caught_up = card(
            _catalogue(s1=[_episode(1), _episode(2), _episode(3, air_date=FUTURE)]),
        )
        finished = card(_catalogue(s1=[_episode(1), _episode(2)]))

        self.assertIn("caughtUp: true", caught_up)
        self.assertIn("Caught Up", caught_up)
        self.assertIn("caughtUp: false", finished)


class ProgressBreakdownViewTests(BreakdownTestCase):
    """The endpoints behind the progress card."""

    def setUp(self):
        """Log in and seed a watched season."""
        super().setUp()
        self.season_one = self.season(1)
        self.watch(self.season_one, 1)
        self.client.force_login(self.user)
        self.fake = _catalogue(s1=[_episode(1), _episode(2)])

    def get(self, url):
        """Fetch a breakdown with the provider faked."""
        with patch("app.providers.services.get_media_metadata", side_effect=self.fake):
            return self.client.get(url)

    def test_show_breakdown_renders_seasons_and_episode_links(self):
        """The show fragment lists seasons, counts and episode links."""
        response = self.get(reverse("tv_progress_breakdown", args=[self.tv.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Season 1")
        self.assertContains(response, "1/2")
        self.assertContains(response, "50%")
        self.assertContains(response, "/details/tmdb/tv/1396/breaking-bad/season/1/episode/2")
        self.assertIn("no-store", response["Cache-Control"])

    def test_season_breakdown_renders(self):
        """The season fragment works from the season's own id."""
        response = self.get(reverse("season_progress_breakdown", args=[self.season_one.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1/2")

    def test_modal_glows_only_for_an_open_rewatch(self):
        """The rewatch line and glow appear while a pass is open, and vanish after."""
        url = reverse("tv_progress_breakdown", args=[self.tv.id])
        self.assertNotContains(self.get(url), "progress-glow")

        self.season_one.rewatch_started_at = timezone.now() - timedelta(hours=1)
        self.season_one.save()
        self.watch(self.season_one, 2)
        response = self.get(url)

        self.assertContains(response, "Rewatching")
        self.assertContains(response, "progress-glow")
        self.assertContains(response, "Watched again")

        self.season_one.rewatch_started_at = None
        self.season_one.save()
        self.assertNotContains(self.get(url), "progress-glow")

    def test_provider_failure_still_renders(self):
        """A provider outage shows the notice instead of an error page."""
        self.fake = ProviderAPIError("tmdb", "boom")
        with patch("app.providers.services.get_media_metadata", side_effect=self.fake):
            response = self.client.get(reverse("tv_progress_breakdown", args=[self.tv.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "could not be loaded")

    def test_other_users_library_is_not_reachable(self):
        """Another user's show or season is a 404."""
        self.client.force_login(get_user_model().objects.create_user(username="other"))

        self.assertEqual(self.get(reverse("tv_progress_breakdown", args=[self.tv.id])).status_code, 404)
        self.assertEqual(
            self.get(reverse("season_progress_breakdown", args=[self.season_one.id])).status_code,
            404,
        )

    def test_anonymous_is_sent_to_login(self):
        """The fragment is private."""
        self.client.logout()

        response = self.client.get(reverse("tv_progress_breakdown", args=[self.tv.id]))

        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_progress_card_opens_the_matching_breakdown(self):
        """The card on a show page and on a season page each load their own fragment."""
        self.tv.max_progress = 2
        self.season_one.max_progress = 2
        for media_type, instance, url_name in (
            ("tv", self.tv, "tv_progress_breakdown"),
            ("season", self.season_one, "season_progress_breakdown"),
        ):
            html = render_to_string(
                "app/components/detail_progress_card_slot.html",
                {
                    "media": instance.item,
                    "media_type": media_type,
                    "current_instance": instance,
                    "public_view": False,
                },
            )

            self.assertIn(f'hx-get="{reverse(url_name, args=[instance.id])}"', html)

    def test_progress_card_shows_completion_and_the_rewatch_subtitle(self):
        """The card reads watched-once; an open pass adds a subtitle and glow."""
        self.watch(self.season_one, 2)
        self.season_one.max_progress = 2

        def card():
            return render_to_string(
                "app/components/detail_progress_card_slot.html",
                {
                    "media": self.season_one.item,
                    "media_type": "season",
                    "current_instance": self.season_one,
                    "public_view": False,
                },
            )

        self.assertIn("percent: 100,", card())
        self.assertIn("rewatch: null", card())

        # The info tip explains the card and sits beside the clickable card,
        # not inside it (a button cannot hold a button).
        html = card()
        self.assertIn('aria-label="About your progress"', html)
        self.assertIn("watched at least once", html)
        self.assertGreater(
            html.index('aria-label="About your progress"'),
            html.index("</button>"),
        )

        self.season_one.rewatch_started_at = timezone.now() + timedelta(minutes=1)
        self.season_one._invalidate_episode_stats()
        html = card()

        self.assertIn("percent: 100,", html)
        self.assertIn("rewatch: 0,", html)
        self.assertIn("detail-progress-card__sub", html)
        self.assertIn("progress-glow", html)

    def test_progress_card_is_not_clickable_in_public_view(self):
        """Public viewers get no card, so no way to load a private fragment."""
        html = render_to_string(
            "app/components/detail_progress_card_slot.html",
            {
                "media": self.show,
                "media_type": "tv",
                "current_instance": self.tv,
                "public_view": True,
            },
        )

        self.assertNotIn("hx-get", html)
