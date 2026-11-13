from django.template import Context, Template
from django.test import TestCase


class TemplateFiltersTagsTests(TestCase):
    """Tests for custom template filters and tags."""

    def test_get_item_filter(self):
        """Test the get_item filter."""
        # Create a template that uses the get_item filter
        template_str = """
            {% load events_tags %}
            {{ my_dict|get_item:"key1" }}
            {{ my_dict|get_item:"key2" }}
            {{ my_dict|get_item:"nonexistent_key" }}
        """
        template = Template(template_str)

        # Create a context with a dictionary
        context = Context(
            {
                "my_dict": {
                    "key1": "value1",
                    "key2": ["item1", "item2"],
                },
            },
        )

        # Render the template
        rendered = template.render(context)

        # Check the output
        self.assertIn("value1", rendered)
        self.assertIn("item1", rendered)
        self.assertIn("item2", rendered)
        self.assertIn("[]", rendered)  # Default empty list for nonexistent key

    def test_get_item_filter_with_empty_dict(self):
        """Test the get_item filter with an empty dictionary."""
        template_str = """
            {% load events_tags %}
            {{ empty_dict|get_item:"any_key" }}
        """
        template = Template(template_str)
        context = Context({"empty_dict": {}})
        rendered = template.render(context)
        self.assertIn("[]", rendered)

    def test_day_of_week_tag(self):
        """Test the day_of_week tag."""
        # Create a template that uses the day_of_week tag
        template_str = """
            {% load events_tags %}
            {% day_of_week 1 1 2023 %}
            {% day_of_week 4 7 2023 %}
            {% day_of_week 25 12 2023 %}
            {% day_of_week "31" "10" "2023" %}
        """
        template = Template(template_str)

        # Render the template
        rendered = template.render(Context({}))

        # Check the output
        # January 1, 2023 was a Sunday
        self.assertIn("Sunday", rendered)
        # July 4, 2023 was a Tuesday
        self.assertIn("Tuesday", rendered)
        # December 25, 2023 was a Monday
        self.assertIn("Monday", rendered)
        # October 31, 2023 was a Tuesday
        self.assertIn("Tuesday", rendered)

    def test_day_of_week_tag_with_variables(self):
        """Test the day_of_week tag with variables."""
        template_str = """
            {% load events_tags %}
            {% day_of_week day month year %}
        """
        template = Template(template_str)

        # Test with different dates
        test_dates = [
            {"day": 1, "month": 1, "year": 2023, "expected": "Sunday"},
            {"day": 4, "month": 7, "year": 2023, "expected": "Tuesday"},
            {"day": 25, "month": 12, "year": 2023, "expected": "Monday"},
            {"day": "31", "month": "10", "year": "2023", "expected": "Tuesday"},
        ]

        for date_data in test_dates:
            context = Context(
                {
                    "day": date_data["day"],
                    "month": date_data["month"],
                    "year": date_data["year"],
                },
            )
            rendered = template.render(context)
            self.assertIn(date_data["expected"], rendered)

    def test_day_of_week_tag_edge_cases(self):
        """Test the day_of_week tag with edge cases."""
        # Test leap year
        template_str = """
            {% load events_tags %}
            {% day_of_week 29 2 2020 %}
        """
        template = Template(template_str)
        rendered = template.render(Context({}))
        self.assertIn("Saturday", rendered)  # February 29, 2020 was a Saturday

        # Test with future date
        template_str = """
            {% load events_tags %}
            {% day_of_week 1 1 2030 %}
        """
        template = Template(template_str)
        rendered = template.render(Context({}))
        # January 1, 2030 will be a Tuesday
        self.assertIn("Tuesday", rendered)

    def test_day_of_week_tag_invalid_input(self):
        """Test the day_of_week tag with invalid input."""
        # Test with invalid date (February 30)
        template_str = """
            {% load events_tags %}
            {% day_of_week 30 2 2023 %}
        """
        template = Template(template_str)

        # This should raise a ValueError
        with self.assertRaises(ValueError):
            template.render(Context({}))

        # Test with non-numeric input
        template_str = """
            {% load events_tags %}
            {% day_of_week "day" "month" "year" %}
        """
        template = Template(template_str)

        # This should raise a ValueError
        with self.assertRaises(ValueError):
            template.render(Context({"day": "day", "month": "month", "year": "year"}))


class CalendarEventUrlTests(TestCase):
    """Calendar entries open the episode page for TV episodes."""

    def _event(self, media_type, content_number, library_media_type=""):
        from datetime import UTC, datetime

        from app.models import Item, Sources
        from events.models import Event

        item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=media_type,
            title="Friends",
            image="none",
            season_number=2 if media_type == "season" else None,
            library_media_type=library_media_type,
        )
        return Event.objects.create(
            item=item,
            content_number=content_number,
            datetime=datetime(2025, 1, 1, tzinfo=UTC),
        )

    def test_season_event_links_to_episode(self):
        from events.templatetags.events_tags import calendar_event_url

        url = calendar_event_url(self._event("season", 5))
        self.assertTrue(url.endswith("/season/2/episode/5"), url)

    def test_season_event_without_episode_number_falls_back(self):
        from events.templatetags.events_tags import calendar_event_url

        url = calendar_event_url(self._event("season", None))
        self.assertIn("/season/2", url)
        self.assertNotIn("/episode/", url)

    def test_movie_event_keeps_item_url(self):
        from events.templatetags.events_tags import calendar_event_url

        self.assertIn("/movie/", calendar_event_url(self._event("movie", None)))
