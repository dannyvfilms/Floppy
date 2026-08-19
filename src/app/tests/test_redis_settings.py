"""Tests for Redis role configuration (issue #596)."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings


class RedisSettingsTests(SimpleTestCase):
    """Read production settings in an isolated process."""

    settings_script = """
import json
from config import settings

print(json.dumps({
    "redis": settings.REDIS_URL,
    "cache": settings.CACHES["default"]["LOCATION"],
    "broker": settings.CELERY_BROKER_URL,
    "result": settings.CELERY_RESULT_BACKEND,
    "admin": settings.REDIS_ADMIN_URL,
}))
"""

    def _read_settings(self, **overrides):
        root = Path(__file__).resolve().parents[3]
        env = os.environ.copy()
        for name in (
            "REDIS_URL",
            "REDIS_CACHE_URL",
            "CELERY_BROKER_URL",
            "CELERY_RESULT_BACKEND",
            "REDIS_ADMIN_URL",
        ):
            env.pop(name, None)
        env.update(
            {
                "SECRET": "redis-settings-test-secret",
                "PYTHONPATH": str(root / "src"),
                **overrides,
            },
        )
        completed = subprocess.run(  # noqa: S603 - fixed interpreter and script
            [sys.executable, "-c", self.settings_script],
            cwd=root,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    def test_redis_url_remains_the_compatibility_fallback(self):
        """One REDIS_URL must keep the current deployment behavior."""
        values = self._read_settings(REDIS_URL="redis://compatibility:6379/0")

        self.assertEqual(set(values.values()), {"redis://compatibility:6379/0"})

    def test_each_redis_role_accepts_a_separate_url(self):
        """Each consumer must use its selected Redis service."""
        values = self._read_settings(
            REDIS_URL="redis://limiter:6379/0",
            REDIS_CACHE_URL="redis://cache:6379/1",
            CELERY_BROKER_URL="redis://broker:6379/2",
            CELERY_RESULT_BACKEND="redis://results:6379/3",
            REDIS_ADMIN_URL="redis://admin:6379/4",
        )

        self.assertEqual(
            values,
            {
                "redis": "redis://limiter:6379/0",
                "cache": "redis://cache:6379/1",
                "broker": "redis://broker:6379/2",
                "result": "redis://results:6379/3",
                "admin": "redis://admin:6379/4",
            },
        )

    def test_empty_overrides_use_the_documented_fallbacks(self):
        """An empty role setting must not disable its compatibility fallback."""
        values = self._read_settings(
            REDIS_URL="redis://compatibility:6379/0",
            REDIS_CACHE_URL="",
            CELERY_BROKER_URL="",
            CELERY_RESULT_BACKEND="",
            REDIS_ADMIN_URL="",
        )

        self.assertEqual(set(values.values()), {"redis://compatibility:6379/0"})

    def test_admin_defaults_to_the_cache_url(self):
        """Automatic Redis tuning must normally target the cache server."""
        values = self._read_settings(
            REDIS_URL="redis://compatibility:6379/0",
            REDIS_CACHE_URL="redis://cache:6379/1",
        )

        self.assertEqual(values["admin"], "redis://cache:6379/1")


class ProviderLimiterRedisSettingsTests(SimpleTestCase):
    """Keep provider rate limiting on the compatibility Redis URL."""

    @override_settings(
        TESTING=False,
        REDIS_URL="redis://limiter:6379/0",
        REDIS_CACHE_URL="redis://cache:6379/1",
    )
    @patch("app.providers.services.ConnectionPool.from_url")
    def test_provider_limiter_keeps_using_redis_url(self, mock_from_url):
        """Issue #596 must not change the provider limiter target."""
        from app.providers.services import get_redis_pool

        get_redis_pool()

        mock_from_url.assert_called_once_with(
            "redis://limiter:6379/0",
            max_connections=8,
        )
