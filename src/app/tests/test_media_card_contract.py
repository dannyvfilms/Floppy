"""The media card contract: every poster grid is one card, varied only by surface.

See docs/architecture/media-card.md. If a test here fails after adding a grid,
declare the surface in app.card_surfaces rather than special-casing the card.
"""

import re
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.template import engines
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.urls import reverse

from app.card_surfaces import SURFACES
from app.models import (
    Album,
    AlbumTracker,
    Artist,
    ArtistTracker,
    Item,
    MediaTypes,
    Movie,
    Sources,
    Status,
)

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

    def test_home_grid_preserves_mapping_entry_subtitles(self):
        """Detail carousels reuse Home cards with mapping-shaped entries."""
        content = self.render(
            '{% include "app/components/home_grid.html" %}',
            media_list={
                "items": [{
                    "item": self.item,
                    "media": self.movie,
                    "subtitle_override": "Existing Home subtitle",
                }],
            },
        )
        self.assertIn("Existing Home subtitle", content)
        self.assertIn("Contract Movie", content)

    def test_mixed_home_row_marks_square_and_video_cards(self):
        for media_type, expected_class in (
            (MediaTypes.MUSIC.value, "home-row-card-mixed-square"),
            (MediaTypes.PODCAST.value, "home-row-card-mixed-square"),
            (MediaTypes.VIDEO.value, "home-row-card-mixed-video"),
            (MediaTypes.MOVIE.value, None),
        ):
            with self.subTest(media_type=media_type):
                self.item.media_type = media_type
                for mixed in (True, False):
                    content = self.render(
                        '{% include "app/components/home_grid.html" %}',
                        media_list={
                            "items": [{"item": self.item}],
                            "mixed_media": mixed,
                        },
                    )
                    if expected_class:
                        self.assertEqual(expected_class in content, mixed)
                    else:
                        self.assertNotIn("home-row-card-mixed-", content)

    def test_rating_shows_on_every_surface(self):
        """A rating is never a per-surface choice: a tracked card always shows it."""
        for surface in SURFACES:
            with self.subTest(surface=surface):
                self.assertIn(">8.5</span>", self.render_card(surface))

    def test_artwork_url_is_available_without_javascript_on_every_surface(self):
        """Warm artwork can load from browser cache without a JS unveil step."""
        self.item.image = "/static/test-poster.jpg"
        for surface in SURFACES:
            with self.subTest(surface=surface):
                content = self.render_card(surface)
                self.assertIn('src="/static/test-poster.jpg"', content)
                self.assertIn('loading="lazy"', content)
                self.assertNotIn("data-src=", content)
                self.assertNotIn("lazyload", content)

    @patch("app.image_cache.is_enabled", return_value=False)
    def test_video_cards_use_landscape_only_on_dedicated_surfaces(self, _is_enabled):
        self.item.media_type = MediaTypes.VIDEO.value
        self.item.image = "https://i.ytimg.com/vi/vidAAAAAAAA/hqdefault.jpg"
        template = "{% media_card surface item=item card_media_type='video' video_landscape=wide %}"
        for surface, wide, landscape in (
            ("library", False, True),
            ("home", True, True),
            ("home", False, False),
            ("list", False, False),
        ):
            with self.subTest(surface=surface, wide=wide):
                content = self.render(
                    template, surface=surface, item=self.item, wide=wide
                )
                self.assertIn("video-card", content)
                self.assertEqual("video-card-landscape" in content, landscape)
                self.assertIn("/maxresdefault.jpg", content)
                self.assertIn(
                    'data-image-fallback="https://i.ytimg.com/vi/vidAAAAAAAA/hqdefault.jpg"',
                    content,
                )

    @patch("app.image_cache.is_enabled", return_value=False)
    def test_history_places_video_in_its_own_landscape_row(self, _is_enabled):
        from django.utils import timezone

        video = Item.objects.create(
            media_id="vidAAAAAAAA",
            source=Sources.YOUTUBE.value,
            media_type=MediaTypes.VIDEO.value,
            title="Video example",
            image="https://i.ytimg.com/vi/vidAAAAAAAA/hqdefault.jpg",
        )
        entries = [
            {
                "media_type": "movie",
                "item": self.item,
                "poster": self.item.image,
                "title": self.item.title,
                "display_title": self.item.title,
                "entry_key": "movie",
                "played_at_local": timezone.now(),
            },
            {
                "media_type": "video",
                "item": video,
                "poster": video.image,
                "title": video.title,
                "display_title": video.title,
                "entry_key": "video",
                "played_at_local": timezone.now(),
            },
        ]
        request = RequestFactory().get("/history")
        request.user = self.user
        content = render_to_string(
            "app/components/history_day.html",
            {
                "day": {"entries": entries, "entry_count": 2, "day_key": "today"},
                "user": self.user,
                "history_mode": "activity",
            },
            request=request,
        )
        self.assertEqual(content.count('data-media-type="video"'), 1)
        self.assertEqual(content.count("video-card-landscape"), 1)
        self.assertIn("media-grid media-grid-video", content)
        self.assertIn("/maxresdefault.jpg", content)
        self.assertIn("/hqdefault.jpg", content)

    def test_video_thumbnail_does_not_rewrite_custom_artwork(self):
        from app.templatetags.app_tags import youtube_landscape_thumbnail

        self.assertEqual(
            youtube_landscape_thumbnail(
                "https://i.ytimg.com/vi/vidAAAAAAAA/mqdefault.jpg"
            ),
            "https://i.ytimg.com/vi/vidAAAAAAAA/maxresdefault.jpg",
        )
        custom = "https://example.com/cover.jpg"
        self.assertEqual(youtube_landscape_thumbnail(custom), custom)
        self.assertEqual(
            youtube_landscape_thumbnail("https://i.ytimg.com/vi/other/hqdefault.jpg"),
            "https://i.ytimg.com/vi/other/hqdefault.jpg",
        )

    def test_credit_runtime_chip_stays_clear_of_the_next_episode_link(self):
        """The watched-runtime chip sits at the bottom, not under the top-right link."""
        content = self.render(
            "{% media_card 'credit' item=item media=media credit=credit %}",
            item=self.item,
            media=self.movie,
            credit={"watched_person_runtime_display": "2:30"},
        )
        self.assertRegex(content, r'class="absolute bottom-3 right-2[^"]*">\s*2:30')
        self.assertNotRegex(content, r'top-2 right-2[^"]*">\s*2:30')

    def test_rating_is_a_button_that_rates_the_tracked_item(self):
        """A tracked card's rating opens the shared picker, posting to this item."""
        rate_url = reverse(
            "update_media_score", args=[MediaTypes.MOVIE.value, self.movie.id]
        )
        for surface, flags in SURFACES.items():
            with self.subTest(surface=surface):
                content = self.render_card(surface)
                rate_button = not flags.is_recommend_mode and not flags.rating_read_only
                self.assertEqual("media-card-rate-button" in content, rate_button)
                self.assertEqual(f'hx-post="{rate_url}"' in content, rate_button)

    def test_rating_is_read_only_where_the_viewer_cannot_rate(self):
        """Public pages and untracked items keep the plain rating, with no button."""
        self.assertNotIn(
            "media-card-rate-button",
            self.render_card("related", public_view=True),
        )
        content = self.render(
            "{% media_card 'library' item=item %}",
            item=self.item,
        )
        self.assertNotIn("media-card-rate-button", content)

    def test_unrated_tracked_card_offers_the_empty_star(self):
        """A tracked item with no rating still gets the button, starting empty."""
        self.movie.score = None
        self.movie.save()
        content = self.render_card("library")
        self.assertIn("media-card-rate-button", content)
        self.assertIn("rating: null", content)

    def test_disabled_ratings_hide_the_card_rating(self):
        """Turning ratings off removes the rating and the rate button on every surface."""
        self.user.rating_scale = "0"
        self.user.save()
        for surface in SURFACES:
            with self.subTest(surface=surface):
                content = self.render_card(surface)
                self.assertNotIn("media-card-rate-button", content)
                self.assertNotIn("8.5", content)
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.score, 8.5)

    def test_picker_has_one_star_per_point_of_the_users_scale(self):
        """The picker shows 10 stars on the 10-point scale and 5 on the 5-point scale."""
        for scale, stars in (("10", 10), ("5", 5)):
            with self.subTest(scale=scale):
                self.user.rating_scale = scale
                self.user.save()
                content = self.render_card("library")
                self.assertEqual(content.count('"toggle": true'), stars)

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

    def test_artwork_does_not_wait_for_a_javascript_src_swap(self):
        """Rows and hand-built cards must share native loading with grid cards."""
        offenders = [
            name
            for name, source in self.template_sources()
            if re.search(r"<img\b[^>]*\bdata-src=", source, re.DOTALL)
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


class MusicGridRatingTest(TestCase):
    """The music library's artist and album cards rate through the same picker."""

    def setUp(self):
        """Create an artist and an album the user tracks."""
        self.user = get_user_model().objects.create_user(
            username="music-grid",
            password="12345",
        )
        self.artist = Artist.objects.create(name="Grid Artist")
        self.album = Album.objects.create(title="Grid Album", artist=self.artist)

    def render_grid(self, template, tracker):
        """Render a music grid partial holding one tracker."""
        request = RequestFactory().get("/")
        request.user = self.user
        return render_to_string(
            template,
            {"media_list": [tracker], "user": self.user, "media_type": "music"},
            request,
        )

    def test_artist_card_rates_the_artist(self):
        """An unrated artist card offers the empty star and posts to the artist."""
        tracker = ArtistTracker.objects.create(user=self.user, artist=self.artist)
        content = self.render_grid("app/components/artist_grid_items.html", tracker)
        self.assertIn("media-card-rate-button", content)
        self.assertIn(
            f'hx-post="{reverse("update_artist_score", args=[self.artist.id])}"',
            content,
        )

    def test_album_card_rates_the_album(self):
        """A rated album card shows its score and posts to the album."""
        tracker = AlbumTracker.objects.create(
            user=self.user,
            album=self.album,
            score=6,
        )
        content = self.render_grid("app/components/album_list_grid_items.html", tracker)
        self.assertIn("rating: 6", content)
        self.assertIn(
            f'hx-post="{reverse("update_album_score", args=[self.album.id])}"',
            content,
        )


# Hand-rolled cards that are not the shared card. Each one has to call the
# profile tag. list_grid is a list index, not a media card.
PROFILE_CARDS = (
    "app/components/history_card.html",
    "app/components/artist_grid_items.html",
    "app/components/album_list_grid_items.html",
    "app/components/album_grid.html",
    "app/components/artist_relation_grid.html",
    "app/search.html",
    "app/components/media_card_list.html",
    "app/components/episode_row.html",
    "app/components/person_card_inline.html",
    "app/components/person_filmography_card.html",
    "app/components/statistics/highlight_set.html",
    "app/components/active_playback_card.html",
    "app/episode_details.html",
    "events/components/calendar_list.html",
    "events/components/calendar_grid.html",
)


class CardProfileContractTest(TestCase):
    """A card that ignores the profile fails here."""

    def test_inventory_templates_read_the_profile(self):
        """Every listed card calls the shared line tag."""
        missing = [
            name
            for name in PROFILE_CARDS
            if "card_lines" not in (TEMPLATES_DIR / name).read_text()
        ]
        self.assertEqual(missing, [])

    def test_lists_index_has_no_hover_class(self):
        """Item count stays visible. The index is not a media card."""
        source = (TEMPLATES_DIR / "lists/components/list_grid.html").read_text()
        self.assertNotIn("media-card-subtitle-always", source)
        self.assertNotIn("card_lines", source)

    def test_custom_movie_fields_render_on_the_shared_card(self):
        """A saved field list replaces the default year line."""
        self.user = get_user_model().objects.create_user(
            username="card-user",
            password="12345",
        )
        item = Item.objects.create(
            media_id="card-fields",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Field Movie",
            genres=["Drama"],
            runtime="120 min",
        )
        movie = Movie.objects.create(
            item=item,
            user=self.user,
            status=Status.COMPLETED.value,
            progress=1,
            score=8,
        )
        self.user.card_metadata = {
            "version": 1,
            "types": {
                "movie": {
                    "display": "always",
                    "fields": ["genres", "runtime"],
                    "options": {"rating": {"hide_zero": False}},
                }
            },
        }
        self.user.save(update_fields=["card_metadata"])
        request = RequestFactory().get("/")
        request.user = self.user
        template = engines["django"].from_string(
            "{% load app_tags %}{% media_card 'library' item=item media=media %}"
        )
        content = template.render(
            {"user": self.user, "item": item, "media": movie},
            request,
        )
        self.assertIn("Drama", content)
        self.assertIn("120 min", content)
