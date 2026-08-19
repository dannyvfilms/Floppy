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
