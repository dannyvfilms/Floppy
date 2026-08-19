# FORK: tests for the advanced list API endpoints — smart rules,
# collaborators, reorder, recommendations, and activity.
from http import HTTPStatus as HTTP  # noqa: N814

from app.models import MediaTypes
from lists.models import (
    CustomList,
    CustomListItem,
    ListActivity,
    ListRecommendation,
)

from .base import FloppyApiTestCase


class SmartRulesTests(FloppyApiTestCase):
    """GET/PUT smart-rules and POST smart-sync."""

    def setUp(self):
        """Create a smart list matching the user's movies."""
        super().setUp()
        self.smart_list = CustomList.objects.create(
            name="Smart Movies",
            owner=self.user1,
            is_smart=True,
            smart_media_types=[MediaTypes.MOVIE.value],
        )

    def test_get_rules(self):
        """The smart configuration is returned."""
        response = self.call_api(
            "get",
            "api_list_smart_rules",
            args=(self.smart_list.id,),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertTrue(response.json()["is_smart"])

    def test_put_rules_syncs_membership(self):
        """PUT normalizes rules and syncs items into the list."""
        response = self.call_api(
            "put",
            "api_list_smart_rules",
            args=(self.smart_list.id,),
            payload={"media_types": [MediaTypes.MOVIE.value]},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        # The base fixtures track three movies for user1.
        self.assertEqual(response.json()["items_count"], 3)

    def test_put_on_regular_list_rejected(self):
        """PUT smart-rules on a non-smart list returns 400."""
        regular = self.lists_by_name["favorites"]
        response = self.call_api(
            "put",
            "api_list_smart_rules",
            args=(regular.id,),
            payload={"media_types": []},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_smart_sync(self):
        """POST smart-sync repopulates membership."""
        response = self.call_api(
            "post",
            "api_list_smart_sync",
            args=(self.smart_list.id,),
            payload={},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["items_count"], 3)

    def test_other_users_list_not_found(self):
        """Another user's private list 404s."""
        response = self.call_api(
            "get",
            "api_list_smart_rules",
            args=(self.lists_by_name["user2_private"].id,),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)


class CollaboratorTests(FloppyApiTestCase):
    """GET/PUT collaborators."""

    def test_get_collaborators(self):
        """The shared fixture list reports its collaborator."""
        response = self.call_api(
            "get",
            "api_list_collaborators",
            args=(self.lists_by_name["shared"].id,),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        payload = response.json()
        self.assertEqual(payload["owner"], self.user1.username)
        self.assertIn(self.user2.username, payload["collaborators"])

    def test_put_replaces_collaborators(self):
        """PUT sets the collaborator list and logs activity."""
        favorites = self.lists_by_name["favorites"]
        response = self.call_api(
            "put",
            "api_list_collaborators",
            args=(favorites.id,),
            payload={"usernames": [self.user2.username]},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["collaborators"], [self.user2.username])
        self.assertTrue(
            ListActivity.objects.filter(
                custom_list=favorites,
                activity_type="collaborator_added",
            ).exists(),
        )

        cleared = self.call_api(
            "put",
            "api_list_collaborators",
            args=(favorites.id,),
            payload={"usernames": []},
            headers=self.auth_headers,
        )
        self.assertEqual(cleared.json()["collaborators"], [])

    def test_unknown_username_rejected(self):
        """Unknown usernames return 404 with the missing names."""
        response = self.call_api(
            "put",
            "api_list_collaborators",
            args=(self.lists_by_name["favorites"].id,),
            payload={"usernames": ["nobody-here"]},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
        self.assertEqual(response.json()["missing"], ["nobody-here"])


class ReorderTests(FloppyApiTestCase):
    """Reorder endpoints."""

    def _ordered_item_ids(self, custom_list):
        return [
            entry.item_id
            for entry in CustomListItem.objects.filter(
                custom_list=custom_list,
            ).order_by("date_added", "id")
        ]

    def test_reorder_action_moves_item(self):
        """POST reorder moves an item to the front."""
        favorites = self.lists_by_name["favorites"]
        original = self._ordered_item_ids(favorites)
        if len(original) < 2:
            self.skipTest("Fixture list has fewer than two items")
        response = self.call_api(
            "post",
            "api_list_items_reorder",
            args=(favorites.id,),
            payload={"item_id": original[-1], "action": "first"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NO_CONTENT)
        reordered = self._ordered_item_ids(favorites)
        self.assertEqual(reordered[0], original[-1])

    def test_full_order_replacement(self):
        """PUT order applies a full custom order."""
        favorites = self.lists_by_name["favorites"]
        original = self._ordered_item_ids(favorites)
        if len(original) < 2:
            self.skipTest("Fixture list has fewer than two items")
        desired = list(reversed(original))
        response = self.call_api(
            "put",
            "api_list_items_order",
            args=(favorites.id,),
            payload={"item_ids": desired},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NO_CONTENT)
        self.assertEqual(self._ordered_item_ids(favorites), desired)


class RecommendationTests(FloppyApiTestCase):
    """Recommendation submit/list/approve/deny and activity."""

    def setUp(self):
        """Make the favorites list public with recommendations enabled."""
        super().setUp()
        self.rec_list = self.lists_by_name["favorites"]
        self.rec_list.visibility = "public"
        self.rec_list.allow_recommendations = True
        self.rec_list.save(update_fields=["visibility", "allow_recommendations"])
        self.candidate = self.items_by_type[MediaTypes.MOVIE.value][2]
        CustomListItem.objects.filter(
            custom_list=self.rec_list,
            item=self.candidate,
        ).delete()

    def _submit(self, headers=None):
        return self.call_api(
            "post",
            "api_list_recommendations",
            args=(self.rec_list.id,),
            payload={
                "media_id": self.candidate.media_id,
                "media_type": self.candidate.media_type,
                "source": self.candidate.source,
                "note": "you would like this",
            },
            headers=headers or self.auth_headers2,
        )

    def test_submit_list_and_approve(self):
        """A recommendation can be submitted, listed, and approved."""
        submitted = self._submit()
        self.assertEqual(submitted.status_code, HTTP.CREATED)
        rec_id = submitted.json()["id"]

        listed = self.call_api(
            "get",
            "api_list_recommendations",
            args=(self.rec_list.id,),
            headers=self.auth_headers,
        )
        self.assertEqual(listed.status_code, HTTP.OK)
        self.assertEqual(len(listed.json()["results"]), 1)

        approved = self.call_api(
            "post",
            "api_list_recommendation_decision",
            args=(self.rec_list.id, rec_id, "approve"),
            payload={},
            headers=self.auth_headers,
        )
        self.assertEqual(approved.status_code, HTTP.OK)
        self.assertTrue(approved.json()["added"])
        self.assertTrue(
            self.rec_list.items.filter(id=self.candidate.id).exists(),
        )
        self.assertFalse(ListRecommendation.objects.filter(id=rec_id).exists())

    def test_deny_removes_recommendation(self):
        """Denying deletes the recommendation without adding the item."""
        rec_id = self._submit().json()["id"]
        denied = self.call_api(
            "post",
            "api_list_recommendation_decision",
            args=(self.rec_list.id, rec_id, "deny"),
            payload={},
            headers=self.auth_headers,
        )
        self.assertEqual(denied.status_code, HTTP.OK)
        self.assertFalse(self.rec_list.items.filter(id=self.candidate.id).exists())

    def test_duplicate_submission_conflict(self):
        """Submitting the same item twice returns 409."""
        self._submit()
        response = self._submit()
        self.assertEqual(response.status_code, HTTP.CONFLICT)

    def test_recommendations_disabled_rejected(self):
        """Lists without recommendations enabled reject submissions."""
        self.rec_list.allow_recommendations = False
        self.rec_list.save(update_fields=["allow_recommendations"])
        response = self._submit()
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_activity_log(self):
        """Approvals appear in the activity log."""
        rec_id = self._submit().json()["id"]
        self.call_api(
            "post",
            "api_list_recommendation_decision",
            args=(self.rec_list.id, rec_id, "approve"),
            payload={},
            headers=self.auth_headers,
        )
        response = self.call_api(
            "get",
            "api_list_activity",
            args=(self.rec_list.id,),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        types = [row["activity_type"] for row in response.json()["results"]]
        self.assertIn("recommendation_approved", types)
