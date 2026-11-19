"""No module reaches into ``app.views`` for an underscore-prefixed name.

``app/views.py`` is an index for ``app/urls.py``. Shared detail builders have
public homes: ``app/detail_builders.py`` (link sections and other detail
cards), ``app/tag_views.py`` (tag sections), ``app/track_modal_views.py``
(track modal pieces) and ``app/discover_views.py`` (Discover refresh). Import
from those modules instead of calling ``app.views._name``.
"""

import re
from pathlib import Path

from django.test import SimpleTestCase

SRC = Path(__file__).resolve().parents[2]
BARREL_ALIAS = re.compile(r"from app import views as (\w+)")
FROM_BARREL_PRIVATE = re.compile(r"from app\.views import [^\n]*\b_\w+")
MESSAGE = (
    "{path}:{line} uses a private name through app.views. Import the public "
    "builder from its own module (app/detail_builders.py, app/tag_views.py, "
    "app/track_modal_views.py or app/discover_views.py) instead."
)


class NoViewBarrelPrivateReachTests(SimpleTestCase):
    def test_no_module_calls_app_views_private_names(self):
        problems = []
        for path in sorted(SRC.rglob("*.py")):
            relative = path.relative_to(SRC)
            if relative == Path("app/views.py") or "tests" in relative.parts:
                continue
            text = path.read_text(encoding="utf-8")
            if "app.views" not in text and "from app import views" not in text:
                continue
            aliases = {"view_barrel", *BARREL_ALIAS.findall(text)}
            if re.search(r"from app import (\w+, )*views\b(?! as)", text):
                aliases.add("views")
            private_use = re.compile(
                r"\b(?:" + "|".join(sorted(aliases)) + r"|app\.views)\._\w",
            )
            for number, line in enumerate(text.splitlines(), start=1):
                if private_use.search(line) or FROM_BARREL_PRIVATE.search(line):
                    problems.append(MESSAGE.format(path=relative, line=number))
        self.assertEqual(problems, [], "\n".join(problems))
