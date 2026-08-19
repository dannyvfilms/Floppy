from fakeredis import FakeConnection

from .settings import *  # noqa: F403

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
