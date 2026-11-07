import json
import re
from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.urls import reverse

from app.models import MediaTypes


class ProgressChangerTagTests(SimpleTestCase):
    """The quick progress controls render a React host and a working fallback."""

    def render(self, media):
        return render_to_string("app/components/progress_changer.html", {
            "media": media,
            "csrf_token": "token",
        })

    def media(self, media_type, *, progress=1, maximum=10, value="1", max_value="10",
              unit="episodes", percentage=False):
        return SimpleNamespace(
            id=7,
            item=SimpleNamespace(media_type=media_type),
            progress=progress,
            max_progress=maximum,
            formatted_progress=value,
            formatted_max_progress=max_value,
            progress_unit=unit,
            progress_is_percentage=percentage,
        )

    def test_tv_controls_are_a_host_with_labelled_episode_units(self):
        html = self.render(self.media(MediaTypes.TV.value))
        self.assertIn("data-progress-changer-root", html)
        self.assertIn('"value": "1"', html)
        self.assertIn('"max": "10"', html)
        self.assertIn('"unit": "Episodes"', html)
        self.assertIn('"showMax": true', html)
        self.assertIn('aria-label="Decrease progress"', html)
        self.assertIn('aria-label="Increase progress"', html)
        self.assertIn('hx-post="' + reverse("progress_edit", args=["tv", 7]) + '"', html)
        self.assertIn('hx-target="#progress-tv-7"', html)

    def test_tv_increase_carries_a_watch_operation_identity(self):
        html = self.render(self.media(MediaTypes.TV.value))
        props = json.loads(re.search(r'type="application/json">(.*?)</script>', html, re.DOTALL).group(1))
        self.assertTrue(props["watchOperationId"])
        self.assertIn('"watch_operation_id"', html)
        self.assertIn(props["watchOperationId"], html)

    def test_movie_hides_units_and_maximum_like_the_legacy_control(self):
        html = self.render(self.media(MediaTypes.MOVIE.value, maximum=120, max_value="120"))
        props = json.loads(re.search(r'type="application/json">(.*?)</script>', html, re.DOTALL).group(1))
        self.assertEqual(props["unit"], "")
        self.assertFalse(props["showMax"])
        self.assertEqual(props["watchOperationId"], "")

    def test_minutes_keep_the_maximum_but_drop_the_unit(self):
        html = self.render(self.media(MediaTypes.BOOK.value, maximum=120, max_value="120", unit="minutes"))
        self.assertIn('"unit": ""', html)
        self.assertIn('"showMax": true', html)

    def test_percentage_values_never_show_a_raw_maximum(self):
        html = self.render(self.media(
            MediaTypes.BOOK.value, progress=4, maximum=10, value="40%",
            max_value="100%", unit="percentage", percentage=True,
        ))
        self.assertIn('"value": "40%"', html)
        self.assertIn('"unit": ""', html)
        self.assertIn('"showMax": false', html)

    def test_zero_and_complete_disable_the_matching_button(self):
        empty = self.render(self.media(MediaTypes.TV.value, progress=0, value="0"))
        self.assertIn('"canDecrease": false', empty)
        self.assertRegex(empty, r'aria-label="Decrease progress"[\s\S]*?disabled')
        complete = self.render(self.media(MediaTypes.TV.value, progress=10, value="10", maximum=10))
        self.assertIn('"canIncrease": false', complete)
        self.assertRegex(complete, r'aria-label="Increase progress"[\s\S]*?disabled')

    def test_each_control_gets_its_own_props_id(self):
        first = self.render(self.media(MediaTypes.TV.value))
        second = self.render(self.media(MediaTypes.TV.value))
        ids = re.findall(r'data-props-id="([^"]+)"', first + second)
        self.assertEqual(len(set(ids)), 2)
