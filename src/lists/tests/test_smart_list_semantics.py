"""Smart lists keep the evaluation semantics they were saved under."""

from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from app.models import Item, MediaTypes, Movie, Sources, Status
from lists import smart_rules
from lists.forms import CustomListForm
from lists.models import CustomList


class SmartListSemanticsTests(TestCase):
    """New lists use the current semantics; saved lists never change theirs."""

    def setUp(self):
        """Create a user with one movie completed, then re-watched and dropped."""
        self.user = get_user_model().objects.create_user(username="sem", password="x")
        self.user.movie_enabled = True
        self.user.save()
        self.item = Item.objects.create(
            media_id="1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Rewatched",
            image="https://example.com/i.jpg",
        )
        now = timezone.now()
        Movie.objects.bulk_create(
            [
                Movie(
                    item=self.item,
                    user=self.user,
                    status=Status.COMPLETED.value,
                    end_date=now - timedelta(days=30),
                ),
                Movie(
                    item=self.item,
                    user=self.user,
                    status=Status.DROPPED.value,
                    end_date=now,
                ),
            ],
        )

    def completed_rules(self, **extra):
        """Return normalized "completed movies" rules."""
        return smart_rules.normalize_rule_payload(
            {"media_types": [MediaTypes.MOVIE.value], "status": ["Completed"], **extra},
            self.user,
        )

    def test_saved_rules_match_any_row(self):
        """A list saved before the engine still matches the older completed row."""
        self.assertEqual(
            smart_rules.collect_matching_item_ids(self.user, self.completed_rules()),
            {self.item.pk},
        )

    def test_current_rules_follow_the_latest_row(self):
        """A new list reads the item's current status, as the media list does."""
        self.assertEqual(
            smart_rules.collect_matching_item_ids(
                self.user,
                self.completed_rules(semantics_version="2"),
            ),
            set(),
        )

    def test_a_new_smart_list_starts_on_current_semantics(self):
        """Creating a smart list stamps the current version."""
        form = CustomListForm(data={"name": "New", "is_smart": True})
        self.assertTrue(form.is_valid(), form.errors)
        form.instance.owner = self.user
        custom_list = form.save()
        self.assertEqual(custom_list.smart_filters.get("semantics_version"), "2")

    def test_editing_rules_keeps_the_saved_version(self):
        """Saving new rules on an old list does not change how it evaluates."""
        custom_list = CustomList.objects.create(
            name="Old",
            owner=self.user,
            is_smart=True,
            smart_media_types=[MediaTypes.MOVIE.value],
            smart_filters={},
        )
        self.client.force_login(self.user)
        with mock.patch("lists.models.CustomList.sync_smart_items"):
            response = self.client.post(
                reverse("list_smart_rules_update", args=[custom_list.id]),
                {"media_types": [MediaTypes.MOVIE.value], "status": ["Completed"]},
            )
        self.assertEqual(response.status_code, 200)
        custom_list.refresh_from_db()
        self.assertEqual(custom_list.smart_filters.get("semantics_version"), "")
        self.assertEqual(custom_list.smart_filters.get("status"), ["Completed"])
