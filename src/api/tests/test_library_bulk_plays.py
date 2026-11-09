from .base import FloppyApiTestCase


class LibraryBulkPlaysTests(FloppyApiTestCase):
    """Native bulk history operations retain the web option and owner rules."""

    endpoint = "/api/v1/library/bulk/plays/"

    def test_preview_returns_user_owned_operation_status(self):
        response = self.client.post(
            self.endpoint,
            {
                "item_ids": [self.items_by_type["movie"][0].id],
                "options": {"scope": "aired", "existing": "skip", "date_mode": "air_date"},
                "dry_run": True,
            },
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, 202)
        operation_id = response.data["operation_id"]
        status = self.client.get(
            f"{self.endpoint}{operation_id}/",
            **self.auth_headers,
        )
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.data["state"], "done")
        self.assertTrue(status.data["dry_run"])

    def test_invalid_options_are_rejected(self):
        response = self.client.post(
            self.endpoint,
            {"item_ids": [self.items_by_type["movie"][0].id], "options": {"scope": "unknown"}},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, 400)

