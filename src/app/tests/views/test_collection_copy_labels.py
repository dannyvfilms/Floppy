"""Collection page: a copy says which volume or issue it is (#809).

A manga series imported from CLZ is one item whose copies differ only by the
number stored in a custom field, so the page must show it.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.collection_views import _copy_labels
from app.models import (
    CollectionEntry,
    CollectionField,
    CollectionFieldGroup,
    CollectionFieldType,
    Item,
    MediaTypes,
    Sources,
)


class CollectionCopyLabelTest(TestCase):
    """Volume and issue numbers label copies; other fields do not."""

    def setUp(self):
        """Create a series with numbered copies."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)
        group = CollectionFieldGroup.objects.create(user=self.user, name="Imported")
        self.volume = CollectionField.objects.create(
            group=group,
            label="Volume",
            field_type=CollectionFieldType.NUMBER,
            media_types=[MediaTypes.MANGA.value],
        )
        self.issue = CollectionField.objects.create(
            group=group,
            label="Issue Nr",
            field_type=CollectionFieldType.TEXT,
            media_types=[MediaTypes.COMIC_ISSUE.value],
        )
        self.notes = CollectionField.objects.create(
            group=group,
            label="Notes",
            field_type=CollectionFieldType.TEXT,
            media_types=[MediaTypes.MANGA.value],
        )
        self.item = Item.objects.create(
            media_id="m1",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.MANGA.value,
            library_media_type=MediaTypes.MANGA.value,
            title="Test Series",
            image="",
        )

    def entry(self, values):
        """Create a copy of the series carrying *values*."""
        return CollectionEntry.objects.create(
            user=self.user,
            item=self.item,
            custom_field_values=values,
        )

    def test_volume_and_issue_numbers_label_a_copy(self):
        """A number reads as Vol. 3 or #007, keeping leading zeros."""
        volume = self.entry({str(self.volume.id): 3.0})
        issue = self.entry({str(self.issue.id): "007"})

        labels = _copy_labels(self.user, [volume, issue])

        self.assertEqual(labels, {volume.id: "Vol. 3", issue.id: "#007"})

    def test_copy_without_a_number_has_no_label(self):
        """Other fields never label a copy, and a missing number leaves it blank."""
        plain = self.entry({str(self.notes.id): "Signed"})
        empty = self.entry({str(self.volume.id): ""})

        self.assertEqual(_copy_labels(self.user, [plain, empty]), {})

    def test_another_users_fields_do_not_label_my_copies(self):
        """Labels come from the viewer's own fields only."""
        other = get_user_model().objects.create_user(username="other")
        other_group = CollectionFieldGroup.objects.create(user=other, name="Theirs")
        theirs = CollectionField.objects.create(
            group=other_group,
            label="Volume",
            field_type=CollectionFieldType.NUMBER,
            media_types=[MediaTypes.MANGA.value],
        )
        mine = self.entry({str(theirs.id): 5.0})

        self.assertEqual(_copy_labels(self.user, [mine]), {})

    def test_collection_page_shows_the_volume(self):
        """The Collection page renders each copy's volume."""
        self.entry({str(self.volume.id): 3.0})

        response = self.client.get(reverse("collection_list"))

        self.assertContains(response, "Vol. 3")
