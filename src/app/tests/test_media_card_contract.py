"""The media card contract: every poster grid is one card, varied only by surface.

See docs/architecture/media-card.md. If a test here fails after adding a grid,
declare the surface in app.card_surfaces rather than special-casing the card.
"""

import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.template import engines
from django.test import RequestFactory, TestCase

from app.card_surfaces import SURFACES
from app.models import Item, MediaTypes, Movie, Sources, Status

TEMPLATES_DIR = Path(settings.BASE_DIR) / "templates"
CARD_TEMPLATE = "app/components/media_card.html"


class MediaCardSurfaceContractTest(TestCase):
    """Render one tracked, rated, completed movie on every surface."""

    def setUp(self):
        """Create a user who rated and completed a movie."""
        self.user = get_user_model().objects.create_user(
            username="card-user",
            password="12345",
        )
        self.item = Item.objects.create(
            media_id="card-contract",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Contract Movie",
        )
        self.movie = Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.COMPLETED.value,
            progress=1,
            score=8.5,
        )

    def render(self, source, **context):
        """Render template ``source`` as a request by the test user."""
        request = RequestFactory().get("/")
        request.user = self.user
        template = engines["django"].from_string("{% load app_tags %}" + source)
        return template.render({"user": self.user, **context}, request)

    def render_card(self, surface, **context):
        """Render the card for the test movie on ``surface``."""
        return self.render(
            "{% media_card surface item=item media=media %}",
            surface=surface,
            item=self.item,
            media=self.movie,
            search_preview_url="/preview",
            **context,
        )

    def test_rating_shows_on_every_surface(self):
        """A rating is never a per-surface choice: a tracked card always shows it."""
        for surface in SURFACES:
            with self.subTest(surface=surface):
                self.assertIn(">8.5</span>", self.render_card(surface))

    def test_status_chip_follows_the_surface_table(self):
        """The status chip shows exactly where the surface declares it."""
        for surface, flags in SURFACES.items():
            with self.subTest(surface=surface):
                content = self.render_card(surface)
                self.assertEqual(
                    'class="media-status-chip ' in content,
                    flags.show_status_chip,
                )

    def test_untracked_card_has_no_rating_or_status(self):
        """An untracked item shows neither, on any surface."""
        for surface in SURFACES:
            with self.subTest(surface=surface):
                content = self.render(
                    "{% media_card surface item=item %}",
                    surface=surface,
                    item=self.item,
                    search_preview_url="/preview",
                )
                self.assertIn("Contract Movie", content)
                self.assertNotIn(">8.5</span>", content)
                self.assertNotIn('class="media-status-chip ', content)

    def test_card_values_do_not_leak_from_the_page(self):
        """A value the call does not set is cleared, not read from the page."""
        content = self.render_card(
            "library",
            collection_completeness={"is_partial": True, "collected": 1, "total": 9},
            matched_title="Leaked Title",
        )
        self.assertNotIn("1/9 collected", content)
        self.assertNotIn("Leaked Title", content)

    def test_page_values_are_inherited_from_the_page(self):
        """A public page hides hover actions on its cards without each call saying so."""
        content = self.render_card("related", public_view=True)
        self.assertNotIn("media-card-overlay absolute", content)

    def test_two_cards_for_one_item_do_not_share_modal_targets(self):
        """A second copy of an item opens its own modal, not the first card's."""
        content = self.render_card("collection") + self.render_card("collection")
        track_ids = re.findall(r'<div id="(track-movie-[^"]+)"></div>', content)
        self.assertEqual(len(track_ids), 2)
        self.assertNotEqual(track_ids[0], track_ids[1])
        for track_id in track_ids:
            self.assertIn(f'hx-target="#{track_id}"', content)

    def test_unknown_value_is_rejected(self):
        """An ad-hoc flag must be declared in app.card_surfaces first."""
        with self.assertRaises(TypeError):
            self.render(
                "{% media_card 'library' item=item show_new_thing=True %}",
                item=self.item,
            )

    def test_unknown_surface_is_rejected(self):
        """A surface must be declared before a template can use it."""
        with self.assertRaises(ValueError):
            self.render("{% media_card 'nowhere' item=item %}", item=self.item)


class MediaCardTemplateUsageTest(TestCase):
    """Every template renders the card through the tag, with a declared surface."""

    def template_sources(self):
        """Yield ``(relative path, source)`` for every project template."""
        for path in TEMPLATES_DIR.rglob("*.html"):
            yield path.relative_to(TEMPLATES_DIR).as_posix(), path.read_text()

    def test_no_template_includes_the_card_directly(self):
        """A direct include bypasses the surface table, which is how drift starts."""
        offenders = [
            name
            for name, source in self.template_sources()
            if re.search(r"\{%\s*include\s+[\"']" + re.escape(CARD_TEMPLATE), source)
        ]
        self.assertEqual(offenders, [])

    def test_every_surface_used_in_a_template_is_declared(self):
        """A typo in a surface name fails here, not on the page."""
        used = {
            (name, surface)
            for name, source in self.template_sources()
            for surface in re.findall(r"\{%\s*media_card\s+[\"'](\w+)[\"']", source)
        }
        self.assertTrue(used)
        undeclared = sorted(pair for pair in used if pair[1] not in SURFACES)
        self.assertEqual(undeclared, [])
