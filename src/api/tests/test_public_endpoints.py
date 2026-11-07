import hashlib

from django.conf import settings
from django.urls import reverse

from .base import FloppyApiTestCase
from .helpers import check_health_structure, check_info_structure


class PublicEndpointsTests(FloppyApiTestCase):
    """Verify public endpoints stay accessible without auth."""

    def test_health_endpoint(self):
        """Health endpoint test."""
        response = self.call_api("get", "api_health")

        self.assertIn(response.status_code, [200, 500])
        payload = response.json()
        check_health_structure(self, payload)

    def test_info_endpoint(self):
        """Info endpoint test."""
        response = self.call_api("get", "api_info")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        check_info_structure(self, payload)
        self.assertEqual(
            set(payload),
            {
                "version",
                "debug",
                "frontend_url",
                "language",
                "timezone",
                "admin_enabled",
                "track_time",
            },
        )

    def test_openapi_endpoints_are_public(self):
        for route_name in (
            "schema",
            "swagger-ui",
            "openapi-contract",
            "jsonld-context",
            "asyncapi-contract",
        ):
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)

    def test_schema_endpoint_content_negotiation(self):
        url = reverse("schema")

        default = self.client.get(url)
        self.assertEqual(default.status_code, 200)
        self.assertEqual(default["Content-Type"], "text/yaml; charset=utf-8")

        for accept, expected_content_type in (
            ("application/json", "application/json"),
            ("application/yaml", "application/yaml; charset=utf-8"),
            ("application/vnd.oai.openapi+json", "application/vnd.oai.openapi+json"),
        ):
            with self.subTest(accept=accept):
                response = self.client.get(url, HTTP_ACCEPT=accept)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], expected_content_type)

    def test_contracts_support_explicit_download(self):
        for name, expected in (
            ("openapi-contract", 'attachment; filename="openapi.yaml"'),
            ("jsonld-context", 'attachment; filename="context.jsonld"'),
            ("asyncapi-contract", 'attachment; filename="asyncapi.json"'),
        ):
            with self.subTest(name=name):
                response = self.client.get(reverse(name), {"download": "1"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Disposition"], expected)

    def test_openapi_contract_supports_public_cache_validation(self):
        artifact = (
            settings.BASE_DIR / "api" / "contracts" / "openapi.yaml"
        ).read_bytes()
        expected_etag = f'"{hashlib.sha256(artifact).hexdigest()}"'
        url = reverse("openapi-contract")

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/yaml; charset=utf-8")
        self.assertEqual(
            response["Content-Disposition"], 'inline; filename="openapi.yaml"'
        )
        self.assertEqual(response["Cache-Control"], "public, max-age=3600")
        self.assertEqual(response["ETag"], expected_etag)
        self.assertEqual(int(response["Content-Length"]), len(artifact))
        self.assertEqual(b"".join(response.streaming_content), artifact)

        head = self.client.head(url)
        self.assertEqual(head.status_code, 200)
        self.assertEqual(b"".join(head.streaming_content), b"")
        self.assertEqual(head["Content-Length"], response["Content-Length"])
        self.assertEqual(head["Cache-Control"], response["Cache-Control"])
        self.assertEqual(head["ETag"], expected_etag)

        not_modified = self.client.get(url, HTTP_IF_NONE_MATCH=expected_etag)
        self.assertEqual(not_modified.status_code, 304)
        self.assertEqual(not_modified.content, b"")
        self.assertEqual(not_modified["ETag"], expected_etag)

        head_not_modified = self.client.head(url, HTTP_IF_NONE_MATCH=expected_etag)
        self.assertEqual(head_not_modified.status_code, 304)
        self.assertEqual(head_not_modified.content, b"")
        self.assertEqual(head_not_modified["ETag"], expected_etag)

        changed = self.client.get(url, HTTP_IF_NONE_MATCH='"different"')
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(b"".join(changed.streaming_content), artifact)

    def test_protected_data_endpoint_remains_private(self):
        response = self.client.get(reverse("api_media_list"))

        self.assertIn(response.status_code, (401, 403))
