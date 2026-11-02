"""The Tiers view of a list: moving items, editing tiers, and Sort by Tier."""

import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from app.models import Item, MediaTypes, Sources
from lists.models import CustomList, CustomListItem
from lists.tiers import DEFAULT_TIERS, clean_tiers, ink_for


class TierTestCase(TestCase):
    """A list of five games, one tier set, and a few people around it."""

    def setUp(self):
        """Create an owner, a collaborator, a stranger and a five-item list."""
        users = get_user_model().objects
        self.owner = users.create_user(username="owner", password="12345")
        self.collaborator = users.create_user(username="collab", password="12345")
        self.stranger = users.create_user(username="stranger", password="12345")
        self.custom_list = CustomList.objects.create(name="Games", owner=self.owner)
        self.custom_list.collaborators.add(self.collaborator)
        start = timezone.now() - timedelta(days=1)
        self.items = {}
        for index, title in enumerate(["One", "Two", "Three", "Four", "Five"]):
            item = Item.objects.create(
                media_id=str(index),
                source=Sources.MANUAL.value,
                media_type=MediaTypes.GAME.value,
                title=title,
                image="none",
            )
            CustomListItem.objects.create(
                item=item,
                custom_list=self.custom_list,
                added_by=self.owner,
            )
            # Distinct, increasing dates give the list a known manual order.
            CustomListItem.objects.filter(item=item).update(
                date_added=start + timedelta(minutes=index),
            )
            self.items[title] = item

    def tier_of(self, title):
        """Return the stored tier id of the item titled ``title``."""
        return CustomListItem.objects.get(
            custom_list=self.custom_list,
            item=self.items[title],
        ).tier

    def place(self, **tiers):
        """Set tiers by item title, for example ``place(One="s", Two="a")``."""
        for title, tier in tiers.items():
            CustomListItem.objects.filter(
                custom_list=self.custom_list,
                item=self.items[title],
            ).update(tier=tier)

    def titles_in_order(self):
        """Return list item titles in the list's own manual order."""
        return [
            entry.item.title
            for entry in CustomListItem.objects.filter(
                custom_list=self.custom_list,
            ).order_by("date_added", "id")
        ]


class TierDefinitionTests(TestCase):
    """The tier config a list stores."""

    def test_clean_tiers_accepts_valid_tiers(self):
        """Names are trimmed and colours lower-cased."""
        cleaned = clean_tiers([{"id": "gold", "name": " Gold ", "color": "#FFD700"}])
        self.assertEqual(
            cleaned,
            [{"id": "gold", "name": "Gold", "color": "#ffd700"}],
        )

    def test_clean_tiers_rejects_bad_input(self):
        """Empty, duplicate, unnamed, badly coloured or too many tiers fail."""
        good = {"id": "a", "name": "A", "color": "#112233"}
        bad_inputs = [
            None,
            [],
            [good, good],
            [{**good, "name": "  "}],
            [{**good, "color": "red"}],
            [{**good, "id": "Not Valid"}],
            [{"id": f"t{index}", "name": "T", "color": "#112233"} for index in range(13)],
            ["a"],
        ]
        for raw in bad_inputs:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                clean_tiers(raw)

    def test_ink_follows_the_colour(self):
        """Dark colours get white text and light ones dark text."""
        self.assertEqual(ink_for("#000000"), "#ffffff")
        self.assertEqual(ink_for("#ffffff"), "#1f2937")


class MoveTierItemTests(TierTestCase):
    """POST list/<id>/tiers/move."""

    def move(self, user, **data):
        """Post a move as ``user`` and return the response."""
        self.client.force_login(user)
        return self.client.post(
            reverse("list_tier_move", args=[self.custom_list.id]),
            data,
        )

    def test_move_sets_the_tier_and_the_order_in_it(self):
        """Dropping Four between One and Two puts it there within the tier."""
        self.place(One="s", Two="s")
        response = self.move(
            self.owner,
            item_id=self.items["Four"].id,
            tier="s",
            **{
                "item_ids[]": [
                    self.items["One"].id,
                    self.items["Four"].id,
                    self.items["Two"].id,
                ],
            },
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.tier_of("Four"), "s")
        self.assertEqual(
            [t for t in self.titles_in_order() if t in {"One", "Two", "Four"}],
            ["One", "Four", "Two"],
        )

    def test_move_to_unranked_clears_the_tier(self):
        """An empty tier means Unranked."""
        self.place(One="s")
        response = self.move(self.owner, item_id=self.items["One"].id, tier="")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.tier_of("One"), "")

    def test_collaborator_can_move(self):
        """Collaborators edit a list's tiers like its owner."""
        response = self.move(
            self.collaborator,
            item_id=self.items["One"].id,
            tier="a",
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.tier_of("One"), "a")

    def test_stranger_cannot_move(self):
        """Someone with no access is refused and nothing changes."""
        response = self.move(self.stranger, item_id=self.items["One"].id, tier="a")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.tier_of("One"), "")

    def test_anonymous_is_sent_to_login(self):
        """A logged-out request is redirected, not served."""
        response = self.client.post(
            reverse("list_tier_move", args=[self.custom_list.id]),
            {"item_id": self.items["One"].id, "tier": "a"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.tier_of("One"), "")

    def test_unknown_tier_is_rejected(self):
        """A tier the list does not have is a bad request."""
        response = self.move(self.owner, item_id=self.items["One"].id, tier="zzz")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.tier_of("One"), "")

    def test_item_outside_the_list_is_not_found(self):
        """Only items on the list can be placed."""
        other = Item.objects.create(
            media_id="x",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.GAME.value,
            title="Other",
        )
        response = self.move(self.owner, item_id=other.id, tier="a")
        self.assertEqual(response.status_code, 404)

    def test_smart_lists_have_no_tiers(self):
        """A smart list's items come from rules, so they cannot be placed."""
        self.custom_list.is_smart = True
        self.custom_list.save(update_fields=["is_smart"])
        response = self.move(self.owner, item_id=self.items["One"].id, tier="a")
        self.assertEqual(response.status_code, 403)

    def test_custom_tier_ids_are_valid_targets(self):
        """After a list defines its own tiers, those ids are the valid ones."""
        self.custom_list.tiers = [{"id": "gold", "name": "Gold", "color": "#ffd700"}]
        self.custom_list.save(update_fields=["tiers"])
        self.assertEqual(
            self.move(self.owner, item_id=self.items["One"].id, tier="gold").status_code,
            204,
        )
        self.assertEqual(
            self.move(self.owner, item_id=self.items["Two"].id, tier="s").status_code,
            400,
        )


class SaveTiersTests(TierTestCase):
    """POST list/<id>/tiers/save."""

    def save(self, user, tiers):
        """Post ``tiers`` as ``user`` and return the response."""
        self.client.force_login(user)
        return self.client.post(
            reverse("list_tier_save", args=[self.custom_list.id]),
            json.dumps({"tiers": tiers}),
            content_type="application/json",
        )

    def test_save_replaces_the_tiers(self):
        """The list stores the new names and colours."""
        tiers = [
            {"id": "s", "name": "Great", "color": "#ff0000"},
            {"id": "new1", "name": "Meh", "color": "#00ff00"},
        ]
        response = self.save(self.owner, tiers)
        self.assertEqual(response.status_code, 200)
        self.custom_list.refresh_from_db()
        self.assertEqual(self.custom_list.tiers, tiers)

    def test_removed_tier_sends_its_items_to_unranked(self):
        """Deleting a tier blanks it on its items and leaves the others alone."""
        self.place(One="s", Two="a")
        self.save(self.owner, [{"id": "s", "name": "S", "color": "#ff0000"}])
        self.assertEqual(self.tier_of("One"), "s")
        self.assertEqual(self.tier_of("Two"), "")

    def test_invalid_tiers_change_nothing(self):
        """A bad payload is a 400 and the stored tiers stay as they were."""
        response = self.save(self.owner, [{"id": "s", "name": "", "color": "#ff0000"}])
        self.assertEqual(response.status_code, 400)
        self.custom_list.refresh_from_db()
        self.assertEqual(self.custom_list.tiers, [])

    def test_stranger_cannot_save(self):
        """Only people who can edit the list can change its tiers."""
        response = self.save(self.stranger, [{"id": "s", "name": "S", "color": "#ff0000"}])
        self.assertEqual(response.status_code, 403)


class TierViewTests(TierTestCase):
    """The list page in the Tiers layout, and Sort by Tier."""

    def titles_on_page(self, response):
        """Return the item titles the page lists, in order."""
        return [item.title for item in response.context["items"].object_list]

    def test_board_groups_items_by_tier(self):
        """Each tier shows its items; the rest are Unranked."""
        self.place(One="s", Two="s", Three="b")
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("list_detail", args=[self.custom_list.public_reference]),
            {"layout": "tiers"},
        )
        self.assertEqual(response.status_code, 200)
        columns = response.context["tier_columns"]
        self.assertEqual(
            [entry["id"] for entry in (column["tier"] for column in columns)],
            [tier["id"] for tier in DEFAULT_TIERS],
        )
        by_id = {
            column["tier"]["id"]: [item.title for item in column["items"]]
            for column in columns
        }
        self.assertEqual(by_id["s"], ["One", "Two"])
        self.assertEqual(by_id["b"], ["Three"])
        self.assertEqual(
            [item.title for item in response.context["tier_unranked"]],
            ["Four", "Five"],
        )

    def test_layout_choice_is_remembered(self):
        """Choosing Tiers is saved like Grid and Table."""
        self.client.force_login(self.owner)
        url = reverse("list_detail", args=[self.custom_list.public_reference])
        self.client.get(url, {"layout": "tiers"})
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.list_detail_layout, "tiers")
        self.assertEqual(self.client.get(url).context["current_layout"], "tiers")

    def test_public_visitors_see_a_read_only_board(self):
        """Anonymous visitors see tiers but get no editing controls."""
        self.custom_list.visibility = "public"
        self.custom_list.save(update_fields=["visibility"])
        self.place(One="s")
        response = self.client.get(
            reverse("list_detail", args=[self.custom_list.public_reference]),
            {"layout": "tiers"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["can_edit"])
        self.assertNotContains(response, "tier-move")
        self.assertNotContains(response, "editTier(")

    def test_smart_lists_fall_back_to_grid(self):
        """A smart list ignores a saved Tiers layout."""
        smart = CustomList.objects.create(
            name="Smart",
            owner=self.owner,
            is_smart=True,
            smart_media_types=[MediaTypes.GAME.value],
        )
        self.owner.list_detail_layout = "tiers"
        self.owner.save(update_fields=["list_detail_layout"])
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("list_detail", args=[smart.public_reference]),
        )
        self.assertEqual(response.context["current_layout"], "grid")
        self.assertNotIn("tier", [value for value, _ in response.context["sort_choices"]])

    def test_sort_by_tier_orders_by_tier_then_place(self):
        """Tier order first, then the list's order; Unranked comes last."""
        self.place(Five="s", Three="s", Two="a", One="b")
        self.client.force_login(self.owner)
        url = reverse("list_detail", args=[self.custom_list.public_reference])
        ascending = self.client.get(url, {"layout": "grid", "sort": "tier"})
        self.assertEqual(
            self.titles_on_page(ascending),
            ["Three", "Five", "Two", "One", "Four"],
        )
        descending = self.client.get(
            url,
            {"layout": "grid", "sort": "tier", "direction": "desc"},
        )
        self.assertEqual(
            self.titles_on_page(descending),
            ["Four", "One", "Two", "Five", "Three"],
        )
