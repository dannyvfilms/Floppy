from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from app.models import MediaTypes, Sources


class RtExtrasFragmentTests(TestCase):
    """The deferred Rotten Tomatoes extras for detail pages."""

    @patch("app.views.rottentomatoes.media_scores")
    @patch("app.views.services.get_media_metadata")
    def test_movie_page_returns_oob_link_chip(
        self, mock_get_metadata, mock_media_scores
    ):
        """A resolved movie emits the external-links chip out of band."""
        mock_get_metadata.return_value = {"media_type": MediaTypes.MOVIE.value}
        mock_media_scores.return_value = {
            "url": "https://www.rottentomatoes.com/m/dune_2021"
        }

        response = self.client.get(
            reverse(
                "rt_extras",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.MOVIE.value,
                    "media_id": "118340",
                },
            ),
        )

        content = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="detail-link-rt"', content)
        self.assertIn('hx-swap-oob="true"', content)
        self.assertIn("https://www.rottentomatoes.com/m/dune_2021", content)
        self.assertIn("Rotten Tomatoes", content)

    @patch("app.views.rottentomatoes.media_scores")
    @patch("app.views.services.get_media_metadata")
    def test_movie_page_returns_oob_score_cards(
        self, mock_get_metadata, mock_media_scores
    ):
        """Resolved scores emit Tomatometer and Popcornmeter cards out of band."""
        mock_get_metadata.return_value = {"media_type": MediaTypes.MOVIE.value}
        mock_media_scores.return_value = {
            "url": "https://www.rottentomatoes.com/m/dune_2021",
            "tomatometer": {
                "value": "83",
                "suffix": "%",
                "count": "458 reviews",
                "certified": True,
            },
            "popcornmeter": {
                "value": "95",
                "suffix": "%",
                "count": "5,000+ Ratings",
                "certified": False,
            },
        }

        response = self.client.get(
            reverse(
                "rt_extras",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.MOVIE.value,
                    "media_id": "118340",
                },
            ),
        )

        content = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="detail-score-rt"', content)
        self.assertIn("83%", content)
        self.assertIn("458 reviews", content)
        self.assertIn("95%", content)
        self.assertIn("5,000+ Ratings", content)

    @patch("app.views.rottentomatoes.media_scores")
    @patch("app.views.services.get_media_metadata")
    def test_movie_page_without_scores_returns_no_cards(
        self, mock_get_metadata, mock_media_scores
    ):
        """A match without a scorecard emits no score cards."""
        mock_get_metadata.return_value = {"media_type": MediaTypes.MOVIE.value}
        mock_media_scores.return_value = {
            "url": "https://www.rottentomatoes.com/m/dune_2021",
            "tomatometer": None,
            "popcornmeter": None,
        }

        response = self.client.get(
            reverse(
                "rt_extras",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.MOVIE.value,
                    "media_id": "118340",
                },
            ),
        )

        content = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('id="detail-score-rt"', content)

    @patch("app.views.services.get_media_metadata")
    def test_route_is_public(self, mock_get_metadata):
        """Anonymous viewers of a public detail page get the same extras."""
        mock_get_metadata.return_value = {"media_type": MediaTypes.MOVIE.value}
        self.client.logout()

        response = self.client.get(
            reverse(
                "rt_extras",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.MOVIE.value,
                    "media_id": "118340",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
