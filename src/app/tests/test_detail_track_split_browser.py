"""Browser coverage for shared tracking controls and their server actions."""

import os
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import tag
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from app.models import BoardGame, Item, MediaTypes, Sources, Status
from app.tests.live_server import SerialStaticLiveServerTestCase


@tag("slow", "playwright")
class DetailTrackSplitBrowserTests(SerialStaticLiveServerTestCase):
    def test_boardgame_menu_survives_edit(self):
        user = get_user_model().objects.create_user(username="track-split", game_logging_style="sessions")
        item = Item.objects.create(media_id="13", source=Sources.BGG.value,
                                   media_type=MediaTypes.BOARDGAME.value, title="Board Game")
        BoardGame.objects.create(item=item, user=user, status=Status.COMPLETED.value, progress=1)
        self.client.force_login(user)
        metadata = {"media_id": "13", "title": item.title, "media_type": item.media_type,
                    "source": item.source, "image": "", "max_progress": None,
                    "details": {}, "related": {}}
        url = reverse("media_details", kwargs={"source": item.source, "media_type": item.media_type,
                                               "media_id": item.media_id, "title": "board-game"})
        with (patch.dict(os.environ, {"DJANGO_ALLOW_ASYNC_UNSAFE": "true"}),
              patch("app.providers.services.get_media_metadata", return_value=metadata),
              sync_playwright() as playwright,
              playwright.chromium.launch(executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")) as browser):
            phone = bool(os.environ.get("FLOPPY_TRACK_REVIEW_PHONE"))
            context = browser.new_context(service_workers="block", viewport={
                "width": 390 if phone else 1280, "height": 844 if phone else 720,
            })
            context.add_cookies([{"name": "sessionid", "value": self.client.cookies["sessionid"].value,
                                  "url": self.live_server_url}])
            page = context.new_page()
            page.goto(self.live_server_url + url)
            split = page.locator("[data-track-split-root]")
            expect(split.get_by_role("button", name="Log a play")).to_be_visible(timeout=15000)
            self.assertGreater(split.get_by_role("button", name="Log a play").bounding_box()["width"], 120)
            capture = os.environ.get("FLOPPY_TRACK_REVIEW_DIR")
            if capture:
                # The preserved fallback is the pre-migration button at the same
                # viewport and state; show it before capturing the shared button.
                page.evaluate("""() => {
                  document.querySelector('[data-track-split-root]').style.display = 'none';
                  document.querySelector('[data-track-split-fallback]').style.display = '';
                }""")
                page.locator('[data-track-split-fallback] button[aria-label="More tracking actions"]').click()
                expect(page.locator('[data-track-split-fallback] [data-track-action-key="start"]')).to_be_visible()
                page.wait_for_timeout(250)
                page.screenshot(path=str(Path(capture) / ("web-phone-before.png" if phone else "web-before.png")))
                page.goto(self.live_server_url + url)
                expect(split.get_by_role("button", name="Log a play")).to_be_visible(timeout=15000)
            split.get_by_role("button", name="More tracking actions").click()
            expect(split.get_by_role("button", name="Check-in")).to_be_visible()
            split.get_by_role("button", name="Edit").click()
            expect(page.locator("[data-track-modal-root]")).to_be_visible()
            page.locator("button.ui-button").filter(has_text="Update").click(timeout=15000)
            expect(split.get_by_role("button", name="Log a play")).to_be_visible(timeout=15000)
            if capture:
                page.get_by_role("button", name="Dismiss notification").click()
            split.get_by_role("button", name="More tracking actions").click()
            expect(split.get_by_role("button", name="Check-in")).to_be_visible()
            if capture:
                page.screenshot(path=str(Path(capture) / ("web-phone-after.png" if phone else "web-after.png")))
            context.close()
