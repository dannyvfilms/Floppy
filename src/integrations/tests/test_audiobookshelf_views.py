# FORK: recurring-schedule coverage for the Audiobookshelf connect/import views.
import tempfile
from unittest.mock import Mock, patch

import requests
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django_celery_beat.models import CrontabSchedule, IntervalSchedule, PeriodicTask

from app import image_cache
from integrations import audiobookshelf_cover, views
from integrations.imports import helpers
from integrations.models import AudiobookshelfAccount

BASE_URL = "https://audiobookshelf.example.com"
API_TOKEN = "abs-secret-token"


class AudiobookshelfScheduleTests(TestCase):
    """Connecting/importing keeps a minute-based recurring schedule in sync."""

    def setUp(self):
        """Create an authenticated user for Audiobookshelf view requests."""
        self.user = get_user_model().objects.create_user(username="abs-connect")
        self.client.force_login(self.user)

    @patch("integrations.views.tasks.import_audiobookshelf.delay")
    @patch("integrations.views.AudiobookshelfClient.get_me", return_value={})
    def test_connect_creates_interval_schedule_immediately(
        self, mock_get_me, mock_import
    ):
        """Connecting (not just a manual import) schedules the recurring poll."""
        response = self.client.post(
            reverse("audiobookshelf_connect"),
            {"base_url": BASE_URL, "api_token": API_TOKEN},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            AudiobookshelfAccount.objects.filter(user=self.user).exists()
        )
        mock_import.assert_called_once()

        task = PeriodicTask.objects.get(
            task="Import from Audiobookshelf (Recurring)",
            kwargs__contains=f'"user_id": {self.user.id}',
        )
        self.assertIsNotNone(task.interval)
        self.assertIsNone(task.crontab)
        self.assertEqual(task.interval.every, 15)
        self.assertEqual(task.interval.period, IntervalSchedule.MINUTES)
        self.assertTrue(task.enabled)

    @override_settings(AUDIOBOOKSHELF_POLL_INTERVAL_MINUTES=5)
    @patch("integrations.views.tasks.import_audiobookshelf.delay")
    @patch("integrations.views.AudiobookshelfClient.get_me", return_value={})
    def test_connect_honors_configured_interval(self, mock_get_me, mock_import):
        """The polling cadence respects AUDIOBOOKSHELF_POLL_INTERVAL_MINUTES."""
        self.client.post(
            reverse("audiobookshelf_connect"),
            {"base_url": BASE_URL, "api_token": API_TOKEN},
        )

        task = PeriodicTask.objects.get(
            task="Import from Audiobookshelf (Recurring)",
            kwargs__contains=f'"user_id": {self.user.id}',
        )
        self.assertEqual(task.interval.every, 5)

    @patch("integrations.views.tasks.import_audiobookshelf.delay")
    def test_manual_import_migrates_legacy_crontab_schedule(self, mock_import):
        """A pre-existing 2-hour crontab schedule is converted, not duplicated."""
        AudiobookshelfAccount.objects.create(
            user=self.user, base_url=BASE_URL, api_token="encrypted"
        )
        crontab, _ = CrontabSchedule.objects.get_or_create(
            minute=0,
            hour="*/2",
            day_of_week="*",
            day_of_month="*",
            month_of_year="*",
        )
        PeriodicTask.objects.create(
            name=f"Import from Audiobookshelf for {self.user.username} (every 2 hours)",
            task="Import from Audiobookshelf (Recurring)",
            crontab=crontab,
            kwargs=f'{{"user_id": {self.user.id}}}',
            enabled=True,
        )

        response = self.client.post(reverse("import_audiobookshelf"))
        self.assertEqual(response.status_code, 302)

        tasks_for_user = PeriodicTask.objects.filter(
            task="Import from Audiobookshelf (Recurring)",
            kwargs__contains=f'"user_id": {self.user.id}',
        )
        self.assertEqual(tasks_for_user.count(), 1)
        task = tasks_for_user.get()
        self.assertIsNone(task.crontab)
        self.assertIsNotNone(task.interval)
        self.assertEqual(task.interval.every, 15)

    @patch("integrations.views.tasks.import_audiobookshelf.delay")
    def test_manual_import_and_disconnect_return_to_safe_provider_page(self, mock_import):
        AudiobookshelfAccount.objects.create(user=self.user, base_url=BASE_URL, api_token="encrypted")
        next_url = reverse("provider_detail", args=["audiobookshelf"]) + "?tab=import"
        response = self.client.post(reverse("import_audiobookshelf"), {"next": next_url})
        self.assertRedirects(response, next_url, fetch_redirect_response=False)
        mock_import.assert_called_once()
        response = self.client.post(reverse("audiobookshelf_disconnect"), {"next": "https://evil.example/"})
        self.assertRedirects(response, reverse("import_data"), fetch_redirect_response=False)

    def test_disconnect_removes_schedule(self):
        """Disconnecting deletes the recurring periodic task."""
        AudiobookshelfAccount.objects.create(
            user=self.user, base_url=BASE_URL, api_token="encrypted"
        )
        interval, _ = IntervalSchedule.objects.get_or_create(
            every=15, period=IntervalSchedule.MINUTES
        )
        PeriodicTask.objects.create(
            name="Import from Audiobookshelf for abs-connect (every 15 minutes)",
            task="Import from Audiobookshelf (Recurring)",
            interval=interval,
            kwargs=f'{{"user_id": {self.user.id}}}',
            enabled=True,
        )

        response = self.client.post(reverse("audiobookshelf_disconnect"))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            AudiobookshelfAccount.objects.filter(user=self.user).exists()
        )
        self.assertFalse(
            PeriodicTask.objects.filter(
                task="Import from Audiobookshelf (Recurring)",
                kwargs__contains=f'"user_id": {self.user.id}',
            ).exists()
        )


class AudiobookshelfCoverProxyTests(TestCase):
    """The cover proxy authenticates to ABS server-side (see issue #861)."""

    def setUp(self):
        """Create a connected Audiobookshelf account to proxy covers for."""
        cache.clear()
        data_dir = tempfile.TemporaryDirectory()
        self.addCleanup(data_dir.cleanup)
        settings_override = override_settings(FLOPPY_DATA_DIR=data_dir.name)
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        self.user = get_user_model().objects.create_user(username="abs-cover")
        self.account = AudiobookshelfAccount.objects.create(
            user=self.user,
            base_url=BASE_URL,
            api_token=helpers.encrypt(API_TOKEN),
        )

    def _cover_url(self, library_item_id="item-1"):
        return audiobookshelf_cover.build_cover_proxy_url(
            self.account.id,
            library_item_id,
        )

    def _mock_upstream(self, *, status_code=200, content=b"", headers=None):
        """Build a requests.Response-shaped mock for the streaming proxy path."""
        def iter_content(chunk_size):
            return iter(
                content[i : i + chunk_size] for i in range(0, len(content), chunk_size)
            )

        upstream = Mock(status_code=status_code, headers=headers or {})
        upstream.iter_content = iter_content
        return upstream

    def assertPlaceholder(self, response):  # noqa: N802 - unittest naming
        """Assert the response is Floppy's own placeholder, not a broken image.

        A 404 renders as the browser's broken-image glyph because nothing in
        the templates has an onerror fallback for a URL that is itself valid,
        which is what made #861 look like corruption rather than an offline
        server. The short TTL lets the real cover reappear once ABS recovers.
        """
        placeholder_body, placeholder_type = views._placeholder_image_bytes()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, placeholder_body)
        self.assertEqual(response["Content-Type"], placeholder_type)
        self.assertEqual(response["Cache-Control"], "private, max-age=300")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    @patch("integrations.views.requests.get")
    def test_streams_cover_with_valid_token(self, mock_get):
        """A valid signed token fetches the upstream cover with the stored token."""
        mock_get.return_value = self._mock_upstream(
            content=b"fake-image-bytes",
            headers={"Content-Type": "image/webp"},
        )

        response = self.client.get(self._cover_url("item-1"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"fake-image-bytes")
        self.assertEqual(response["Content-Type"], "image/webp")
        self.assertEqual(response["Cache-Control"], "private, max-age=3600")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

        mock_get.assert_called_once_with(
            f"{BASE_URL}/api/items/item-1/cover",
            headers={"Authorization": f"Bearer {API_TOKEN}"},
            timeout=15,
            stream=True,
            allow_redirects=False,
        )

    def test_returns_404_for_invalid_token(self):
        """A tampered or malformed token never reaches the ABS request."""
        response = self.client.get(
            reverse("audiobookshelf_cover", kwargs={"token": "not-a-real-token"}),
        )
        self.assertEqual(response.status_code, 404)

    def test_serves_placeholder_when_account_no_longer_exists(self):
        """A signed token for a deleted account degrades to the placeholder."""
        url = audiobookshelf_cover.build_cover_proxy_url(999_999, "item-1")

        with self.assertLogs("integrations.views", level="WARNING") as logs:
            response = self.client.get(url)

        self.assertPlaceholder(response)
        self.assertIn("item-1", "\n".join(logs.output))

    @patch("integrations.views.requests.get")
    def test_serves_placeholder_on_upstream_error_status(self, mock_get):
        """An ABS-side auth failure degrades to the placeholder, and is logged.

        Every failure below used to be a silent 404, which is exactly why the
        #861 reports carried no usable evidence in Settings > Advanced.
        """
        mock_get.return_value = self._mock_upstream(status_code=401)

        with self.assertLogs("integrations.views", level="WARNING") as logs:
            response = self.client.get(self._cover_url())

        self.assertPlaceholder(response)
        self.assertIn("status=401", "\n".join(logs.output))

    @patch("integrations.views.requests.get")
    def test_serves_placeholder_on_request_exception(self, mock_get):
        """A network failure talking to ABS degrades to the placeholder."""
        mock_get.side_effect = requests.ConnectionError("boom")

        with self.assertLogs("integrations.views", level="WARNING") as logs:
            response = self.client.get(self._cover_url())

        self.assertPlaceholder(response)
        self.assertIn("request failed", "\n".join(logs.output))

    @patch("integrations.views.requests.get")
    def test_unreachable_server_backs_off_the_remaining_covers(self, mock_get):
        """After one timeout, the next covers skip ABS instead of each waiting.

        Every poster on a page held a web worker for the full timeout while
        the server was down (#1307).
        """
        mock_get.side_effect = requests.ReadTimeout("Read timed out.")

        with self.assertLogs("integrations.views", level="WARNING"):
            first = self.client.get(self._cover_url("item-1"))
        second = self.client.get(self._cover_url("item-2"))

        self.assertPlaceholder(first)
        self.assertPlaceholder(second)
        mock_get.assert_called_once()

    @patch("integrations.views.requests.get")
    def test_body_stalling_mid_stream_serves_placeholder_and_backs_off(
        self,
        mock_get,
    ):
        """Headers arrive but the body stalls: same placeholder and backoff."""
        upstream = self._mock_upstream(headers={"Content-Type": "image/jpeg"})

        def stalled(chunk_size):
            yield b"partial"
            raise requests.ConnectionError("Read timed out.")

        upstream.iter_content = stalled
        mock_get.return_value = upstream

        with self.assertLogs("integrations.views", level="WARNING"):
            first = self.client.get(self._cover_url("item-1"))
        second = self.client.get(self._cover_url("item-2"))

        self.assertPlaceholder(first)
        self.assertPlaceholder(second)
        mock_get.assert_called_once()
        upstream.close.assert_called_once()

    @patch("integrations.views.requests.get")
    def test_backoff_lapses_and_covers_load_again(self, mock_get):
        """Once the backoff expires the real cover is fetched again."""
        mock_get.side_effect = requests.ReadTimeout("Read timed out.")
        with self.assertLogs("integrations.views", level="WARNING"):
            self.client.get(self._cover_url("item-1"))

        cache.delete(f"abs_cover_backoff:{self.account.id}")
        mock_get.side_effect = None
        mock_get.return_value = self._mock_upstream(
            content=b"fake-image-bytes",
            headers={"Content-Type": "image/webp"},
        )

        response = self.client.get(self._cover_url("item-2"))

        self.assertEqual(response.content, b"fake-image-bytes")

    @patch("integrations.views.requests.get")
    def test_fresh_stored_cover_is_served_without_calling_abs(self, mock_get):
        """Once a cover has loaded, the next request does not reach ABS."""
        mock_get.return_value = self._mock_upstream(
            content=b"fake-image-bytes",
            headers={"Content-Type": "image/webp"},
        )
        self.client.get(self._cover_url("item-1"))

        response = self.client.get(self._cover_url("item-1"))

        self.assertEqual(response.content, b"fake-image-bytes")
        self.assertEqual(response["Content-Type"], "image/webp")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        mock_get.assert_called_once()

    @patch("integrations.views.requests.get")
    def test_stored_cover_is_served_while_abs_is_down(self, mock_get):
        """An old stored copy beats the placeholder when ABS times out (#1307)."""
        mock_get.return_value = self._mock_upstream(
            content=b"fake-image-bytes",
            headers={"Content-Type": "image/webp"},
        )
        self.client.get(self._cover_url("item-1"))
        mock_get.reset_mock()
        mock_get.return_value = None
        mock_get.side_effect = requests.ReadTimeout("Read timed out.")

        with patch.object(image_cache, "STORED_COVER_FRESH_SECONDS", 0):
            with self.assertLogs("integrations.views", level="WARNING"):
                response = self.client.get(self._cover_url("item-1"))
            during_backoff = self.client.get(self._cover_url("item-1"))

        mock_get.assert_called_once()
        self.assertEqual(response.content, b"fake-image-bytes")
        self.assertEqual(during_backoff.content, b"fake-image-bytes")

    @patch("integrations.views.requests.get")
    def test_stale_stored_cover_is_replaced_by_a_new_one(self, mock_get):
        """After the fresh window, ABS is asked again and a changed cover wins."""
        mock_get.return_value = self._mock_upstream(
            content=b"old-cover",
            headers={"Content-Type": "image/png"},
        )
        self.client.get(self._cover_url("item-1"))
        mock_get.return_value = self._mock_upstream(
            content=b"new-cover",
            headers={"Content-Type": "image/jpeg"},
        )

        with patch.object(image_cache, "STORED_COVER_FRESH_SECONDS", 0):
            refreshed = self.client.get(self._cover_url("item-1"))
        again = self.client.get(self._cover_url("item-1"))

        self.assertEqual(refreshed.content, b"new-cover")
        self.assertEqual(again.content, b"new-cover")
        self.assertEqual(again["Content-Type"], "image/jpeg")
        self.assertEqual(mock_get.call_count, 2)

    @patch("integrations.views.requests.get")
    def test_refused_cover_is_never_stored(self, mock_get):
        """Only validated images are kept; a refused type still gets the placeholder."""
        mock_get.return_value = self._mock_upstream(
            content=b"<svg/>",
            headers={"Content-Type": "image/svg+xml"},
        )
        with self.assertLogs("integrations.views", level="WARNING"):
            self.client.get(self._cover_url("item-1"))
        mock_get.side_effect = requests.ReadTimeout("Read timed out.")

        with self.assertLogs("integrations.views", level="WARNING"):
            response = self.client.get(self._cover_url("item-1"))

        self.assertPlaceholder(response)

    @patch("integrations.views.requests.get")
    def test_deleted_account_does_not_serve_its_stored_cover(self, mock_get):
        """Disconnecting the account stops its covers, stored or not."""
        mock_get.return_value = self._mock_upstream(
            content=b"fake-image-bytes",
            headers={"Content-Type": "image/webp"},
        )
        url = self._cover_url("item-1")
        self.client.get(url)
        self.account.delete()

        with self.assertLogs("integrations.views", level="WARNING"):
            response = self.client.get(url)

        self.assertPlaceholder(response)

    @patch("integrations.views.requests.get")
    def test_cover_is_not_fetched_from_a_forbidden_server_address(self, mock_get):
        """The cover proxy goes through the self-hosted policy like the importer."""
        self.account.base_url = "http://169.254.169.254"
        self.account.save(update_fields=["base_url"])

        with self.assertLogs("integrations.views", level="WARNING"):
            response = self.client.get(self._cover_url())

        self.assertPlaceholder(response)
        mock_get.assert_not_called()

    @patch("integrations.views.requests.get")
    def test_rejects_non_image_content_type(self, mock_get):
        """An HTML (or otherwise non-image) upstream response is never served.

        A compromised or attacker-controlled ABS server could otherwise have
        active content served from Floppy's own origin to anyone holding the
        signed proxy URL (#861 review).
        """
        mock_get.return_value = self._mock_upstream(
            content=b"<script>alert(1)</script>",
            headers={"Content-Type": "text/html"},
        )

        with self.assertLogs("integrations.views", level="WARNING"):
            response = self.client.get(self._cover_url())

        self.assertPlaceholder(response)
        self.assertNotIn(b"<script>", response.content)

    @patch("integrations.views.requests.get")
    def test_rejects_svg_content_type(self, mock_get):
        """SVG is an active format and must not be proxied as a plain image."""
        mock_get.return_value = self._mock_upstream(
            content=b"<svg onload='alert(1)'></svg>",
            headers={"Content-Type": "image/svg+xml"},
        )

        with self.assertLogs("integrations.views", level="WARNING"):
            response = self.client.get(self._cover_url())

        self.assertPlaceholder(response)
        self.assertNotIn(b"onload", response.content)

    @patch("integrations.views.requests.get")
    def test_rejects_untyped_body_that_is_not_an_image(self, mock_get):
        """An unlabelled body still has to prove it is a raster image.

        Sniffing exists so a reverse proxy that strips or genericises the
        content type doesn't cost the poster (#861) - but it must not become a
        way to smuggle SVG or HTML past the allow-list.
        """
        mock_get.return_value = self._mock_upstream(
            content=b"<svg onload='alert(1)'></svg>",
            headers={"Content-Type": "application/octet-stream"},
        )

        with self.assertLogs("integrations.views", level="WARNING"):
            response = self.client.get(self._cover_url())

        self.assertPlaceholder(response)

    @patch("integrations.views.requests.get")
    def test_sniffs_untyped_jpeg_body(self, mock_get):
        """A JPEG behind a generic content type is served as image/jpeg."""
        jpeg = b"\xff\xd8\xff\xe0" + b"0" * 32
        mock_get.return_value = self._mock_upstream(
            content=jpeg,
            headers={"Content-Type": "application/octet-stream"},
        )

        response = self.client.get(self._cover_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, jpeg)
        self.assertEqual(response["Content-Type"], "image/jpeg")

    @patch("integrations.views.requests.get")
    def test_accepts_non_standard_jpeg_content_type(self, mock_get):
        """Real ABS deployments emit image/jpg; rejecting it lost the poster."""
        mock_get.return_value = self._mock_upstream(
            content=b"fake-image-bytes",
            headers={"Content-Type": "image/jpg"},
        )

        response = self.client.get(self._cover_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"fake-image-bytes")

    @patch("integrations.views.requests.get")
    def test_rejects_oversized_content_length(self, mock_get):
        """A declared Content-Length above the cap is rejected before reading."""
        mock_get.return_value = self._mock_upstream(
            content=b"x",
            headers={
                "Content-Type": "image/jpeg",
                "Content-Length": str(image_cache.MAX_IMAGE_BYTES + 1),
            },
        )

        with self.assertLogs("integrations.views", level="WARNING"):
            response = self.client.get(self._cover_url())

        self.assertPlaceholder(response)

    @patch("integrations.views.requests.get")
    def test_rejects_stream_exceeding_max_bytes(self, mock_get):
        """A body that grows past the cap while streaming is rejected mid-read.

        Content-Length is attacker-controlled and can simply be omitted, so
        the accumulated byte count must be enforced independently.
        """
        oversized = b"x" * (image_cache.MAX_IMAGE_BYTES + 1)
        mock_get.return_value = self._mock_upstream(
            content=oversized,
            headers={"Content-Type": "image/jpeg"},
        )

        with self.assertLogs("integrations.views", level="WARNING"):
            response = self.client.get(self._cover_url())

        self.assertPlaceholder(response)

    def test_invalid_token_does_not_log_a_warning(self):
        """Junk tokens stay below warning, and the token is never echoed.

        The view is anonymous, so warning on an unsignable token would let
        anyone flood the log and bury the real Audiobookshelf failures these
        warnings exist to surface (#1069 review).
        """
        with self.assertLogs("integrations.views", level="DEBUG") as logs:
            self.client.get(
                reverse(
                    "audiobookshelf_cover",
                    kwargs={"token": "sneaky-token-value"},
                ),
            )

        output = "\n".join(logs.output)
        self.assertNotIn("sneaky-token-value", output)
        self.assertNotIn("WARNING", output)


class AudiobookshelfCoverProxyUrlCeleryTests(TestCase):
    """build_cover_proxy_url must work from a Celery worker (#1199).

    Every Audiobookshelf import - including a manual "sync now" - runs
    inside a Celery worker, whose ROOT_URLCONF is deliberately empty since
    it never serves HTTP. reverse() must not depend on that setting.
    """

    @override_settings(ROOT_URLCONF="config.celery_urls")
    def test_builds_url_under_the_empty_celery_urlconf(self):
        url = audiobookshelf_cover.build_cover_proxy_url(1, "item-1")
        self.assertTrue(url.startswith(audiobookshelf_cover.PROXY_PATH_PREFIX))

    @override_settings(ROOT_URLCONF="config.celery_urls", FORCE_SCRIPT_NAME="/floppy")
    def test_applies_base_url_subpath_when_no_request_set_it(self):
        url = audiobookshelf_cover.build_cover_proxy_url(1, "item-1")
        self.assertTrue(url.startswith("/floppy" + audiobookshelf_cover.PROXY_PATH_PREFIX))
