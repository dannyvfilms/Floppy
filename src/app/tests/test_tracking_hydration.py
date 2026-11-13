from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError
from django.test import TestCase

from app import view_constants
from app.models import (
    Item,
    MediaTypes,
    MetadataBackfillField,
    MetadataBackfillState,
    MetadataProviderPreference,
    Movie,
    Sources,
    Status,
)
from app.services import tracking_hydration
from app.tasks_backfill_state import WATCH_PROVIDERS_BACKFILL_VERSION


class TrackingHydrationTests(TestCase):
    @patch("app.services.tracking_hydration.credits.sync_item_credits_from_metadata")
    @patch("app.services.tracking_hydration.upsert_provider_links")
    @patch("app.services.tracking_hydration.services.get_media_metadata")
    def test_tracking_refresh_preserves_spanish_titles_and_library_search(
        self,
        mock_metadata,
        _mock_links,
        _mock_credits,
    ):
        user = get_user_model().objects.create_user(
            username="spanish",
            metadata_language="es-ES",
        )
        item = Item.objects.create(
            media_id="238",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="El padrino",
            localized_title="El padrino",
            original_title="The Godfather",
        )
        Movie.objects.create(
            user=user, item=item, status=Status.PLANNING.value, progress=0
        )

        def fetch(*args, **kwargs):
            spanish = kwargs.get("language") in {"es-ES", "es-MX"}
            return {
                "title": "El padrino" if spanish else "The Godfather",
                "original_title": "The Godfather",
                "image": "https://example.com/poster.jpg",
                "details": {},
                "related": {},
            }

        mock_metadata.side_effect = fetch
        for override in ("", "es-MX"):
            with self.subTest(override=override):
                MetadataProviderPreference.objects.update_or_create(
                    user=user,
                    item=item,
                    defaults={"language": override},
                )
                tracking_hydration.ensure_item_metadata(
                    user,
                    item.media_type,
                    item.media_id,
                    item.source,
                )
                self.assertEqual(
                    mock_metadata.call_args.kwargs["language"],
                    override or "es-ES",
                )
                item.refresh_from_db()
                self.assertEqual(item.localized_title, "El padrino")
        from app.search_views import get_saved_suggestions

        for query in ("padrino", "godfather"):
            with self.subTest(query=query):
                results = get_saved_suggestions(user, item.media_type, query)
                self.assertEqual(len(results), 1)

    @patch("app.services.tracking_hydration.credits.sync_item_credits_from_metadata")
    @patch("app.services.tracking_hydration.upsert_provider_links")
    @patch("app.services.tracking_hydration.services.get_media_metadata")
    def test_ensure_item_metadata_preserves_tmdb_tv_anime_genre_supplement(
        self,
        mock_get_media_metadata,
        _mock_upsert_provider_links,
        _mock_sync_item_credits,
    ):
        item = Item.objects.create(
            media_id="2001",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Tracked Anime Show",
            image="https://example.com/tracked-anime-show.jpg",
            genres=["Comedy", "Anime"],
        )
        mock_get_media_metadata.return_value = {
            "media_id": item.media_id,
            "source": Sources.TMDB.value,
            "media_type": MediaTypes.TV.value,
            "title": item.title,
            "image": item.image,
            "genres": ["Comedy"],
            "details": {},
            "related": {},
        }

        result = tracking_hydration.ensure_item_metadata(
            None,
            MediaTypes.TV.value,
            item.media_id,
            Sources.TMDB.value,
        )

        item.refresh_from_db()
        self.assertFalse(result.created)
        self.assertEqual(item.genres, ["Comedy", "Anime"])

    @patch("app.services.tracking_hydration.credits.sync_item_credits_from_metadata")
    @patch("app.services.tracking_hydration.upsert_provider_links")
    @patch("app.services.tracking_hydration.services.get_media_metadata")
    def test_ensure_item_metadata_stores_anime_episode_count(
        self,
        mock_get_media_metadata,
        _mock_upsert_provider_links,
        _mock_sync_item_credits,
    ):
        mock_get_media_metadata.return_value = {
            "media_id": "437",
            "source": Sources.MAL.value,
            "media_type": MediaTypes.ANIME.value,
            "title": "Perfect Blue",
            "image": "https://example.com/perfect-blue.jpg",
            "max_progress": 12,
            "details": {"episodes": 12, "runtime": "24 min", "status": "Finished"},
            "related": {},
        }

        result = tracking_hydration.ensure_item_metadata(
            None,
            MediaTypes.ANIME.value,
            "437",
            Sources.MAL.value,
        )

        result.item.refresh_from_db()
        self.assertEqual(result.item.provider_episode_count, 12)
        self.assertEqual(result.item.runtime_minutes, 24)

    @patch("app.services.tracking_hydration.credits.sync_item_credits_from_metadata")
    @patch("app.services.tracking_hydration.upsert_provider_links")
    @patch("app.services.tracking_hydration.services.get_media_metadata")
    def test_ensure_item_metadata_always_passes_a_list_of_season_numbers(
        self,
        mock_get_media_metadata,
        _mock_upsert_provider_links,
        _mock_sync_item_credits,
    ):
        """season_numbers must always be a list, never a bare None.

        Regression test for GitHub issue #323: a bare `None` reaching
        tvdb.tv_with_seasons crashes with TypeError: 'NoneType' object is not
        iterable. season_number=None should still produce `[None]`, matching
        every other caller of get_media_metadata in the codebase.
        """
        mock_get_media_metadata.return_value = {
            "media_id": "388593",
            "source": Sources.TVDB.value,
            "media_type": MediaTypes.SEASON.value,
            "title": "Horimiya",
            "image": "https://example.com/horimiya.jpg",
            "genres": [],
            "details": {},
            "related": {},
        }

        # A season Item without a resolvable season_number is rejected by the
        # season_number_required_for_season DB constraint further down this
        # function - that's expected and unrelated to this regression. What
        # matters here is that get_media_metadata was reached and called with
        # a list, not that a bare None crashed it beforehand.
        with self.assertRaises(IntegrityError):
            tracking_hydration.ensure_item_metadata(
                None,
                MediaTypes.SEASON.value,
                "388593",
                Sources.TVDB.value,
                None,
            )

        self.assertEqual(
            mock_get_media_metadata.call_args.args[3],
            [None],
        )

    @patch("app.services.tracking_hydration.credits.sync_item_credits_from_metadata")
    @patch("app.services.tracking_hydration.upsert_provider_links")
    def test_ensure_item_metadata_persists_watch_providers(
        self,
        _mock_upsert_provider_links,
        _mock_sync_item_credits,
    ):
        """TMDB provider payload should be stored on create so Smart Lists can match."""
        result = tracking_hydration.ensure_item_metadata(
            None,
            MediaTypes.TV.value,
            "125988",
            Sources.TMDB.value,
            prefetched_metadata={
                "media_id": "125988",
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.TV.value,
                "title": "Cape Fear",
                "image": "https://example.com/cape-fear.jpg",
                "genres": [],
                "details": {},
                "related": {},
                "providers": {
                    "US": {
                        "flatrate": [
                            {"provider_id": 350, "provider_name": "Apple TV"},
                        ],
                    },
                },
            },
        )

        self.assertTrue(result.created)
        self.assertEqual(
            result.item.watch_providers["US"]["flatrate"][0]["provider_name"],
            "Apple TV",
        )

    @patch("app.services.tracking_hydration.credits.sync_item_credits_from_metadata")
    @patch("app.services.tracking_hydration.upsert_provider_links")
    def test_ensure_item_metadata_schedules_retry_when_providers_are_empty(
        self,
        _mock_upsert_provider_links,
        _mock_sync_item_credits,
    ):
        """Empty TMDB providers must stay in the retry queue, not count as done."""
        result = tracking_hydration.ensure_item_metadata(
            None,
            MediaTypes.TV.value,
            "125989",
            Sources.TMDB.value,
            prefetched_metadata={
                "media_id": "125989",
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.TV.value,
                "title": "No Providers Yet",
                "image": "https://example.com/no-providers.jpg",
                "genres": [],
                "details": {},
                "related": {},
                "providers": {},
            },
        )

        self.assertTrue(result.created)
        self.assertEqual(result.item.watch_providers, {})
        state = MetadataBackfillState.objects.get(
            item=result.item,
            field=MetadataBackfillField.WATCH_PROVIDERS,
        )
        self.assertIsNone(state.last_success_at)
        self.assertFalse(state.give_up)
        self.assertEqual(state.fail_count, 1)
        self.assertIsNotNone(state.next_retry_at)
        self.assertEqual(state.strategy_version, WATCH_PROVIDERS_BACKFILL_VERSION)

    @patch("app.services.tracking_hydration.credits.sync_item_credits_from_metadata")
    @patch("app.services.tracking_hydration.upsert_provider_links")
    def test_ensure_item_metadata_forces_live_metadata_on_next_detail_view(
        self,
        _mock_upsert_provider_links,
        _mock_sync_item_credits,
    ):
        """After a live fetch, the detail view must not serve the stored-metadata
        fallback on the page load(s) that follow.

        Regression test for GitHub issue #992: Discover's "planning" bookmark for
        a movie calls ensure_item_metadata, which persists metadata_fetched_at
        without setting the force_live_metadata cache flag - so the next detail
        page view took the impoverished Item-only fallback (cast/recommendations
        gone) instead of a live fetch. TV/anime were unaffected because their
        Discover path never sets metadata_fetched_at. See also #931.
        """
        result = tracking_hydration.ensure_item_metadata(
            None,
            MediaTypes.MOVIE.value,
            "603692",
            Sources.TMDB.value,
            prefetched_metadata={
                "media_id": "603692",
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "title": "John Wick: Chapter 4",
                "image": "https://example.com/john-wick-4.jpg",
                "genres": [],
                "details": {},
                "related": {},
            },
        )

        self.assertTrue(result.created)
        self.assertIsNotNone(result.item.metadata_fetched_at)
        self.assertTrue(
            cache.get(
                view_constants.force_live_metadata_cache_key(result.item.id),
            ),
        )
