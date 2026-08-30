import json
import re

from django.core.exceptions import ValidationError

THEME_PRESETS = {
    "system": {"label": "System default"},
    "light": {"label": "Light"},
    "dark": {"label": "Dark"},
    "catppuccin_mocha": {"label": "Catppuccin Mocha"},
    "dracula": {"label": "Dracula"},
    "nord": {"label": "Nord"},
    "gruvbox": {"label": "Gruvbox"},
    "oled": {"label": "OLED"},
    "glass": {"label": "Glass cinema"},
    "plex": {"label": "Plex inspired"},
    "projector": {"label": "Projector"},
    "video_store": {"label": "Video store"},
    "custom": {"label": "Custom palette"},
}
BASIC_THEME_KEYS = frozenset(("system", "light", "dark"))

CUSTOM_THEME_COLORS = {
    "page_bg": {"label": "Page", "default": "#10141f", "token": "page-bg"},
    "surface": {"label": "Cards", "default": "#1b2233", "token": "surface"},
    "panel": {"label": "Panels", "default": "#202940", "token": "panel"},
    "text": {"label": "Text", "default": "#f6f1df", "token": "text"},
    "muted": {"label": "Muted text", "default": "#adb7cc", "token": "text-muted"},
    "accent": {"label": "Accent", "default": "#ffb454", "token": "accent"},
}

CUSTOM_THEME_EFFECTS = {
    "radius": {
        "label": "Corner radius",
        "default": 12,
        "min": 0,
        "max": 28,
        "step": 2,
        "token": "radius",
        "unit": "px",
    },
    "blur": {
        "label": "Backdrop blur",
        "default": 12,
        "min": 0,
        "max": 24,
        "step": 2,
        "token": "blur",
        "unit": "px",
    },
    "surface_opacity": {
        "label": "Surface opacity",
        "default": 82,
        "min": 40,
        "max": 100,
        "step": 2,
        "token": "surface-opacity",
        "unit": "%",
    },
}


def _zone(label, *sections):
    return {
        "label": label,
        "sections": [{"key": key, "label": title} for key, title in sections],
    }


DETAIL_LAYOUT_FAMILIES = {
    "media": {
        "label": "Films, books and manga",
        "zones": {
            "sidebar": _zone(
                "Information column",
                ("history", "Your history"),
                ("details", "Details"),
                ("genres", "Genres"),
                ("studios", "Studios"),
                ("collection", "Collection"),
            ),
            "content": _zone(
                "Main content",
                ("notes", "Notes"),
                ("related", "Related titles"),
                ("cast", "Cast"),
                ("crew", "Crew"),
                ("recommendations", "Recommendations"),
            ),
        },
    },
    "series": {
        "label": "Series and seasons",
        "zones": {
            "sidebar": _zone(
                "Information column",
                ("history", "Your history"),
                ("details", "Details"),
                ("genres", "Genres"),
                ("studios", "Studios"),
                ("collection", "Collection"),
            ),
            "content": _zone(
                "Main content",
                ("notes", "Notes"),
                ("seasons", "Seasons"),
                ("episodes", "Episodes"),
                ("cast", "Cast"),
                ("crew", "Crew"),
                ("recommendations", "Recommendations"),
            ),
        },
    },
    "game": {
        "label": "Games",
        "zones": {
            "sidebar": _zone(
                "Information column",
                ("history", "Your history"),
                ("details", "Details"),
                ("genres", "Genres"),
                ("studios", "Studios"),
                ("collection", "Collection"),
            ),
            "content": _zone(
                "Main content",
                ("notes", "Notes"),
                ("game_lengths", "Play times"),
                ("cast", "Cast"),
                ("crew", "Crew"),
                ("recommendations", "Recommendations"),
            ),
        },
    },
    "episode": {
        "label": "Episodes",
        "zones": {
            "content": _zone(
                "Content",
                ("notes", "Notes"),
                ("cast", "Cast"),
                ("crew", "Crew"),
            )
        },
    },
    "comic": {
        "label": "Comic volumes",
        "zones": {
            "sidebar": _zone(
                "Information column",
                ("history", "Your history"),
                ("details", "Details"),
                ("genres", "Genres"),
                ("studios", "Studios"),
                ("collection", "Collection"),
            ),
            "content": _zone(
                "Main content",
                ("notes", "Notes"),
                ("episodes", "Issues"),
                ("recommendations", "Recommendations"),
            ),
        },
    },
    "comic_issue": {
        "label": "Comic issues",
        "zones": {
            "sidebar": _zone(
                "Information column",
                ("details", "Details"),
                ("authors", "Authors"),
                ("collection", "Collection"),
            ),
        },
    },
    "music_album": {
        "label": "Music albums",
        "zones": {
            "sidebar": _zone(
                "Information column",
                ("details", "Details"),
                ("collection", "Collection"),
            ),
            "content": _zone(
                "Main content", ("notes", "Notes"), ("tracks", "Tracks")
            ),
        },
    },
    "music_artist": {
        "label": "Music artists",
        "zones": {
            "sidebar": _zone(
                "Information column",
                ("details", "Details"),
                ("collection", "Collection"),
            ),
            "content": _zone(
                "Main content",
                ("notes", "Notes"),
                ("relations", "Related artists"),
                ("discography", "Discography"),
            ),
        },
    },
    "podcast": {
        "label": "Podcasts",
        "zones": {
            "sidebar": _zone(
                "Information column",
                ("details", "Details"),
                ("genres", "Genres"),
            ),
            "content": _zone(
                "Main content", ("notes", "Notes"), ("episodes", "Episodes")
            ),
        },
    },
    "person": {
        "label": "People",
        "zones": {
            "hero": _zone("Profile", ("biography", "Biography and facts")),
            "content": _zone("Content", ("filmography", "Filmography")),
        },
    },
    "studio": {
        "label": "Studios",
        "zones": {
            "hero": _zone("Profile", ("overview", "Overview and facts")),
            "content": _zone("Content", ("works", "Works")),
        },
    },
}

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_INVALID_LAYOUT = "Invalid detail layout configuration."
_INVALID_FAMILY = "Unsupported detail page family."
_INVALID_ZONE = "Unsupported detail page zone."
_INVALID_SECTION = "Unsupported detail page section."
_INVALID_PALETTE = "Invalid custom palette."


def default_detail_layouts():
    """Return the complete default order for every detail page zone."""
    return {
        family_key: {
            zone_key: [section["key"] for section in zone["sections"]]
            for zone_key, zone in family["zones"].items()
        }
        for family_key, family in DETAIL_LAYOUT_FAMILIES.items()
    }


def resolved_detail_layouts(saved_layouts):
    """Overlay valid saved choices on the current default registry."""
    resolved = default_detail_layouts()
    if not isinstance(saved_layouts, dict):
        return resolved
    for family_key, family_layout in saved_layouts.items():
        if family_key not in resolved or not isinstance(family_layout, dict):
            continue
        for zone_key, section_keys in family_layout.items():
            if zone_key in resolved[family_key] and isinstance(section_keys, list):
                resolved[family_key][zone_key] = section_keys
    return resolved


def parse_detail_layouts(raw_payload):
    """Parse and validate ordered visible sections submitted by settings."""
    try:
        payload = json.loads(raw_payload or "{}")
    except json.JSONDecodeError as exc:
        raise ValidationError(_INVALID_LAYOUT) from exc
    if not isinstance(payload, dict):
        raise ValidationError(_INVALID_LAYOUT)

    cleaned = {}
    for family_key, family_layout in payload.items():
        family = DETAIL_LAYOUT_FAMILIES.get(family_key)
        if family is None or not isinstance(family_layout, dict):
            raise ValidationError(_INVALID_FAMILY)
        cleaned_family = {}
        for zone_key, section_keys in family_layout.items():
            zone = family["zones"].get(zone_key)
            if zone is None or not isinstance(section_keys, list):
                raise ValidationError(_INVALID_ZONE)
            allowed = {section["key"] for section in zone["sections"]}
            if len(section_keys) != len(set(section_keys)) or any(
                not isinstance(key, str) or key not in allowed for key in section_keys
            ):
                raise ValidationError(_INVALID_SECTION)
            cleaned_family[zone_key] = section_keys
        cleaned[family_key] = cleaned_family
    return cleaned


def parse_custom_theme(raw_payload):
    """Parse allowlisted custom colours and bounded visual effects."""
    try:
        payload = json.loads(raw_payload or "{}")
    except json.JSONDecodeError as exc:
        raise ValidationError(_INVALID_PALETTE) from exc
    if not isinstance(payload, dict):
        raise ValidationError(_INVALID_PALETTE)
    cleaned = {}
    for key, value in payload.items():
        if key in CUSTOM_THEME_COLORS:
            if not isinstance(value, str) or not _HEX_COLOR.fullmatch(value):
                raise ValidationError(_INVALID_PALETTE)
            cleaned[key] = value.lower()
        elif key in CUSTOM_THEME_EFFECTS:
            definition = CUSTOM_THEME_EFFECTS[key]
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not definition["min"] <= value <= definition["max"]
                or (value - definition["min"]) % definition["step"]
            ):
                raise ValidationError(_INVALID_PALETTE)
            cleaned[key] = value
    return cleaned


def custom_theme_css(saved_palette):
    """Serialize validated palette values as CSS custom properties."""
    if not isinstance(saved_palette, dict):
        return ""
    declarations = []
    for key, definition in CUSTOM_THEME_COLORS.items():
        value = saved_palette.get(key)
        if isinstance(value, str) and _HEX_COLOR.fullmatch(value):
            declarations.append(f"--color-{definition['token']}: {value.lower()}")
    for key, definition in CUSTOM_THEME_EFFECTS.items():
        value = saved_palette.get(key)
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and definition["min"] <= value <= definition["max"]
            and not (value - definition["min"]) % definition["step"]
        ):
            declarations.append(
                f"--theme-{definition['token']}: {value}{definition['unit']}"
            )
    return "; ".join(declarations)
