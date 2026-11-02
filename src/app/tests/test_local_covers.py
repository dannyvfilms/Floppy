"""Covers a person adds to their own items (issue #809)."""

import tempfile
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from app import cover_views, custom_metadata, image_cache, local_covers
from app.models import (
    CollectionEntry,
    CollectionField,
    CollectionFieldGroup,
    Item,
    MediaTypes,
    Sources,
    Status,
)
from app.models import Manga as MangaTracker
from integrations.safe_fetch import REASON_FORBIDDEN_ADDRESS, UnsafeUrlError

PAGE_URL = "https://books.example.com/moonlight-courier-1"


def image_bytes(image_format="PNG", size=(40, 60), color="red", **save_options):
    """Return a small valid image."""
    output = BytesIO()
    Image.new("RGB", size, color).save(output, format=image_format, **save_options)
    return output.getvalue()


def fetched(body, content_type, status_code=200, logical_url=None):
    """Return what ``safe_fetch`` returns: (response, body)."""
    response = Mock()
    response.logical_url = logical_url or PAGE_URL
    response.status_code = status_code
    response.headers = {"Content-Type": content_type}
    response.encoding = "utf-8"
    return response, body


class CoverTestCase(TestCase):
    """Common setup: an isolated data folder and a user with a manga."""

    def setUp(self):
        self.data_dir = tempfile.TemporaryDirectory()
        override = override_settings(FLOPPY_DATA_DIR=self.data_dir.name)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(self.data_dir.cleanup)

        self.user = get_user_model().objects.create_user(
            username="reader", password="12345"
        )
        self.client.login(username="reader", password="12345")
        self.item = self.make_item("Moonlight Courier")
        self.tracker = MangaTracker.objects.create(
            user=self.user, item=self.item, status=Status.PLANNING.value
        )

    def make_item(self, title, **extra):
        return Item.objects.create(
            media_id=Item.generate_manual_id(),
            source=Sources.MANUAL.value,
            media_type=MediaTypes.MANGA.value,
            library_media_type=MediaTypes.MANGA.value,
            title=title,
            image="https://example.com/old.jpg",
            **extra,
        )

    def post_cover(self, item=None, **data):
        item = item or self.item
        return self.client.post(
            reverse("update_item_cover", args=[item.id]),
            {"next": "/"} | data,
        )

    def covers(self):
        root = Path(self.data_dir.name) / "covers"
        return sorted(path.name for path in root.glob("*")) if root.exists() else []


class StoreBytesTests(CoverTestCase):
    """What is accepted, and what is kept of it."""

    def test_a_png_is_stored_under_its_own_hash(self):
        value = local_covers.store_bytes(image_bytes("PNG"))

        self.assertTrue(local_covers.is_local(value))
        self.assertTrue(value.endswith(".png"))
        self.assertEqual(self.covers(), [value.removeprefix("/covers/")])

    def test_the_same_picture_is_stored_once(self):
        first = local_covers.store_bytes(image_bytes("PNG"))
        second = local_covers.store_bytes(image_bytes("PNG"))

        self.assertEqual(first, second)
        self.assertEqual(len(self.covers()), 1)

    def test_location_data_is_removed(self):
        exif = Image.Exif()
        exif[0x8825] = {1: "N", 2: (51.0, 30.0, 0.0)}  # GPS block
        body = image_bytes("JPEG", exif=exif)
        with Image.open(BytesIO(body)) as original:
            self.assertIn(0x8825, original.getexif())

        value = local_covers.store_bytes(body)

        stored = Path(self.data_dir.name, "covers", value.removeprefix("/covers/"))
        with Image.open(stored) as result:
            self.assertEqual(dict(result.getexif()), {})

    def test_a_large_photo_is_scaled_down(self):
        value = local_covers.store_bytes(image_bytes("PNG", size=(3200, 2400)))

        stored = Path(self.data_dir.name, "covers", value.removeprefix("/covers/"))
        with Image.open(stored) as result:
            self.assertEqual(max(result.size), local_covers.MAX_EDGE_PIXELS)

    def test_other_formats_and_non_images_are_refused(self):
        for body in (image_bytes("GIF"), b"<svg xmlns='x'/>", b"not an image"):
            with self.subTest(body=body[:6]), self.assertRaises(local_covers.CoverError):
                local_covers.store_bytes(body)
        self.assertEqual(self.covers(), [])

    def test_more_than_ten_megabytes_is_refused(self):
        with self.assertRaises(local_covers.CoverError):
            local_covers.store_bytes(b"0" * (local_covers.MAX_COVER_BYTES + 1))


class ServeLocalCoverTests(CoverTestCase):
    """The file route."""

    def test_a_cover_is_served_without_a_session_and_cached_for_good(self):
        value = local_covers.store_bytes(image_bytes("PNG"))
        self.client.logout()

        response = self.client.get(value)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertIn("immutable", response["Cache-Control"])
        again = self.client.get(value, HTTP_IF_NONE_MATCH=response["ETag"])
        self.assertEqual(again.status_code, 304)

    def test_only_names_floppy_made_are_served(self):
        local_covers.store_bytes(image_bytes("PNG"))
        (Path(self.data_dir.name) / "secret.txt").write_text("secret")

        for name in ("secret.txt", "..%2Fsecret.txt", "a" * 64 + ".png", "x.png"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(f"/covers/{name}").status_code, 404)


class UpdateItemCoverTests(CoverTestCase):
    """Upload, image link, page link."""

    def test_an_upload_becomes_the_cover(self):
        upload = SimpleUploadedFile(
            "front.png", image_bytes("PNG"), content_type="image/png"
        )

        response = self.post_cover(cover_file=upload)

        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        self.assertTrue(local_covers.is_local(self.item.image))
        self.assertEqual(len(self.covers()), 1)

    def test_a_link_to_an_image_is_copied(self):
        with patch(
            "app.local_covers.safe_fetch.safe_fetch",
            return_value=fetched(image_bytes("JPEG"), "image/jpeg"),
        ) as fetch:
            self.post_cover(cover_url="https://img.example.com/front.jpg")

        self.item.refresh_from_db()
        self.assertTrue(self.item.image.endswith(".jpg"))
        self.assertEqual(fetch.call_args.kwargs["max_bytes"], local_covers.MAX_COVER_BYTES)

    def test_a_link_to_a_book_page_uses_the_cover_the_page_names(self):
        page = (
            '<html><head><meta property="og:image" content="/img/front.png">'
            "</head></html>"
        )
        responses = [
            fetched(page.encode(), "text/html; charset=utf-8"),
            fetched(image_bytes("PNG"), "image/png"),
        ]
        with patch(
            "app.local_covers.safe_fetch.safe_fetch", side_effect=responses
        ) as fetch:
            self.post_cover(cover_url=PAGE_URL)

        self.item.refresh_from_db()
        self.assertTrue(local_covers.is_local(self.item.image))
        self.assertEqual(
            fetch.call_args_list[1].args[0], "https://books.example.com/img/front.png"
        )

    def test_a_relative_cover_follows_the_page_a_redirect_led_to(self):
        page = '<html><head><meta property="og:image" content="cover.jpg"></head></html>'
        responses = [
            fetched(
                page.encode(),
                "text/html",
                logical_url="https://books.example.com/books/123/",
            ),
            fetched(image_bytes("JPEG"), "image/jpeg"),
        ]
        with patch(
            "app.local_covers.safe_fetch.safe_fetch", side_effect=responses
        ) as fetch:
            self.post_cover(cover_url="https://books.example.com/book")

        self.assertEqual(
            fetch.call_args_list[1].args[0],
            "https://books.example.com/books/123/cover.jpg",
        )

    def test_a_page_without_a_cover_says_so_and_changes_nothing(self):
        with patch(
            "app.local_covers.safe_fetch.safe_fetch",
            return_value=fetched(b"<html></html>", "text/html"),
        ):
            response = self.client.post(
                reverse("update_item_cover", args=[self.item.id]),
                {"next": "/", "cover_url": PAGE_URL},
                follow=True,
            )

        self.item.refresh_from_db()
        self.assertEqual(self.item.image, "https://example.com/old.jpg")
        self.assertContains(response, "That page does not name a cover image.")

    def test_a_link_the_outbound_boundary_refuses_is_not_fetched(self):
        error = UnsafeUrlError(REASON_FORBIDDEN_ADDRESS, "private address")
        with patch("app.local_covers.safe_fetch.safe_fetch", side_effect=error):
            self.post_cover(cover_url="http://192.168.1.5/cover.jpg")

        self.item.refresh_from_db()
        self.assertEqual(self.item.image, "https://example.com/old.jpg")

    def test_nothing_chosen_changes_nothing(self):
        self.post_cover()

        self.item.refresh_from_db()
        self.assertEqual(self.item.image, "https://example.com/old.jpg")

    def test_someone_elses_item_is_refused(self):
        other = self.make_item("Not Mine")
        upload = SimpleUploadedFile("f.png", image_bytes("PNG"), content_type="image/png")

        self.post_cover(item=other, cover_file=upload)

        other.refresh_from_db()
        self.assertEqual(other.image, "https://example.com/old.jpg")
        self.assertEqual(self.covers(), [])

    def test_a_collected_only_item_can_be_given_a_cover(self):
        collected = self.make_item("Only Collected")
        CollectionEntry.objects.create(user=self.user, item=collected)
        upload = SimpleUploadedFile("f.png", image_bytes("PNG"), content_type="image/png")

        self.post_cover(item=collected, cover_file=upload)

        collected.refresh_from_db()
        self.assertTrue(local_covers.is_local(collected.image))

    def test_you_must_be_logged_in(self):
        self.client.logout()
        upload = SimpleUploadedFile("f.png", image_bytes("PNG"), content_type="image/png")

        response = self.post_cover(cover_file=upload)

        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])
        self.assertEqual(self.covers(), [])

    def test_a_manual_items_stored_metadata_follows_the_new_cover(self):
        self.item.manual_metadata = {"image": "https://example.com/old.jpg", "title": "X"}
        self.item.save()
        upload = SimpleUploadedFile("f.png", image_bytes("PNG"), content_type="image/png")

        self.post_cover(cover_file=upload)

        self.item.refresh_from_db()
        self.assertEqual(self.item.manual_metadata["image"], self.item.image)
        self.assertEqual(self.item.manual_metadata["title"], "X")


class ReplacingACoverTests(CoverTestCase):
    """The file behind a replaced cover goes only when nothing uses it."""

    def upload(self, color):
        return SimpleUploadedFile(
            "f.png", image_bytes("PNG", color=color), content_type="image/png"
        )

    def test_the_replaced_file_is_removed(self):
        self.post_cover(cover_file=self.upload("red"))
        self.post_cover(cover_file=self.upload("blue"))

        self.assertEqual(len(self.covers()), 1)

    def test_a_file_another_item_still_uses_is_kept(self):
        twin = self.make_item("Twin")
        CollectionEntry.objects.create(user=self.user, item=twin)
        self.post_cover(cover_file=self.upload("red"))
        self.item.refresh_from_db()
        twin.image = self.item.image
        twin.save()

        self.post_cover(cover_file=self.upload("blue"))

        self.assertEqual(len(self.covers()), 2)
        self.assertTrue(local_covers.path_for(twin.image.removeprefix("/covers/")))


class MetadataFormTests(CoverTestCase):
    """The Metadata tab's own form must not reject or wipe an uploaded cover."""

    def test_saving_the_form_keeps_a_local_cover(self):
        value = local_covers.store_bytes(image_bytes("PNG"))
        self.item.image = value
        self.item.save()

        form = custom_metadata.ManualMetadataForm(
            {"metadata-title": "Moonlight Courier", "metadata-image_url": value},
            item=self.item,
            prefix="metadata",
        )

        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.item.refresh_from_db()
        self.assertEqual(self.item.image, value)

    def test_the_image_box_accepts_a_local_path_in_the_browser(self):
        form = custom_metadata.ManualMetadataForm(
            item=self.item, prefix="metadata"
        )

        # type="url" would make the browser refuse /covers/... on save.
        self.assertNotIn('type="url"', str(form["image_url"]))

    def test_other_values_are_still_checked_as_urls(self):
        form = custom_metadata.ManualMetadataForm(
            {"metadata-title": "Moonlight Courier", "metadata-image_url": "/covers/x"},
            item=self.item,
            prefix="metadata",
        )

        self.assertFalse(form.is_valid())


class RenderingTests(CoverTestCase):
    """Where else a local cover shows up."""

    def test_api_clients_get_an_absolute_link(self):
        value = local_covers.store_bytes(image_bytes("PNG"))
        request = RequestFactory().get("/api/v1/info/")

        self.assertEqual(
            image_cache.rewrite_image_url(value, request),
            f"http://testserver{value}",
        )
        self.assertEqual(image_cache.rewrite_image_url(value), value)

    def test_server_side_code_can_read_the_pixels(self):
        body = image_bytes("PNG")
        value = local_covers.store_bytes(body)

        self.assertIsNotNone(image_cache.cover_bytes(value, fetch=False))
        self.assertIsNone(image_cache.cover_bytes("/covers/" + "0" * 64 + ".png"))

    def test_clearing_the_image_cache_leaves_local_covers_alone(self):
        local_covers.store_bytes(image_bytes("PNG"))

        image_cache.clear_cache()

        self.assertEqual(len(self.covers()), 1)


class CandidatesTests(CoverTestCase):
    """The pictures the cover picker offers."""

    def candidates(self):
        return self.client.get(
            reverse("item_cover_candidates", args=[self.item.id])
        )

    def test_provider_search_results_are_offered(self):
        results = {
            "results": [
                {"title": "Moonlight Courier, Vol. 1", "image": "https://covers.openlibrary.org/a.jpg"},
                {"title": "No art", "image": settings.IMG_NONE},
            ]
        }
        with patch.object(cover_views.services, "search", return_value=results):
            response = self.candidates()

        self.assertContains(response, "Moonlight Courier, Vol. 1")
        self.assertNotContains(response, "No art")
        self.assertContains(response, 'data-url="https://covers.openlibrary.org/a.jpg"')

    def test_the_users_barcode_is_offered_first(self):
        group = CollectionFieldGroup.objects.create(user=self.user, name="Details")
        field = CollectionField.objects.create(group=group, label="Barcode")
        CollectionEntry.objects.create(
            user=self.user,
            item=self.item,
            custom_field_values={str(field.id): "9781234543994"},
        )
        with patch.object(cover_views.services, "search", return_value={"results": []}):
            response = self.candidates()

        self.assertContains(response, "covers.openlibrary.org/b/isbn/9781234543994-L.jpg")

    def test_a_provider_outage_still_shows_the_page(self):
        with patch.object(cover_views.services, "search", side_effect=RuntimeError("down")):
            response = self.candidates()

        self.assertContains(response, "No other covers found")

    def test_other_peoples_items_are_not_listed(self):
        other = self.make_item("Not Mine")

        response = self.client.get(reverse("item_cover_candidates", args=[other.id]))

        self.assertEqual(response.status_code, 404)


class MetadataTabTests(CoverTestCase):
    """The Cover section is on the Metadata tab of the track modal."""

    def test_the_section_appears_for_an_item_in_the_library(self):
        response = self.client.get(
            reverse(
                "track_modal",
                kwargs={
                    "source": Sources.MANUAL.value,
                    "media_type": MediaTypes.MANGA.value,
                    "media_id": self.item.media_id,
                },
            )
        )

        self.assertContains(response, reverse("update_item_cover", args=[self.item.id]))
        self.assertContains(response, "choose an image")
        self.assertContains(response, "enter a URL")
