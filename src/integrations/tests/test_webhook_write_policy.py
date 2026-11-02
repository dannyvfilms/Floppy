"""Contract tests for integrations/webhooks/write_policy.py.

If one of these fails after you added or changed a webhook integration, read
docs/architecture/webhook-write-rules.md: every processor must have a row in
WEBHOOK_WRITE_POLICIES and ask ``_should_record`` before ``_process_media``.
"""

import importlib
import pkgutil
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

import integrations.webhooks
from app import live_playback
from integrations.webhooks import write_policy
from integrations.webhooks.base import BaseWebhookProcessor
from integrations.webhooks.emby import EmbyWebhookProcessor
from integrations.webhooks.generic_scrobble import GenericScrobbleProcessor
from integrations.webhooks.jellyfin import JellyfinWebhookProcessor
from integrations.webhooks.kodi import KodiWebhookProcessor
from integrations.webhooks.plex import PlexWebhookProcessor
from integrations.webhooks.stremio import StremioWebhookProcessor
from integrations.webhooks.write_policy import (
    MAX_STOP_POSITION_SECONDS,
    MIN_STOP_POSITION_SECONDS,
    WEBHOOK_WRITE_POLICIES,
    WritePolicy,
    minimum_stop_position_seconds,
    should_record,
)

DOC_HINT = (
    "See integrations/webhooks/write_policy.py and "
    "docs/architecture/webhook-write-rules.md."
)


def _all_processor_classes():
    for module in pkgutil.iter_modules(integrations.webhooks.__path__):
        importlib.import_module(f"integrations.webhooks.{module.name}")

    found, pending = [], [BaseWebhookProcessor]
    while pending:
        for subclass in pending.pop().__subclasses__():
            found.append(subclass)
            pending.append(subclass)
    return found


class WritePolicyCoverageTests(SimpleTestCase):
    """Every webhook integration is listed in the one policy table."""

    def test_every_processor_has_a_policy_row(self):
        for cls in _all_processor_classes():
            with self.subTest(processor=cls.__name__):
                self.assertIn(
                    cls.SOURCE_LABEL,
                    WEBHOOK_WRITE_POLICIES,
                    f"{cls.__name__} (SOURCE_LABEL={cls.SOURCE_LABEL!r}) has no "
                    f"webhook write policy. {DOC_HINT}",
                )

    def test_every_row_explains_itself(self):
        for label, (policy, reason) in WEBHOOK_WRITE_POLICIES.items():
            with self.subTest(source=label):
                self.assertIsInstance(policy, WritePolicy)
                self.assertTrue(reason.strip())

    def test_unknown_source_fails_loudly(self):
        with self.assertRaisesMessage(LookupError, "write_policy.py"):
            should_record("not-a-source", "media.stop", played=True, position_seconds=0)


class WritePolicyRuleTests(SimpleTestCase):
    """The rule itself, independent of any integration."""

    def _record(self, policy, event, *, played=False, position=None, duration=None):
        with patch.dict(WEBHOOK_WRITE_POLICIES, {"test": (policy, "test")}):
            return should_record(
                "test",
                event,
                played=played,
                position_seconds=position,
                duration_seconds=duration,
            )

    def test_minimum_stop_position_seconds(self):
        cases = [
            (None, MIN_STOP_POSITION_SECONDS),
            (0, MIN_STOP_POSITION_SECONDS),
            (600, MIN_STOP_POSITION_SECONDS),
            (1800, 90),
            (3600, MAX_STOP_POSITION_SECONDS),
            (7200, MAX_STOP_POSITION_SECONDS),
        ]
        for duration, expected in cases:
            with self.subTest(duration=duration):
                self.assertEqual(
                    minimum_stop_position_seconds(duration),
                    expected,
                )

    def test_stop_only(self):
        short = MIN_STOP_POSITION_SECONDS - 1
        cases = [
            ("media.play", {}, False),
            ("media.resume", {}, False),
            ("media.pause", {}, False),
            ("media.play", {"played": True}, False),
            ("media.stop", {"position": short}, False),
            ("media.stop", {"position": 0}, False),
            ("media.stop", {"position": MIN_STOP_POSITION_SECONDS}, True),
            ("media.stop", {"position": short, "duration": 600}, False),
            ("media.stop", {"position": MIN_STOP_POSITION_SECONDS, "duration": 600}, True),
            ("media.stop", {"position": 89, "duration": 1800}, False),
            ("media.stop", {"position": 90, "duration": 1800}, True),
            ("media.stop", {"position": 179, "duration": 7200}, False),
            ("media.stop", {"position": MAX_STOP_POSITION_SECONDS, "duration": 7200}, True),
            ("media.stop", {"position": None}, True),
            ("media.stop", {"position": short, "played": True}, True),
            ("media.scrobble", {"position": 0}, True),
            ("mark", {}, True),
            ("media.rate", {}, False),
        ]
        for event, kwargs, expected in cases:
            with self.subTest(event=event, **kwargs):
                self.assertIs(
                    self._record(WritePolicy.STOP_ONLY, event, **kwargs),
                    expected,
                )

    def test_start_only_records_its_start_ping(self):
        self.assertTrue(self._record(WritePolicy.START_ONLY, "media.play"))
        self.assertFalse(
            self._record(WritePolicy.START_ONLY, "media.stop", position=0),
        )

    def test_final_only_records_everything(self):
        for event in ("media.play", "media.stop", "media.scrobble"):
            with self.subTest(event=event):
                self.assertTrue(
                    self._record(WritePolicy.FINAL_ONLY, event, position=0),
                )


@patch("app.live_playback._attach_resolved_image")
class ProcessorWiringTests(TestCase):
    """Each processor asks the policy before it writes.

    ``_process_media`` is patched, so these check the gate only and never
    reach a provider.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="policyuser",
            token="policy-token",
            plex_usernames="policyuser",
        )

    def tearDown(self):
        live_playback.clear_user_playback_state(self.user.id)

    def _writes(self, processor_cls, payload, **process_kwargs):
        with (
            patch.object(processor_cls, "_process_media", return_value=None) as mock,
            patch.object(
                processor_cls,
                "_update_live_playback_state",
                return_value=None,
                create=True,
            ),
        ):
            processor_cls().process_payload(payload, self.user, **process_kwargs)
        return mock.called

    # Payload builders: (start-ish payload, stop payload at `position` seconds)

    def _plex(self, event, position, duration=8100):
        return {
            "event": event,
            "Account": {"title": "policyuser"},
            "Metadata": {
                "type": "movie",
                "title": "The Matrix",
                "ratingKey": "rk-1",
                "duration": duration * 1000,
                "viewOffset": position * 1000,
                "Guid": [{"id": "tmdb://603"}],
            },
        }

    def _jellyfin(self, event, position, duration=8100):
        return {
            "Event": event,
            "PlaybackPositionTicks": position * 10_000_000,
            "Item": {
                "Name": "The Matrix",
                "Type": "Movie",
                "ProviderIds": {"Tmdb": "603"},
                "RunTimeTicks": duration * 10_000_000,
                "UserData": {"Played": False},
            },
        }

    def _emby(self, event, position, duration=8100):
        return {
            "Event": event,
            "Item": {
                "Name": "The Matrix",
                "Type": "Movie",
                "ProviderIds": {"Tmdb": "603"},
                "RunTimeTicks": duration * 10_000_000,
            },
            "PlaybackInfo": {
                "PlayedToCompletion": False,
                "PositionTicks": position * 10_000_000,
            },
        }

    def _kodi(self, event, position, duration=8100):
        return {
            "event": event,
            "mediaType": "movie",
            "title": "The Matrix",
            "uniqueIds": {"tmdb": "603", "imdb": None, "tvdb": None},
            "duration": duration,
            "progress": {
                "time": position,
                "percent": position / duration * 100,
            },
        }

    STOP_ONLY_CASES = (
        ("plex", PlexWebhookProcessor, "_plex", "media.play", "media.stop"),
        ("jellyfin", JellyfinWebhookProcessor, "_jellyfin", "Play", "Stop"),
        ("emby", EmbyWebhookProcessor, "_emby", "playback.start", "playback.stop"),
        ("kodi", KodiWebhookProcessor, "_kodi", "start", "stop"),
    )

    def test_stop_only_processors_never_write_on_start(self, _image):
        for label, cls, build, start, _stop in self.STOP_ONLY_CASES:
            with self.subTest(source=label):
                payload = getattr(self, build)(start, 300)
                self.assertFalse(
                    self._writes(cls, payload),
                    f"{cls.__name__} wrote on {start!r}. {DOC_HINT}",
                )

    def test_stop_only_processors_skip_short_stops(self, _image):
        duration = 8100
        short = minimum_stop_position_seconds(duration) - 1
        for label, cls, build, _start, stop in self.STOP_ONLY_CASES:
            with self.subTest(source=label):
                payload = getattr(self, build)(stop, short, duration=duration)
                self.assertFalse(self._writes(cls, payload), DOC_HINT)

    def test_stop_only_processors_write_on_real_stops(self, _image):
        duration = 8100
        minimum = minimum_stop_position_seconds(duration)
        for label, cls, build, _start, stop in self.STOP_ONLY_CASES:
            with self.subTest(source=label):
                payload = getattr(self, build)(stop, minimum, duration=duration)
                self.assertTrue(self._writes(cls, payload), DOC_HINT)

    def test_stop_only_processors_scale_the_threshold_with_runtime(self, _image):
        duration = 1800
        minimum = minimum_stop_position_seconds(duration)
        for label, cls, build, _start, stop in self.STOP_ONLY_CASES:
            with self.subTest(source=label):
                too_short = getattr(self, build)(
                    stop, minimum - 1, duration=duration,
                )
                self.assertFalse(self._writes(cls, too_short), DOC_HINT)
                long_enough = getattr(self, build)(
                    stop, minimum, duration=duration,
                )
                self.assertTrue(self._writes(cls, long_enough), DOC_HINT)

    def test_emby_zero_position_is_a_known_short_stop(self, _image):
        """A zero position is real, not missing, whichever field carries it."""
        payload = self._emby("playback.stop", 0)
        del payload["PlaybackInfo"]["PositionTicks"]
        payload["PlaybackPositionTicks"] = 0
        self.assertFalse(self._writes(EmbyWebhookProcessor, payload), DOC_HINT)

    def test_plex_stop_without_view_offset_is_a_short_stop(self, _image):
        """Plex omits viewOffset at position 0, so absent means zero."""
        payload = self._plex("media.stop", 0)
        del payload["Metadata"]["viewOffset"]
        self.assertFalse(self._writes(PlexWebhookProcessor, payload), DOC_HINT)

    def test_stremio_start_still_writes(self, _image):
        """Stremio's documented START_ONLY exception."""
        payload = {"id": "tt0133093", "type": "movie"}
        self.assertTrue(self._writes(StremioWebhookProcessor, payload))

    def test_scrobble_api_always_writes(self, _image):
        payload = {
            "media_type": "movie",
            "ids": {"tmdb": "603"},
            "position_seconds": 0,
        }
        self.assertTrue(self._writes(GenericScrobbleProcessor, payload))

    def test_policy_rows_match_processor_labels(self, _image):
        expected = {
            PlexWebhookProcessor: WritePolicy.STOP_ONLY,
            JellyfinWebhookProcessor: WritePolicy.STOP_ONLY,
            EmbyWebhookProcessor: WritePolicy.STOP_ONLY,
            KodiWebhookProcessor: WritePolicy.STOP_ONLY,
            StremioWebhookProcessor: WritePolicy.START_ONLY,
            GenericScrobbleProcessor: WritePolicy.FINAL_ONLY,
        }
        for cls, policy in expected.items():
            with self.subTest(processor=cls.__name__):
                self.assertIs(write_policy.policy_for(cls.SOURCE_LABEL), policy)
