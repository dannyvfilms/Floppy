"""Fill from ratings: place unranked items in tiers by the user's own scores."""

import json

from django.urls import reverse

from app.models import Game, Status
from lists.models import CustomListItem
from lists.tests.test_tiers import TierTestCase
from lists.tiers import tier_index_for_score
from users.models import RatingScaleChoices


class TierIndexTests(TierTestCase):
    """The rating range is split evenly, best scores in the first tier."""

    def test_six_tiers_split_the_range_evenly(self):
        """Ten is the top tier, zero the bottom, and bands are about 1.67 wide."""
        expected = {10: 0, 9: 0, 8.5: 0, 8: 1, 7: 1, 6.5: 2, 5: 3, 3.5: 3, 3: 4, 0: 5}
        for score, index in expected.items():
            with self.subTest(score=score):
                self.assertEqual(tier_index_for_score(score, 6), index)

    def test_one_tier_takes_everything(self):
        """With a single tier every score lands in it."""
        self.assertEqual(tier_index_for_score(10, 1), 0)
        self.assertEqual(tier_index_for_score(0, 1), 0)

    def test_scores_are_never_out_of_range(self):
        """Even an odd stored value stays inside the tiers."""
        self.assertEqual(tier_index_for_score(11, 4), 0)
        self.assertEqual(tier_index_for_score(-1, 4), 3)


class FillTests(TierTestCase):
    """The fill and undo endpoints."""

    def setUp(self):
        """Rate three of the five items as the owner."""
        super().setUp()
        self.fill_url = reverse("list_tier_fill", args=[self.custom_list.id])
        self.undo_url = reverse("list_tier_fill_undo", args=[self.custom_list.id])
        for title, score in {"One": 9.5, "Two": 7, "Three": 1}.items():
            Game.objects.create(
                item=self.items[title],
                user=self.owner,
                status=Status.COMPLETED.value,
                score=score,
            )
        self.client.force_login(self.owner)

    def fill(self):
        """POST the fill and return the response."""
        return self.client.post(self.fill_url)

    def test_rated_items_land_in_their_tier_and_the_rest_stay_unranked(self):
        """9.5 is S, 7 is A, 1 is F; unrated items are untouched."""
        response = self.fill()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.tier_of("One"), "s")
        self.assertEqual(self.tier_of("Two"), "a")
        self.assertEqual(self.tier_of("Three"), "f")
        self.assertEqual(self.tier_of("Four"), "")
        self.assertEqual(self.tier_of("Five"), "")
        placements = {
            entry["item_id"]: entry["tier"] for entry in response.json()["placements"]
        }
        self.assertEqual(
            placements,
            {
                self.items["One"].id: "s",
                self.items["Two"].id: "a",
                self.items["Three"].id: "f",
            },
        )

    def test_items_already_in_a_tier_are_not_moved(self):
        """Only the Unranked pool is filled."""
        self.place(One="d")
        self.fill()
        self.assertEqual(self.tier_of("One"), "d")
        self.assertEqual(self.tier_of("Two"), "a")

    def test_response_sorts_each_touched_tier_in_list_order(self):
        """The client gets the order the page would show after a reload."""
        self.place(Four="a")
        order = self.fill().json()["order"]
        self.assertEqual(
            order["a"],
            [self.items["Two"].id, self.items["Four"].id],
        )

    def test_undo_returns_the_filled_items_to_unranked(self):
        """Undo clears the tiers the fill set."""
        placements = self.fill().json()["placements"]
        response = self.client.post(
            self.undo_url,
            json.dumps({"placements": placements}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        for title in ("One", "Two", "Three"):
            self.assertEqual(self.tier_of(title), "")

    def test_undo_leaves_items_that_were_moved_since(self):
        """An item dragged elsewhere after the fill keeps its new tier."""
        placements = self.fill().json()["placements"]
        self.place(One="a")
        self.client.post(
            self.undo_url,
            json.dumps({"placements": placements}),
            content_type="application/json",
        )
        self.assertEqual(self.tier_of("One"), "a")
        self.assertEqual(self.tier_of("Two"), "")

    def test_bad_undo_payload_changes_nothing(self):
        """Malformed bodies are rejected."""
        self.fill()
        for body in ("nope", json.dumps({"placements": [{"item_id": "x"}]})):
            response = self.client.post(
                self.undo_url,
                body,
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.tier_of("One"), "s")

    def test_custom_tier_count_changes_the_split(self):
        """Two tiers split the range at 5."""
        self.custom_list.tiers = [
            {"id": "top", "name": "Top", "color": "#ff0000"},
            {"id": "low", "name": "Low", "color": "#0000ff"},
        ]
        self.custom_list.save(update_fields=["tiers"])
        self.fill()
        self.assertEqual(self.tier_of("One"), "top")
        self.assertEqual(self.tier_of("Two"), "top")
        self.assertEqual(self.tier_of("Three"), "low")

    def test_five_point_scale_users_fill_from_the_same_scores(self):
        """Stored scores are 0-10 whatever the user's display scale is."""
        self.owner.rating_scale = RatingScaleChoices.FIVE
        self.owner.save(update_fields=["rating_scale"])
        self.fill()
        self.assertEqual(self.tier_of("One"), "s")

    def test_disabled_ratings_turn_the_fill_off(self):
        """With ratings disabled the endpoint refuses and the button is hidden."""
        self.owner.rating_scale = RatingScaleChoices.DISABLED
        self.owner.save(update_fields=["rating_scale"])
        self.assertEqual(self.fill().status_code, 400)
        self.assertEqual(self.tier_of("One"), "")
        page = self.client.get(
            reverse("list_detail", args=[self.custom_list.public_reference]),
            {"layout": "tiers"},
        )
        self.assertFalse(page.context["tier_config"]["canFill"])

    def test_button_is_offered_to_editors_with_ratings_on(self):
        """The board config enables the fill for people who can edit."""
        page = reverse("list_detail", args=[self.custom_list.public_reference])
        self.assertTrue(
            self.client.get(page, {"layout": "tiers"}).context["tier_config"]["canFill"],
        )

    def test_people_who_cannot_edit_cannot_fill(self):
        """A stranger or a visitor of a public list gets a 403."""
        self.custom_list.visibility = "public"
        self.custom_list.save(update_fields=["visibility"])
        self.client.force_login(self.stranger)
        self.assertEqual(self.fill().status_code, 403)
        self.assertEqual(
            self.client.post(self.undo_url, "{}", content_type="application/json").status_code,
            403,
        )
        self.assertEqual(self.tier_of("One"), "")
        self.assertEqual(CustomListItem.objects.filter(tier="").count(), 5)

    def test_fills_use_the_collaborators_own_ratings(self):
        """Ratings come from whoever presses the button."""
        Game.objects.create(
            item=self.items["Four"],
            user=self.collaborator,
            status=Status.COMPLETED.value,
            score=10,
        )
        self.client.force_login(self.collaborator)
        self.fill()
        self.assertEqual(self.tier_of("Four"), "s")
        self.assertEqual(self.tier_of("One"), "")
