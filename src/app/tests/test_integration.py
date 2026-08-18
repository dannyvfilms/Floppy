import copy
import os
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import tag
from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import expect, sync_playwright

from app.models import Game, Item, MediaTypes, Movie, Sources, Status
from app.tests.views.test_track_modal import _tv_with_seasons_payload
from users.models import DateFormatChoices


@tag("slow", "playwright")
class IntegrationTest(StaticLiveServerTestCase):
    """Integration tests for the application."""

    @classmethod
    def setUpClass(cls):
        """Set up the test class."""
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        super().setUpClass()
        cls.playwright = sync_playwright().start()
        # use headless=False, slow_mo=200 to see the browser
        cls.browser = cls.playwright.chromium.launch()
        # CI runners for this repo's full test suite (~2900 tests including
        # heavy benchmarks) get slow enough under load that the default 5s
        # expect() timeout occasionally races a real HTMX swap/navigation
        # that would otherwise succeed. Reset in tearDownClass since this is
        # process-global, not scoped to this class.
        expect.set_options(timeout=15000)

    def setUp(self):
        """Set up test data for CustomList model."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.user.date_format = DateFormatChoices.ISO_8601
        self.user.save(update_fields=["date_format"])
        show = _tv_with_seasons_payload(
            "1396",
            Sources.TMDB.value,
            title="Breaking Bad",
            episode_count=1,
        )
        episode = {
            "title": "Breaking Bad",
            "season_title": "Season 1",
            "episode_title": "Episode 1",
            "image": "https://example.com/episode.jpg",
            "cast": [],
            "crew": [],
        }
        search = {
            "page": 1,
            "total_pages": 1,
            "total_results": 1,
            "results": [show],
        }
        # Views mutate the returned dicts in place (e.g. replacing related.seasons
        # entries with enriched {"item": ..., "media": ...} wrappers), so a shared
        # return_value would corrupt later calls within the same test. Hand back a
        # fresh deep copy every call instead.
        for provider_patch in (
            patch(
                "app.providers.tmdb.search",
                side_effect=lambda *a, **k: copy.deepcopy(search),
            ),
            patch(
                "app.providers.tmdb.tv",
                side_effect=lambda *a, **k: copy.deepcopy(show),
            ),
            patch(
                "app.providers.tmdb.tv_with_seasons",
                side_effect=lambda *a, **k: copy.deepcopy(show),
            ),
            patch(
                "app.providers.tmdb.episode",
                side_effect=lambda *a, **k: copy.deepcopy(episode),
            ),
            patch("app.providers.tmdb.get_tvdb_episode_image_map", return_value={}),
            patch(
                "app.tasks_trakt.populate_trakt_episode_ratings_for_season.delay",
            ),
        ):
            provider_patch.start()
            self.addCleanup(provider_patch.stop)

        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self.page.goto(f"{self.live_server_url}/")
        self.page.get_by_placeholder("Enter your username").fill(
            self.credentials["username"],
        )
        self.page.get_by_placeholder("Enter your password").fill(
            self.credentials["password"],
        )
        self.page.get_by_role("button", name="Sign in").click()
        expect(self.page.locator("#global-search")).to_be_visible()

    def search_and_submit(self, query):
        """Run a global search via the submit button.

        The search form's Alpine.js submit guard only reliably recognizes
        the click event's target as its own search button; relying on the
        input's implicit Enter-to-submit behavior races with the
        hx-trigger="... , search" suggestions fetch firing on the same
        native `search` event and is intermittently swallowed.
        """
        self.page.locator("#global-search").fill(query)
        self.page.locator('form:has(#global-search) button[type="submit"]').click()

    def set_date_input(self, locator, value):
        """Set a hidden date-picker input and dispatch its change events."""
        locator.evaluate(
            """(input, value) => {
                input.value = value;
                input.dispatchEvent(new Event("input", { bubbles: true }));
                input.dispatchEvent(new Event("change", { bubbles: true }));
            }""",
            value,
        )

    def test_home_row_load_more_guard_and_progress(self):
        """Home rows append normally and stop after a zero-progress response."""
        load_more_requests = []

        def record_request(request):
            query = parse_qs(urlparse(request.url).query)
            if "load_row" in query:
                load_more_requests.append(
                    (query["load_row"][0], query.get("offset", ["0"])[0]),
                )

        def handle_route(route):
            query = parse_qs(urlparse(route.request.url).query)
            row_id = query.get("load_row", [None])[0]
            offset = query.get("offset", ["0"])[0]
            if offset != "14" or row_id not in {"624", "625"}:
                route.continue_()
                return

            headers = {
                "Content-Type": "text/html; charset=utf-8",
                "X-Home-Row-Total": "15" if row_id == "624" else "37",
                "X-Home-Row-Loaded": "15" if row_id == "624" else "14",
            }
            route.fulfill(
                status=200,
                body=(
                    '<div class="home-row-card" data-test-card="new">new</div>'
                    if row_id == "624"
                    else ""
                ),
                headers=headers,
            )

        def install_row(row_id, loaded, total):
            self.page.evaluate(
                """
                ({rowId, loaded, total}) => {
                    const row = document.createElement('div');
                    row.id = `test-home-row-${rowId}`;
                    row.style.width = '1px';
                    row.style.height = '20px';
                    row.style.display = 'flex';
                    row.style.flexWrap = 'nowrap';
                    row.style.overflowX = 'auto';
                    row.dataset.homeRow = 'true';
                    row.dataset.loadedCount = String(loaded);
                    row.dataset.loading = 'false';
                    row.dataset.totalCount = String(total);
                    row.dataset.rowId = rowId;
                    row.dataset.stickToEnd = 'false';
                    row.setAttribute('hx-get', `/?load_row=${rowId}`);
                    row.setAttribute(
                        'hx-vals',
                        'js:{offset: Number(event.target.dataset.loadedCount || 0)}',
                    );
                    row.setAttribute('hx-trigger', 'home-row-load-more');
                    row.setAttribute('hx-target', 'this');
                    row.setAttribute('hx-swap', 'beforeend');

                    for (let index = 0; index < loaded; index += 1) {
                        const card = document.createElement('div');
                        card.className = 'home-row-card';
                        card.style.width = '100px';
                        card.style.flex = '0 0 auto';
                        card.textContent = `card-${index}`;
                        row.appendChild(card);
                    }

                    const sentinel = document.createElement('div');
                    sentinel.dataset.homeRowSentinel = 'true';
                    row.appendChild(sentinel);
                    document.body.appendChild(row);
                    htmx.process(row);
                    const realIntersectionObserver = window.IntersectionObserver;
                    window.IntersectionObserver = class {
                        observe() {}
                        disconnect() {}
                    };
                    window.initHomeRowInfiniteScroll();
                    window.IntersectionObserver = realIntersectionObserver;
                    row.scrollLeft = row.scrollWidth;
                }
                """,
                {"rowId": row_id, "loaded": loaded, "total": total},
            )

        self.page.on("request", record_request)
        self.page.route("**/*", handle_route)

        install_row("624", loaded=14, total=15)
        success_row = self.page.locator("#test-home-row-624")
        success_row.evaluate(
            """
            row => {
                row.scrollLeft = row.scrollWidth;
                row.dispatchEvent(new Event('scroll'));
                row.dispatchEvent(new Event('scroll'));
            }
            """,
        )
        expect(success_row).to_have_attribute("data-loaded-count", "15")
        self.assertEqual(
            [request for request in load_more_requests if request[0] == "624"],
            [("624", "14")],
        )

        success_row.evaluate(
            "row => row.dispatchEvent(new Event('scroll'))",
        )
        self.page.wait_for_timeout(200)
        self.assertEqual(
            [request for request in load_more_requests if request[0] == "624"],
            [("624", "14")],
        )

        install_row("625", loaded=14, total=37)
        empty_row = self.page.locator("#test-home-row-625")
        empty_row.evaluate(
            "row => row.dispatchEvent(new Event('scroll'))",
        )
        expect(empty_row).to_have_attribute("data-home-row-exhausted", "true")
        self.page.wait_for_timeout(4000)
        self.assertEqual(
            [request for request in load_more_requests if request[0] == "625"],
            [("625", "14")],
        )

    @classmethod
    def tearDownClass(cls):
        """Tear down the test class."""
        expect.set_options(timeout=5000)
        cls.browser.close()
        cls.playwright.stop()
        super().tearDownClass()

    def tearDown(self):
        """Close browser connections before Django flushes the database."""
        self.context.close()
        super().tearDown()

    def test_season_progress_edit(self):
        """Test the progress edit of a season."""
        self.search_and_submit("breaking bad")
        expect(self.page.locator("h2", has_text="Search Results")).to_be_visible()
        self.page.get_by_title("Breaking Bad", exact=True).click()
        expect(self.page.get_by_role("main")).to_contain_text("Breaking Bad")
        season_href = self.page.locator(
            'a[href*="/season/1"]',
        ).first.get_attribute("href")
        self.page.goto(f"{self.live_server_url}{season_href}")
        expect(self.page.get_by_role("main")).to_contain_text("Breaking Bad")
        self.page.locator('button[title="Track Episode"]:visible').first.click()
        datetime_format = "%Y-%m-%d"

        # Episode 1 air date is 2008-01-20
        fixed_date = date(2008, 1, 20)
        modal = self.page.locator("[data-track-modal-root]:visible").first
        first_watch_operation_id = modal.locator(
            'input[name="watch_operation_id"]',
        ).input_value()
        self.set_date_input(
            modal.locator('input[name="end_date"]'),
            f"{fixed_date.isoformat()}T12:00",
        )
        with self.page.expect_request(
            lambda request: request.method == "POST" and "/episode_save" in request.url,
        ) as save_request:
            self.page.get_by_role("button", name="Add", exact=True).click()
        save_request.value.response()

        expect(self.page.get_by_role("main")).to_contain_text(
            f"Ended: {fixed_date.strftime(datetime_format)}",
        )

        with self.page.expect_response(
            lambda response: "fragment=secondary" in response.url,
        ) as secondary_response:
            self.page.reload()
        self.assertEqual(secondary_response.value.status, 200)
        expect(self.page.locator("#episodes-list")).to_be_visible()
        today = timezone.localtime().strftime(datetime_format)
        tracked_button = self.page.locator(
            "button[title='Track Episode'][hx-vals*='instance_id']:visible",
        ).first
        expect(tracked_button).to_be_visible()
        tracked_button.click()
        modal = self.page.locator("[data-track-modal-root]:visible").first
        add_new_entry = modal.get_by_role("button", name="Add new entry")
        expect(add_new_entry).to_be_visible()
        add_new_entry.click()
        expect(modal.locator('input[name="watch_operation_id"]')).not_to_have_value(
            first_watch_operation_id,
        )
        self.set_date_input(modal.locator('input[name="end_date"]'), f"{today}T12:00")
        with self.page.expect_request(
            lambda request: request.method == "POST" and "/episode_save" in request.url,
        ) as save_request:
            self.page.get_by_role("button", name="Add", exact=True).click()
        save_request.value.response()
        expect(self.page.get_by_role("main")).to_contain_text(f"Ended: {today}")

    def test_tv_completed(self):
        """Test the completed status of a TV show."""
        self.search_and_submit("breaking bad")
        expect(self.page.locator("h2", has_text="Search Results")).to_be_visible()
        self.page.get_by_title("Breaking Bad", exact=True).click()
        expect(self.page.get_by_role("main")).to_contain_text("Breaking Bad")
        self.page.locator("button").filter(has_text="Add to tracker").click()
        track_form = self.page.locator("#track-tv-1396")
        expect(track_form).to_contain_text("Score")
        track_form.get_by_label("Status").select_option("Completed")
        with self.page.expect_request(
            lambda request: request.method == "POST" and "/media_save" in request.url,
        ) as save_request:
            track_form.get_by_role("button", name="Add", exact=True).click()
        save_request.value.response()
        self.page.goto(f"{self.live_server_url}/medialist/tv")
        expect(self.page.get_by_role("main")).to_contain_text("Breaking Bad")
        expect(self.page.get_by_role("main")).to_contain_text("Completed")

    def test_season_completed(self):
        """Test the completed status of a season."""
        self.search_and_submit("breaking bad")
        expect(self.page.locator("h2", has_text="Search Results")).to_be_visible()
        self.page.get_by_title("Breaking Bad", exact=True).click()
        expect(self.page.get_by_role("main")).to_contain_text("Breaking Bad")
        season_href = self.page.locator(
            'a[href*="/season/1"]',
        ).first.get_attribute("href")
        self.page.goto(f"{self.live_server_url}{season_href}")
        expect(self.page.get_by_role("main")).to_contain_text("Breaking Bad")
        self.page.get_by_role("button", name="Add to tracker").click()
        track_form = self.page.locator("#track-season-1396-1")
        expect(track_form).to_contain_text("Score")
        with self.page.expect_request(
            lambda request: request.method == "POST" and "/media_save" in request.url,
        ) as save_request:
            track_form.get_by_role("button", name="Add", exact=True).click()
        save_request.value.response()
        self.page.goto(f"{self.live_server_url}/medialist/season")
        expect(self.page.get_by_role("main")).to_contain_text("Completed")

    def test_tv_manual(self):
        """Test the manual creation of a TV show."""
        # Create TV show
        self.page.get_by_role("link", name="Custom", exact=True).click()
        self.page.get_by_placeholder("Enter title").click()
        self.page.get_by_placeholder("Enter title").fill("Friends")
        self.page.get_by_placeholder("Enter image URL").click()
        self.page.get_by_placeholder("Enter image URL").fill(
            "https://media.themoviedb.org/t/p/w300_and_h450_bestv2/2koX1xLkpTQM4IZebYvKysFW1Nh.jpg",
        )
        self.page.locator('select[name="status"]').select_option("In progress")
        self.page.get_by_role("button", name="Create Entry").click()
        expect(
            self.page.get_by_text("Friends added successfully.", exact=True)
        ).to_be_visible()

        # Create season
        self.page.get_by_role("button", name="Season").click()
        expect(self.page.get_by_role("main")).to_contain_text("Parent TV Show")
        self.page.get_by_placeholder("Search for a TV show...").click()
        self.page.get_by_placeholder("Search for a TV show...").type("fri")
        expect(self.page.locator("#parent-tv-results")).to_contain_text("Friends")
        self.page.get_by_role("button", name="Friends").click()
        self.page.get_by_placeholder("Enter image URL").click()
        self.page.get_by_placeholder("Enter image URL").fill(
            "https://media.themoviedb.org/t/p/w130_and_h195_bestv2/odCW88Cq5hAF0ZFVOkeJmeQv1nV.jpg",
        )
        self.page.get_by_role("button", name="Create Entry").click()
        expect(self.page.locator("body")).to_contain_text(
            "Friends S1 added successfully.",
        )

        # Create episode
        self.page.get_by_role("button", name="Episode").click()
        expect(self.page.get_by_role("main")).to_contain_text("Parent Season")
        self.page.get_by_placeholder("Search for a season...").click()
        self.page.get_by_placeholder("Search for a season...").type("frien")
        expect(self.page.locator("#parent-season-results")).to_contain_text(
            "Friends - Season 1",
        )
        self.page.get_by_role("button", name="Friends - Season").click()
        self.page.get_by_placeholder("Enter image URL").click()
        self.page.get_by_placeholder("Enter image URL").fill(
            "https://media.themoviedb.org/t/p/w227_and_h127_bestv2/v6Elr1W2elOyGi1MClgV0mIBVHC.jpg",
        )
        self.page.locator('input[name="end_date"]').fill("2025-03-07")
        self.page.get_by_role("button", name="Create Entry").click()
        expect(self.page.locator("body")).to_contain_text(
            "Friends S1E1 added successfully.",
        )

        # Check visibility
        self.page.goto(f"{self.live_server_url}/medialist/tv")
        expect(self.page.get_by_role("main")).to_contain_text("Friends")
        self.page.goto(f"{self.live_server_url}/medialist/season")
        expect(self.page.get_by_role("main")).to_contain_text("Season 1")
        self.page.goto(f"{self.live_server_url}/medialist/tv")
        friends_href = self.page.get_by_role(
            "link", name="Friends", exact=True
        ).get_attribute("href")
        self.page.goto(f"{self.live_server_url}{friends_href}")
        expect(self.page.get_by_role("main")).to_contain_text("Friends")
        season_href = self.page.locator(
            'a[href*="/season/1"]',
        ).first.get_attribute("href")
        self.page.goto(f"{self.live_server_url}{season_href}")
        expect(self.page.get_by_role("main")).to_contain_text("Friends")
        expect(self.page.get_by_role("main")).to_contain_text("Episode 1")

    @patch("app.providers.services.get_media_metadata")
    def test_movie_split_track_modal_close_button_and_release_date(
        self,
        mock_get_metadata,
    ):
        """Date picker shortcuts support release dates and clearing both dates."""
        mock_get_metadata.return_value = {
            "media_id": "238",
            "title": "Test Movie",
            "media_type": MediaTypes.MOVIE.value,
            "source": Sources.TMDB.value,
            "image": "http://example.com/image.jpg",
            "max_progress": 1,
            "score": 7.6,
            "score_count": 42000,
            "details": {
                "release_date": "2019-11-08",
            },
            "related": {},
        }
        item = Item.objects.create(
            media_id="238",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Test Movie",
            image="http://example.com/image.jpg",
            runtime_minutes=95,
        )
        Movie.objects.create(
            item=item,
            user=self.user,
            status=Status.COMPLETED.value,
            progress=1,
            start_date=datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
            end_date=datetime(2026, 3, 1, 14, 0, tzinfo=UTC),
        )
        Movie.objects.create(
            item=item,
            user=self.user,
            status=Status.COMPLETED.value,
            progress=1,
            start_date=datetime(2026, 3, 12, 12, 0, tzinfo=UTC),
            end_date=datetime(2026, 3, 12, 14, 0, tzinfo=UTC),
        )

        self.page.goto(
            self.live_server_url
            + reverse(
                "media_details",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.MOVIE.value,
                    "media_id": "238",
                    "title": "test-movie",
                },
            ),
        )

        expect(self.page.get_by_role("main")).to_contain_text("Test Movie")

        self.page.get_by_role("button", name="More tracking actions").click()
        expect(self.page.get_by_role("button", name="Add new entry")).to_be_visible()
        self.page.get_by_role("button", name="Add new entry").click()

        create_modal = self.page.locator("[data-track-modal-root]:visible").first
        expect(create_modal).to_be_visible()
        create_modal.locator("button[type='button']").first.click()
        expect(self.page.locator("[data-track-modal-root]:visible")).to_have_count(0)

        self.page.get_by_role("button", name="More tracking actions").click()
        self.page.get_by_role("button", name="Add new entry").click()
        expect(create_modal).to_be_visible()
        self.page.set_viewport_size({"width": 375, "height": 812})

        end_date_input = create_modal.locator('input[name="end_date"]')
        end_time_segment = "14:25"
        start_date_input = create_modal.locator('input[name="start_date"]')

        create_modal.get_by_role("button", name="End date picker").click()
        end_date_picker = create_modal.get_by_role(
            "dialog",
            name="End date picker",
        )
        expect(
            end_date_picker.get_by_role("button", name="None", exact=True),
        ).to_be_visible()
        time_selects = end_date_picker.locator("select")
        time_selects.nth(0).select_option("14")
        time_selects.nth(1).select_option("25")
        create_modal.get_by_role("button", name="Release date").click()
        expect(end_date_input).to_have_value(f"2019-11-08T{end_time_segment}")
        end_hour, end_minute = [int(segment) for segment in end_time_segment.split(":")]
        expected_start_date = (
            datetime(2019, 11, 8, end_hour, end_minute, tzinfo=UTC)
            - timedelta(minutes=95)
        ).strftime("%Y-%m-%dT%H:%M")
        expect(start_date_input).to_have_value(expected_start_date)

        end_date_picker.get_by_role("button", name="None", exact=True).click()
        expect(end_date_input).to_have_value("")

        create_modal.get_by_role("button", name="Start date picker").click()
        start_date_picker = create_modal.get_by_role(
            "dialog",
            name="Start date picker",
        )
        start_date_picker.get_by_role("button", name="None", exact=True).click()
        expect(start_date_input).to_have_value("")

        with self.page.expect_request(
            lambda request: request.method == "POST" and "/media_save" in request.url,
        ) as save_request:
            create_modal.get_by_role("button", name="Add", exact=True).click()
        save_request.value.response()
        expect(self.page.locator("[data-track-modal-root]:visible")).to_have_count(0)

        new_movie = Movie.objects.filter(item=item, user=self.user).order_by("-id").first()
        self.assertIsNotNone(new_movie)
        self.assertIsNone(new_movie.start_date)
        self.assertIsNone(new_movie.end_date)

        self.page.get_by_role("button", name="Completed", exact=True).click()
        edit_modal = self.page.locator("[data-track-modal-root]:visible").first
        expect(edit_modal).to_be_visible()
        edit_modal.locator("button[type='button']").first.click()
        expect(self.page.locator("[data-track-modal-root]:visible")).to_have_count(0)

    @patch("app.models.Item.fetch_releases")
    @patch("app.views._should_queue_game_lengths_refresh", return_value=False)
    @patch("app.providers.services.get_media_metadata")
    def test_game_progress_live_updates_start_date(
        self,
        mock_get_metadata,
        _mock_should_queue_game_lengths_refresh,
        _mock_fetch_releases,
    ):
        """Game progress should backfill the start date immediately in the modal."""
        mock_get_metadata.return_value = {
            "media_id": "186090",
            "title": "Wordle",
            "media_type": MediaTypes.GAME.value,
            "source": Sources.IGDB.value,
            "image": "http://example.com/wordle.jpg",
            "details": {
                "release_date": "2021-06-21",
            },
            "related": {},
            "score": 8.5,
            "score_count": 17,
        }
        item = Item.objects.create(
            media_id="186090",
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title="Wordle",
            image="http://example.com/wordle.jpg",
            release_datetime=datetime(2021, 6, 21, 12, 0, tzinfo=UTC),
        )
        Game.objects.create(
            item=item,
            user=self.user,
            status=Status.PLANNING.value,
            progress=0,
            end_date=datetime(2026, 5, 12, 19, 47, tzinfo=UTC),
        )

        self.page.goto(
            self.live_server_url
            + reverse(
                "media_details",
                kwargs={
                    "source": Sources.IGDB.value,
                    "media_type": MediaTypes.GAME.value,
                    "media_id": "186090",
                    "title": "wordle",
                },
            ),
        )

        expect(self.page.get_by_role("main")).to_contain_text("Wordle")
        self.page.get_by_role("button", name="Planning", exact=True).click()

        modal = self.page.locator("[data-track-modal-root]:visible").first
        expect(modal).to_be_visible()

        end_date_input = modal.locator('input[name="end_date"]')
        start_date_input = modal.locator('input[name="start_date"]')
        progress_input = modal.locator('input[name="progress"]')

        end_date_value = end_date_input.input_value()
        self.assertIn("T", end_date_value)
        end_dt = datetime.strptime(end_date_value, "%Y-%m-%dT%H:%M")

        progress_input.fill("5min")

        expect(start_date_input).to_have_value(
            (end_dt - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M"),
        )

    def test_statistics_status_composition_legend_scrolls_without_page_overflow(self):
        """Status legend scrolls inside its card at responsive widths."""
        statuses = (
            Status.COMPLETED.value,
            Status.IN_PROGRESS.value,
            Status.PLANNING.value,
            Status.PAUSED.value,
            Status.DROPPED.value,
        )
        for index, status in enumerate(statuses):
            item = Item.objects.create(
                media_id=f"status-layout-{index}",
                source=Sources.MANUAL.value,
                media_type=MediaTypes.MOVIE.value,
                title=f"Status layout {index}",
            )
            Movie.objects.create(
                item=item,
                user=self.user,
                status=status,
                progress=1 if status == Status.COMPLETED.value else 0,
            )

        self.page.set_viewport_size({"width": 1024, "height": 774})
        self.page.goto(
            self.live_server_url
            + reverse("statistics")
            + "?start-date=all&end-date=all&compare=none",
        )

        legend = self.page.locator("#statusCompositionLegend")
        expect(legend).to_be_visible()
        expect(legend.locator(":scope > div")).to_have_count(5)

        layout = legend.evaluate(
            """element => ({
                overflowX: getComputedStyle(element).overflowX,
                overflowY: getComputedStyle(element).overflowY,
                clientWidth: element.clientWidth,
                scrollWidth: element.scrollWidth,
            })""",
        )
        self.assertEqual(layout["overflowX"], "auto")
        self.assertEqual(layout["overflowY"], "hidden")
        self.assertGreater(layout["scrollWidth"], layout["clientWidth"])

        page_layout = self.page.evaluate(
            """() => ({
                viewportWidth: window.innerWidth,
                documentWidth: document.documentElement.scrollWidth,
                bodyWidth: document.body.scrollWidth,
                chartWidth: document.getElementById("statusCompositionChart")
                    ?.getBoundingClientRect().width,
            })""",
        )
        self.assertLessEqual(page_layout["documentWidth"], page_layout["viewportWidth"])
        self.assertLessEqual(page_layout["bodyWidth"], page_layout["viewportWidth"])
        self.assertEqual(page_layout["chartWidth"], 150)

        self.page.get_by_role("button", name="All media", exact=True).click()
        self.page.get_by_role("button", name="Movies", exact=True).click()
        expect(self.page.locator("#statusCompositionSubtitle")).to_have_text(
            "Movie status breakdown.",
        )
        filtered_layout = legend.evaluate(
            """element => ({
                overflowX: getComputedStyle(element).overflowX,
                overflowY: getComputedStyle(element).overflowY,
                clientWidth: element.clientWidth,
                scrollWidth: element.scrollWidth,
            })""",
        )
        self.assertEqual(filtered_layout["overflowX"], "auto")
        self.assertEqual(filtered_layout["overflowY"], "hidden")
        self.assertGreater(filtered_layout["scrollWidth"], filtered_layout["clientWidth"])

        self.page.set_viewport_size({"width": 390, "height": 774})
        mobile_layout = self.page.evaluate(
            """() => ({
                viewportWidth: window.innerWidth,
                documentWidth: document.documentElement.scrollWidth,
                bodyWidth: document.body.scrollWidth,
            })""",
        )
        self.assertLessEqual(mobile_layout["documentWidth"], mobile_layout["viewportWidth"])
        self.assertLessEqual(mobile_layout["bodyWidth"], mobile_layout["viewportWidth"])

        self.page.set_viewport_size({"width": 1440, "height": 774})
        desktop_layout = self.page.evaluate(
            """() => ({
                viewportWidth: window.innerWidth,
                documentWidth: document.documentElement.scrollWidth,
                chartWidth: document.getElementById("statusCompositionChart")
                    ?.getBoundingClientRect().width,
            })""",
        )
        self.assertLessEqual(desktop_layout["documentWidth"], desktop_layout["viewportWidth"])
        self.assertEqual(desktop_layout["chartWidth"], 150)
