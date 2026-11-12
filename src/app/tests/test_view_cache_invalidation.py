"""Which per-user view caches each kind of change clears.

The media list, Home rows and TV time-left order are cleared only through
``cache_utils.clear_library_view_caches``. These tests pin, per change and per
write path, which of the three end up empty. Contract:
docs/architecture/view-caches.md.
"""

import datetime
import re
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from app import cache_utils
from app.models import (
    TV,
    CollectionEntry,
    Item,
    ItemTag,
    MediaTypes,
    Season,
    Sources,
    Status,
    Tag,
)
from users.models import HomeScreenRow

ALL = {"time_left", "media_list", "home"}
_REGISTER = {
    "time_left": cache_utils.register_time_left_cache_key,
    "media_list": cache_utils.register_media_list_cache_key,
    "home": cache_utils.register_home_row_cache_key,
}


def seed(user_id):
    """Put one registered entry in each of the user's three view caches."""
    for name, register in _REGISTER.items():
        key = f"probe_{name}_{user_id}"
        cache.set(key, 1, 600)
        register(user_id, key)


def cleared(user_id):
    """Return the names of the user's view caches whose entry is gone."""
    return {name for name in _REGISTER if cache.get(f"probe_{name}_{user_id}") is None}


def _episode_metadata(media_type, *_args, **_kwargs):
    episodes = [{"episode_number": 1, "name": "One", "still_path": None}]
    if media_type == "tv_with_seasons":
        return {"season/1": {"episodes": episodes}}
    return {"season_number": 1, "episodes": episodes, "_tvdb_episode_image_map": {}}


class ChangeTableTests(TestCase):
    """The shared function clears what each named change can affect."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username="views")

    def assert_clears(self, expected, change, **kwargs):
        seed(self.user.id)
        cache_utils.clear_library_view_caches(self.user.id, change, **kwargs)
        self.assertEqual(cleared(self.user.id), expected)

    def test_library_edit_of_non_tv_media_leaves_time_left(self):
        self.assert_clears(
            {"media_list", "home"},
            cache_utils.LIBRARY_EDIT,
            media_types=(MediaTypes.MOVIE.value,),
        )

    def test_library_edit_of_tv_media_clears_all_three(self):
        for media_type in ("tv", "season", "episode"):
            with self.subTest(media_type=media_type):
                self.assert_clears(
                    ALL, cache_utils.LIBRARY_EDIT, media_types=(media_type,)
                )

    def test_tags_clear_the_list_only_without_a_tag_filtered_home_row(self):
        HomeScreenRow.objects.create(user=self.user, media_type="movie", filters={})
        self.assert_clears({"media_list"}, cache_utils.TAGS)

    def test_tags_clear_home_when_a_home_row_filters_by_tag(self):
        HomeScreenRow.objects.create(
            user=self.user, media_type="movie", filters={"tag": ["Cozy"]}
        )
        self.assert_clears({"media_list", "home"}, cache_utils.TAGS)

    def test_disabled_tag_filtered_home_row_does_not_clear_home(self):
        HomeScreenRow.objects.create(
            user=self.user,
            media_type="movie",
            enabled=False,
            filters={"tag": ["Cozy"]},
        )
        self.assert_clears({"media_list"}, cache_utils.TAGS)

    def test_settings_clear_only_their_own_view(self):
        self.assert_clears({"media_list"}, cache_utils.LIST_SETTING)
        self.assert_clears({"home"}, cache_utils.HOME_SETTING)

    def test_episode_details_leave_home_to_its_ttl(self):
        self.assert_clears({"time_left", "media_list"}, cache_utils.EPISODE_DETAILS)

    def test_inside_a_transaction_it_clears_again_on_commit(self):
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            cache_utils.clear_library_view_caches(
                self.user.id, media_types=(MediaTypes.EPISODE.value,)
            )
        # A reader re-caches pre-write rows before the commit.
        seed(self.user.id)
        for callback in callbacks:
            callback()
        self.assertEqual(cleared(self.user.id), ALL)

    def test_no_user_is_a_no_op(self):
        cache_utils.clear_library_view_caches(None)


class WritePathTests(TestCase):
    """Each family of write paths clears the views it can make stale."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="paths", password="12345"
        )
        self.client.force_login(self.user)
        patcher = patch(
            "app.models.providers.services.get_media_metadata",
            side_effect=_episode_metadata,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _show(self):
        tv_item = Item.objects.create(
            media_id="77",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Show",
        )
        tv = TV.objects.create(item=tv_item, user=self.user, status=Status.IN_PROGRESS.value)
        season_item = Item.objects.create(
            media_id="77",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="Show",
        )
        season = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=tv,
            status=Status.IN_PROGRESS.value,
        )
        return tv, season

    def _movie_item(self):
        return Item.objects.create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Movie",
        )

    def test_collection_entry_clears_list_and_home(self):
        item = self._movie_item()
        seed(self.user.id)
        with self.captureOnCommitCallbacks(execute=True):
            CollectionEntry.objects.create(user=self.user, item=item)
        self.assertEqual(cleared(self.user.id), {"media_list", "home"})

    def test_tv_delete_clears_all_three(self):
        tv, _season = self._show()
        seed(self.user.id)
        with self.captureOnCommitCallbacks(execute=True):
            tv.delete()
        self.assertEqual(cleared(self.user.id), ALL)

    def test_episode_watch_clears_all_three(self):
        _tv, season = self._show()
        seed(self.user.id)
        with self.captureOnCommitCallbacks(execute=True):
            season.watch(1, datetime.datetime.now(datetime.UTC))
        self.assertEqual(cleared(self.user.id), ALL)

    def test_episode_runtime_update_clears_time_left_and_list(self):
        self._show()
        episode_item = Item.objects.create(
            media_id="77",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="Show",
        )
        seed(self.user.id)
        episode_item.runtime_minutes = 42
        episode_item.save(update_fields=["runtime_minutes"])
        self.assertEqual(cleared(self.user.id), {"time_left", "media_list"})

    def test_air_date_refresh_clears_every_tracker_list_and_time_left(self):
        self._show()
        seed(self.user.id)
        cache_utils.clear_show_view_caches(
            "77", Sources.TMDB.value, cache_utils.EPISODE_DETAILS
        )
        self.assertEqual(cleared(self.user.id), {"time_left", "media_list"})

    def test_tag_toggle_clears_the_list(self):
        item = self._movie_item()
        tag = Tag.objects.create(user=self.user, name="Cozy")
        seed(self.user.id)
        self.client.post(
            reverse("tag_item_toggle"), {"item_id": item.id, "tag_id": tag.id}
        )
        self.assertTrue(ItemTag.objects.filter(tag=tag, item=item).exists())
        self.assertEqual(cleared(self.user.id), {"media_list"})

    def test_tag_toggle_clears_a_tag_filtered_home_row(self):
        item = self._movie_item()
        tag = Tag.objects.create(user=self.user, name="Cozy")
        HomeScreenRow.objects.create(
            user=self.user, media_type="movie", filters={"tag": ["Cozy"]}
        )
        seed(self.user.id)
        self.client.post(
            reverse("tag_item_toggle"), {"item_id": item.id, "tag_id": tag.id}
        )
        self.assertEqual(cleared(self.user.id), {"media_list", "home"})

    def test_entry_grouping_setting_clears_the_list(self):
        seed(self.user.id)
        self.client.post(
            reverse("medialist_entry_grouping", args=[MediaTypes.MOVIE.value]),
            {"show_separate_entries": "true"},
        )
        self.assertEqual(cleared(self.user.id), {"media_list"})

    def test_enabled_media_types_setting_clears_home(self):
        seed(self.user.id)
        self.client.post(
            reverse("sidebar"), {"media_types_checkboxes": [MediaTypes.MOVIE.value]}
        )
        self.assertEqual(cleared(self.user.id), {"home"})


class DirectClearGuardTests(TestCase):
    """Only cache_utils may call the three specific clear functions."""

    def test_no_module_calls_a_specific_clear_function(self):
        src = Path(__file__).resolve().parents[2]
        pattern = re.compile(
            r"\bclear_(?:time_left|media_list|home_row)_cache_for_user\b"
            r"|\b_clear_media_runtime_caches\b"
        )
        offenders = []
        for path in src.rglob("*.py"):
            relative = path.relative_to(src).as_posix()
            if relative == "app/cache_utils.py" or "/tests/" in f"/{relative}":
                continue
            for number, line in enumerate(path.read_text().splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{relative}:{number}")
        self.assertEqual(
            offenders,
            [],
            "Call cache_utils.clear_library_view_caches(user_id, <change>) "
            "instead; see docs/architecture/view-caches.md.",
        )
