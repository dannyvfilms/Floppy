from unittest import TestCase
from unittest.mock import patch
from importlib import reload
from django.conf import settings
import sys

class RedisUrlsTest(TestCase):
    """Test that Redis endpoints can be independently configured."""

    def test_independent_redis_urls(self):
        env = {
            "REDIS_URL": "redis://default:6379",
            "REDIS_CACHE_URL": "redis://cache:6379",
            "CELERY_BROKER_URL": "redis://broker:6379",
            "CELERY_RESULT_BACKEND": "redis://results:6379",
            "REDIS_ADMIN_URL": "redis://admin:6379",
        }
        
        with patch.dict("os.environ", env):
            from decouple import Config, RepositoryEnv
            
            # Since decouple's config function caches os.environ locally,
            # we must reload it to reflect our patch.
            import decouple
            reload(decouple)
            
            # Now we must reload settings to re-evaluate config()
            import config.settings
            reload(config.settings)
            
            self.assertEqual(config.settings.REDIS_URL, "redis://default:6379")
            self.assertEqual(config.settings.REDIS_CACHE_URL, "redis://cache:6379")
            self.assertEqual(config.settings.CELERY_BROKER_URL, "redis://broker:6379")
            self.assertEqual(config.settings.CELERY_RESULT_BACKEND, "redis://results:6379")
            self.assertEqual(config.settings.REDIS_ADMIN_URL, "redis://admin:6379")
            
            self.assertEqual(
                config.settings.CACHES["default"]["LOCATION"],
                "redis://cache:6379"
            )
