from django.db.backends.signals import connection_created
from fakeredis import FakeConnection

from config.test_network import install_test_network_guard

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
