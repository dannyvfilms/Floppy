from django.test import TestCase
from django.template.loader import render_to_string

class StaticAssetsTest(TestCase):
    def test_no_external_cdns(self):
        """Ensure base.html does not load external CDN scripts or stylesheets."""
        # Use the test client to render a real page that extends base.html
        response = self.client.get("/users/login/")
        content = response.content.decode("utf-8")
        
        # Check for common CDNs or external HTTP calls
        self.assertNotIn("cdn.jsdelivr.net", content)
        self.assertNotIn("unpkg.com", content)
        self.assertNotIn("cdnjs.cloudflare.com", content)
        
        # Verify zxing is loaded locally
        self.assertIn("js/libraries/zxing.min.js", content)
