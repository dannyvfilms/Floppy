"""Server-owned content slots for the incremental React settings-card pilot."""

from uuid import uuid4

from django import template
from django.template.base import token_kwargs
from django.template.loader import render_to_string
from django.urls import reverse

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


def _number_or_value(value):
    """Render integral display scores without a trailing `.0`."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    return int(number) if number.is_integer() else number


def _derived_value(derived, name):
    if derived is None:
        return None
    if isinstance(derived, dict):
        return derived.get(name)
    return getattr(derived, name, None)


@register.simple_tag(takes_context=True)
def rating_chip(context, instance, media_type, post_url, derived_tv_score=None):
    """Render the shared personal score chip and popup with a server fallback."""
    from django.template.defaultfilters import floatformat
    from django.utils.translation import gettext as _

    from app.templatetags.app_tags import rating_scale_max, score_display
    from users.models import FIVE_POINT_RATING_SCALE

    user = context.get("user")
    scale_max = rating_scale_max(user)
    score = getattr(instance, "score", None)
    display = _number_or_value(score_display(score, user)) if score is not None else None
    if display is None:
        display_value = None
        card_display_value = None
    elif scale_max == FIVE_POINT_RATING_SCALE:
        display_value = f"{display}/5"
        card_display_value = f"{display}/5"
    else:
        display_value = str(display)
        card_display_value = floatformat(display, 1)

    derived = None
    derived_score = _derived_value(derived_tv_score, "score")
    if derived_score is not None:
        coverage = render_to_string(
            "app/components/derived_tv_rating_coverage.html",
            {"derived_tv_score": derived_tv_score},
        ).strip()
        derived = {
            "score": floatformat(derived_score, "-1"),
            "coverage": coverage,
            "label": str(_derived_value(derived_tv_score, "label") or ""),
            "title": str(_derived_value(derived_tv_score, "title") or ""),
        }

    noun = {
        "tv": _("show"),
        "season": _("show"),
        "movie": _("movie"),
    }.get(media_type, _("item"))
    labels = {
        "rate": str(_("Rate")),
        "derived": str(_("Derived")),
        "yourRating": str(_("Your rating")),
        "close": str(_("Close")),
        "prompt": f"{_('Rate this')} {noun}",
    }
    if score is not None:
        labels["yourScore"] = str(_("Your score"))
    if derived is not None:
        labels["derivedRating"] = str(_("Derived rating"))
    elif score is None:
        labels["addRating"] = str(_("Add rating"))
    else:
        labels["editRating"] = str(_("Edit rating"))

    csrf_token = context.get("csrf_token")
    if not csrf_token and context.get("request"):
        csrf_token = context["request"].META.get("CSRF_COOKIE", "")

    return render_to_string("app/components/rating_chip.html", {
        "props": {
            "postUrl": str(post_url),
            "csrfToken": str(csrf_token or ""),
            "scaleMax": scale_max,
            "value": float(display) if display is not None else None,
            "displayValue": display_value,
            "cardDisplayValue": card_display_value,
            "derived": derived,
            "labels": labels,
        },
        "props_id": f"rating-chip-{uuid4().hex}",
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
def progress_changer(media, csrf_token=""):
    """Render the shared quick progress controls with a working server fallback."""
    from django.utils.translation import gettext as _
    from django.utils.translation import ngettext

    from app.models import MediaTypes
    from app.templatetags.app_tags import progress_unit_label, watch_operation_id

    media_type = media.item.media_type
    percentage = bool(getattr(media, "progress_is_percentage", False))
    show_units = media_type not in {MediaTypes.GAME.value, MediaTypes.MOVIE.value} and not percentage
    max_progress = getattr(media, "max_progress", None)
    unit = ""
    if show_units and getattr(media, "progress_unit", None) != "minutes":
        count = max_progress or (getattr(media, "progress", 0) or 0)
        if media_type == MediaTypes.TV.value:
            unit = ngettext("Episode", "Episodes", count)
        else:
            unit = progress_unit_label(media_type, count)
    value = getattr(media, "formatted_progress", None) or str(getattr(media, "progress", ""))
    progress = getattr(media, "progress", 0) or 0
    formatted_max = getattr(media, "formatted_max_progress", None) or str(max_progress)
    props = {
        "value": str(value),
        "max": str(formatted_max) if max_progress else None,
        "unit": str(unit),
        "showMax": bool(max_progress) and show_units,
        "canDecrease": progress != 0,
        "canIncrease": max_progress is None or progress != max_progress,
        "decreaseLabel": str(_("Decrease progress")),
        "increaseLabel": str(_("Increase progress")),
        "url": reverse("progress_edit", args=[media_type, media.id]),
        "target": f"progress-{media_type}-{media.id}",
        "csrfToken": str(csrf_token or ""),
        "watchOperationId": (
            watch_operation_id()
            if media_type in {MediaTypes.TV.value, MediaTypes.SEASON.value}
            else ""
        ),
    }
    return render_to_string("users/components/progress_changer.html", {
        "props": props,
        "props_id": f"progress-changer-{uuid4().hex}",
    })


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
