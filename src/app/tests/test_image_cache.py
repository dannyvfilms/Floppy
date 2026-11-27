import json
import os
import tempfile
import time
from io import BytesIO
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from PIL import Image
from rest_framework.request import Request

from api.renderers import ImageCacheJSONRenderer
from app import image_cache


def _png_bytes():
    output = BytesIO()
    Image.new("RGB", (2, 2), "red").save(output, format="PNG")
    return output.getvalue()


def _response(body, *, content_type="image/png", status_code=200, **headers):
    response = Mock()
    response.status_code = status_code
    response.headers = {"Content-Type": content_type, **headers}
    response.is_redirect = status_code in {301, 302, 303, 307, 308}
    response.is_permanent_redirect = status_code in {301, 308}
    response.iter_content.side_effect = lambda chunk_size: [body]
    response.close = Mock()
    return response


class ImageCacheServiceTests(TestCase):
    """Exercise URL policy, disk storage, endpoint headers, and cleanup."""

    def setUp(self):
        self.data_dir = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(FLOPPY_DATA_DIR=self.data_dir.name)
        self.settings_override.enable()
        cache.delete(image_cache.SETTING_CACHE_KEY)
        image_cache.set_enabled(False)

    def tearDown(self):
        cache.delete(image_cache.SETTING_CACHE_KEY)
        self.settings_override.disable()
        self.data_dir.cleanup()

    def test_approved_urls_rewrite_but_manual_and_local_urls_do_not(self):
        image_cache.set_enabled(True)
        request = RequestFactory().get("/api/v1/info/")
        approved = "https://image.tmdb.org/t/p/w500/poster.jpg?x=1"

        rewritten = image_cache.rewrite_image_url(approved, request=request)

        self.assertTrue(rewritten.startswith("http://testserver/image-cache/"))
        self.assertNotEqual(rewritten, approved)
        for value in (
            "",
            "data:image/png;base64,abc",
            "/static/img/placeholder.png",
            "https://example.com/manual.jpg",
            "http://127.0.0.1:8080/image.jpg",
            "http://audiobookshelf.local/image.jpg",
        ):
            self.assertEqual(image_cache.rewrite_image_url(value, request), value)

    def test_trakt_artwork_is_always_proxied_even_when_cache_is_disabled(self):
        image_cache.set_enabled(False)
        request = RequestFactory().get("/api/v1/info/")
        urls = (
            "https://media.trakt.tv/movies/42897/medium/poster.webp",
            "https://walter-r2.trakt.tv/images/movies/000/042/897/posters/medium/poster.webp",
        )

        for source_url in urls:
            with self.subTest(source_url=source_url):
                self.assertTrue(image_cache.is_approved_url(source_url))
                rewritten = image_cache.rewrite_image_url(source_url, request=request)
                self.assertIn("/image-cache/", rewritten)
                self.assertNotIn("media.trakt.tv", rewritten)

    def test_trakt_artwork_cache_follows_only_approved_provider_redirects(self):
        source_url = "https://media.trakt.tv/movies/42897/medium/poster.webp"
        redirected_url = (
            "https://walter-r2.trakt.tv/images/movies/000/042/897/"
            "posters/medium/poster.webp"
        )
        body = _png_bytes()
        redirect = _response(
            b"",
            status_code=302,
            **{"Location": redirected_url, "Content-Type": "text/plain"},
        )
        final = _response(body, **{"Content-Length": str(len(body))})

        with patch(
            "app.image_cache.requests.get",
            side_effect=[redirect, final],
        ) as fetch:
            response = self.client.get(
                reverse(
                    "image_cache",
                    kwargs={"token": image_cache._token_for_url(source_url)},
                ),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), body)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(fetch.call_args_list[0].args[0], source_url)
        self.assertEqual(fetch.call_args_list[1].args[0], redirected_url)

    def test_trakt_artwork_redirect_cannot_leave_trakt_cdn_hosts(self):
        source_url = "https://media.trakt.tv/movies/42897/medium/poster.webp"
        redirected_url = "https://image.tmdb.org/t/p/w500/poster.webp"
        redirect = _response(
            b"",
            status_code=302,
            **{"Location": redirected_url, "Content-Type": "text/plain"},
        )
        final = _response(_png_bytes())

        with patch(
            "app.image_cache.requests.get",
            side_effect=[redirect, final],
        ) as fetch:
            response = self.client.get(
                reverse(
                    "image_cache",
                    kwargs={"token": image_cache._token_for_url(source_url)},
                ),
            )

        self.assertEqual(response.status_code, 404)
        fetch.assert_called_once()

    def test_anonymous_miss_fetches_once_then_hit_returns_cache_headers(self):
        image_cache.set_enabled(True)
        source_url = "https://image.tmdb.org/t/p/original/poster.jpg"
        token = image_cache._token_for_url(source_url)
        body = _png_bytes()
        response = _response(body, **{"Content-Length": str(len(body))})

        with patch("app.image_cache.requests.get", return_value=response) as fetch:
            first = self.client.get(reverse("image_cache", kwargs={"token": token}))
            second = self.client.get(
                reverse("image_cache", kwargs={"token": token}),
                HTTP_IF_NONE_MATCH=first["ETag"],
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first["Content-Type"], "image/png")
        self.assertEqual(first["Content-Length"], str(len(body)))
        self.assertEqual(first["Cache-Control"], "public, max-age=86400")
        self.assertEqual(b"".join(first.streaming_content), body)
        self.assertEqual(second.status_code, 304)
        fetch.assert_called_once()
        self.assertEqual(image_cache.cache_stats()["count"], 1)

    def test_disabled_cache_serves_existing_files_but_does_not_download(self):
        source_url = "https://image.tmdb.org/t/p/original/poster.jpg"
        token = image_cache._token_for_url(source_url)
        body = _png_bytes()
        image_cache.set_enabled(True)
        with patch(
            "app.image_cache.requests.get",
            return_value=_response(body, **{"Content-Length": str(len(body))}),
        ):
            self.assertEqual(
                self.client.get(reverse("image_cache", kwargs={"token": token})).status_code,
                200,
            )

        image_cache.set_enabled(False)
        with patch("app.image_cache.requests.get") as fetch:
            self.assertEqual(
                self.client.get(reverse("image_cache", kwargs={"token": token})).status_code,
                200,
            )
            missing_token = image_cache._token_for_url(
                "https://image.tmdb.org/t/p/original/missing.jpg",
            )
            self.assertEqual(
                self.client.get(
                    reverse("image_cache", kwargs={"token": missing_token}),
                ).status_code,
                404,
            )
        fetch.assert_not_called()

    def test_tampering_unknown_hosts_redirects_and_non_images_are_rejected(self):
        image_cache.set_enabled(True)
        valid_token = image_cache._token_for_url(
            "https://image.tmdb.org/t/p/original/valid.jpg",
        )
        tampered_token = f"{valid_token[:-1]}x"
        self.assertEqual(
            self.client.get(reverse("image_cache", kwargs={"token": tampered_token})).status_code,
            404,
        )
        unknown_token = image_cache._token_for_url("https://example.com/image.jpg")
        self.assertEqual(
            self.client.get(reverse("image_cache", kwargs={"token": unknown_token})).status_code,
            404,
        )

        source_url = "https://image.tmdb.org/t/p/original/unsafe.jpg"
        token = image_cache._token_for_url(source_url)
        redirect = _response(
            b"",
            status_code=302,
            **{"Location": "http://127.0.0.1/private", "Content-Type": "text/plain"},
        )
        with patch("app.image_cache.requests.get", return_value=redirect) as fetch:
            self.assertEqual(
                self.client.get(reverse("image_cache", kwargs={"token": token})).status_code,
                404,
            )
        fetch.assert_called_once()

        non_image = _response(b"not an image", content_type="text/html")
        with patch("app.image_cache.requests.get", return_value=non_image):
            self.assertEqual(
                self.client.get(reverse("image_cache", kwargs={"token": token})).status_code,
                404,
            )

    def test_cleanup_removes_old_entries_and_preserves_recent_entries(self):
        image_cache.set_enabled(True)
        body = _png_bytes()
        urls = [
            "https://image.tmdb.org/t/p/original/old.jpg",
            "https://image.tmdb.org/t/p/original/recent.jpg",
        ]
        with patch(
            "app.image_cache.requests.get",
            side_effect=[
                _response(body, **{"Content-Length": str(len(body))}),
                _response(body, **{"Content-Length": str(len(body))}),
            ],
        ):
            for url in urls:
                self.client.get(
                    reverse(
                        "image_cache",
                        kwargs={"token": image_cache._token_for_url(url)},
                    ),
                )

        old_data, old_metadata = image_cache._paths(urls[0])
        old_time = time.time() - image_cache.CACHE_STALE_AFTER_SECONDS - 1
        os.utime(old_data, (old_time, old_time))
        os.utime(old_metadata, (old_time, old_time))

        summary = image_cache.cleanup_stale_images()

        self.assertEqual(summary["removed_count"], 1)
        self.assertGreater(summary["removed_bytes"], 0)
        self.assertFalse(old_data.exists())
        self.assertTrue(image_cache._paths(urls[1])[0].exists())

    def test_api_renderer_rewrites_image_fields_without_changing_shape(self):
        image_cache.set_enabled(True)
        request = Request(RequestFactory().get("/api/v1/info/"))
        payload = {
            "image": "https://image.tmdb.org/t/p/w500/poster.jpg",
            "nested": [{"image_url": "https://example.com/manual.jpg"}],
        }

        rendered = ImageCacheJSONRenderer().render(
            payload,
            renderer_context={"request": request},
        )
        result = json.loads(rendered)

        self.assertTrue(result["image"].startswith("http://testserver/image-cache/"))
        self.assertEqual(result["nested"][0]["image_url"], "https://example.com/manual.jpg")
        self.assertEqual(set(result), set(payload))
