from django.test import SimpleTestCase


class LocalStaticServingTests(SimpleTestCase):
    """Without nginx, Django serves /static/ for every installed app."""

    def test_serves_project_static(self):
        """The project's own files are served."""
        response = self.client.get("/static/css/main.css")

        self.assertEqual(response.status_code, 200)

    def test_serves_installed_app_static(self):
        """Form widgets load their app's static, which is not in the project directory."""
        response = self.client.get("/static/django_select2/django_select2.js")

        self.assertEqual(response.status_code, 200)

    def test_missing_file_is_not_found(self):
        """A path no finder knows is still a 404."""
        response = self.client.get("/static/js/does-not-exist.js")

        self.assertEqual(response.status_code, 404)
