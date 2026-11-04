"""Idempotency-Key replay for POST media/{media_type}/ (#1613)."""

from http import HTTPStatus as HTTP  # noqa: N814

from django.core.cache import cache

from app.models import Game

from .base import FloppyApiTestCase


class IdempotentCreateTests(FloppyApiTestCase):
    """A retried POST with the same key must not append a second play."""

    payload = {
        "source": "manual",
        "title": "Idempotent game",
        "status": 3,
        "progress": 90,
        "start_date": "2019-03-01",
        "end_date": "2019-03-07",
    }

    def setUp(self):
        """Start each test without replay records from the previous one."""
        super().setUp()
        cache.clear()

    def _post(self, payload=None, key=None):
        headers = dict(self.auth_headers)
        if key:
            headers["HTTP_IDEMPOTENCY_KEY"] = key
        return self.call_api(
            "post",
            "api_media_type_list",
            args=("game",),
            payload=payload or self.payload,
            headers=headers,
        )

    def _count(self):
        return Game.objects.filter(
            user=self.user1,
            item__title="Idempotent game",
        ).count()

    def test_create_response_names_the_consumption_and_unit(self):
        """A create reports the new consumption_id, minutes and dates."""
        response = self._post()
        self.assertEqual(response.status_code, HTTP.CREATED)
        body = response.json()
        self.assertIsNotNone(body["consumption_id"])
        self.assertEqual(body["progress_unit"], "minutes")
        self.assertEqual(body["progress_scope"], "entry")
        self.assertEqual(
            Game.objects.get(id=body["consumption_id"]).item.title,
            "Idempotent game",
        )

    def test_same_key_replays_first_success(self):
        """The retry returns the first body and writes nothing."""
        first = self._post(key="abc")
        second = self._post(key="abc")
        self.assertEqual(second.status_code, HTTP.CREATED)
        self.assertEqual(
            second.json(),
            {**first.json(), "idempotent_replayed": True},
        )
        self.assertEqual(second["Idempotent-Replayed"], "true")
        self.assertEqual(self._count(), 1)

    def test_without_key_each_post_is_independent(self):
        """No header keeps today's behaviour (the duplicate is refused or appended)."""
        self._post()
        second = self._post()
        self.assertNotIn("Idempotent-Replayed", second)

    def test_same_key_with_different_body_is_refused(self):
        """Reusing a key for another request is a client bug, not a replay."""
        self._post(key="abc")
        other = {**self.payload, "progress": 120}
        response = self._post(payload=other, key="abc")
        self.assertEqual(response.status_code, HTTP.UNPROCESSABLE_ENTITY)
        self.assertEqual(response.json()["code"], "IDEMPOTENCY_KEY_REUSED")
        self.assertEqual(self._count(), 1)

    def test_failed_write_leaves_key_reusable(self):
        """A 400 commits nothing, so the corrected retry must run."""
        bad = {"source": "manual", "title": "Idempotent game", "start_date": "nonsense"}
        self.assertEqual(self._post(payload=bad, key="k").status_code, HTTP.BAD_REQUEST)
        self.assertEqual(self._post(payload=bad, key="k").status_code, HTTP.BAD_REQUEST)

    def test_overlong_key_is_rejected(self):
        """Keys are bounded."""
        response = self._post(key="x" * 201)
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.assertEqual(response.json()["code"], "IDEMPOTENCY_KEY_INVALID")
