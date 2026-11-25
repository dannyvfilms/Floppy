"""Custom rating scales: scoring, validation, persistence and form saves."""

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.forms import AnimeForm
from app.models import Anime, Item, MediaTypes, Sources, Status
from users import rating_scales
from users.rating_scales import RatingScaleError

ANIME_SCALE = {
    "name": "Anime",
    "criteria": [
        {"name": "Visuals", "min": 0, "max": 10, "weight": 1},
        {"name": "Audio", "min": 0, "max": 10, "weight": 1},
        {"name": "Story", "min": 0, "max": 10, "weight": 2},
        {"name": "Characters", "min": 0, "max": 10, "weight": 2},
        {"name": "Enjoyment", "min": 0, "max": 10, "weight": 3},
        {"name": "Bonus", "min": 0, "max": 10, "weight": 1},
    ],
}


class ScaleTestCase(TestCase):
    """Create a user with the issue's anime scale."""

    def setUp(self):
        """Create the user and scale."""
        self.user = get_user_model().objects.create_user(
            username="scaler",
            password="12345",
        )
        self.scale = rating_scales.save_scale(self.user, ANIME_SCALE)
        self.by_name = {c.name: str(c.id) for c in self.scale.criteria.all()}

    def values(self, **named):
        """Map criterion names to ids for a values dict."""
        return {self.by_name[name]: value for name, value in named.items()}


class ComputeScoreTests(ScaleTestCase):
    """The weighted average rules from the issue."""

    def test_issue_example_is_8_4(self):
        """Weights 1,1,2,2,3,1 over 8,9,7,8,9,10 give 8.4, not the plain 8.5."""
        values = self.values(
            Visuals=8, Audio=9, Story=7, Characters=8, Enjoyment=9, Bonus=10,
        )
        score = rating_scales.compute_score(
            rating_scales.active_criteria(self.scale),
            values,
        )
        self.assertEqual(score, Decimal("8.4"))

    def test_empty_criterion_is_excluded_and_zero_counts(self):
        """An empty criterion leaves the average; a real 0 pulls it down."""
        criteria = rating_scales.active_criteria(self.scale)
        without = rating_scales.compute_score(
            criteria,
            self.values(Visuals=10, Story=10),
        )
        zero = rating_scales.compute_score(
            criteria,
            self.values(Visuals=10, Story=10, Audio=0),
        )
        self.assertEqual(without, Decimal("10.0"))
        self.assertLess(zero, without)

    def test_nothing_filled_is_none(self):
        """No values means no score."""
        self.assertIsNone(
            rating_scales.compute_score(rating_scales.active_criteria(self.scale), {}),
        )

    def test_mixed_ranges_are_normalised(self):
        """A 1-100 and a 1-5 criterion weigh the same at the same fraction."""
        scale = rating_scales.save_scale(
            self.user,
            {
                "name": "Mixed",
                "criteria": [
                    {"name": "Percent", "min": 0, "max": 100, "weight": 1},
                    {"name": "Stars", "min": 1, "max": 5, "weight": 1},
                ],
            },
        )
        ids = {c.name: str(c.id) for c in scale.criteria.all()}
        score = rating_scales.compute_score(
            rating_scales.active_criteria(scale),
            {ids["Percent"]: 100, ids["Stars"]: 1},
        )
        self.assertEqual(score, Decimal("5.0"))


class ScaleLifecycleTests(ScaleTestCase):
    """Editing and deleting never destroy saved ratings."""

    def test_validation(self):
        """Bad ranges, empty names and tier gaps are rejected."""
        bad = [
            {"name": "", "criteria": ANIME_SCALE["criteria"]},
            {"name": "x", "criteria": []},
            {"name": "x", "criteria": [{"name": "a", "min": 5, "max": 5, "weight": 1}]},
            {"name": "x", "criteria": [{"name": "a", "min": 0, "max": 5, "weight": 2}]},
        ]
        for data in bad:
            with self.assertRaises(RatingScaleError):
                rating_scales.save_scale(self.user, data)

    def test_rename_and_reorder_keep_criterion_ids(self):
        """Saved ratings stay attached when criteria are renamed or moved tier."""
        data = rating_scales.scale_payload(self.scale)
        data["criteria"][0]["name"] = "Art"
        data["criteria"][0]["weight"] = 2
        data["criteria"][2]["weight"] = 1
        saved = rating_scales.save_scale(self.user, data, scale=self.scale)
        ids = {str(c.id) for c in saved.criteria.all()}
        self.assertEqual(ids, set(self.by_name.values()))

    def test_removed_criterion_is_archived(self):
        """A criterion dropped from the editor is archived, not deleted."""
        data = rating_scales.scale_payload(self.scale)
        dropped = data["criteria"].pop()
        saved = rating_scales.save_scale(self.user, data, scale=self.scale)
        self.assertEqual(len(rating_scales.active_criteria(saved)), 5)
        self.assertTrue(saved.criteria.filter(id=dropped["id"]).exists())

    def test_delete_archives_when_ratings_exist(self):
        """A scale with ratings is archived; an unused one is deleted."""
        item = Item.objects.create(
            media_id="1",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="A",
            image="http://example.com/i.jpg",
        )
        anime = Anime.objects.create(item=item, user=self.user, status=Status.COMPLETED.value)
        self.user.custom_rating_scale = self.scale
        rating_scales.save_entry_rating(
            self.user, anime, {self.by_name["Story"]: Decimal(5)}, Decimal("5.0"), manual=False,
        )
        self.assertEqual(rating_scales.delete_scale(self.user, self.scale), "archived")
        self.user.refresh_from_db()
        self.assertIsNone(self.user.custom_rating_scale)
        self.assertEqual(rating_scales.get_entry_rating(anime).computed_score, Decimal("5.0"))
        spare = rating_scales.save_scale(self.user, {"name": "S", "criteria": [{"name": "a", "min": 0, "max": 5, "weight": 1}]})
        self.assertEqual(rating_scales.delete_scale(self.user, spare), "deleted")


class FormSaveTests(ScaleTestCase):
    """The track form derives the score and keeps manual overrides."""

    def setUp(self):
        """Activate the scale and create an anime entry."""
        super().setUp()
        self.user.custom_rating_scale = self.scale
        self.user.save()
        item = Item.objects.create(
            media_id="1",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="A",
            image="http://example.com/i.jpg",
        )
        self.anime = Anime.objects.create(
            item=item, user=self.user, status=Status.COMPLETED.value, score=3,
        )

    def post(self, extra):
        """Save the entry through the form."""
        data = {
            "media_id": "1",
            "source": Sources.MAL.value,
            "media_type": MediaTypes.ANIME.value,
            "user": self.user.id,
            "status": Status.COMPLETED.value,
            "progress": 0,
            "criteria_submitted": "1",
            **extra,
        }
        form = AnimeForm(data=data, instance=self.anime, user=self.user)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.anime.refresh_from_db()
        return form

    def test_score_follows_criteria(self):
        """The stored score is the calculated one and the values persist."""
        self.post({f"criterion:{self.by_name['Visuals']}": "8", f"criterion:{self.by_name['Story']}": "6"})
        self.assertEqual(self.anime.score, Decimal("6.7"))
        row = rating_scales.get_entry_rating(self.anime)
        self.assertFalse(row.is_manual)
        self.assertEqual(row.computed_score, Decimal("6.7"))

    def test_manual_override_keeps_computed(self):
        """A manual score wins but the calculated one is stored beside it."""
        self.post({
            f"criterion:{self.by_name['Visuals']}": "8",
            "score": "9",
            "score_is_manual": "1",
        })
        self.assertEqual(self.anime.score, Decimal("9.0"))
        row = rating_scales.get_entry_rating(self.anime)
        self.assertTrue(row.is_manual)
        self.assertEqual(row.computed_score, Decimal("8.0"))
        payload = rating_scales.entry_payload(self.user, self.anime)
        self.assertTrue(payload["manual"])
        self.post({f"criterion:{self.by_name['Visuals']}": "8"})
        self.assertEqual(self.anime.score, Decimal("8.0"))

    def test_out_of_range_value_is_rejected(self):
        """A value outside its criterion's range is a form error."""
        form = AnimeForm(
            data={
                "media_id": "1", "source": Sources.MAL.value,
                "media_type": MediaTypes.ANIME.value, "user": self.user.id,
                "status": Status.COMPLETED.value, "progress": 0,
                "criteria_submitted": "1",
                f"criterion:{self.by_name['Visuals']}": "11",
            },
            instance=self.anime,
            user=self.user,
        )
        self.assertFalse(form.is_valid())

    def test_built_in_scale_is_unchanged(self):
        """Without a custom scale the form behaves exactly as before."""
        self.user.custom_rating_scale = None
        self.user.rating_scale = "5"
        self.user.save()
        form = AnimeForm(
            data={
                "media_id": "1", "source": Sources.MAL.value,
                "media_type": MediaTypes.ANIME.value, "user": self.user.id,
                "status": Status.COMPLETED.value, "progress": 0, "score": "4",
            },
            instance=self.anime,
            user=self.user,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.anime.refresh_from_db()
        self.assertEqual(self.anime.score, Decimal("8.0"))
        self.assertIsNone(rating_scales.get_entry_rating(self.anime))


class ApiTests(ScaleTestCase):
    """The preference, scale and entry endpoints."""

    def setUp(self):
        """Sign in and track an anime."""
        super().setUp()
        self.client.force_login(self.user)
        patcher = patch(
            "api.views.services.get_media_metadata",
            return_value={"max_progress": None, "related": {"seasons": [], "recommendations": []}, "episodes": []},
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        item = Item.objects.create(
            media_id="9", source=Sources.MAL.value, media_type=MediaTypes.ANIME.value,
            title="B", image="http://example.com/i.jpg",
        )
        self.anime = Anime.objects.create(
            item=item, user=self.user, status=Status.COMPLETED.value, score=6,
        )

    def test_scale_crud_and_preference(self):
        """Create, select, edit and delete a scale through the API."""
        body = {"name": "Mine", "criteria": [{"name": "A", "min": 1, "max": 5, "weight": 1}]}
        created = self.client.post("/api/v1/user/rating-scales/", body, content_type="application/json")
        self.assertEqual(created.status_code, 201, created.content)
        scale_id = created.json()["id"]
        patched = self.client.patch(
            "/api/v1/user/preferences/", {"custom_rating_scale": scale_id}, content_type="application/json",
        )
        self.assertEqual(patched.json()["preferences"]["custom_rating_scale"], scale_id)
        self.assertEqual(len(patched.json()["preferences"]["rating_scales"]), 2)
        builtin = self.client.patch("/api/v1/user/preferences/", {"rating_scale": "5"}, content_type="application/json")
        self.assertIsNone(builtin.json()["preferences"]["custom_rating_scale"])
        bad = self.client.patch(
            "/api/v1/user/preferences/", {"custom_rating_scale": "00000000-0000-0000-0000-000000000000"},
            content_type="application/json",
        )
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.client.delete(f"/api/v1/user/rating-scales/{scale_id}/").json()["result"], "deleted")

    def test_patch_media_with_criteria_and_flat_override(self):
        """A criteria body sets the score; a later flat score is a manual override."""
        self.user.custom_rating_scale = self.scale
        self.user.save()
        url = f"/api/v1/media/anime/mal/{self.anime.item.media_id}/"
        body = {"criteria": {self.by_name["Visuals"]: 8, self.by_name["Story"]: 6}}
        response = self.client.patch(url, body, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.anime.refresh_from_db()
        self.assertEqual(self.anime.score, Decimal("6.7"))
        breakdown = response.json()["consumptions"][0]["criteria"]
        self.assertEqual(breakdown["computed_score"], 6.7)
        self.assertFalse(breakdown["score_is_manual"])
        self.assertEqual(sorted(c["label"] for c in breakdown["criteria"])[0], "Audio")
        self.client.patch(url, {"score": 9}, content_type="application/json")
        self.anime.refresh_from_db()
        row = rating_scales.get_entry_rating(self.anime)
        self.assertEqual(self.anime.score, Decimal("9.0"))
        self.assertTrue(row.is_manual)
        self.assertEqual(row.computed_score, Decimal("6.7"))
        out_of_range = self.client.patch(
            url, {"criteria": {self.by_name["Visuals"]: 99}}, content_type="application/json",
        )
        self.assertEqual(out_of_range.status_code, 400)

    def test_historical_score_survives_empty_criteria(self):
        """Saving with no criteria values keeps a score from before the scale."""
        self.user.custom_rating_scale = self.scale
        self.user.save()
        url = f"/api/v1/media/anime/mal/{self.anime.item.media_id}/"
        self.client.patch(url, {"criteria": {}, "notes": "x"}, content_type="application/json")
        self.anime.refresh_from_db()
        self.assertEqual(self.anime.score, Decimal(6))

    def test_chip_endpoint_with_criteria(self):
        """The detail chip posts criterion values and gets the calculated score."""
        self.user.custom_rating_scale = self.scale
        self.user.save()
        response = self.client.post(
            self._score_url(),
            {"criteria_submitted": "1", f"criterion:{self.by_name['Audio']}": "4"},
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.anime.refresh_from_db()
        self.assertEqual(self.anime.score, Decimal("4.0"))

    def _score_url(self):
        from django.urls import reverse

        return reverse("update_media_score", args=["anime", self.anime.id])


class PreferencesPageTests(ScaleTestCase):
    """The Rating Scale menu lists custom scales and a create action."""

    def test_menu_data_is_json_script_not_inline(self):
        """Scale JSON must not be inlined in the double-quoted x-data attribute."""
        self.client.force_login(self.user)
        self.user.custom_rating_scale = self.scale
        self.user.save()
        with patch("app.providers.tmdb.watch_provider_regions", return_value=[("UNSET", "Not set")]), patch(
            "app.providers.tmdb.metadata_languages", return_value=[("", "Default")],
        ):
            html = self.client.get("/settings/preferences").content.decode()
        self.assertIn('id="rating-scales-data"', html)
        self.assertIn(f"custom:{self.scale.id}", html)
        self.assertIn("Create Rating Scale", html)

    def test_form_post_selects_and_clears_custom_scale(self):
        """Posting custom:<id> selects it; a built-in value clears it."""
        self.client.force_login(self.user)
        self.client.post("/settings/preferences", {"rating_scale": f"custom:{self.scale.id}"})
        self.user.refresh_from_db()
        self.assertEqual(self.user.custom_rating_scale_id, self.scale.id)
        self.client.post("/settings/preferences", {"rating_scale": "5"})
        self.user.refresh_from_db()
        self.assertIsNone(self.user.custom_rating_scale_id)
        self.assertEqual(self.user.rating_scale, "5")


class HalfStarStorageTests(ScaleTestCase):
    """Half stars on the built-in star scales store and read back exactly (#2164)."""

    def test_half_star_round_trips_on_both_star_scales(self):
        """3.5 of 5 stores as 7.0 and 6.5 of 10 stays 6.5."""
        self.user.rating_scale = "5"
        self.assertEqual(self.user.scale_score_for_storage(Decimal("3.5")), Decimal("7.0"))
        self.assertEqual(self.user.scale_score_for_display(Decimal("7.0")), Decimal("3.5"))
        self.user.rating_scale = "10"
        self.assertEqual(self.user.scale_score_for_storage(Decimal("6.5")), Decimal("6.5"))
