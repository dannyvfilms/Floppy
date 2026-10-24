from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from app.models import Item, Sources, WatchState
from integrations import plex as plex_api
from integrations import plex_watched_push
from integrations.imports.plex import PlexHistoryImporter
from integrations.models import ExternalReference, PlexAccount, PlexWatchedPush
from integrations.tasks import _plex_push as push_task


def _response(status=200, payload=None):
    response = Mock()
    response.status_code = status
    response.headers = {"Content-Type": "application/json"}
    response.json.return_value = payload or {}
    response.raise_for_status.return_value = None
    return response


class SwitchHomeUserTests(TestCase):
    """switch_home_user() returns a per-request token for one Home user."""

    @patch("integrations.plex.requests.post")
    def test_returns_home_user_token_and_sends_pin(self, mock_post):
        mock_post.return_value = _response(payload={"authToken": "home-token"})

        token = plex_api.switch_home_user("owner-token", "uuid-1", pin="1234")

        self.assertEqual(token, "home-token")
        self.assertTrue(mock_post.call_args.args[0].endswith("/users/uuid-1/switch"))
        self.assertEqual(mock_post.call_args.kwargs["params"], {"pin": "1234"})
        self.assertEqual(
            mock_post.call_args.kwargs["headers"]["X-Plex-Token"],
            "owner-token",
        )

    @patch("integrations.plex.requests.post")
    def test_wrong_pin_is_an_auth_error(self, mock_post):
        mock_post.return_value = _response(status=403)

        with self.assertRaises(plex_api.PlexAuthError):
            plex_api.switch_home_user("owner-token", "uuid-1", pin="0000")

    @patch("integrations.plex.requests.post")
    def test_missing_token_is_an_error(self, mock_post):
        mock_post.return_value = _response(payload={})

        with self.assertRaises(plex_api.PlexClientError):
            plex_api.switch_home_user("owner-token", "uuid-1")


class MarkWatchedTests(TestCase):
    """mark_watched() scrobbles exactly one rating key as the token's user."""

    @patch("integrations.plex.requests.get")
    def test_scrobbles_one_rating_key(self, mock_get):
        mock_get.return_value = _response()

        plex_api.mark_watched("user-token", "http://plex.local:32400", "123")

        mock_get.assert_called_once()
        self.assertEqual(mock_get.call_args.args[0], "http://plex.local:32400/:/scrobble")
        self.assertEqual(
            mock_get.call_args.kwargs["params"],
            {"key": "123", "identifier": "com.plexapp.plugins.library"},
        )
        self.assertEqual(
            mock_get.call_args.kwargs["headers"]["X-Plex-Token"],
            "user-token",
        )

    @patch("integrations.plex.requests.get")
    def test_rejected_token_is_an_auth_error(self, mock_get):
        mock_get.return_value = _response(status=401)

        with self.assertRaises(plex_api.PlexAuthError):
            plex_api.mark_watched("bad-token", "http://plex.local:32400", "123")


class FetchSectionItemTypeTests(TestCase):
    """fetch_section_all_items() can list episodes of a TV section in bulk."""

    @patch("integrations.plex.requests.get")
    def test_item_type_is_sent_only_when_given(self, mock_get):
        mock_get.return_value = _response(payload={"MediaContainer": {"Metadata": []}})

        plex_api.fetch_section_all_items("t", "http://plex.local", "2", item_type=4)
        self.assertEqual(mock_get.call_args.kwargs["params"]["type"], 4)

        plex_api.fetch_section_all_items("t", "http://plex.local", "2")
        self.assertNotIn("type", mock_get.call_args.kwargs["params"])


class SwitchHomeUserIdentityTests(TestCase):
    """switch_home_user() refuses a token for a different user."""

    @patch("integrations.plex.requests.post")
    def test_mismatched_user_is_refused(self, mock_post):
        mock_post.return_value = _response(
            payload={"uuid": "someone-else", "authToken": "t"},
        )

        with self.assertRaises(plex_api.PlexClientError):
            plex_api.switch_home_user("owner-token", "uuid-1")


class ListHomeUsersTests(TestCase):
    """list_home_users() surfaces failures instead of an empty Home."""

    @patch("integrations.plex.requests.get")
    def test_returns_users(self, mock_get):
        mock_get.return_value = _response(payload={"users": [{"uuid": "u1"}]})

        self.assertEqual(plex_api.list_home_users("t"), [{"uuid": "u1"}])

    @patch("integrations.plex.requests.get")
    def test_rejected_token_raises(self, mock_get):
        mock_get.return_value = _response(status=401)

        with self.assertRaises(plex_api.PlexAuthError):
            plex_api.list_home_users("t")


HOME_USERS = [
    {"uuid": "owner", "title": "Owner", "admin": True, "protected": True},
    {"uuid": "kid", "title": "Kid", "admin": False, "protected": False},
    {"uuid": "locked", "title": "Locked", "admin": False, "protected": True},
]
OWNED = {"machine_identifier": "srv", "name": "Home", "owned": True}
FRIENDS = {"machine_identifier": "other", "name": "Friend", "owned": False}


def _resources(token):
    """Each token sees the owned server with its own access token."""
    if token == "owner-token":
        return [{**OWNED, "access_token": "owner-srv"}, FRIENDS]
    return [{**OWNED, "access_token": f"{token}-srv", "owned": False}]


@patch("integrations.plex.list_resources", side_effect=_resources)
@patch("integrations.plex.list_home_users", return_value=HOME_USERS)
class OpenSessionTests(TestCase):
    """open_session() writes only as the chosen user on an owned server."""

    def setUp(self):
        self.account = Mock(
            plex_token="owner-token",
            sections=[{"machine_identifier": "srv", "uri": "http://plex.local"}],
        )

    def test_lists_owner_home_users_and_owned_servers_only(self, *_mocks):
        users, servers = plex_watched_push.list_targets(self.account)

        self.assertEqual([u.uuid for u in users], ["owner", "kid", "locked"])
        self.assertTrue(users[0].is_owner)
        self.assertEqual([s.machine_identifier for s in servers], ["srv"])

    @patch("integrations.plex.switch_home_user")
    def test_owner_uses_own_token_without_switching(self, mock_switch, *_mocks):
        session = plex_watched_push.open_session(self.account, "owner", "srv")

        mock_switch.assert_not_called()
        self.assertEqual(session.token, "owner-srv")
        self.assertEqual(session.uri, "http://plex.local")

    @patch("integrations.plex.switch_home_user", return_value="kid-token")
    def test_home_user_writes_with_their_own_server_token(self, mock_switch, *_m):
        session = plex_watched_push.open_session(self.account, "kid", "srv")

        mock_switch.assert_called_once_with("owner-token", "kid", None)
        self.assertEqual(session.token, "kid-token-srv")
        self.assertEqual(session.target.title, "Kid")

    @patch("integrations.plex.switch_home_user")
    def test_protected_user_needs_pin(self, mock_switch, *_mocks):
        with self.assertRaises(plex_watched_push.PinRequiredError):
            plex_watched_push.open_session(self.account, "locked", "srv")
        mock_switch.assert_not_called()

    def test_unknown_user_is_refused(self, *_mocks):
        with self.assertRaises(plex_watched_push.PlexPushError):
            plex_watched_push.open_session(self.account, "stranger", "srv")

    def test_server_not_owned_is_refused(self, *_mocks):
        with self.assertRaises(plex_watched_push.PlexPushError):
            plex_watched_push.open_session(self.account, "owner", "other")

    def test_uncached_server_address_is_refused(self, *_mocks):
        self.account.sections = []
        with self.assertRaises(plex_watched_push.PlexPushError):
            plex_watched_push.open_session(self.account, "owner", "srv")


def _movie(rating_key, tmdb_id, view_count=0, title="Movie"):
    return {
        "ratingKey": rating_key,
        "title": title,
        "year": 2000,
        "viewCount": view_count,
        "Guid": [{"id": f"tmdb://{tmdb_id}"}],
    }


def _episode(rating_key, show_key, season, number, view_count=0, title=""):
    return {
        "ratingKey": rating_key,
        "grandparentRatingKey": show_key,
        "grandparentTitle": "Show",
        "parentIndex": season,
        "index": number,
        "title": title,
        "viewCount": view_count,
    }


class BuildPlanTests(TestCase):
    """build_plan() reads both sides and plans only safe, exact writes."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="u", password="p")
        self.account = PlexAccount.objects.create(
            user=self.user,
            plex_token="owner-token",
            plex_username="owner",
            plex_account_id="acct",
            sections=[
                {"id": "1", "type": "movie", "title": "Movies",
                 "machine_identifier": "srv", "uri": "http://plex.local"},
                {"id": "2", "type": "show", "title": "TV",
                 "machine_identifier": "srv", "uri": "http://plex.local"},
                {"id": "9", "type": "movie", "title": "Elsewhere",
                 "machine_identifier": "other", "uri": "http://other"},
            ],
        )
        self.session = plex_watched_push.PushSession(
            target=plex_watched_push.PushTarget("kid", "Kid", False, False),
            server=plex_watched_push.PushServer("srv", "Home"),
            uri="http://plex.local",
            token="kid-srv",
        )
        self.library = {
            ("1", None): [],
            ("2", None): [{"ratingKey": "s1", "Guid": [{"id": "tmdb://1399"}]}],
            ("2", 4): [],
        }

    def _fetch(self, _token, _uri, section_id, start=0, item_type=None, **_kw):
        if section_id == "9":
            msg = "should never read another server"
            raise AssertionError(msg)
        entries = self.library[(section_id, item_type)]
        return entries[start:start + 2], len(entries)

    def _watched(self, media_id, media_type="movie", **fields):
        item = Item.objects.create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=media_type,
            title=fields.pop("title", f"Item {media_id}"),
            **fields,
        )
        WatchState.objects.create(user=self.user, item=item, watched=True)
        return item

    def _reference(self, rating_key, media_type, review_status="resolved", **fields):
        return ExternalReference.objects.create(
            user=self.user,
            integration="plex",
            source_account="srv::acct",
            external_namespace="plex_rating_key",
            external_identity=rating_key,
            media_type=media_type,
            review_status=review_status,
            **fields,
        )

    def _plan(self):
        with (
            patch("integrations.plex.fetch_section_all_items", side_effect=self._fetch),
            patch("integrations.plex.mark_watched") as mark,
            patch("integrations.plex.requests.post") as post,
        ):
            plan = plex_watched_push.build_plan(self.user, self.account, self.session)
        mark.assert_not_called()
        post.assert_not_called()
        return plan

    def test_plans_only_floppy_watched_movies_unwatched_in_plex(self):
        matrix = self._watched("603")
        self._watched("604")
        self.library[("1", None)] = [
            _movie("m1", 603, title="The Matrix"),
            _movie("m2", 604, view_count=2),
            _movie("m3", 999),
        ]

        plan = self._plan()

        self.assertEqual([w.rating_key for w in plan.writes], ["m1"])
        self.assertEqual(plan.writes[0].item_id, matrix.id)
        self.assertEqual(plan.writes[0].plex_title, "The Matrix (2000)")
        self.assertEqual(plan.already_watched, 1)

    def test_unknown_view_count_is_never_treated_as_unwatched(self):
        self._watched("603")
        self.library[("1", None)] = [_movie("m1", 603, view_count="?")]

        self.assertEqual(self._plan().writes, [])

    def test_ignored_decision_is_never_written(self):
        self._watched("603")
        self._reference("m1", "movie", review_status="ignored")
        self.library[("1", None)] = [_movie("m1", 603)]

        plan = self._plan()

        self.assertEqual(plan.writes, [])
        self.assertEqual(plan.ignored, 1)

    def test_corrected_decision_wins_over_plex_ids(self):
        self._watched("603")
        unwatched = Item.objects.create(
            media_id="605", source=Sources.TMDB.value, media_type="movie", title="X",
        )
        self._reference("m1", "movie", corrected_item=unwatched)
        self.library[("1", None)] = [_movie("m1", 603)]

        # Plex says 603, but the user corrected it to 605, which is unwatched.
        self.assertEqual(self._plan().writes, [])

    def test_plans_episode_by_show_id_and_numbers(self):
        episode = self._watched(
            "1399", "episode", season_number=1, episode_number=1,
            title="Winter Is Coming",
        )
        self.library[("2", 4)] = [
            _episode("e1", "s1", 1, 1, title="Winter Is Coming"),
            _episode("e2", "s1", 1, 2),
        ]

        plan = self._plan()

        self.assertEqual([w.rating_key for w in plan.writes], ["e1"])
        self.assertEqual(plan.writes[0].item_id, episode.id)
        self.assertEqual(plan.writes[0].plex_title, "Show S01E01 Winter Is Coming")
        self.assertEqual(plan.writes[0].warning, "")

    def test_differing_episode_titles_are_flagged(self):
        self._watched(
            "1399", "episode", season_number=1, episode_number=1, title="Pilot",
        )
        self.library[("2", 4)] = [_episode("e1", "s1", 1, 1, title="Something Else")]

        self.assertTrue(self._plan().writes[0].warning)

    def test_generic_or_show_titles_are_not_flagged(self):
        self._watched("1399", "episode", season_number=1, episode_number=1,
                      title="Show")
        self._watched("1399", "episode", season_number=1, episode_number=2,
                      title="Real Title")
        self.library[("2", 4)] = [
            _episode("e1", "s1", 1, 1, title="Winter Is Coming"),
            _episode("e2", "s1", 1, 2, title="Episode 2"),
        ]

        self.assertEqual([w.warning for w in self._plan().writes], ["", ""])

    def test_anime_episode_without_exact_decision_is_not_written(self):
        self._watched(
            "1399", "episode", season_number=1, episode_number=1,
            library_media_type="anime",
        )
        self.library[("2", 4)] = [_episode("e1", "s1", 1, 1)]

        plan = self._plan()

        self.assertEqual(plan.writes, [])
        self.assertEqual(len(plan.not_matched), 1)

    def test_anime_episode_with_exact_decision_is_written(self):
        episode = self._watched(
            "1399", "episode", season_number=1, episode_number=1,
            library_media_type="anime",
        )
        self._reference("e1", "episode", matched_item=episode)
        self.library[("2", 4)] = [_episode("e1", "s1", 3, 7)]

        self.assertEqual(self._plan().writes[0].item_id, episode.id)

    def test_show_decision_maps_episode_numbers(self):
        show = Item.objects.create(
            media_id="1400", source=Sources.TMDB.value, media_type="tv", title="S",
        )
        episode = self._watched("1400", "episode", season_number=2, episode_number=1)
        self._reference(
            "s1", "tv", matched_item=show, episode_mapping={"1:13": [2, 1]},
        )
        self.library[("2", 4)] = [_episode("e1", "s1", 1, 13)]

        self.assertEqual(self._plan().writes[0].item_id, episode.id)

    def test_unreadable_library_is_reported_and_others_continue(self):
        self._watched("1399", "episode", season_number=1, episode_number=1)
        self.library[("2", 4)] = [_episode("e1", "s1", 1, 1)]
        original = self._fetch

        def fetch(token, uri, section_id, **kwargs):
            if section_id == "1":
                msg = "denied"
                raise plex_api.PlexAuthError(msg)
            return original(token, uri, section_id, **kwargs)

        self._fetch = fetch
        plan = self._plan()

        self.assertEqual(plan.failed_libraries, ["Movies"])
        self.assertEqual([w.rating_key for w in plan.writes], ["e1"])

    def test_pages_through_large_libraries(self):
        for media_id in ("1", "2", "3"):
            self._watched(media_id)
        self.library[("1", None)] = [
            _movie("m1", 1), _movie("m2", 2), _movie("m3", 3),
        ]

        self.assertEqual(len(self._plan().writes), 3)


class PlexPushViewTests(TestCase):
    """The Plex modal reads only, and offers no way to send yet."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="v", password="p")
        self.client.force_login(self.user)
        self.session = plex_watched_push.PushSession(
            target=plex_watched_push.PushTarget("kid", "Kid", False, False),
            server=plex_watched_push.PushServer("srv", "Home"),
            uri="http://plex.local",
            token="kid-srv",
        )

    def _connect(self):
        return PlexAccount.objects.create(
            user=self.user, plex_token="owner-token", plex_username="owner",
        )

    def _write(self, rating_key, warning=""):
        return plex_watched_push.PlannedWrite(
            rating_key=rating_key, item_id=1, media_type="movie", library="Movies",
            plex_title=f"Title {rating_key}", floppy_title="Floppy title",
            warning=warning,
        )

    def test_integrations_card_follows_the_plex_connection(self):
        page = self.client.get(reverse("integrations"))
        self.assertContains(page, "Send Watched to Plex")
        self.assertNotContains(page, reverse("plex_push_targets"))

        self._connect()
        with patch("integrations.plex.list_home_users") as users:
            page = self.client.get(reverse("integrations"))
        # Opening the page never calls plex.tv; users load on request.
        users.assert_not_called()
        self.assertContains(page, reverse("plex_push_targets"))
        self.assertNotContains(self.client.get(reverse("mal_export")), "plex_push")

    @patch(
        "integrations.plex_watched_push.list_targets",
        return_value=(
            [plex_watched_push.PushTarget("kid", "Kid", False, True)],
            [plex_watched_push.PushServer("srv", "Home")],
        ),
    )
    def test_targets_lists_users_and_servers(self, _targets):
        self._connect()

        response = self.client.get(reverse("plex_push_targets"))

        self.assertContains(response, 'value="kid"')
        self.assertContains(response, 'value="srv"')
        self.assertContains(response, reverse("plex_push_preview"))

    def test_targets_without_plex_asks_to_connect(self):
        self.assertContains(self.client.get(reverse("plex_push_targets")), "Connect Plex first.")

    @patch("integrations.plex.mark_watched")
    def test_preview_lists_writes_and_sends_only_the_previewed_user(self, mark):
        self._connect()
        plan = plex_watched_push.PushPlan(
            writes=[self._write("m1"), self._write("m2", warning="Titles differ")],
            already_watched=4,
            not_matched=[("Anime S01E01", "numbering may differ")],
            failed_libraries=["Kids"],
        )
        with (
            patch("integrations.plex_watched_push.open_session", return_value=self.session),
            patch("integrations.plex_watched_push.build_plan", return_value=plan),
        ):
            response = self.client.post(
                reverse("plex_push_preview"),
                {"user_uuid": "kid", "machine_identifier": "srv", "pin": "1234"},
            )

        content = response.content.decode()
        self.assertIn('value="m1:1" class="mt-1 shrink-0" checked', content)
        self.assertIn('value="m2:1" class="mt-1 shrink-0">', content)
        self.assertIn("Titles differ", content)
        self.assertIn("4 already watched in Plex", content)
        self.assertIn("Could not read: Kids", content)
        self.assertIn("Anime S01E01", content)
        self.assertIn(reverse("plex_push_send"), content)
        self.assertIn('name="user_uuid" value="kid"', content)
        self.assertIn('name="machine_identifier" value="srv"', content)
        self.assertIn("for Kid?", content)
        # The PIN is re-read from its field at send time, never echoed.
        self.assertNotIn("1234", content)
        mark.assert_not_called()

    def test_preview_reports_a_missing_pin(self):
        self._connect()
        with patch(
            "integrations.plex_watched_push.open_session",
            side_effect=plex_watched_push.PinRequiredError("Kid needs their Plex PIN"),
        ):
            response = self.client.post(reverse("plex_push_preview"), {"user_uuid": "kid"})

        self.assertContains(response, "Kid needs their Plex PIN")

    def test_preview_runs_one_check_at_a_time(self):
        self._connect()
        cache.add(f"plex_push:{self.user.pk}", 1)
        with patch("integrations.plex_watched_push.open_session") as session:
            response = self.client.post(reverse("plex_push_preview"), {})

        session.assert_not_called()
        self.assertContains(response, "is already running")
        cache.delete(f"plex_push:{self.user.pk}")

    def test_preview_is_post_only(self):
        self._connect()
        self.assertEqual(self.client.get(reverse("plex_push_preview")).status_code, 405)


def _plan_with(*writes):
    return plex_watched_push.PushPlan(writes=list(writes))


class SendTests(TestCase):
    """send() writes only confirmed, still-unwatched items, one read at a time."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="s", password="p")
        self.account = PlexAccount.objects.create(
            user=self.user, plex_token="owner-token", plex_username="owner",
        )
        self.item = Item.objects.create(
            media_id="603", source=Sources.TMDB.value, media_type="movie", title="M",
        )
        self.session = plex_watched_push.PushSession(
            target=plex_watched_push.PushTarget("kid", "Kid", False, False),
            server=plex_watched_push.PushServer("srv", "Home"),
            uri="http://plex.local",
            token="kid-srv",
        )
        self.remote = {}

    def _write(self, rating_key):
        return plex_watched_push.PlannedWrite(
            rating_key=rating_key, item_id=self.item.id, media_type="movie",
            library="Movies", plex_title=f"Title {rating_key}", floppy_title="M",
        )

    def _fetch(self, _token, _uri, rating_key, **_kwargs):
        return self.remote.get(rating_key)

    def _mark(self, _token, _uri, rating_key):
        # The echo record must exist before Plex is told anything.
        self.assertTrue(
            PlexWatchedPush.objects.filter(rating_key=rating_key).exists(),
        )
        self.remote[rating_key] = {**self.remote[rating_key], "viewCount": 1}

    def _send(self, plan, selected, mark=None):
        with (
            patch("integrations.plex_watched_push.build_plan", return_value=plan),
            patch("integrations.plex.fetch_metadata", side_effect=self._fetch),
            patch("integrations.plex.mark_watched", side_effect=mark or self._mark) as m,
            patch("integrations.plex_watched_push.time.sleep"),
        ):
            result = plex_watched_push.send(
                self.user, self.account, self.session, selected,
            )
        return result, m

    def test_a_wrong_already_watched_answer_is_rechecked_and_sent_once(self):
        """Plex can report "watched" for an item its listing shows unwatched."""
        answers = {"m1": [{"type": "movie", "viewCount": 1}]}
        self.remote = {"m1": {"type": "movie", "viewCount": 0}}

        def fetch(token, uri, rating_key, **kwargs):
            pending = answers.get(rating_key)
            return pending.pop(0) if pending else self._fetch(token, uri, rating_key)

        with patch("integrations.plex_watched_push.time.sleep") as sleep:
            with (
                patch("integrations.plex_watched_push.build_plan",
                      return_value=_plan_with(self._write("m1"))),
                patch("integrations.plex.fetch_metadata", side_effect=fetch),
                patch("integrations.plex.mark_watched", side_effect=self._mark) as mark,
            ):
                result = plex_watched_push.send(
                    self.user, self.account, self.session, {("m1", self.item.id)},
                )

        sleep.assert_called_once()
        mark.assert_called_once()
        self.assertEqual(result.sent, ["Title m1"])
        self.assertEqual(PlexWatchedPush.objects.count(), 1)

    def test_an_item_still_watched_on_recheck_is_skipped(self):
        self.remote = {"m1": {"type": "movie", "viewCount": 1}}

        result, mark = self._send(_plan_with(self._write("m1")), {("m1", self.item.id)})

        mark.assert_not_called()
        self.assertEqual(result.skipped, [("Title m1", "Already watched in Plex")])
        self.assertFalse(PlexWatchedPush.objects.exists())

    def test_writes_only_ticked_items_the_fresh_plan_still_has(self):
        self.remote = {"m1": {"type": "movie", "viewCount": 0}}
        selected = {("m1", self.item.id), ("gone", self.item.id)}

        result, mark = self._send(
            _plan_with(self._write("m1"), self._write("m2")), selected,
        )

        mark.assert_called_once_with("kid-srv", "http://plex.local", "m1")
        self.assertEqual(result.sent, ["Title m1"])
        self.assertEqual(result.stale, 1)
        push = PlexWatchedPush.objects.get()
        self.assertEqual(
            (push.machine_identifier, push.rating_key, push.item_id, push.plex_user_uuid),
            ("srv", "m1", self.item.id, "kid"),
        )

    def test_item_watched_since_the_preview_is_not_written(self):
        self.remote = {"m1": {"type": "movie", "viewCount": 3}}

        result, mark = self._send(_plan_with(self._write("m1")), {("m1", self.item.id)})

        mark.assert_not_called()
        self.assertEqual(result.skipped, [("Title m1", "Already watched in Plex")])
        self.assertFalse(PlexWatchedPush.objects.exists())

    def test_item_of_another_type_is_not_written(self):
        self.remote = {"m1": {"type": "episode", "viewCount": 0}}

        result, mark = self._send(_plan_with(self._write("m1")), {("m1", self.item.id)})

        mark.assert_not_called()
        self.assertEqual(result.skipped[0][1], "No longer found in Plex")

    def test_unconfirmed_write_is_reported(self):
        self.remote = {"m1": {"type": "movie", "viewCount": 0}}

        result, _mark = self._send(
            _plan_with(self._write("m1")),
            {("m1", self.item.id)},
            mark=lambda *_args: None,
        )

        self.assertEqual(result.sent, [])
        self.assertIn("does not show it as watched", result.skipped[0][1])

    def test_plex_error_stops_and_keeps_what_was_sent(self):
        self.remote = {
            "m1": {"type": "movie", "viewCount": 0},
            "m2": {"type": "movie", "viewCount": 0},
            "m3": {"type": "movie", "viewCount": 0},
        }

        def mark(token, uri, rating_key):
            if rating_key == "m2":
                msg = "down"
                raise plex_api.PlexClientError(msg)
            self._mark(token, uri, rating_key)

        result, mock = self._send(
            _plan_with(self._write("m1"), self._write("m2"), self._write("m3")),
            {("m1", self.item.id), ("m2", self.item.id), ("m3", self.item.id)},
            mark=mark,
        )

        self.assertEqual(result.sent, ["Title m1"])
        self.assertTrue(result.stopped)
        self.assertEqual(mock.call_count, 2)


class SendViewTests(TestCase):
    """The send view validates the selection, then the task does the writing."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username="w", password="p")
        self.client.force_login(self.user)
        PlexAccount.objects.create(user=self.user, plex_token="t", plex_username="o")

    @patch("integrations.plex_watched_push.open_session")
    def test_nothing_ticked_is_refused(self, session):
        response = self.client.post(reverse("plex_push_send"), {"user_uuid": "kid"})

        session.assert_not_called()
        self.assertContains(response, "Tick at least one item.")

    def test_a_large_selection_is_sent_in_the_background(self):
        session = plex_watched_push.PushSession(
            target=plex_watched_push.PushTarget("kid", "Kid", False, True),
            server=plex_watched_push.PushServer("srv", "Home"),
            uri="http://plex.local",
            token="kid-srv",
        )
        writes = ",".join(f"rk{i}:{i}" for i in range(5000))
        with (
            patch(
                "integrations.plex_watched_push.open_session",
                return_value=session,
            ) as open_session,
            patch(
                "integrations.plex_watched_push.send",
                return_value=plex_watched_push.PushResult(sent=["A"]),
            ) as send,
            patch(
                "integrations.tasks._plex_push.send_plex_watched_push.delay",
                wraps=push_task.send_plex_watched_push.delay,
            ) as delay,
        ):
            response = self.client.post(
                reverse("plex_push_send"),
                {"user_uuid": "kid", "machine_identifier": "srv", "pin": "1234",
                 "writes": writes},
            )

        self.assertEqual(len(send.call_args.args[3]), 5000)
        # The PIN reaches the task through the cache, never its stored arguments.
        self.assertEqual(delay.call_args.args[:3], (self.user.pk, "kid", "srv"))
        self.assertEqual(len(delay.call_args.args), 4)
        self.assertEqual(delay.call_args.kwargs, {})
        self.assertEqual(open_session.call_args_list[-1].args[3], "1234")
        self.assertIsNone(cache.get(plex_watched_push.pin_key(self.user.pk)))
        self.assertIsNone(cache.get(plex_watched_push.lock_key(self.user.pk)))
        self.assertContains(response, "1 item marked watched in Plex for Kid.")

    def test_status_shows_progress_while_running(self):
        cache.set(
            plex_watched_push.status_key(self.user.pk),
            {"done": False, "current": 3, "total": 10},
        )

        response = self.client.get(reverse("plex_push_status"))

        self.assertContains(response, "3 of 10 done")
        self.assertContains(response, 'hx-trigger="every 2s"')

    def test_wrong_pin_is_refused_before_queueing(self):
        with (
            patch(
                "integrations.plex_watched_push.open_session",
                side_effect=plex_api.PlexAuthError("no"),
            ),
            patch("integrations.tasks._plex_push.send_plex_watched_push.delay") as delay,
        ):
            response = self.client.post(
                reverse("plex_push_send"),
                {"user_uuid": "kid", "pin": "0000", "writes": "m1:5"},
            )

        delay.assert_not_called()
        self.assertContains(response, "Check the PIN")
        self.assertIsNone(cache.get(plex_watched_push.lock_key(self.user.pk)))

    def test_a_failed_send_releases_the_lock_and_reports(self):
        session = plex_watched_push.PushSession(
            target=plex_watched_push.PushTarget("kid", "Kid", False, False),
            server=plex_watched_push.PushServer("srv", "Home"),
            uri="http://plex.local",
            token="kid-srv",
        )
        with (
            patch("integrations.plex_watched_push.open_session", return_value=session),
            patch(
                "integrations.plex_watched_push.send",
                side_effect=plex_api.PlexClientError("down"),
            ),
        ):
            response = self.client.post(
                reverse("plex_push_send"),
                {"user_uuid": "kid", "machine_identifier": "srv", "writes": "m1:5"},
            )

        self.assertContains(response, "Plex could not be reached")
        self.assertIsNone(cache.get(plex_watched_push.lock_key(self.user.pk)))
        self.assertNotIn("kid-srv", str(cache.get(plex_watched_push.status_key(self.user.pk))))

    def test_sends_the_parsed_selection_and_renders_the_result(self):
        session = plex_watched_push.PushSession(
            target=plex_watched_push.PushTarget("kid", "Kid", False, False),
            server=plex_watched_push.PushServer("srv", "Home"),
            uri="http://plex.local",
            token="kid-srv",
        )
        result = plex_watched_push.PushResult(sent=["A"], stale=1)
        with (
            patch("integrations.plex_watched_push.open_session", return_value=session),
            patch("integrations.plex_watched_push.send", return_value=result) as send,
        ):
            response = self.client.post(
                reverse("plex_push_send"),
                {"user_uuid": "kid", "machine_identifier": "srv",
                 "writes": "m1:5,bad,m:2:7"},
            )

        self.assertEqual(send.call_args.args[3], {("m1", 5), ("m:2", 7)})
        self.assertContains(response, "1 item marked watched in Plex for Kid.")
        self.assertContains(response, "1 ticked item changed since the check")

    def test_demo_account_cannot_send(self):
        self.user.is_demo = True
        self.user.save(update_fields=["is_demo"])
        with patch("integrations.plex_watched_push.send") as send:
            self.client.post(
                reverse("plex_push_send"),
                {"writes": "m1:5"},
                HTTP_HX_REQUEST="true",
            )

        send.assert_not_called()


class PushEchoImportTests(TestCase):
    """The history importer skips the marks Floppy pushed itself."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="e", password="p")
        self.account = PlexAccount.objects.create(
            user=self.user, plex_token="t", plex_username="o",
        )
        self.pushed_at = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
        PlexWatchedPush.objects.create(
            user=self.user, machine_identifier="srv", rating_key="m1",
            pushed_at=self.pushed_at,
        )
        self.importer = PlexHistoryImporter(
            user=self.user, account=self.account, mode="new", library="srv::1",
        )
        self.importer._current_section_machine_id = "srv"

    def _entry(self, rating_key="m1", offset=timedelta(0)):
        return {
            "type": "movie",
            "ratingKey": rating_key,
            "viewedAt": int((self.pushed_at + offset).timestamp()),
        }

    def test_mark_within_the_window_is_an_echo(self):
        echo = self.importer._is_floppy_push_echo
        self.assertTrue(echo(self._entry()))
        self.assertTrue(echo(self._entry(offset=timedelta(minutes=9))))

    def test_real_plays_are_not_echoes(self):
        echo = self.importer._is_floppy_push_echo
        self.assertFalse(echo(self._entry(offset=timedelta(minutes=11))))
        self.assertFalse(echo(self._entry(offset=-timedelta(days=1))))
        self.assertFalse(echo(self._entry(rating_key="m2")))
        self.importer._current_section_machine_id = "other"
        self.assertFalse(echo(self._entry()))

    def test_process_entry_skips_and_counts_the_echo(self):
        with (
            patch.object(self.importer, "_is_allowed_history_user", return_value=True),
            patch.object(self.importer, "_normalize_guid_list") as normalize,
        ):
            self.importer._process_entry(self._entry(), "http://plex", "movie")

        normalize.assert_not_called()
        self.assertEqual(self.importer.summary_counts["skipped_floppy_push"], 1)
