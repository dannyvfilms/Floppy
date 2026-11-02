"""Per-user cache registries are atomic sets and invalidate every key."""

import threading

from django.core.cache import cache
from django.test import TestCase

from app import cache_utils

FAMILIES = {
    "time_left": (
        cache_utils.register_time_left_cache_key,
        cache_utils.clear_time_left_cache_for_user,
        cache_utils._registry_key_for_user,
    ),
    "home_row": (
        cache_utils.register_home_row_cache_key,
        cache_utils.clear_home_row_cache_for_user,
        cache_utils._home_row_registry_key,
    ),
    "media_list": (
        cache_utils.register_media_list_cache_key,
        cache_utils.clear_media_list_cache_for_user,
        cache_utils._media_list_registry_key,
    ),
}


class CacheRegistryTests(TestCase):
    """Registration and invalidation for each registry family."""

    def setUp(self):
        cache.clear()

    def test_clear_deletes_every_key_and_only_that_user(self):
        for name, (register, clear, _) in FAMILIES.items():
            for user_id in (1, 2):
                for i in range(25):
                    key = f"{name}_{user_id}_{i}"
                    cache.set(key, i, 60)
                    register(user_id, key)
            clear(1)
            for i in range(25):
                self.assertIsNone(cache.get(f"{name}_1_{i}"), name)
                self.assertEqual(cache.get(f"{name}_2_{i}"), i, name)

    def test_register_is_idempotent_and_clear_is_repeatable(self):
        for name, (register, clear, _) in FAMILIES.items():
            cache.set(f"{name}_a", 1, 60)
            register(1, f"{name}_a")
            register(1, f"{name}_a")
            clear(1)
            clear(1)
            self.assertIsNone(cache.get(f"{name}_a"))

    def test_concurrent_registrations_are_not_lost(self):
        register, clear, _ = FAMILIES["media_list"]
        keys = [f"ml_{i}" for i in range(60)]
        for key in keys:
            cache.set(key, 1, 60)
        threads = [threading.Thread(target=register, args=(1, key)) for key in keys]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        clear(1)
        self.assertEqual([k for k in keys if cache.get(k) is not None], [])

    def test_legacy_pickled_list_registry_is_migrated(self):
        for name, (register, clear, registry_key) in FAMILIES.items():
            cache.set(f"{name}_old", 1, 60)
            cache.set(f"{name}_new", 1, 60)
            cache.set(registry_key(1), [f"{name}_old"], 60)
            register(1, f"{name}_new")
            clear(1)
            self.assertIsNone(cache.get(f"{name}_old"), name)
            self.assertIsNone(cache.get(f"{name}_new"), name)

    def test_legacy_pickled_list_registry_is_cleared(self):
        for name, (_, clear, registry_key) in FAMILIES.items():
            cache.set(f"{name}_old", 1, 60)
            cache.set(registry_key(1), [f"{name}_old"], 60)
            clear(1)
            self.assertIsNone(cache.get(f"{name}_old"), name)
            self.assertIsNone(cache.get(registry_key(1)), name)
