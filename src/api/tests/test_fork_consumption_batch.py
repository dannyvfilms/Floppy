from datetime import UTC, datetime
from unittest.mock import patch

from app.models import ConsumptionBatchItem, Game, Item, MediaTypes, Sources
from app.providers import services
from app.tasks_bulk_plays import bulk_consumption_batch_task

from .base import FloppyApiTestCase


def _metadata(media_id, title="A Game"):
    return {
        "media_id": media_id,
        "source": Sources.IGDB.value,
        "media_type": MediaTypes.GAME.value,
        "title": title,
        "image": "https://example.com/cover.jpg",
        "max_progress": 600,
    }


def _spec(ref, media_id, **extra):
    spec = {
        "client_ref": ref,
        "media_type": MediaTypes.GAME.value,
        "source": Sources.IGDB.value,
        "media_id": media_id,
        "status": "Completed",
        "start_date": "2010-03-01",
        "end_date": "2010-03-20",
        "progress": 600,
    }
    spec.update(extra)
    return spec


class ConsumptionBatchTests(FloppyApiTestCase):
    """Dry-run and execution of consumption batches (#1614)."""

    def setUp(self):
        super().setUp()
        patcher = patch(
            "api.consumption_create.services.get_media_metadata",
            side_effect=lambda media_type, media_id, *a, **kw: _metadata(media_id),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _post(self, payload):
        return self.call_api(
            "post",
            "api_consumption_batch",
            payload=payload,
            headers=self.auth_headers,
        )

    def _track(self, media_id, **fields):
        item = Item.objects.create(
            media_id=media_id,
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title="A Game",
        )
        return Game.objects.create(item=item, user=self.user1, **fields)

    def test_dry_run_reports_each_outcome_and_writes_nothing(self):
        self._track(
            "2",
            status="Completed",
            start_date=datetime(2010, 3, 5, tzinfo=UTC),
            end_date=datetime(2010, 3, 10, tzinfo=UTC),
        )
        self._track(
            "3",
            status="Completed",
            start_date=datetime(2026, 10, 1, tzinfo=UTC),
            end_date=datetime(2026, 10, 2, tzinfo=UTC),
        )
        before = (Item.objects.count(), Game.objects.count())

        def metadata(media_type, media_id, *args, **kwargs):
            if media_id == "6":
                raise services.ProviderAPIError(Sources.IGDB.value, Exception("down"))
            return _metadata(media_id)

        with patch(
            "api.consumption_create.services.get_media_metadata", side_effect=metadata
        ):
            response = self._post(
                {
                    "items": [
                        _spec("new", "1"),
                        _spec("hist", "2", skip_if_existing={"overlaps": True}),
                        _spec("recent", "3", skip_if_existing={"overlaps": True}),
                        _spec("bad", "4", end_date="not-a-date"),
                        _spec("down", "6"),
                    ],
                },
            )

        self.assertEqual(response.status_code, 200)
        outcomes = {r["client_ref"]: r["outcome"] for r in response.json()["results"]}
        self.assertEqual(
            outcomes,
            {
                "new": "would_create",
                "hist": "skip",
                "recent": "would_append",
                "bad": "invalid",
                "down": "unavailable",
            },
        )
        recent = next(
            r for r in response.json()["results"] if r["client_ref"] == "recent"
        )
        self.assertEqual(len(recent["existing"]), 1)
        self.assertEqual((Item.objects.count(), Game.objects.count()), before)
        self.assertFalse(ConsumptionBatchItem.objects.exists())

    def test_execute_creates_once_and_rerun_is_idempotent(self):
        payload = {
            "operation_id": "op-1",
            "execute": True,
            "items": [_spec("a", "10"), _spec("b", "11")],
        }
        response = self._post(payload)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(
            Game.objects.filter(
                user=self.user1,
                item__source=Sources.IGDB.value,
                item__media_id__in=["10", "11", "30", "31"],
            ).count(),
            2,
        )

        detail = self.call_api(
            "get",
            "api_consumption_batch_detail",
            args=("op-1",),
            headers=self.auth_headers,
        )
        self.assertEqual(detail.json()["counts"], {"created": 2})
        game = Game.objects.get(item__media_id="10")
        self.assertEqual(game.progress, 600)

        again = self._post(payload)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(
            Game.objects.filter(
                user=self.user1,
                item__source=Sources.IGDB.value,
                item__media_id__in=["10", "11", "30", "31"],
            ).count(),
            2,
        )

    def test_changed_payload_for_same_operation_conflicts(self):
        self._post(
            {"operation_id": "op-2", "execute": True, "items": [_spec("a", "10")]}
        )
        response = self._post(
            {
                "operation_id": "op-2",
                "execute": True,
                "items": [_spec("a", "10", progress=1)],
            },
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "idempotency_conflict")
        self.assertEqual(
            Game.objects.filter(
                user=self.user1,
                item__source=Sources.IGDB.value,
                item__media_id__in=["10", "11", "30", "31"],
            ).count(),
            1,
        )

    def test_partial_failure_keeps_good_items(self):
        response = self._post(
            {
                "operation_id": "op-3",
                "execute": True,
                "items": [_spec("good", "20"), _spec("bad", "21", end_date="nope")],
            },
        )
        self.assertEqual(response.status_code, 202)
        detail = self.call_api(
            "get",
            "api_consumption_batch_detail",
            args=("op-3",),
            headers=self.auth_headers,
        ).json()
        self.assertEqual(detail["counts"], {"created": 1, "failed": 1}, detail)
        self.assertTrue(Game.objects.filter(item__media_id="20").exists())
        self.assertFalse(Game.objects.filter(item__media_id="21").exists())

    def test_interrupted_run_finishes_on_resubmit_without_duplicates(self):
        items = [_spec("a", "30"), _spec("b", "31")]
        for ref, spec in (("a", items[0]), ("b", items[1])):
            from api.consumption_batch import item_digest

            ConsumptionBatchItem.objects.create(
                user=self.user1,
                operation_id="op-4",
                client_ref=ref,
                payload_digest=item_digest(spec),
            )
        # A worker died after claiming "a" but before committing.
        ConsumptionBatchItem.objects.filter(client_ref="a").update(outcome="running")
        from datetime import timedelta

        from django.utils import timezone

        ConsumptionBatchItem.objects.filter(client_ref="a").update(
            updated_at=timezone.now() - timedelta(hours=1),
        )
        results = {
            r["client_ref"]: r["outcome"]
            for r in __import__(
                "api.consumption_batch", fromlist=["x"]
            ).operation_results(
                self.user1,
                "op-4",
            )
        }
        self.assertEqual(results["a"], "interrupted")

        response = self._post({"operation_id": "op-4", "execute": True, "items": items})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(
            Game.objects.filter(
                user=self.user1,
                item__source=Sources.IGDB.value,
                item__media_id__in=["10", "11", "30", "31"],
            ).count(),
            2,
        )

        bulk_consumption_batch_task.apply(
            kwargs={"user_id": self.user1.id, "operation_id": "op-4", "items": items},
        )
        self.assertEqual(
            Game.objects.filter(
                user=self.user1,
                item__source=Sources.IGDB.value,
                item__media_id__in=["10", "11", "30", "31"],
            ).count(),
            2,
        )

    def test_limits_and_validation(self):
        self.assertEqual(self._post({"items": []}).status_code, 400)
        self.assertEqual(
            self._post({"execute": True, "items": [_spec("a", "1")]}).status_code,
            400,
        )
        self.assertEqual(
            self._post({"items": [_spec("a", "1"), _spec("a", "2")]}).status_code,
            400,
        )
        with self.settings(CONSUMPTION_BATCH_MAX_ITEMS=1):
            response = self._post({"items": [_spec("a", "1"), _spec("b", "2")]})
        self.assertEqual(response.status_code, 400)

    def test_unauthenticated_is_rejected(self):
        response = self.call_api("post", "api_consumption_batch", payload={"items": []})
        self.assertIn(response.status_code, (401, 403))
