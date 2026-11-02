"""A failing OOB fragment must not take the rest of the save response with it."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, tag
from django.urls import reverse

from app.models import TV, Item, MediaTypes, Movie, Season, Sources, Status

# Marker present in each fragment of a successful htmx save response.
FRAGMENT_MARKERS = {
    "status pill": "data-track-action-root",
    "activity subtitle": "activity-subtitle",
    "score chip": "score-chip",
    "card rating": "media-card-rating",
    "status chip": "status-chip",
    "notes section": "detail-notes-section",
}

METADATA = {
    "media_id": "238",
    "title": "Test Movie",
    "media_type": MediaTypes.MOVIE.value,
    "source": Sources.TMDB.value,
    "image": "http://example.com/image.jpg",
    "synopsis": "Test overview",
    "max_progress": 1,
    "details": {},
    "related": {},
    "cast": [],
    "crew": [],
    "studios_full": [],
}


class SaveResponseFragmentIsolationTests(TestCase):
    """media_save composes one required pill plus independent OOB fragments."""

    def setUp(self):
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)
        self.item = Item.objects.create(
            media_id="238",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Test Movie",
        )
        Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.COMPLETED.value,
            progress=1,
            notes="a note",
        )

    def _save(self):
        return self.client.post(
            reverse("media_save"),
            {
                "media_id": "238",
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "status": Status.COMPLETED.value,
                "progress": 1,
                "repeats": 0,
                "notes": "a note",
            },
            headers={"hx-request": "true"},
        )

    @tag("slow", "benchmark")
    def test_populated_save_profiles(self):
        """Measure the real handler's synchronous completion fan-out."""
        import cProfile
        import json
        import os
        import pstats
        import time
        from pathlib import Path

        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        results = []
        original_get_item = Season.get_episode_item

        def get_item_without_preload(season, episode_number, season_metadata=None, *, existing_item=None):
            return original_get_item(season, episode_number, season_metadata)

        for media_type, count, warm_items, preload in ((MediaTypes.MOVIE.value, 0, False, True), (MediaTypes.SEASON.value, 20, False, True), (MediaTypes.TV.value, 20, False, True), (MediaTypes.TV.value, 300, False, True), (MediaTypes.TV.value, 300, True, False), (MediaTypes.TV.value, 300, True, True)):
            identifier = f"save-profile-{media_type}-{count}-{warm_items}-{preload}"
            if media_type == MediaTypes.MOVIE.value:
                instance = Movie.objects.get(item=self.item, user=self.user)
            else:
                show_item = Item.objects.create(media_id=identifier, source=Sources.TMDB.value, media_type=MediaTypes.TV.value, title="Profile Show")
                show = TV.objects.create(item=show_item, user=self.user, status=Status.PLANNING.value)
                if media_type == MediaTypes.SEASON.value:
                    season_item = Item.objects.create(media_id=identifier, source=Sources.TMDB.value, media_type=media_type, season_number=1, title="Profile Season")
                    instance = Season.objects.create(item=season_item, user=self.user, related_tv=show, status=Status.PLANNING.value)
                else:
                    instance = show
            episodes = [{"episode_number": index + 1, "title": f"Episode {index + 1}", "runtime": 45} for index in range(count)]
            if warm_items:
                Item.objects.bulk_create([
                    Item(
                        media_id=identifier, source=Sources.TMDB.value,
                        media_type=MediaTypes.EPISODE.value, library_media_type=MediaTypes.EPISODE.value, season_number=1,
                        episode_number=episode["episode_number"], runtime_minutes=45,
                        **Item.title_fields_from_episode_metadata(episode, fallback_title="Profile Show"),
                    ) for episode in episodes
                ])
            metadata = {
                **METADATA, "max_progress": count or 1, "episodes": episodes,
                "season_number": 1, "related": {"seasons": [{"season_number": 1}]},
                "season/1": {"max_progress": count, "season_number": 1, "episodes": episodes},
            }
            profile = cProfile.Profile()
            started = time.perf_counter()
            with patch("app.providers.services.get_media_metadata", return_value=metadata), patch.object(
                Season, "get_episode_item", original_get_item if preload else get_item_without_preload,
            ):
                profile.enable()
                with CaptureQueriesContext(connection) as captured:
                    response = self.client.post(reverse("media_save"), {
                        "media_id": instance.item.media_id, "source": Sources.TMDB.value,
                        "media_type": media_type, "instance_id": instance.id,
                        "season_number": 1 if media_type == MediaTypes.SEASON.value else "",
                        "status": Status.COMPLETED.value, "progress": count or 1,
                        "repeats": 0, "notes": "",
                    })
                profile.disable()
            self.assertEqual(response.status_code, 302)
            hot = sorted(
                ((key, value) for key, value in pstats.Stats(profile).stats.items() if "/src/" in key[0] and key[2] != "__call__"),
                key=lambda row: row[1][3], reverse=True,
            )[:15]
            results.append({
                "media_type": media_type, "episodes": count, "warm_items": warm_items, "preload": preload, "elapsed_seconds": time.perf_counter() - started,
                "queries": len(captured),
                "statement_counts": {
                    verb: sum(query["sql"].lstrip().startswith(verb) for query in captured)
                    for verb in ("SELECT", "INSERT", "UPDATE", "SAVEPOINT", "RELEASE")
                },
                "hot_functions": [{"file": key[0], "line": key[1], "function": key[2], "calls": value[1], "cumulative_seconds": value[3]} for key, value in hot],
            })
        if output_path := os.environ.get("FLOPPY_SAVE_PROFILE_OUTPUT"):
            Path(output_path).write_text(json.dumps(results, indent=2))

    @patch("app.views.services.get_media_metadata", return_value=METADATA)
    @patch("app.providers.services.get_media_metadata", return_value=METADATA)
    def test_healthy_save_carries_every_fragment(self, *_mocks):
        body = self._save().content.decode()
        for label, marker in FRAGMENT_MARKERS.items():
            self.assertIn(marker, body, f"{label} missing from a healthy save")

    @patch("app.views.services.get_media_metadata", return_value=METADATA)
    @patch("app.providers.services.get_media_metadata", return_value=METADATA)
    def test_one_failing_fragment_costs_only_itself(self, *_mocks):
        """The notes section is the last fragment appended.

        Before fragments were isolated, a failure here rebound the whole
        response to a bare confirmation, discarding the five fragments that had
        already rendered - and still returned 200, so the client saw most of
        the page silently not update.
        """
        with patch(
            "app.save_views._render_notes_section_oob",
            side_effect=RuntimeError("boom"),
        ):
            response = self._save()

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()

        for label, marker in FRAGMENT_MARKERS.items():
            if label == "notes section":
                self.assertNotIn(marker, body, "the failing fragment should be absent")
            else:
                self.assertIn(marker, body, f"{label} was lost to an unrelated failure")

    @patch("app.views.services.get_media_metadata", return_value=METADATA)
    @patch("app.providers.services.get_media_metadata", return_value=METADATA)
    def test_an_early_failing_fragment_does_not_stop_later_ones(self, *_mocks):
        """Isolation runs both ways: a failure first must not skip the rest."""
        with patch(
            "app.save_views._build_detail_activity_state",
            side_effect=RuntimeError("boom"),
        ):
            response = self._save()

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()

        self.assertNotIn(FRAGMENT_MARKERS["activity subtitle"], body)
        for label in ("status pill", "score chip", "card rating", "notes section"):
            self.assertIn(
                FRAGMENT_MARKERS[label],
                body,
                f"{label} was skipped after an earlier fragment failed",
            )
