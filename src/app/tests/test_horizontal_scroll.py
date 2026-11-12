from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class HorizontalScrollContractTests(SimpleTestCase):
    def setUp(self):
        self.root = Path(settings.BASE_DIR)

    def read(self, relative_path):
        return self.root.joinpath(relative_path).read_text(encoding="utf-8")

    def test_shared_rows_enable_accessible_horizontal_drag(self):
        row = self.read("templates/app/components/_scrollable_row.html")

        self.assertIn('data-horizontal-drag="true"', row)
        self.assertIn('tabindex="0"', row)
        self.assertIn('role="region"', row)
        self.assertIn('aria-label="{{ translated_title_main }}"', row)
        self.assertIn(
            'aria-label="{{ translated_title_main }} • {{ translated_title_detail }}"',
            row,
        )
        # Filter arguments raise VariableDoesNotExist when the key is missing,
        # so the label must not resolve row.title_main as a `default` argument:
        # rows built outside the home screen only carry `title`. See #1139.
        self.assertNotIn("default:row.title_main", row)

    def test_base_loads_the_horizontal_drag_controller_once(self):
        base = self.read("templates/base.html")

        script_tag = '<script src="{% static \'js/horizontal-scroll.js\' %}'
        self.assertEqual(base.count(script_tag), 1)

    def test_drag_styles_use_theme_tokens(self):
        css = self.read("static/css/input.css")

        self.assertIn('[data-horizontal-drag="true"]', css)
        self.assertIn("cursor: grab", css)
        self.assertIn("cursor: grabbing", css)
        self.assertIn("var(--color-link)", css)

    def test_proven_rows_opt_in_to_the_shared_rail(self):
        home = self.read("templates/app/components/home_groups.html")
        detail = self.read("templates/app/components/detail_secondary_content.html")
        row = self.read("templates/app/components/_scrollable_row.html")

        self.assertIn("row=row rails_mount=True", home)
        self.assertIn(
            'grid_template="app/components/home_grid.html" '
            'collapse_key="detail-recommendations-open" rails_mount=True',
            detail,
        )
        self.assertIn("{% rails_row_props row as rails_row %}", row)
        self.assertIn("data-rails-row-root", row)
        self.assertIn('data-props-id="{{ rails_row.id }}"', row)
