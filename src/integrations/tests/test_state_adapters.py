"""Adapters must be honest about what they can do.

The engine intersects an adapter's declared capabilities with what the user
approved, so a capability declared before it has been verified is how an
unverified write reaches someone's library. Emby and Kodi therefore declare
reads only, and these tests pin that rather than trusting the docstrings.
"""

import logging
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import Item, MediaTypes, Sources
from integrations.imports.helpers import encrypt
from integrations.models import (
    CAPABILITY_WATCHED_PUSH_PLAYED,
    CAPABILITY_WATCHED_READ,
    CAPABILITY_WATCHED_WRITE_PLAYED,
    EmbyAccount,
    KodiAccount,
    SyncClientKind,
)
from integrations.state import outbound
from integrations.state.adapters.base import TerminalAdapterError
from integrations.state.adapters.emby import EmbyStateAdapter
from integrations.state.adapters.jellyfin import JellyfinStateAdapter
from integrations.state.adapters.kodi import KodiStateAdapter
from integrations.state.identity import get_or_create_binding


def setUpModule():
    """Silence log noise for this module only."""
    logging.disable(logging.DEBUG)


def tearDownModule():
    """Restore logging so other modules' assertLogs still see records."""
    logging.disable(logging.NOTSET)


class CapabilityHonestyTests(TestCase):
    def test_only_jellyfin_declares_a_write_capability(self):
        """The whole program's safety claim, in one assertion.

        If this fails, some adapter has started claiming it can write before
        anyone verified that it can.
        """
        self.assertIn(CAPABILITY_WATCHED_WRITE_PLAYED, JellyfinStateAdapter.CAPABILITIES)
        self.assertIn(CAPABILITY_WATCHED_PUSH_PLAYED, JellyfinStateAdapter.CAPABILITIES)

        for adapter in (EmbyStateAdapter, KodiStateAdapter):
            self.assertEqual(
                adapter.CAPABILITIES,
                frozenset({CAPABILITY_WATCHED_READ}),
                f"{adapter.__name__} must declare reads only",
            )

    def test_an_unverified_write_refuses_loudly(self):
        for adapter_class, account in (
            (EmbyStateAdapter, Mock()),
            (KodiStateAdapter, Mock()),
        ):
            adapter = adapter_class(account)
            with self.assertRaises(TerminalAdapterError):
                adapter.write_watched("x", watched=True)


class EmbyAdapterTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="owner")
        self.account = EmbyAccount.objects.create(
            user=self.user,
            base_url="https://emby.example",
            api_key=encrypt("secret"),
            emby_user_id="emby-user-1",
        )
        self.adapter = EmbyStateAdapter(self.account)
        self.movie, _ = Item.objects.get_or_create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": "The Matrix"},
        )

    def test_a_single_match_resolves(self):
        with patch.object(
            self.adapter,
            "_request",
            return_value={"Items": [{"Id": "emby-1"}]},
        ):
            self.assertEqual(self.adapter.resolve_external_id(self.movie), "emby-1")

    def test_an_ambiguous_match_resolves_to_nothing(self):
        """Two candidates must never become a write target."""
        with patch.object(
            self.adapter,
            "_request",
            return_value={"Items": [{"Id": "emby-1"}, {"Id": "emby-2"}]},
        ):
            self.assertIsNone(self.adapter.resolve_external_id(self.movie))

    def test_no_match_resolves_to_nothing(self):
        with patch.object(self.adapter, "_request", return_value={"Items": []}):
            self.assertIsNone(self.adapter.resolve_external_id(self.movie))

    def test_an_episode_must_agree_on_its_numbers(self):
        """A series-level provider id matches every episode of the show."""
        episode, _ = Item.objects.get_or_create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            defaults={"title": "Friends"},
        )
        with patch.object(
            self.adapter,
            "_request",
            return_value={
                "Items": [
                    {"Id": "emby-9", "ParentIndexNumber": 2, "IndexNumber": 4},
                ],
            },
        ):
            self.assertIsNone(self.adapter.resolve_external_id(episode))

    def test_state_reads_played_and_count(self):
        with patch.object(
            self.adapter,
            "_request",
            return_value={"UserData": {"Played": True, "PlayCount": 3}},
        ):
            state = self.adapter.read_state("emby-1")

        self.assertTrue(state.watched)
        self.assertEqual(state.play_count, 3)

    def test_missing_user_data_is_unknown_not_unwatched(self):
        """None means unknown. Returning unwatched here would be evidence."""
        with patch.object(self.adapter, "_request", return_value={}):
            self.assertIsNone(self.adapter.read_state("emby-1"))

    def test_an_unsupported_source_resolves_to_nothing(self):
        item, _ = Item.objects.get_or_create(
            media_id="x1",
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            defaults={"title": "Game"},
        )
        self.assertIsNone(self.adapter.resolve_external_id(item))


class KodiAdapterTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="owner")
        self.account = KodiAccount.objects.create(
            user=self.user,
            base_url="http://kodi.example/jsonrpc",
        )
        self.adapter = KodiStateAdapter(self.account)
        self.movie, _ = Item.objects.get_or_create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": "The Matrix"},
        )

    def test_identity_comes_from_the_library_not_the_provider_id(self):
        with patch.object(
            self.adapter,
            "_call",
            return_value={
                "movies": [
                    {"movieid": 7, "uniqueid": {"tmdb": "603"}},
                    {"movieid": 8, "uniqueid": {"tmdb": "604"}},
                ],
            },
        ):
            self.assertEqual(self.adapter.resolve_external_id(self.movie), "movie:7")

    def test_two_library_entries_with_one_provider_id_are_ambiguous(self):
        with patch.object(
            self.adapter,
            "_call",
            return_value={
                "movies": [
                    {"movieid": 7, "uniqueid": {"tmdb": "603"}},
                    {"movieid": 9, "uniqueid": {"tmdb": "603"}},
                ],
            },
        ):
            self.assertIsNone(self.adapter.resolve_external_id(self.movie))

    def test_playcount_becomes_watched(self):
        with patch.object(
            self.adapter,
            "_call",
            return_value={"moviedetails": {"playcount": 2}},
        ):
            state = self.adapter.read_state("movie:7")

        self.assertTrue(state.watched)
        self.assertEqual(state.play_count, 2)

    def test_zero_playcount_is_unwatched(self):
        with patch.object(
            self.adapter,
            "_call",
            return_value={"moviedetails": {"playcount": 0}},
        ):
            state = self.adapter.read_state("movie:7")

        self.assertFalse(state.watched)

    def test_a_malformed_id_is_unknown(self):
        self.assertIsNone(self.adapter.read_state("garbage"))


class AdapterRegistryTests(TestCase):
    def test_each_client_kind_builds_its_own_adapter(self):
        user = get_user_model().objects.create_user(username="owner")
        EmbyAccount.objects.create(
            user=user,
            base_url="https://emby.example",
            api_key=encrypt("secret"),
            emby_user_id="u",
        )
        binding, _ = get_or_create_binding(
            user,
            SyncClientKind.EMBY.value,
            instance_key="s",
            profile_key="u",
        )

        adapter = outbound.get_adapter(binding)

        self.assertIsInstance(adapter, EmbyStateAdapter)

    def test_a_client_kind_with_no_adapter_returns_none(self):
        user = get_user_model().objects.create_user(username="owner")
        binding, _ = get_or_create_binding(
            user,
            SyncClientKind.STREMIO.value,
            instance_key="s",
            profile_key="u",
        )

        self.assertIsNone(outbound.get_adapter(binding))

    def test_an_unconnected_account_yields_no_adapter(self):
        user = get_user_model().objects.create_user(username="owner")
        EmbyAccount.objects.create(
            user=user,
            base_url="https://emby.example",
            api_key=encrypt("secret"),
            connection_broken=True,
        )
        binding, _ = get_or_create_binding(
            user,
            SyncClientKind.EMBY.value,
            instance_key="s",
            profile_key="u",
        )

        self.assertIsNone(outbound.get_adapter(binding))
