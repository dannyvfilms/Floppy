# FORK: tests for the Bearer-safe tier endpoints, viewers-by-username and the
# smart/tags/notes fields native clients use on lists.
from http import HTTPStatus as HTTP  # noqa: N814

from lists.models import CustomList, CustomListItem

from .base import FloppyApiTestCase


class ListTierApiTests(FloppyApiTestCase):
    """GET/PUT tiers, move, fill and undo."""

    def setUp(self):
        """Use the seeded favorites list, which has items."""
        super().setUp()
        self.custom_list = self.lists_by_name["favorites"]
        self.entries = list(
            CustomListItem.objects.filter(custom_list=self.custom_list).order_by("id"),
        )

    def test_get_returns_default_tiers_and_placements(self):
        """An untouched list reports the default tiers and Unranked items."""
        response = self.call_api(
            "get",
            "api_list_tiers",
            args=(self.custom_list.id,),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        body = response.json()
        self.assertEqual([tier["id"] for tier in body["tiers"]][:2], ["s", "a"])
        self.assertEqual(len(body["placements"]), len(self.entries))
        self.assertTrue(all(row["tier"] == "" for row in body["placements"]))

    def test_put_saves_tiers_and_unranks_removed_ones(self):
        """Replacing tiers keeps valid placements and clears removed tiers."""
        entry = self.entries[0]
        move = self.call_api(
            "post",
            "api_list_tier_move",
            args=(self.custom_list.id,),
            payload={"tier": "a", "item_id": entry.item_id},
            headers=self.auth_headers,
        )
        self.assertEqual(move.status_code, HTTP.NO_CONTENT)
        entry.refresh_from_db()
        self.assertEqual(entry.tier, "a")

        saved = self.call_api(
            "put",
            "api_list_tiers",
            args=(self.custom_list.id,),
            payload={"tiers": [{"id": "top", "name": "Top", "color": "#112233"}]},
            headers=self.auth_headers,
        )
        self.assertEqual(saved.status_code, HTTP.OK)
        self.assertEqual(saved.json()["tiers"][0]["id"], "top")
        entry.refresh_from_db()
        self.assertEqual(entry.tier, "")

    def test_move_with_a_rejected_order_changes_nothing(self):
        """A bad item_ids order is a 400 and the tier move is rolled back."""
        entry = self.entries[0]
        response = self.call_api(
            "post",
            "api_list_tier_move",
            args=(self.custom_list.id,),
            payload={
                "tier": "s",
                "item_id": entry.item_id,
                "item_ids": [entry.item_id, entry.item_id],
            },
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        entry.refresh_from_db()
        self.assertEqual(entry.tier, "")

    def test_put_rejects_bad_tiers(self):
        """Invalid tier definitions return 400."""
        response = self.call_api(
            "put",
            "api_list_tiers",
            args=(self.custom_list.id,),
            payload={"tiers": []},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.assertEqual(response.json(), {"detail": "Provide between 1 and 12 tiers."})

    def test_move_rejects_unknown_tier_and_foreign_item(self):
        """Unknown tier is 400; an item outside the list is 404."""
        unknown = self.call_api(
            "post",
            "api_list_tier_move",
            args=(self.custom_list.id,),
            payload={"tier": "zz", "item_id": self.entries[0].item_id},
            headers=self.auth_headers,
        )
        self.assertEqual(unknown.status_code, HTTP.BAD_REQUEST)
        missing = self.call_api(
            "post",
            "api_list_tier_move",
            args=(self.custom_list.id,),
            payload={"tier": "s", "item_id": 99999999},
            headers=self.auth_headers,
        )
        self.assertEqual(missing.status_code, HTTP.NOT_FOUND)

    def test_viewer_without_edit_cannot_write(self):
        """A non-editor sees 404 or 403 and nothing changes."""
        private = CustomList.objects.create(name="Mine", owner=self.user1)
        response = self.call_api(
            "post",
            "api_list_tier_move",
            args=(private.id,),
            payload={"tier": "s", "item_id": 1},
            headers=self.auth_headers2,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    def test_smart_list_tiers_not_editable(self):
        """Smart lists reject tier writes."""
        smart = CustomList.objects.create(
            name="Smart",
            owner=self.user1,
            is_smart=True,
        )
        response = self.call_api(
            "put",
            "api_list_tiers",
            args=(smart.id,),
            payload={"tiers": [{"id": "s", "name": "S", "color": "#ffffff"}]},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_fill_and_undo_round_trip(self):
        """Fill places rated items; undo returns them to Unranked."""
        fill = self.call_api(
            "post",
            "api_list_tier_fill",
            args=(self.custom_list.id,),
            headers=self.auth_headers,
        )
        self.assertEqual(fill.status_code, HTTP.OK)
        placements = fill.json()["placements"]
        undo = self.call_api(
            "post",
            "api_list_tier_fill_undo",
            args=(self.custom_list.id,),
            payload={"placements": placements},
            headers=self.auth_headers,
        )
        self.assertEqual(undo.status_code, HTTP.OK)
        self.assertFalse(
            CustomListItem.objects.filter(custom_list=self.custom_list)
            .exclude(tier="")
            .exists(),
        )


class ListViewersAndFieldsTests(FloppyApiTestCase):
    """Viewers by username and the smart/tags/notes list fields."""

    def test_put_viewers_by_username(self):
        """PUT replaces the viewer set; unknown names are 404."""
        custom_list = CustomList.objects.create(name="Shared", owner=self.user1)
        ok = self.call_api(
            "put",
            "api_list_viewers",
            args=(custom_list.id,),
            payload={"usernames": [self.user2.username]},
            headers=self.auth_headers,
        )
        self.assertEqual(ok.status_code, HTTP.OK)
        self.assertEqual(ok.json()["viewers"], [self.user2.username])
        bad = self.call_api(
            "put",
            "api_list_viewers",
            args=(custom_list.id,),
            payload={"usernames": ["nobody-here"]},
            headers=self.auth_headers,
        )
        self.assertEqual(bad.status_code, HTTP.NOT_FOUND)

    def test_create_smart_list_with_tags_and_notes(self):
        """POST accepts is_smart, tags and include_notes and echoes them."""
        response = self.client.post(
            "/api/v1/lists/",
            data={
                "name": "Smart tagged",
                "is_smart": True,
                "visibility": "public",
                "tags": ["Weekend", " weekend ", "Horror"],
                "include_notes": True,
            },
            content_type="application/json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.CREATED)
        body = response.json()
        self.assertTrue(body["is_smart"])
        self.assertEqual(body["tags"], ["Weekend", "Horror"])
        self.assertTrue(body["include_notes"])

    def test_patch_tags_and_notes(self):
        """PATCH updates tags and notes; private lists force notes off."""
        custom_list = CustomList.objects.create(name="Plain", owner=self.user1)
        response = self.client.patch(
            f"/api/v1/lists/{custom_list.id}/",
            data={"tags": ["A"], "include_notes": True},
            content_type="application/json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["tags"], ["A"])
        self.assertFalse(response.json()["include_notes"])

    def test_items_media_type_filter(self):
        """The items endpoint filters by media type on the server."""
        favorites = self.lists_by_name["favorites"]
        response = self.client.get(
            f"/api/v1/lists/{favorites.id}/?media_type=nonexistent",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["items"]["results"], [])

    def test_patch_toggles_smart(self):
        """PATCH can turn a list smart and back, clearing the rules."""
        custom_list = CustomList.objects.create(name="Toggle", owner=self.user1)
        on = self.client.patch(
            f"/api/v1/lists/{custom_list.id}/",
            data={"is_smart": True},
            content_type="application/json",
            **self.auth_headers,
        )
        self.assertTrue(on.json()["is_smart"])
        off = self.client.patch(
            f"/api/v1/lists/{custom_list.id}/",
            data={"is_smart": False},
            content_type="application/json",
            **self.auth_headers,
        )
        self.assertFalse(off.json()["is_smart"])
        custom_list.refresh_from_db()
        self.assertEqual(custom_list.smart_filters, {})
