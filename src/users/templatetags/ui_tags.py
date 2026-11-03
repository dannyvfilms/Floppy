"""Server-owned content slots for the incremental React settings-card pilot."""

from uuid import uuid4

from django import template
from django.template.base import token_kwargs
from django.template.loader import render_to_string

register = template.Library()

SPINNER_SIZES = (8, 48)
BADGE_SIZES = {"xs", "sm", "md", "tag"}
BADGE_TONES = {
    "indigo", "rose", "violet", "neutral", "outline", "tint", "genre",
    "green-soft", "indigo-soft", "emerald-soft", "amber-soft",
}
BUTTON_TONES = {"primary", "danger-solid", "danger-deep", "surface", "ghost-danger"}
BUTTON_ATTRS = {"id", "name", "value", "form", "formaction", "title"}
BUTTON_ATTR_PREFIXES = ("hx-", "data-", "aria-")


@register.tag
def settings_card(parser, token):
    """Render a shared card without passing its forms or credentials to React."""
    bits = token.split_contents()
    options = token_kwargs(bits[1:], parser)
    allowed = {"title", "tone", "badge", "info_label", "info_title", "enabled"}
    if "title" not in options or set(options) - allowed or any("=" not in bit for bit in bits[1:]):
        message = "settings_card requires title and named presentation options only"
        raise template.TemplateSyntaxError(message)
    body = parser.parse(("endsettings_card",))
    parser.delete_first_token()
    return SettingsCardNode(options, body)


class SettingsCardNode(template.Node):
    """Compose escaped presentation props and a separately rendered content slot."""

    def __init__(self, options, body):
        """Keep the compiled expressions and Django body for each render."""
        self.options = options
        self.body = body

    def render(self, context):
        """Render the shell, or only its body for legacy dialog consumers."""
        if "enabled" in self.options and not self.options["enabled"].resolve(context):
            return self.body.render(context)
        props = {name: str(value.resolve(context)) for name, value in self.options.items()}
        props.pop("enabled", None)
        if props.get("tone") not in {"neutral", "info", "warning", "success"}:
            props["tone"] = "neutral"
        # The body remains Django HTML, outside the React root. Never serialize it.
        return render_to_string("users/components/settings_card.html", {
            "card": props,
            "props_id": f"settings-card-{uuid4().hex}",
            "body": self.body.render(context),
        })


@register.simple_tag
def settings_link_chip(label, url):
    """Render a shared link chip with a usable server fallback."""
    return render_to_string("users/components/settings_link_chip.html", {
        "chip": {"label": label, "href": url, "tone": "info",
                 "hrefAttrs": {"target": "_blank", "rel": "noopener"}},
        "props_id": f"settings-chip-{uuid4().hex}",
    })


@register.simple_tag(takes_context=True)
def rating_stars(context, post_url):
    """Render the shared React star row; the caller's popup owns open/close state."""
    from django.utils.translation import gettext as _

    from app.templatetags.app_tags import rating_scale_max

    return render_to_string("app/components/rating_stars.html", {
        "props": {
            "postUrl": str(post_url),
            "scaleMax": rating_scale_max(context.get("user")),
            "csrfToken": str(context.get("csrf_token") or ""),
            "label": str(_("Rate")),
        },
        "props_id": f"rating-stars-{uuid4().hex}",
    })


@register.simple_tag
def spinner(size=16, tone="accent"):
    """Render the shared React loading ring; the server markup is the fallback."""
    return render_to_string("users/components/spinner.html", {
        "props": {
            "size": size if isinstance(size, int) and SPINNER_SIZES[0] <= size <= SPINNER_SIZES[1] else 16,
            "tone": tone if tone in {"accent", "muted", "white"} else "accent",
        },
        "props_id": f"spinner-{uuid4().hex}",
    })


@register.simple_tag
def badge(label, size="sm", tone="outline", href="", nowrap=False):
    """Render the shared React badge; the server markup is the fallback."""
    return render_to_string("users/components/badge.html", {
        "props": {
            "label": str(label),
            "size": size if size in BADGE_SIZES else "sm",
            "tone": tone if tone in BADGE_TONES else "outline",
            "href": str(href) if str(href).startswith(("/", "?")) else "",
            "nowrap": bool(nowrap),
        },
        "props_id": f"badge-{uuid4().hex}",
    })


def _button_attrs(attrs):
    """Keep the attributes a button may carry; names use `_` where HTML uses `-`."""
    kept = {}
    for raw_name, value in attrs.items():
        name = raw_name.replace("_", "-") if raw_name.startswith(("hx_", "data_", "aria_")) else raw_name
        # hx-on* attributes run inline script, so they stay out of the adapter.
        if name in BUTTON_ATTRS or (name.startswith(BUTTON_ATTR_PREFIXES) and not name.startswith("hx-on")):
            kept[name] = str(value)
    return kept


@register.simple_tag
def button(label, tone="primary", size="sm", width="auto", *, submit=False, disabled=False, **attrs):
    """Render the shared React button; the server markup is the fallback.

    `label` is text only. `attrs` take id, name, value, form, formaction, title and
    hx_*, data_*, aria_* (written with `_`). A button that htmx swaps in place of itself,
    or one that carries Alpine bindings, stays hand-written.
    """
    tone = tone if tone in BUTTON_TONES else "primary"
    small = size != "base" or tone == "ghost-danger"
    auto = width != "full"
    classes = "ui-button ui-button-flat"
    classes += "" if tone == "primary" else f" ui-button-tone-{tone}"
    classes += (" ui-button-small" if small else "") + (" ui-button-auto" if auto else "")
    return render_to_string("users/components/button.html", {
        "props": {
            "label": str(label),
            "tone": None if tone == "primary" else tone,
            "small": small,
            "auto": auto,
            "type": "submit" if submit else "button",
            "disabled": bool(disabled),
            "attrs": _button_attrs(attrs),
        },
        "classes": classes,
        "props_id": f"button-{uuid4().hex}",
    })
