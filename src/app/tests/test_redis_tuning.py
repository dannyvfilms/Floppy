"""Tests for Redis memory self-configuration (issue #521)."""

from unittest import mock

import redis
from django.test import SimpleTestCase, override_settings

from app import redis_tuning
from app.redis_tuning import (
    MAXMEMORY_CEILING,
    MAXMEMORY_FLOOR,
    derive_maxmemory_bytes,
    parse_size,
    tune_redis,
)
from config.runtime_profile import GIB, MIB, TIER_MINIMAL, ResourceProfile


def fake_client(config: dict | None = None):
    """Return a Redis stub backed by a plain dict of config values."""
    values = {"maxmemory": "0", "maxmemory-policy": "noeviction", "appendonly": "no"}
    values.update(config or {})
    client = mock.MagicMock()
    client.config_get.side_effect = lambda name: (
        {name: values[name]} if name in values else {}
    )

    def config_set(name, value):
        values[name] = str(value)

    client.config_set.side_effect = config_set
    client.values = values
    return client


class ParseSizeTests(SimpleTestCase):
    """Reading redis.conf-style sizes."""

    def test_accepts_suffixed_and_plain_values(self):
        """The compose-file spelling and a raw byte count must both work."""
        self.assertEqual(parse_size("256mb"), 256 * MIB)
        self.assertEqual(parse_size("1gb"), GIB)
        self.assertEqual(parse_size("512k"), 512 * 1024)
        self.assertEqual(parse_size("1048576"), 1048576)
        self.assertEqual(parse_size(1048576), 1048576)
        self.assertEqual(parse_size(" 128 MB "), 128 * MIB)

    def test_rejects_nonsense(self):
        """An unparseable value must be None, not a wrong number."""
        for value in ("", "lots", "mb", None, "12mib"):
            with self.subTest(value=value):
                self.assertIsNone(parse_size(value))


class DeriveBudgetTests(SimpleTestCase):
    """Choosing how much memory to give Redis."""

    def _with_memory(self, memory_bytes):
        return mock.patch.object(
            redis_tuning,
            "PROFILE",
            ResourceProfile(
                tier=TIER_MINIMAL,
                memory_bytes=memory_bytes,
                available_bytes=None,
                swap_bytes=0,
                cpus=2,
                overridden=False,
            ),
        )

    @override_settings(FLOPPY_REDIS_MAXMEMORY=None)
    def test_scales_with_the_host_between_floor_and_ceiling(self):
        """A 2 GB host gets a fraction; a huge host is still capped."""
        with self._with_memory(2 * GIB):
            budget = derive_maxmemory_bytes()
        self.assertGreaterEqual(budget, MAXMEMORY_FLOOR)
        self.assertLessEqual(budget, MAXMEMORY_CEILING)
        self.assertEqual(budget, int(2 * GIB * redis_tuning.MAXMEMORY_FRACTION))

        with self._with_memory(128 * GIB):
            self.assertEqual(derive_maxmemory_bytes(), MAXMEMORY_CEILING)

        with self._with_memory(256 * MIB):
            self.assertEqual(derive_maxmemory_bytes(), MAXMEMORY_FLOOR)

    @override_settings(FLOPPY_REDIS_MAXMEMORY=None)
    def test_undetectable_memory_yields_no_budget(self):
        """Guessing low would evict hot caches on a large host for no reason."""
        with self._with_memory(None):
            self.assertIsNone(derive_maxmemory_bytes())

    @override_settings(FLOPPY_REDIS_MAXMEMORY="300mb")
    def test_override_wins(self):
        """An explicit ceiling replaces the derived one."""
        with self._with_memory(2 * GIB):
            self.assertEqual(derive_maxmemory_bytes(), 300 * MIB)

    @override_settings(FLOPPY_REDIS_MAXMEMORY="0")
    def test_zero_override_opts_out_entirely(self):
        """Operators who manage Redis themselves can tell Floppy to keep out."""
        with self._with_memory(2 * GIB):
            self.assertIsNone(derive_maxmemory_bytes())

    @override_settings(FLOPPY_REDIS_MAXMEMORY="banana")
    def test_unparseable_override_falls_back_to_detection(self):
        """A typo must not silently disable the protection."""
        with self._with_memory(2 * GIB):
            self.assertEqual(
                derive_maxmemory_bytes(),
                int(2 * GIB * redis_tuning.MAXMEMORY_FRACTION),
            )


@override_settings(
    REDIS_ADMIN_URL="redis://localhost:6379",
    FLOPPY_REDIS_MAXMEMORY="256mb",
)
class TuneRedisTests(SimpleTestCase):
    """Applying the ceiling to a live server."""

    unsafe_error = "redis://admin:password@redis.example:6379/0 refused"

    def _run(self, client, **kwargs):
        with mock.patch.object(redis.Redis, "from_url", return_value=client):
            return tune_redis(**kwargs)

    def _assert_safe_error(self, summary, logs, operation, error_type):
        rendered = f"{summary}\n{' '.join(logs.output)}"
        self.assertIn(operation, rendered)
        self.assertIn(error_type, rendered)
        self.assertNotIn(self.unsafe_error, rendered)
        self.assertNotIn("admin:password", rendered)
        self.assertNotIn("refused", rendered)

    def test_sets_ceiling_and_policy_on_an_untouched_redis(self):
        """The default noeviction/unlimited config is what we're here to fix."""
        client = fake_client()
        summary = self._run(client)

        self.assertEqual(summary["applied"]["maxmemory"], 256 * MIB)
        self.assertEqual(summary["applied"]["maxmemory-policy"], "volatile-lru")
        self.assertEqual(summary["errors"], [])
        self.assertEqual(client.values["maxmemory-policy"], "volatile-lru")

    def test_respects_an_operator_set_maxmemory(self):
        """A non-zero maxmemory means someone already decided."""
        client = fake_client({"maxmemory": "1gb"})
        summary = self._run(client)

        self.assertEqual(summary["applied"], {})
        self.assertEqual(summary["skipped"]["maxmemory"], GIB)
        client.config_set.assert_not_called()

    def test_preserves_a_deliberately_chosen_policy(self):
        """Only the noeviction default gets replaced."""
        client = fake_client({"maxmemory-policy": "volatile-ttl"})
        summary = self._run(client)

        self.assertEqual(summary["applied"]["maxmemory"], 256 * MIB)
        self.assertEqual(summary["skipped"]["maxmemory-policy"], "volatile-ttl")
        self.assertEqual(client.values["maxmemory-policy"], "volatile-ttl")

    def test_denied_config_set_warns_without_raising(self):
        """Managed Redis and ACLs refuse CONFIG SET; that must not fail boot."""
        client = fake_client()
        client.config_set.side_effect = redis.exceptions.ResponseError(
            self.unsafe_error,
        )

        with self.assertLogs("app.redis_tuning", level="WARNING") as logs:
            summary = self._run(client)

        self.assertEqual(summary["applied"], {})
        self.assertTrue(summary["errors"])
        self._assert_safe_error(
            summary,
            logs,
            "Redis maxmemory update",
            "ResponseError",
        )

    def test_unreachable_redis_is_not_an_error_worth_raising(self):
        """The cache layer reports connectivity; this just tries again later."""
        with (
            self.assertLogs("app.redis_tuning", level="INFO") as logs,
            mock.patch.object(
                redis.Redis,
                "from_url",
                side_effect=redis.exceptions.ConnectionError(self.unsafe_error),
            ),
        ):
            summary = tune_redis()

        self.assertEqual(summary["applied"], {})
        self.assertTrue(summary["errors"])
        self._assert_safe_error(
            summary,
            logs,
            "Redis administration maxmemory read",
            "ConnectionError",
        )

    def test_policy_read_error_is_safe(self):
        """A CONFIG read error must not expose Redis connection details."""
        client = fake_client()
        config_get = client.config_get.side_effect

        def fail_policy_read(name):
            if name == "maxmemory-policy":
                raise redis.exceptions.ResponseError(self.unsafe_error)
            return config_get(name)

        client.config_get.side_effect = fail_policy_read
        with self.assertLogs("app.redis_tuning", level="WARNING") as logs:
            summary = self._run(client)

        self._assert_safe_error(
            summary,
            logs,
            "Redis maxmemory-policy read",
            "ResponseError",
        )

    def test_policy_update_error_is_safe(self):
        """A CONFIG policy error must not expose Redis connection details."""
        client = fake_client()
        config_set = client.config_set.side_effect

        def fail_policy_update(name, value):
            if name == "maxmemory-policy":
                raise redis.exceptions.ResponseError(self.unsafe_error)
            return config_set(name, value)

        client.config_set.side_effect = fail_policy_update
        with self.assertLogs("app.redis_tuning", level="WARNING") as logs:
            summary = self._run(client)

        self._assert_safe_error(
            summary,
            logs,
            "Redis maxmemory-policy update",
            "ResponseError",
        )

    def test_persistence_update_error_is_safe(self):
        """A CONFIG persistence error must not expose Redis connection details."""
        client = fake_client({"appendonly": "yes", "appendfsync": "always"})
        config_set = client.config_set.side_effect

        def fail_persistence_update(name, value):
            if name == "appendfsync":
                raise redis.exceptions.ResponseError(self.unsafe_error)
            return config_set(name, value)

        client.config_set.side_effect = fail_persistence_update
        with self.assertLogs("app.redis_tuning", level="WARNING") as logs:
            summary = self._run(client)

        self._assert_safe_error(
            summary,
            logs,
            "Redis persistence update",
            "ResponseError",
        )

    @override_settings(REDIS_ADMIN_URL="redis://admin.example:6379/0")
    def test_uses_the_administration_url(self):
        """Redis CONFIG must use the administration target."""
        client = fake_client()
        with mock.patch.object(
            redis.Redis,
            "from_url",
            return_value=client,
        ) as from_url:
            tune_redis()

        from_url.assert_called_once_with("redis://admin.example:6379/0")

    def test_dry_run_changes_nothing(self):
        """--dry-run must report the plan without touching the server."""
        client = fake_client()
        summary = self._run(client, dry_run=True)

        self.assertEqual(summary["applied"]["maxmemory"], 256 * MIB)
        client.config_set.assert_not_called()

    def test_relaxes_appendfsync_always_only(self):
        """A disk sync per write buys nothing for a regenerable cache."""
        client = fake_client({"appendonly": "yes", "appendfsync": "always"})
        summary = self._run(client)

        self.assertEqual(summary["applied"]["appendfsync"], "everysec")
        self.assertEqual(client.values["appendfsync"], "everysec")

    def test_leaves_other_appendfsync_settings_alone(self):
        """Everysec is already right, and `no` is a deliberate choice."""
        for current in ("everysec", "no"):
            with self.subTest(appendfsync=current):
                client = fake_client(
                    {"appendonly": "yes", "appendfsync": current},
                )
                summary = self._run(client)
                self.assertNotIn("appendfsync", summary["applied"])
                self.assertEqual(client.values["appendfsync"], current)

    @override_settings(REDIS_ADMIN_URL="memory://")
    def test_non_redis_url_is_skipped(self):
        """Nothing to configure when the cache isn't Redis."""
        summary = tune_redis()
        self.assertEqual(summary["skipped"]["reason"], "not_a_redis_url")
