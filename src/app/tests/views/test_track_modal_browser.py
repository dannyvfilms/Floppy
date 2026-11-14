"""Browser coverage for track-modal date autofill preferences."""

import os
import re
from unittest.mock import patch
from urllib.parse import parse_qs

from django.contrib.auth import get_user_model
from django.test import tag
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from app.models import Item, MediaTypes, Movie, Sources, Status
from app.tests.live_server import SerialStaticLiveServerTestCase


@tag("slow", "playwright")
class TrackModalEndDatePreferenceBrowserTests(SerialStaticLiveServerTestCase):
    """Exercise the real Alpine media form date-defaulting behavior."""

    @classmethod
    def setUpClass(cls):
        """Start Chromium with the synchronous ORM guard scoped to its lifetime."""
        super().setUpClass()
        cls.async_override = patch.dict(
            os.environ,
            {"DJANGO_ALLOW_ASYNC_UNSAFE": "true"},
        )
        cls.async_override.start()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        """Close Chromium before restoring Django's async guard."""
        cls.browser.close()
        cls.playwright.stop()
        cls.async_override.stop()
        super().tearDownClass()

    def setUp(self):
        """Open the settings page so the real base scripts initialize Alpine."""
        self.user = get_user_model().objects.create_user(username="end-date-browser")
        self.client.force_login(self.user)
        self.context = self.browser.new_context(service_workers="block")
        self.addCleanup(self.context.close)
        self.context.add_cookies([{
            "name": "sessionid",
            "value": self.client.cookies["sessionid"].value,
            "url": self.live_server_url,
        }])
        self.page = self.context.new_page()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.regions_patch = patch("users.views.tmdb.watch_provider_regions", return_value=[])
        self.languages_patch = patch("users.views.tmdb.metadata_languages", return_value=[])
        self.regions_patch.start()
        self.languages_patch.start()
        self.addCleanup(self.regions_patch.stop)
        self.addCleanup(self.languages_patch.stop)
        response = self.page.goto(f"{self.live_server_url}/settings/preferences")
        self.assertEqual(response.status, 200)
        self.page.wait_for_function(
            "window.Alpine && typeof window.Alpine.initTree === 'function'",
        )

    def test_no_end_date_preference_suppresses_submit_autofill(self):
        """No End Date suppresses automatic dates; the current-date default remains."""
        results = self.page.evaluate("""() => {
          const shouldFill = (preference, status) => {
            const form = document.createElement('form');
            form.dataset.defaultEditEntryDate = preference;
            form.setAttribute('x-data', 'mediaForm');
            form.setAttribute('x-init', 'init()');
            form.innerHTML = `<input type="hidden" name="instance_id" value="">
              <select name="status"><option value="${status}" selected>${status}</option></select>
              <input type="datetime-local" name="start_date">
              <input type="datetime-local" name="end_date">
              <input type="text" name="progress" value="">
              <input type="hidden" name="start_date_cleared">`;
            document.body.append(form);
            window.Alpine.initTree(form);
            form.addEventListener('submit', event => event.preventDefault());
            form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
            const filled = Boolean(form.querySelector('[name="end_date"]').value);
            form.remove();
            return filled;
          };
          return ['Completed', 'In progress'].map(status => [
            shouldFill('current_date', status),
            shouldFill('no_date', status),
          ]);
        }""")

        self.assertEqual(results, [[True, False], [True, False]])
        self.assertEqual(self.errors, [])

    def test_shared_track_dialog_saves_completed_entry_without_end_date(self):
        """The React-owned track dialog honors the account's No End Date choice."""
        self.user.default_edit_entry_date = "no_date"
        self.user.save(update_fields=["default_edit_entry_date"])
        metadata_patch = patch(
            "app.providers.services.get_media_metadata",
            return_value={
                "max_progress": 1,
                "cast": [],
                "crew": [],
                "studios_full": [],
            },
        )
        languages_patch = patch("app.track_modal_views.tmdb.metadata_languages", return_value=[])
        releases_patch = patch("app.models.Item.fetch_releases", return_value=[])
        cover_search_patch = patch("app.cover_views.services.search", return_value={"results": []})
        for patcher in (metadata_patch, languages_patch, releases_patch, cover_search_patch):
            patcher.start()
            self.addCleanup(patcher.stop)
        item = Item.objects.create(
            media_id="238",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Date Preference Movie",
            image="http://example.com/movie.jpg",
        )
        movie = Movie.objects.create(
            item=item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
            progress=0,
        )

        modal_url = reverse(
            "track_modal",
            kwargs={
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "media_id": "238",
            },
        ) + f"?instance_id={movie.pk}"
        status_code = self.page.evaluate("""async url => {
          const response = await fetch(url, { headers: { 'HX-Request': 'true' } });
          const wrapper = document.createElement('div');
          wrapper.innerHTML = await response.text();
          document.body.append(wrapper);
          window.Alpine.initTree(wrapper);
          return response.status;
        }""", modal_url)
        self.assertEqual(status_code, 200)
        status = self.page.get_by_role("button", name=re.compile(r"^Status: "))
        expect(status).to_be_visible()
        status.click()
        self.page.get_by_role("radio", name="Completed", exact=True).click()
        with self.page.expect_response(
            lambda response: response.request.method == "POST"
            and "/media_save" in response.url,
        ) as saved:
            self.page.get_by_role("button", name="Update", exact=True).click()
        self.assertEqual(saved.value.status, 200)
        posted_end_date = parse_qs(
            saved.value.request.post_data or "",
            keep_blank_values=True,
        ).get("end_date")
        self.assertEqual(posted_end_date, [""])
        movie.refresh_from_db()
        self.assertEqual(movie.status, Status.COMPLETED.value)
        self.assertIsNone(movie.end_date)
        self.assertEqual(self.errors, [])
