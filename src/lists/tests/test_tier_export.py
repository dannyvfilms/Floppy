"""Export image: the tier board drawn as a PNG on the server."""

import io
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from django.test import override_settings
from django.urls import reverse
from PIL import Image

from app import image_cache
from app.models import MediaTypes
from lists import tier_export
from lists.models import CustomList
from lists.tests.test_tiers import TierTestCase


def tile_origin(row_top=tier_export.HEADER_H, column=0):
    """Top-left corner of the ``column``-th tile of a one-line tier row."""
    x = tier_export.PAD + tier_export.LABEL_W + tier_export.GAP
    return x + column * (
        tier_export.TILE_W + tier_export.GAP
    ), row_top + tier_export.GAP


class ExportTests(TierTestCase):
    """The download view and the picture it draws."""

    def setUp(self):
        """Log in as the owner and put one item in the first tier."""
        super().setUp()
        self.url = reverse("list_tier_export", args=[self.custom_list.id])
        self.place(One="s")
        self.client.force_login(self.owner)

    def export(self):
        """Download the board and open it as an image."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return response, Image.open(io.BytesIO(response.content))

    def test_downloads_a_png_named_after_the_list(self):
        """The response is a PNG attachment with a readable file name."""
        response, image = self.export()
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertIn('filename="games-tiers.png"', response["Content-Disposition"])
        self.assertEqual(image.width, tier_export.WIDTH)

    def test_cover_is_drawn_in_its_tier_row(self):
        """A cached cover shows up at the first tile position of the first row."""
        cover = io.BytesIO()
        Image.new("RGB", (40, 60), (200, 10, 10)).save(cover, "PNG")
        self.items["One"].image = "https://image.tmdb.org/t/p/w500/one.jpg"
        self.items["One"].save(update_fields=["image"])
        with patch.object(image_cache, "cover_bytes", return_value=cover.getvalue()):
            _, image = self.export()
        x, y = tile_origin()
        red, green, blue = image.getpixel(
            (x + tier_export.TILE_W // 2, y + tier_export.TILE_H // 2)
        )
        self.assertGreater(red, 150)
        self.assertLess(green, 60)
        self.assertLess(blue, 60)

    def test_missing_cover_falls_back_to_a_title_tile(self):
        """An item without a usable cover is still drawn, as a plain tile."""
        _, image = self.export()
        x, y = tile_origin()
        self.assertEqual(image.getpixel((x + 2, y + 2))[:3], tier_export.TILE)

    def test_empty_tiers_stay_thin_and_unranked_items_get_a_row(self):
        """Empty tiers keep the minimum height; items with no tier are included."""
        _, image = self.export()
        tiers = len(tier_export.resolve_tiers(self.custom_list))
        one_line = tier_export.TILE_H + 2 * tier_export.GAP
        rows = [one_line, *[tier_export.MIN_ROW_H] * (tiers - 1), one_line]
        expected = (
            tier_export.HEADER_H
            + sum(rows)
            + tier_export.GAP * (tiers + 1)
            + tier_export.PAD
        )
        self.assertEqual(image.height, expected)

    def test_limit_keeps_the_same_items_as_the_board(self):
        """Past the limit, ranked items win over earlier unranked ones."""
        self.place(One="", Two="s", Three="a")
        drawn = []
        original = tier_export._title_tile
        with (
            patch.object(tier_export, "EXPORT_LIMIT", 2),
            patch.object(
                tier_export,
                "_title_tile",
                side_effect=lambda title: drawn.append(title) or original(title),
            ),
        ):
            self.export()
        self.assertEqual(sorted(drawn), ["Three", "Two"])

    def test_covers_stop_being_fetched_after_the_time_budget(self):
        """Past the deadline only covers already on disk are used."""
        with patch.object(image_cache, "cover_bytes", return_value=None) as lookup:
            tier_export._cover("https://image.tmdb.org/t/p/w500/x.jpg", deadline=0)
        lookup.assert_called_once_with(
            "https://image.tmdb.org/t/p/w500/x.jpg", fetch=False
        )

    def test_private_list_is_hidden_from_strangers(self):
        """Someone who cannot view the list gets a 404, not the picture."""
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_collaborators_and_viewers_of_public_lists_can_export(self):
        """Collaborators can, and a signed-in stranger can once the list is public."""
        self.client.force_login(self.collaborator)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.custom_list.visibility = "public"
        self.custom_list.save(update_fields=["visibility"])
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_anonymous_visitors_are_sent_to_login(self):
        """Export needs an account, like the rest of the app outside public pages."""
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_smart_lists_have_no_board_to_export(self):
        """Smart lists have no tiers, so there is nothing to draw."""
        smart = CustomList.objects.create(
            name="Smart",
            owner=self.owner,
            is_smart=True,
            smart_media_types=[MediaTypes.GAME.value],
        )
        url = reverse("list_tier_export", args=[smart.id])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_board_shows_the_export_button_to_signed_in_viewers_only(self):
        """The Tiers view links to the export for signed-in users."""
        page = reverse("list_detail", args=[self.custom_list.public_reference])
        self.assertContains(self.client.get(page, {"layout": "tiers"}), self.url)
        self.custom_list.visibility = "public"
        self.custom_list.save(update_fields=["visibility"])
        self.client.logout()
        self.assertNotContains(self.client.get(page, {"layout": "tiers"}), self.url)


class CoverBytesTests(TierTestCase):
    """The helper the export uses to get cover pixels."""

    URL = "https://image.tmdb.org/t/p/w500/cover.jpg"

    def setUp(self):
        """Point the image cache at an empty folder."""
        super().setUp()
        self.data_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.data_dir.cleanup)
        override = override_settings(FLOPPY_DATA_DIR=self.data_dir.name)
        override.enable()
        self.addCleanup(override.disable)

    def test_unapproved_urls_are_never_fetched(self):
        """Only approved provider hosts are fetched, like the image proxy."""
        with patch.object(image_cache, "_open_image_response") as opener:
            self.assertIsNone(image_cache.cover_bytes("http://127.0.0.1/a.jpg"))
        opener.assert_not_called()

    def test_fetch_false_only_returns_what_is_already_cached(self):
        """With fetching off, a missing file is None and nothing is downloaded."""
        with patch.object(image_cache, "_open_image_response") as opener:
            self.assertIsNone(image_cache.cover_bytes(self.URL, fetch=False))
        opener.assert_not_called()

    def test_download_stays_in_memory_when_caching_is_off(self):
        """Image caching is off by default; an export must not write cache files."""
        response = Mock()
        response.iter_content.return_value = [b"abc", b"def"]
        with patch.object(
            image_cache, "_open_image_response", return_value=(response, "image/jpeg")
        ):
            self.assertEqual(image_cache.cover_bytes(self.URL), b"abcdef")
        response.close.assert_called_once()
        self.assertEqual(list(Path(self.data_dir.name).rglob("*.data")), [])

    def test_oversized_downloads_are_dropped(self):
        """A body past the size limit is not used."""
        response = Mock()
        response.iter_content.return_value = [b"x" * (image_cache.MAX_IMAGE_BYTES + 1)]
        with patch.object(
            image_cache, "_open_image_response", return_value=(response, "image/jpeg")
        ):
            self.assertIsNone(image_cache.cover_bytes(self.URL))
        response.close.assert_called_once()
