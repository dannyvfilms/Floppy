"""Browser regression coverage for column changes on filtered media lists."""

from django.contrib.auth import get_user_model
from django.test import tag
from playwright.sync_api import expect, sync_playwright

from app.models import Game, Item, MediaTypes, Sources, Status
from app.tests.live_server import SerialStaticLiveServerTestCase


@tag("slow", "playwright")
class MediaListColumnsBrowserTests(SerialStaticLiveServerTestCase):
    """Exercise the actual HTMX swap, including artwork preparation."""

    def test_layout_switch_keeps_updated_status(self):
        user = get_user_model().objects.create_user(
            username="layout-browser", password="12345"
        )
        for title, status in (
            ("Playing", Status.IN_PROGRESS.value),
            ("Finished", Status.COMPLETED.value),
        ):
            item = Item.objects.create(
                media_id=title,
                source=Sources.MANUAL.value,
                media_type=MediaTypes.GAME.value,
                title=title,
            )
            Game.objects.create(item=item, user=user, status=status)

        with sync_playwright() as playwright, playwright.chromium.launch() as browser:
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.goto(self.live_server_url)
            page.get_by_placeholder("Enter your username").fill("layout-browser")
            page.get_by_placeholder("Enter your password").fill("12345")
            page.get_by_role("button", name="Sign in").click()
            page.goto(f"{self.live_server_url}/medialist/game?status=In%20progress")
            page.get_by_role("button", name="In Progress", exact=True).click()
            all_buttons = page.get_by_role("button", name="All", exact=True)
            expect(all_buttons).to_have_count(2)
            all_buttons.last.click()
            expect(page.get_by_text("Finished", exact=True)).to_be_visible()
            page.get_by_role("button", name="View settings").first.click()
            page.get_by_role("link", name="Table View").first.click()
            expect(page.locator(".media-table")).to_contain_text("Finished")
            expect(page.locator(".media-table")).to_contain_text("Playing")
            self.assertIn("status=all", page.url)

    def test_toggle_notes_preserves_filtered_table(self):
        user = get_user_model().objects.create_user(
            username="columns-browser", password="12345"
        )
        for title, status in (
            ("Pac-Man", Status.PAUSED.value),
            ("Galaga", Status.PAUSED.value),
            ("Donkey Kong", Status.COMPLETED.value),
        ):
            item = Item.objects.create(
                media_id=title,
                source=Sources.MANUAL.value,
                media_type=MediaTypes.GAME.value,
                title=title,
            )
            Game.objects.create(item=item, user=user, status=status, notes="A note")

        with (
            sync_playwright() as playwright,
            playwright.chromium.launch() as browser,
        ):
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.goto(self.live_server_url)
            page.get_by_placeholder("Enter your username").fill("columns-browser")
            page.get_by_placeholder("Enter your password").fill("12345")
            page.get_by_role("button", name="Sign in").click()
            page.goto(
                f"{self.live_server_url}/medialist/game?layout=table&status=Paused"
            )
            table = page.locator(".media-table")
            expect(table.locator("tbody > tr")).to_have_count(2)
            expect(
                table.get_by_role("columnheader", name="Notes", exact=True)
            ).to_have_count(1)
            expect(table).not_to_contain_text("Donkey Kong")
            page.get_by_role("button", name="Configure Table Columns").click()

            for action, notes_count in (("Hide column", 0), ("Show column", 1)):
                with page.expect_response(
                    lambda response: (
                        "/medialist/game?" in response.url
                        and response.request.headers.get("hx-request") == "true"
                    )
                ):
                    page.locator('[draggable="true"]').filter(
                        has=page.get_by_text("Notes", exact=True)
                    ).get_by_role("button", name=action, exact=True).click()
                expect(table.locator("tbody > tr")).to_have_count(2)
                expect(
                    table.get_by_role("columnheader", name="Notes", exact=True)
                ).to_have_count(notes_count)
                expect(table).to_contain_text("Pac-Man")
                expect(table).to_contain_text("Galaga")
                expect(table).not_to_contain_text("Donkey Kong")
                expect(table.locator("img[data-media-artwork]").first).to_have_attribute(
                    "loading", "eager"
                )
