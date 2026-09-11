"""Scoped list-write bindings for external tokens."""

from http import HTTPStatus as HTTP  # noqa: N814

from integrations.models import IntegrationToken
from lists.models import CustomList

from .base import FloppyApiTestCase


class ListWriteBindingTests(FloppyApiTestCase):
    """A bound token writes only the lists it names."""

    def setUp(self):
        """Create two lists and a token bound to one of them."""
        super().setUp()
        self.bound_list = CustomList.objects.create(
            owner=self.user1,
            name="Shared",
        )
        self.other_list = CustomList.objects.create(
            owner=self.user1,
            name="Private",
        )
        self.smart_list = CustomList.objects.create(
            owner=self.user1,
            name="Computed",
            is_smart=True,
        )

    def token_for(self, writable_list_ids):
        """Mint a lists:write token with the given binding."""
        token, secret = IntegrationToken.generate(
            user=self.user1,
            name="list client",
            scopes=["lists:read", "lists:write"],
        )
        token.writable_list_ids = writable_list_ids
        token.save(update_fields=["writable_list_ids"])
        return {"HTTP_X_API_KEY": secret}

    def rename(self, list_id, headers):
        """Attempt to rename a list."""
        return self.client.patch(
            f"/api/v1/lists/{list_id}/",
            {"name": "Renamed"},
            format="json",
            **headers,
        )

    def test_an_unbound_token_may_write_any_owned_list(self):
        """An empty allowlist keeps the behaviour lists:write already had."""
        headers = self.token_for([])

        response = self.rename(self.other_list.id, headers)

        self.assertNotEqual(response.status_code, HTTP.FORBIDDEN)

    def test_a_bound_token_may_write_its_list(self):
        """The list it was given still works."""
        headers = self.token_for([self.bound_list.id])

        response = self.rename(self.bound_list.id, headers)

        self.assertNotEqual(response.status_code, HTTP.FORBIDDEN)

    def test_a_bound_token_may_not_write_another_list(self):
        """Binding to one list must not leave the rest reachable by id."""
        headers = self.token_for([self.bound_list.id])

        response = self.rename(self.other_list.id, headers)

        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_a_bound_token_may_still_read(self):
        """A write binding restricts writes, not reads."""
        headers = self.token_for([self.bound_list.id])

        response = self.client.get(
            f"/api/v1/lists/{self.other_list.id}/",
            **headers,
        )

        self.assertNotEqual(response.status_code, HTTP.FORBIDDEN)

    def test_no_external_token_may_write_a_smart_list(self):
        """A computed list's contents come from its rules."""
        headers = self.token_for([self.smart_list.id])

        response = self.rename(self.smart_list.id, headers)

        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_a_smart_list_is_read_only_even_when_unbound(self):
        """The rule is about the list, not about the binding."""
        headers = self.token_for([])

        response = self.rename(self.smart_list.id, headers)

        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_the_session_user_is_unaffected(self):
        """Bindings constrain external tokens, not the person using the app."""
        response = self.rename(self.smart_list.id, self.auth_headers)

        self.assertNotEqual(response.status_code, HTTP.FORBIDDEN)

    def test_string_and_integer_ids_both_match(self):
        """A binding stored from JSON must not fail on type alone."""
        headers = self.token_for([str(self.bound_list.id)])

        response = self.rename(self.bound_list.id, headers)

        self.assertNotEqual(response.status_code, HTTP.FORBIDDEN)

    def test_list_items_are_covered_by_the_same_binding(self):
        """Membership is a write, and goes through the same check."""
        headers = self.token_for([self.bound_list.id])

        response = self.client.post(
            f"/api/v1/lists/{self.other_list.id}/items/reorder/",
            {"order": []},
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, HTTP.FORBIDDEN)
