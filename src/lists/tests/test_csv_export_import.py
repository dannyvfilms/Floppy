import csv
from io import BytesIO, StringIO

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import Item, MediaTypes, Sources
from lists.models import CustomList, CustomListItem


class ListExportCsvViewTests(TestCase):
    """Tests for the list_export_csv view."""

    def setUp(self):
        """Create an owner, another user, and a private list with one item."""
        self.credentials = {"username": "owner", "password": "testpassword"}
        self.owner = get_user_model().objects.create_user(**self.credentials)
        self.other_user = get_user_model().objects.create_user(
            username="otheruser",
            password="testpassword",
        )

        self.item = Item.objects.create(
            media_id="238",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Test Movie",
        )
        self.private_list = CustomList.objects.create(
            name="Private List",
            owner=self.owner,
            visibility="private",
        )
        CustomListItem.objects.create(custom_list=self.private_list, item=self.item)

        self.public_list = CustomList.objects.create(
            name="Public List",
            owner=self.owner,
            visibility="public",
        )
        CustomListItem.objects.create(custom_list=self.public_list, item=self.item)

    def test_owner_can_export_private_list(self):
        """The owner can export their own private list."""
        self.client.login(**self.credentials)
        response = self.client.get(
            reverse("list_export_csv", args=[self.private_list.id]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        content = b"".join(response.streaming_content).decode("utf-8")
        rows = list(csv.DictReader(StringIO(content)))
        list_rows = [row for row in rows if row["row_type"] == "list"]
        self.assertEqual(len(list_rows), 1)
        self.assertEqual(list_rows[0]["list_name"], "Private List")

    def test_anonymous_user_cannot_export_private_list(self):
        """Anonymous visitors get a 404 for a private list."""
        response = self.client.get(
            reverse("list_export_csv", args=[self.private_list.id]),
        )
        self.assertEqual(response.status_code, 404)

    def test_other_user_cannot_export_private_list(self):
        """A non-owner, non-collaborator user gets a 404 for a private list."""
        self.client.login(username="otheruser", password="testpassword")
        response = self.client.get(
            reverse("list_export_csv", args=[self.private_list.id]),
        )
        self.assertEqual(response.status_code, 404)

    def test_anonymous_user_can_export_public_list(self):
        """Anonymous visitors can export a public list."""
        response = self.client.get(
            reverse("list_export_csv", args=[self.public_list.id]),
        )
        self.assertEqual(response.status_code, 200)
        content = b"".join(response.streaming_content).decode("utf-8")
        rows = list(csv.DictReader(StringIO(content)))
        list_rows = [row for row in rows if row["row_type"] == "list"]
        self.assertEqual(len(list_rows), 1)
        self.assertEqual(list_rows[0]["list_name"], "Public List")

    def test_unknown_list_returns_404(self):
        """A missing list reference returns a 404."""
        response = self.client.get(reverse("list_export_csv", args=[999999]))
        self.assertEqual(response.status_code, 404)


class ImportListCsvViewTests(TestCase):
    """Tests for the import_list_csv view."""

    def setUp(self):
        """Create a user."""
        self.credentials = {"username": "importer", "password": "testpassword"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    def _csv_bytes(self):
        content = (
            '"row_type","media_id","source","media_type","title","image",'
            '"season_number","episode_number","list_uid","list_name",'
            '"list_description","list_tags","list_visibility",'
            '"list_allow_recommendations","list_source","list_source_id",'
            '"list_item_date_added"\n'
            '"list","","","","","","","","1","Imported List","","[]","private",'
            '"false","local","",""\n'
            '"list_item","manualbook1","manual","book","Manual Book",'
            '"https://image.url","","","1","Imported List","","","","","","",""\n'
        )
        file = BytesIO(content.encode("utf-8"))
        file.name = "import.csv"
        return file

    def test_missing_file_shows_error(self):
        """Posting without a file redirects with an error message."""
        response = self.client.post(reverse("list_import_csv"), follow=True)
        self.assertRedirects(response, reverse("lists"))
        messages = list(response.context["messages"])
        self.assertTrue(any("Select a CSV file" in str(m) for m in messages))

    def test_csv_import_creates_list(self):
        """A valid CSV creates the list and its items (task runs eagerly in tests)."""
        response = self.client.post(
            reverse("list_import_csv"),
            {"csv_file": self._csv_bytes()},
            follow=True,
        )
        self.assertRedirects(response, reverse("lists"))
        custom_list = CustomList.objects.filter(
            owner=self.user,
            name="Imported List",
        ).first()
        self.assertIsNotNone(custom_list)
        item_count = CustomListItem.objects.filter(custom_list=custom_list).count()
        self.assertEqual(item_count, 1)
