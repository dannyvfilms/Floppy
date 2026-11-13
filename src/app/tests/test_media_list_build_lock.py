import threading
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from app import cache_utils, media_list_views

KEY = "media_list_filters_lock_test"


class MediaListBuildLockTests(SimpleTestCase):
    def setUp(self):
        cache.delete_many([KEY, f"{KEY}_building"])
        self.addCleanup(cache.delete_many, [KEY, f"{KEY}_building"])

    def test_only_one_builder_and_follower_reads_result(self):
        self.assertTrue(cache_utils.acquire_media_list_build_lock(KEY))
        self.assertFalse(cache_utils.acquire_media_list_build_lock(KEY))

        threading.Timer(0.15, lambda: cache.set(KEY, "built", 60)).start()
        ready = cache_utils.wait_for_media_list_build(
            KEY, lambda: cache.get(KEY) is not None
        )
        self.assertTrue(ready)
        self.assertEqual(cache.get(KEY), "built")

    def test_released_lock_without_value_returns_to_builder(self):
        # A builder that died or errored: follower must not wait out the cap.
        cache_utils.acquire_media_list_build_lock(KEY)
        threading.Timer(
            0.1, cache_utils.release_media_list_build_lock, args=(KEY,)
        ).start()
        with mock.patch.object(cache_utils, "MEDIA_LIST_BUILD_WAIT", 3.0):
            ready = cache_utils.wait_for_media_list_build(
                KEY, lambda: cache.get(KEY) is not None
            )
        self.assertFalse(ready)

    def test_wait_is_bounded_when_lock_is_held_but_never_filled(self):
        cache_utils.acquire_media_list_build_lock(KEY)
        with mock.patch.object(cache_utils, "MEDIA_LIST_BUILD_WAIT", 0.2):
            ready = cache_utils.wait_for_media_list_build(
                KEY, lambda: cache.get(KEY) is not None
            )
        self.assertFalse(ready)

    def test_lock_has_a_ttl(self):
        cache_utils.acquire_media_list_build_lock(KEY)
        ttl = cache.ttl(f"{KEY}_building")
        self.assertTrue(0 < ttl <= cache_utils.MEDIA_LIST_BUILD_LOCK_TTL)


class MediaListFollowerTests(TestCase):
    """A request that finds a builder running reads its result, or builds."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="lockuser", password="test-only-pw"
        )
        self.client.force_login(self.user)
        self.url = reverse("medialist", args=["movie"])
        cache.clear()
        self.addCleanup(cache.clear)

    def _filter_key(self):
        registry = cache.make_key(cache_utils._media_list_registry_key(self.user.id))
        keys = [
            k.decode() for k in cache_utils._registry_client().smembers(registry)
        ]
        (key,) = [k for k in keys if "filter" in k]
        return key

    def _count_builds(self):
        real = media_list_views._build_media_list_tag_data
        builds = []

        def counting(*args, **kwargs):
            builds.append(1)
            return real(*args, **kwargs)

        return builds, mock.patch.object(
            media_list_views, "_build_media_list_tag_data", counting
        )

    def test_follower_uses_value_the_builder_publishes(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)
        key = self._filter_key()
        value = cache.get(key)
        self.assertIsNotNone(value)
        cache.delete(key)
        self.assertTrue(cache_utils.acquire_media_list_build_lock(key))

        def publish():
            cache.set(key, value, 60)
            cache_utils.release_media_list_build_lock(key)

        threading.Timer(0.2, publish).start()
        builds, patcher = self._count_builds()
        with patcher:
            self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(builds, [])

    def test_dead_builder_does_not_wedge_readers(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)
        key = self._filter_key()
        cache.delete(key)
        self.assertTrue(
            cache_utils.acquire_media_list_build_lock(key)
        )  # never released
        builds, patcher = self._count_builds()
        with (
            patcher,
            mock.patch.object(cache_utils, "MEDIA_LIST_BUILD_WAIT", 0.3),
        ):
            self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(builds, [1])
        self.assertIsNotNone(cache.get(key))
