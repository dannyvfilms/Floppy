import os
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import tag
from django.urls import reverse
from playwright.sync_api import sync_playwright

from app.models import Item, MediaTypes, Movie, Sources, Status
from app.tests.live_server import SerialStaticLiveServerTestCase


@tag("slow", "playwright")
class ProgressChangerBrowserTests(SerialStaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.allow_async = patch.dict(os.environ, {"DJANGO_ALLOW_ASYNC_UNSAFE": "true"})
        cls.allow_async.start()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.allow_async.stop()
        super().tearDownClass()

    def _media(self, media_type, *, instance_id, progress=1, maximum=None,
               value="1", max_value="", unit="", percentage=False):
        return SimpleNamespace(
            id=instance_id,
            item=SimpleNamespace(media_type=media_type),
            progress=progress,
            max_progress=maximum,
            formatted_progress=value,
            formatted_max_progress=max_value,
            progress_unit=unit,
            progress_is_percentage=percentage,
        )

    def _component(self, media, token):
        return render_to_string("app/components/progress_changer.html", {
            "media": media, "csrf_token": token,
        })

    def test_real_progress_controls_match_the_fallback_and_write(self):
        user = get_user_model().objects.create_user(username="progress-proof")
        item = Item.objects.create(
            media_id="progress-proof", source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value, title="Progress proof",
        )
        movie = Movie.objects.create(
            item=item, user=user, status=Status.IN_PROGRESS.value, progress=1,
        )
        self.client.force_login(user)
        self.client.get(reverse("home"))
        token = self.client.cookies["csrftoken"].value
        movie_html = self._component(
            self._media(MediaTypes.MOVIE.value, instance_id=movie.id), token,
        )
        unit_html = self._component(
            self._media(MediaTypes.TV.value, instance_id=999999, maximum=10, value="1", max_value="10", unit="episodes"),
            token,
        )
        page = self.browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        context = page.context
        context.add_cookies([
            {"name": "sessionid", "value": self.client.cookies["sessionid"].value, "url": self.live_server_url},
            {"name": "csrftoken", "value": token, "url": self.live_server_url},
        ])
        page.goto(self.live_server_url + "/static/css/main.css")
        page.set_content(f"""<!doctype html><html class="dark"><head>
          <link rel="stylesheet" href="/static/css/main.css">
          <link rel="stylesheet" href="/static/ui/settings-islands.css">
          <script src="/static/js/libraries/htmx-2.0.4.min.js"></script>
          </head><body data-quick-season-mobile="true">
          <div class="mt-2 flex items-center justify-center"><div id="progress-movie-{movie.id}" class="media-card-progress" data-progress-mode="always">{movie_html}</div></div>
          <div id="unit-case" class="mt-2 flex items-center justify-center">{unit_html}</div>
          <script>
            const host = document.querySelector('[data-progress-changer-root]');
            const clone = document.createElement('div');
            clone.className = 'old-case';
            clone.innerHTML = host.innerHTML;
            document.body.append(clone);
          </script>
          <script type="module" src="/static/ui/settings-islands.js"></script>
          </body></html>""")
        page.wait_for_function("document.querySelectorAll('[data-progress-changer-root][data-react-mounted]').length === 2")

        self.assertEqual(page.locator(".old-case .progress-value").inner_text(), "1")
        self.assertEqual(page.locator(f"#progress-movie-{movie.id} [data-progress-changer-root] > *").inner_text().strip(), "1")
        self.assertEqual(page.locator("#unit-case [data-progress-changer-root] > *").inner_text().replace("\n", " "), "1 / 10 Episodes")

        for theme in ("", "light", "dark", "catppuccin_mocha", "dracula", "nord", "gruvbox", "oled", "glass", "plex", "projector", "video_store", "custom"):
            page.evaluate("theme => { document.documentElement.className = theme; }", theme)
            # The server fallback uses CSS background transitions when
            # themes change; wait for those to settle before comparing its
            # computed pixels with the immediately updated native surface.
            page.wait_for_timeout(350)
            diffs = page.evaluate("""(id) => {
              const oldRow = document.querySelector('.old-case .progress-changer');
              const newRow = document.querySelector('#progress-movie-' + id + ' [data-progress-changer-root][data-react-mounted] > div');
              const oldButtons = [...oldRow.querySelectorAll('.progress-adjust-btn')].filter(e => getComputedStyle(e).display !== 'none');
              const newButtons = [...newRow.querySelectorAll('[role="button"]')];
              if (oldButtons.length !== newButtons.length) return ['button count'];
              const canvas = document.createElement('canvas'); canvas.width = canvas.height = 1;
              const ctx = canvas.getContext('2d');
              const rgba = value => { ctx.clearRect(0,0,1,1); ctx.fillStyle = value; ctx.fillRect(0,0,1,1); return [...ctx.getImageData(0,0,1,1).data]; };
              const colorDiff = (a, b) => rgba(a).some((v, i) => Math.abs(v - rgba(b)[i]) > 3);
              const a = oldButtons[0].getBoundingClientRect(), b = newButtons[0].getBoundingClientRect();
              const x = getComputedStyle(oldButtons[0]), y = getComputedStyle(newButtons[0]);
              const oldText = oldRow.querySelector('.progress-value');
              const newText = newRow.querySelector('[aria-live] > *');
              const tx = getComputedStyle(oldText), ty = getComputedStyle(newText);
              return [
                Math.abs(a.width - b.width) > 0.2 || Math.abs(a.height - b.height) > 0.2 ? 'button box' : null,
                colorDiff(x.backgroundColor, y.backgroundColor)
                   ? 'button color (server=' + x.backgroundColor + ', shared=' + y.backgroundColor + ')' : null,
                colorDiff(tx.color, ty.color) ? 'text color' : null,
                Math.abs(parseFloat(tx.fontSize) - parseFloat(ty.fontSize)) > 0.2 ? 'font size' : null,
                oldRow.innerText.trim() !== newRow.innerText.trim() ? 'text' : null,
              ].filter(Boolean);
            }""", movie.id)
            self.assertEqual(diffs, [], f"{theme}: {diffs}")

        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(200)
        self.assertEqual(page.locator(f"#progress-movie-{movie.id} [role=button]").count(), 2)
        page.evaluate("document.body.dataset.quickSeasonMobile = 'false'")
        page.wait_for_function(f"document.querySelector('#progress-movie-{movie.id}').getBoundingClientRect().height === 0")
        page.evaluate("document.body.dataset.quickSeasonMobile = 'true'; document.body.dataset.mobileGrid = 'compact'")
        page.wait_for_function("!document.querySelector('#unit-case [data-progress-changer-root] > div').innerText.includes('Episodes')")

        page.set_viewport_size({"width": 1440, "height": 900})
        page.evaluate("document.body.dataset.quickSeasonMobile = 'true'; delete document.body.dataset.mobileGrid")
        page.wait_for_timeout(200)
        increase = page.locator(f"#progress-movie-{movie.id} [role=button]").last
        increase.click()
        page.wait_for_function(f"document.querySelector('#progress-movie-{movie.id} [data-progress-changer-root] > div').innerText.trim() === '2'", timeout=15000)
        page.wait_for_function(f"document.querySelector('#progress-movie-{movie.id} [data-progress-changer-root][data-react-mounted]') !== null")
        page.locator(f"#progress-movie-{movie.id} [role=button]").first.click()
        page.wait_for_function(f"document.querySelector('#progress-movie-{movie.id} [data-progress-changer-root] > div').innerText.trim() === '1'", timeout=15000)
        self.assertFalse(errors, errors)
        page.close()
