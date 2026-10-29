"""Users can delete their own account from Settings > Account."""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django_celery_beat.models import IntervalSchedule, PeriodicTask

from app.models import (
    TV,
    DeletedMedia,
    Episode,
    Item,
    MediaTypes,
    Movie,
    Season,
    Sources,
    Status,
)
from lists.models import CustomList

User = get_user_model()


class DeleteAccountTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user(username="leaver", password="pw-12345")
        self.other = User.objects.create_user(username="stayer", password="pw-12345")
        self.url = reverse("account")

    def _post(self, **extra):
        data = {
            "action": "delete_account",
            "current_password": "pw-12345",
            "confirm_delete": "on",
        }
        data.update(extra)
        return self.client.post(self.url, data)

    def test_deletes_own_account_and_signs_out(self):
        self.client.force_login(self.user)

        response = self._post()

        self.assertRedirects(response, reverse("account_login"), fetch_redirect_response=False)
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.other.pk).exists())
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_wrong_password_keeps_account(self):
        self.client.force_login(self.user)

        response = self._post(current_password="nope")

        self.assertRedirects(response, self.url)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_requires_checkbox(self):
        self.client.force_login(self.user)
        data = {"action": "delete_account", "current_password": "pw-12345"}

        self.client.post(self.url, data)

        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_other_users_data_is_untouched(self):
        item = Item.objects.create(
            media_id="1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Shared",
        )
        mine = CustomList.objects.create(name="Mine", owner=self.user)
        theirs = CustomList.objects.create(name="Theirs", owner=self.other)
        self.client.force_login(self.user)

        self._post()

        self.assertFalse(CustomList.objects.filter(pk=mine.pk).exists())
        self.assertTrue(CustomList.objects.filter(pk=theirs.pk).exists())
        self.assertTrue(Item.objects.filter(pk=item.pk).exists())

    def test_deletes_account_with_tracked_media(self):
        item = Item.objects.create(
            media_id="2",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Tracked",
        )
        Movie.objects.create(item=item, user=self.user, status=Status.COMPLETED.value)
        Movie.objects.create(item=item, user=self.other, status=Status.COMPLETED.value)
        self.client.force_login(self.user)

        self._post()

        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.assertFalse(Movie.objects.filter(item=item, user_id=self.user.pk).exists())
        self.assertTrue(Movie.objects.filter(item=item, user=self.other).exists())
        self.assertFalse(DeletedMedia.objects.exists())

    def test_deletes_account_with_tracked_show_and_episodes(self):
        tv_item = Item.objects.create(
            media_id="3",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Show",
        )
        season_item = Item.objects.create(
            media_id="3",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Show",
            season_number=1,
        )
        episode_item = Item.objects.create(
            media_id="3",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Pilot",
            season_number=1,
            episode_number=1,
        )
        tv = TV.objects.create(item=tv_item, user=self.user)
        season = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=tv,
            status=Status.COMPLETED.value,
        )
        Episode.objects.create(
            item=episode_item, related_season=season, end_date=timezone.now()
        )
        self.client.force_login(self.user)

        self._post()

        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.assertFalse(Episode.objects.filter(item=episode_item).exists())
        self.assertFalse(DeletedMedia.objects.exists())

    def test_removes_only_own_scheduled_tasks(self):
        schedule = IntervalSchedule.objects.create(
            every=1, period=IntervalSchedule.DAYS
        )
        uid = self.user.pk
        PeriodicTask.objects.create(
            name="mine", task="t", interval=schedule, kwargs=f'{{"user_id": {uid}}}'
        )
        PeriodicTask.objects.create(
            name="prefix-match",
            task="t",
            interval=schedule,
            kwargs=f'{{"user_id": {uid}0}}',
        )
        self.client.force_login(self.user)

        self._post()

        self.assertFalse(PeriodicTask.objects.filter(name="mine").exists())
        self.assertTrue(PeriodicTask.objects.filter(name="prefix-match").exists())

    def test_passwordless_account_confirms_with_username(self):
        self.user.set_unusable_password()
        self.user.save()
        self.client.force_login(self.user)

        self._post(confirm_username="wrong")
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

        self._post(confirm_username="leaver")
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())

    def test_demo_account_cannot_be_deleted(self):
        demo = User.objects.create_user(username="demo", password="demodemo", is_demo=True)
        self.client.force_login(demo)

        self._post(current_password="demodemo")

        self.assertTrue(User.objects.filter(pk=demo.pk).exists())

    def test_last_superuser_cannot_delete_self(self):
        boss = User.objects.create_superuser(username="boss", password="pw-12345")
        self.client.force_login(boss)

        self._post()

        self.assertTrue(User.objects.filter(pk=boss.pk).exists())
        self.assertContains(self.client.get(self.url), "only superuser")

    def test_superuser_can_delete_self_when_another_exists(self):
        boss = User.objects.create_superuser(username="boss", password="pw-12345")
        User.objects.create_superuser(username="boss2", password="pw-12345")
        self.client.force_login(boss)

        self._post()

        self.assertFalse(User.objects.filter(pk=boss.pk).exists())

    def test_anonymous_cannot_delete(self):
        response = self._post()

        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.other.pk).exists())
