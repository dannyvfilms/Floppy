from django.db.backends.signals import connection_created
from fakeredis import FakeConnection

from config.test_network import install_test_network_guard, test_network_enabled

from .settings import *  # noqa: F403

# Django's default SQLite test database is a shared in-memory URI. It cannot use
# a persistent WAL/DELETE journal, and the production connection hook is for
# durable database files. The SQLite safety helper has dedicated coverage for
# both memory and persistent names, so do not emit a corruption-grade mismatch
# for the expected MEMORY test journal.
if USING_SQLITE_DATABASE:  # noqa: F405
    connection_created.disconnect(configure_sqlite_connection)  # noqa: F405

# Ordinary tests must be deterministic and offline. An explicit network-tag run
# opts out through FLOPPY_TEST_ALLOW_NETWORK before this settings module loads.
install_test_network_guard()

# AniBridge is a runtime data source, not part of an ordinary test's contract.
# Use a minimal deterministic snapshot for the mapping cases exercised by the
# offline suite. Explicit network-tag runs leave this unset and verify the real
# download path instead.
ANIBRIDGE_MAPPING_DATA_OVERRIDE = None
if not test_network_enabled():
    ANIBRIDGE_MAPPING_DATA_OVERRIDE = {
        "tvdb_show:74796:s2": {"mal:269": {"1-20": "21-40"}},
        "tvdb_show:74796:s17": {"mal:53998": {"14-": "1-"}},
        "anidb:3651:R": {"mal:849": {}},
    }

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_CACHE_URL,  # noqa: F405
        "TIMEOUT": 18000,  # 5 hours
        "OPTIONS": {
            "CONNECTION_POOL_KWARGS": {"connection_class": FakeConnection},
        },
    },
}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_RESULT_BACKEND = "cache+memory://"
CELERY_TASK_STORE_EAGER_RESULT = True

TESTING = True

# Keep test output bounded: the console handler writes to the real stderr,
# bypassing unittest --buffer, so INFO logs flood parallel test runs.
LOGGING["handlers"]["console"]["level"] = "WARNING"  # noqa: F405
LOGGING["root"]["level"] = "WARNING"  # noqa: F405

# Steam API key for testing
STEAM_API_KEY = "test_steam_api_key"

# Trakt API key for testing (production default is empty; see #464)
TRAKT_API = "test_trakt_api_key"
