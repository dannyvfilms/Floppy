from django.urls import reverse

from lists.models import CustomList, CustomListItem

from .base import FloppyApiTestCase
from .helpers import check_complete_lists_structure, check_pagination_structure


class ListsTests(FloppyApiTestCase):
    """Validate list endpoints and basic side effects."""

    def test_lists_get_returns_paginated_payload(self):
        """Lists endpoint should return the standard pagination envelope."""
        response = self.call_api("get", "api_lists", headers=self.auth_headers)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("pagination", payload)
        self.assertIn("results", payload)
        check_pagination_structure(self, payload["pagination"])
        for lst in payload["results"]:
            check_complete_lists_structure(self, lst)

    def test_lists_get_search_filter_returns_filtered_results(self):
        """Lists endpoint should filter by search query."""
        response = self.call_api(
            "get",
            "api_lists",
            params={"search": "Favorites"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["results"][0]["name"], "Favorites")

    def test_lists_get_sort_filter_returns_sorted_results(self):
        """Lists endpoint should sort results when requested."""
        response = self.call_api(
            "get",
            "api_lists",
            params={"sort": "name_desc"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        names = [item["name"] for item in payload["results"]]
        self.assertEqual(names, sorted(names, reverse=True))

    def test_lists_get_items_sort_uses_item_count(self):
        """Lists endpoint should sort by number of items, not by join order."""
        response = self.call_api(
            "get",
            "api_lists",
            params={"sort": "items_desc"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        names = [item["name"] for item in payload["results"]]
        self.assertEqual(
            names,
            ["Favorites", "Shared Picks", "Watching Now"],
        )
        self.assertEqual(
            [item["items_count"] for item in payload["results"]],
            [3, 3, 2],
        )

    def test_lists_post_without_name_returns_bad_request(self):
        """Creating a list without name must fail with 400."""
        response = self.call_api(
            "post",
            "api_lists",
            payload={"description": "missing-name"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("name", response.json().get("detail", "").lower())

    def test_lists_post_with_name_creates_list(self):
        """Creating a list with name should succeed and return 201."""
        response = self.call_api(
            "post",
            "api_lists",
            payload={"name": "New List", "description": "Test list"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["name"], "New List")
        self.assertEqual(payload["description"], "Test list")
        self.assertTrue(
            CustomList.objects.filter(name="New List", owner=self.user1).exists()
        )

    def test_lists_post_with_invalid_collaborators_type_returns_bad_request(self):
        """POST lists with non-array collaborators should fail with 400."""
        response = self.call_api(
            "post",
            "api_lists",
            payload={"name": "New List", "collaborators": "not-array"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("collaborators", response.json().get("detail", "").lower())

    def test_lists_post_with_invalid_collaborator_ids_returns_bad_request(self):
        """POST lists with invalid collaborator IDs should fail with 400."""
        response = self.call_api(
            "post",
            "api_lists",
            payload={"name": "New List", "collaborators": [99999]},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("collaborator", response.json().get("detail", "").lower())

    def test_lists_post_with_valid_collaborators_adds_them(self):
        """POST lists with valid collaborators should create list with collaborators."""
        response = self.call_api(
            "post",
            "api_lists",
            payload={"name": "Collab List", "collaborators": [self.user2.id]},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["name"], "Collab List")
        new_list = CustomList.objects.get(name="Collab List")
        self.assertTrue(new_list.collaborators.filter(id=self.user2.id).exists())

    def test_lists_post_with_is_public_creates_public_list(self):
        """POST lists with is_public=True should create a public list."""
        response = self.call_api(
            "post",
            "api_lists",
            payload={"name": "Public List", "is_public": True},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["is_public"])
        new_list = CustomList.objects.get(name="Public List")
        self.assertEqual(new_list.visibility, "public")

    def test_lists_post_with_public_slug_sets_slug(self):
        """POST lists with public_slug should normalize and save it."""
        response = self.call_api(
            "post",
            "api_lists",
            payload={"name": "Slug List", "public_slug": "My Cool List!"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["public_slug"], "my-cool-list")
        new_list = CustomList.objects.get(name="Slug List")
        self.assertEqual(new_list.public_slug, "my-cool-list")

    def test_lists_post_with_numeric_public_slug_returns_bad_request(self):
        """POST lists with a numeric-only public_slug should fail with 400."""
        response = self.call_api(
            "post",
            "api_lists",
            payload={"name": "New List", "public_slug": "12345"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("numbers", response.json().get("detail", "").lower())

    def test_lists_post_with_reserved_public_slug_returns_bad_request(self):
        """POST lists with a reserved public_slug should fail with 400."""
        response = self.call_api(
            "post",
            "api_lists",
            payload={"name": "New List", "public_slug": "create"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("reserved", response.json().get("detail", "").lower())

    def test_lists_post_with_duplicate_public_slug_returns_bad_request(self):
        """POST lists with an already-used public_slug should fail with 400."""
        self.call_api(
            "post",
            "api_lists",
            payload={"name": "List A", "public_slug": "foo"},
            headers=self.auth_headers,
        )
        response = self.call_api(
            "post",
            "api_lists",
            payload={"name": "List B", "public_slug": "foo"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("already in use", response.json().get("detail", "").lower())

    def test_lists_post_allow_recommendations_forced_false_when_private(self):
        """POST lists with allow_recommendations=True but is_public=False forces it off."""
        response = self.call_api(
            "post",
            "api_lists",
            payload={
                "name": "New List",
                "is_public": False,
                "allow_recommendations": True,
            },
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.json()["allow_recommendations"])

    def test_lists_post_allow_recommendations_true_when_public(self):
        """POST lists with is_public=True and allow_recommendations=True keeps it on."""
        response = self.call_api(
            "post",
            "api_lists",
            payload={
                "name": "New List",
                "is_public": True,
                "allow_recommendations": True,
            },
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["allow_recommendations"])

    def test_lists_post_with_invalid_is_public_type_returns_bad_request(self):
        """POST lists with non-boolean is_public should fail with 400."""
        response = self.call_api(
            "post",
            "api_lists",
            payload={"name": "New List", "is_public": "yes"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("is_public", response.json().get("detail", "").lower())

    def test_list_detail_delete_removes_list(self):
        """List delete should remove the owned list and return 204."""
        custom_list = self.lists_by_name["favorites"]
        response = self.call_api(
            "delete",
            "api_list_detail",
            args=(custom_list.id,),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(CustomList.objects.filter(id=custom_list.id).exists())

    def test_list_detail_delete_not_found_returns_404(self):
        """List delete with non-existent ID should return 404."""
        response = self.call_api(
            "delete",
            "api_list_detail",
            args=(99999,),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)

    def test_list_detail_delete_without_permission_returns_403(self):
        """List delete without permission should return 403."""
        other_list = self.lists_by_name["user2_private"]
        response = self.call_api(
            "delete",
            "api_list_detail",
            args=(other_list.id,),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 403)

    def test_list_detail_get_returns_list_with_paginated_items(self):
        """List detail GET should return list info and paginated items."""
        custom_list = self.lists_by_name["favorites"]
        response = self.call_api(
            "get",
            "api_list_detail",
            args=(custom_list.id,),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("name", payload)
        self.assertEqual(payload["name"], "Favorites")
        self.assertIn("items", payload)
        self.assertIsInstance(payload["items"], dict)
        self.assertIn("pagination", payload["items"])
        self.assertIn("results", payload["items"])

    def test_list_detail_get_search_filter_returns_filtered_results(self):
        """List detail GET should filter items by search query."""
        custom_list = self.lists_by_name["favorites"]
        response = self.call_api(
            "get",
            "api_list_detail",
            args=(custom_list.id,),
            params={"search": "Movie 1"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["items"]["results"]), 1)
        self.assertIn("Movie 1", payload["items"]["results"][0]["item"]["title"])

    def test_list_detail_get_sort_filter_returns_sorted_results(self):
        """List detail GET should sort items when requested."""
        custom_list = self.lists_by_name["favorites"]
        response = self.call_api(
            "get",
            "api_list_detail",
            args=(custom_list.id,),
            params={"sort": "title_desc"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        titles = [item["item"]["title"] for item in payload["items"]["results"]]
        self.assertEqual(titles, sorted(titles, reverse=True))

    def test_list_detail_get_not_found_returns_404(self):
        """List detail GET with non-existent ID should return 404."""
        response = self.call_api(
            "get",
            "api_list_detail",
            args=(99999,),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)

    def test_list_detail_get_without_permission_returns_403(self):
        """List detail GET without permission should return 403."""
        other_list = self.lists_by_name["user2_private"]
        response = self.call_api(
            "get",
            "api_list_detail",
            args=(other_list.id,),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 403)

    def test_list_detail_patch_name(self):
        """List PATCH should update name and return 200."""
        custom_list = self.lists_by_name["favorites"]
        response = self.call_api(
            "patch",
            "api_list_detail",
            args=(custom_list.id,),
            payload={"name": "Updated Name"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        custom_list.refresh_from_db()
        self.assertEqual(custom_list.name, "Updated Name")

    def test_list_detail_patch_description(self):
        """List PATCH should update description and return 200."""
        custom_list = self.lists_by_name["favorites"]
        response = self.call_api(
            "patch",
            "api_list_detail",
            args=(custom_list.id,),
            payload={"description": "New description"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        custom_list.refresh_from_db()
        self.assertEqual(custom_list.description, "New description")

    def test_list_detail_patch_collaborators(self):
        """List PATCH should update collaborators and return 200."""
        custom_list = self.lists_by_name["favorites"]
        response = self.call_api(
            "patch",
            "api_list_detail",
            args=(custom_list.id,),
            payload={"collaborators": [self.user2.id]},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        custom_list.refresh_from_db()
        self.assertTrue(custom_list.collaborators.filter(id=self.user2.id).exists())

    def test_list_detail_patch_not_found_returns_404(self):
        """List PATCH with non-existent ID should return 404."""
        response = self.call_api(
            "patch",
            "api_list_detail",
            args=(99999,),
            payload={"name": "Updated"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)

    def test_list_detail_patch_without_permission_returns_403(self):
        """List PATCH without permission should return 403."""
        other_list = self.lists_by_name["user2_private"]
        response = self.call_api(
            "patch",
            "api_list_detail",
            args=(other_list.id,),
            payload={"name": "Hacked Name"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 403)

    def test_list_detail_patch_invalid_collaborators_returns_400(self):
        """List PATCH with invalid collaborators type should return 400."""
        custom_list = self.lists_by_name["favorites"]
        response = self.call_api(
            "patch",
            "api_list_detail",
            args=(custom_list.id,),
            payload={"collaborators": "not-array"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)

    def test_list_detail_patch_invalid_collaborator_ids_returns_400(self):
        """List PATCH with invalid collaborator IDs should return 400."""
        custom_list = self.lists_by_name["favorites"]
        response = self.call_api(
            "patch",
            "api_list_detail",
            args=(custom_list.id,),
            payload={"collaborators": [99999]},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)

    def test_list_detail_patch_is_public(self):
        """List PATCH should update visibility and return 200."""
        custom_list = self.lists_by_name["favorites"]
        response = self.call_api(
            "patch",
            "api_list_detail",
            args=(custom_list.id,),
            payload={"is_public": True},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        custom_list.refresh_from_db()
        self.assertEqual(custom_list.visibility, "public")

    def test_list_detail_patch_public_slug(self):
        """List PATCH should update public_slug and return 200."""
        custom_list = self.lists_by_name["favorites"]
        response = self.call_api(
            "patch",
            "api_list_detail",
            args=(custom_list.id,),
            payload={"public_slug": "new-slug"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        custom_list.refresh_from_db()
        self.assertEqual(custom_list.public_slug, "new-slug")

    def test_list_detail_patch_public_slug_uniqueness_excludes_self(self):
        """PATCH re-submitting a list's own slug should succeed, not 400."""
        custom_list = self.lists_by_name["favorites"]
        custom_list.public_slug = "existing-slug"
        custom_list.save()
        response = self.call_api(
            "patch",
            "api_list_detail",
            args=(custom_list.id,),
            payload={"public_slug": "existing-slug"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)

    def test_list_detail_patch_public_slug_conflict_returns_400(self):
        """PATCH with a slug already used by another list should return 400."""
        other_list = self.lists_by_name["shared"]
        other_list.public_slug = "taken-slug"
        other_list.save()
        custom_list = self.lists_by_name["favorites"]
        response = self.call_api(
            "patch",
            "api_list_detail",
            args=(custom_list.id,),
            payload={"public_slug": "taken-slug"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("already in use", response.json().get("detail", "").lower())

    def test_list_detail_patch_allow_recommendations_forced_false_when_set_private(
        self,
    ):
        """PATCH setting is_public=False should force allow_recommendations off."""
        custom_list = self.lists_by_name["favorites"]
        custom_list.visibility = "public"
        custom_list.allow_recommendations = True
        custom_list.save()
        response = self.call_api(
            "patch",
            "api_list_detail",
            args=(custom_list.id,),
            payload={"is_public": False},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["allow_recommendations"])
        custom_list.refresh_from_db()
        self.assertFalse(custom_list.allow_recommendations)

    def test_list_detail_patch_allow_recommendations_alone_forced_false_on_private_list(
        self,
    ):
        """PATCH allow_recommendations alone on a private list stays False."""
        custom_list = self.lists_by_name["favorites"]
        response = self.call_api(
            "patch",
            "api_list_detail",
            args=(custom_list.id,),
            payload={"allow_recommendations": True},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["allow_recommendations"])

    def test_list_detail_patch_invalid_public_slug_returns_400(self):
        """List PATCH with a numeric-only public_slug should return 400."""
        custom_list = self.lists_by_name["favorites"]
        response = self.call_api(
            "patch",
            "api_list_detail",
            args=(custom_list.id,),
            payload={"public_slug": "12345"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)

    def test_list_items_get_returns_paginated_payload(self):
        """List items endpoint should return paginated list items."""
        custom_list = self.lists_by_name["favorites"]
        response = self.call_api(
            "get",
            "api_list_add_item",
            args=(custom_list.id,),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("pagination", payload)
        self.assertIn("results", payload)
        check_pagination_structure(self, payload["pagination"])

    def test_list_items_sort_filter_returns_sorted_results(self):
        """List items endpoint should sort items when requested."""
        custom_list = self.lists_by_name["favorites"]
        response = self.call_api(
            "get",
            "api_list_add_item",
            args=(custom_list.id,),
            params={"sort": "title_desc"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        titles = [item["item"]["title"] for item in payload["results"]]
        self.assertEqual(titles, sorted(titles, reverse=True))

    def test_list_items_not_found_returns_404(self):
        """List items endpoint with non-existent ID should return 404."""
        response = self.call_api(
            "get",
            "api_list_add_item",
            args=(99999,),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)

    def test_list_items_without_permission_returns_403(self):
        """List items endpoint without permission should return 403."""
        other_list = self.lists_by_name["user2_private"]
        response = self.call_api(
            "get",
            "api_list_add_item",
            args=(other_list.id,),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 403)

    def test_list_items_search_query(self):
        """List items endpoint should filter by search query."""
        custom_list = self.lists_by_name["favorites"]
        # Add second movie to list; search for first item which contains "Movie"
        other_item = self.items_by_type["movie"][1]
        custom_list.items.add(other_item)

        # Search for item title that matches first item (which contains "Movie 1")
        response = self.client.get(
            reverse("api_list_add_item", args=(custom_list.id,)) + "?search=Movie%201",
            **self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        # Should find only Movie 1, not Movie 2
        self.assertEqual(len(payload["results"]), 1)

    def test_list_items_invalid_sort_returns_404(self):
        """List items endpoint with invalid sort should return 404."""
        custom_list = self.lists_by_name["favorites"]
        response = self.client.get(
            reverse("api_list_add_item", args=(custom_list.id,)) + "?sort=invalid_sort",
            **self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)

    def test_list_item_delete_removes_item(self):
        """Deleting a list item should return 204 and remove relation."""
        custom_list = self.lists_by_name["favorites"]
        list_item = custom_list.get_list_item(1, include_item=True)
        response = self.call_api(
            "delete",
            "api_list_remove_item",
            args=(custom_list.id, 1),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(
            CustomListItem.objects.filter(
                custom_list=custom_list,
                item=list_item.item,
            ).exists(),
        )

    def test_list_item_delete_not_found_returns_404(self):
        """Deleting non-existent list item should return 404."""
        custom_list = self.lists_by_name["favorites"]
        response = self.call_api(
            "delete",
            "api_list_remove_item",
            args=(custom_list.id, 99999),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)

    def test_list_item_delete_list_not_found_returns_404(self):
        """Deleting item from non-existent list should return 404."""
        response = self.call_api(
            "delete",
            "api_list_remove_item",
            args=(99999, 1),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)

    def test_list_item_delete_without_permission_returns_403(self):
        """Deleting item without permission should return 403."""
        other_list = self.lists_by_name["user2_private"]
        response = self.call_api(
            "delete",
            "api_list_remove_item",
            args=(other_list.id, 1),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 403)
