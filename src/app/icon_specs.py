"""Icons as parsed shapes for the shared React ``Icon``, never as markup."""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from django.conf import settings

from app.templatetags import app_tags

ICON_DIR = Path(settings.BASE_DIR) / "templates" / "app" / "icons"
SVG_ATTRS = ("fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin")


def icon_spec(markup):
    """Parse a trusted SVG icon into a root and its child shapes."""
    root = ET.fromstring(re.sub(r"\{\{\s*classes\s*\}\}", "", markup))  # noqa: S314

    def shape(node):
        return {
            "tag": node.tag.rsplit("}", 1)[-1],
            "attrs": dict(node.attrib),
            "children": [shape(child) for child in node],
        }

    return {
        "viewBox": root.get("viewBox", "0 0 24 24"),
        "root": {name: root.get(name) for name in SVG_ATTRS if root.get(name)},
        "children": [shape(child) for child in root],
    }


def file_icon(name):
    """Return the spec for ``app/icons/<name>.svg``."""
    return icon_spec((ICON_DIR / f"{name}.svg").read_text())


def type_icon(name):
    """Return the spec for a media-type icon from the ``icon`` tag."""
    return icon_spec(str(app_tags.icon(name, False, "")))
