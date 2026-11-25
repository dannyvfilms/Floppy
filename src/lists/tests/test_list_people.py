from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import Person, Sources
from lists.models import CustomList, CustomListPerson


class ListPeopleTests(TestCase):
    """Saving a person on a custom list from the person page."""

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="owner", password="x")
        self.other = user_model.objects.create_user(username="other", password="x")
        self.client.login(username="owner", password="x")
        self.person = Person.objects.create(
            source=Sources.TMDB.value,
            source_person_id="287",
            name="Brad Pitt",
            known_for_department="Acting",
        )
        self.custom_list = CustomList.objects.create(name="Favourite actors", owner=self.user)

    def _toggle(self, list_id=None):
        return self.client.post(
            reverse("person_list_toggle"),
            {"custom_list_id": list_id or self.custom_list.id, "item_id": self.person.id},
        )

    def test_modal_reports_membership(self):
        url = reverse("person_lists_modal", args=[Sources.TMDB.value, "287"])
        data = self.client.get(url, {"format": "json"}).json()
        self.assertEqual(data["itemId"], self.person.id)
        self.assertFalse(data["lists"][0]["hasItem"])
        self._toggle()
        data = self.client.get(url).json()
        self.assertTrue(data["lists"][0]["hasItem"])

    def test_toggle_adds_then_removes(self):
        self.assertEqual(self._toggle().json(), {"success": True, "hasItem": True})
        self.assertEqual(CustomListPerson.objects.filter(custom_list=self.custom_list).count(), 1)
        self.assertEqual(self._toggle().json(), {"success": True, "hasItem": False})
        self.assertFalse(CustomListPerson.objects.exists())

    def test_viewer_cannot_edit(self):
        foreign = CustomList.objects.create(name="Theirs", owner=self.other)
        self.assertIn(self._toggle(foreign.id).status_code, (403, 404))
        self.assertFalse(CustomListPerson.objects.exists())

    def test_list_page_shows_people_and_remove_button(self):
        self._toggle()
        response = self.client.get(reverse("list_detail", args=[self.custom_list.id]))
        self.assertContains(response, "Brad Pitt")
        self.assertContains(response, "data-list-person")
        # The shared ListPeople island reads these props; the markup above is its fallback.
        self.assertContains(response, 'id="list-people-props"')
        # People come off a list from the person page, like media; no chip here.
        self.assertNotContains(response, "Remove")


class ListPeopleApiTests(TestCase):
    """The REST endpoints the native app uses for people on lists."""

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="owner", password="x")
        self.other = user_model.objects.create_user(username="other", password="x")
        self.client.force_login(self.user)
        self.person = Person.objects.create(
            source=Sources.TMDB.value, source_person_id="287", name="Brad Pitt",
        )
        self.custom_list = CustomList.objects.create(name="Actors", owner=self.user)
        self.base = "/api/v1/people/tmdb/287/lists/"

    def test_put_get_delete_roundtrip(self):
        self.assertEqual(self.client.put(f"{self.base}{self.custom_list.id}/").status_code, 204)
        results = self.client.get(self.base).json()["results"]
        self.assertEqual(results, [{"list_id": self.custom_list.id}])
        detail = self.client.get(f"/api/v1/lists/{self.custom_list.id}/").json()
        self.assertEqual(detail["people"][0]["name"], "Brad Pitt")
        self.assertEqual(detail["people"][0]["person_id"], "287")
        self.assertEqual(self.client.delete(f"{self.base}{self.custom_list.id}/").status_code, 204)
        self.assertEqual(self.client.get(self.base).json()["results"], [])

    def test_cannot_edit_someone_elses_list(self):
        foreign = CustomList.objects.create(name="Theirs", owner=self.other)
        self.assertIn(self.client.put(f"{self.base}{foreign.id}/").status_code, (403, 404))
        self.assertFalse(CustomListPerson.objects.exists())

    def test_unknown_person_is_404(self):
        response = self.client.put(f"/api/v1/people/tmdb/999/lists/{self.custom_list.id}/")
        self.assertEqual(response.status_code, 404)
