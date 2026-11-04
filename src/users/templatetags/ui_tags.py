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


def _extra_value(extra, name):
    """Read a suggestion extra that may be a mapping or a namespace."""
    if isinstance(extra, dict):
        return extra.get(name, "")
    return getattr(extra, name, "")


@register.simple_tag(takes_context=True)
def date_time_picker(context):
    """Render the shared date/time field with the existing hidden form value.

    Dynamic suggestion expressions stay on the legacy Alpine include; static
    consumer configurations are handed to the React presentation explicitly.
    """
    from django.utils.translation import get_language, pgettext
    from django.utils.translation import gettext as _

    field_label = str(context.get("field_label") or _("Date"))
    mobile_label = str(context.get("mobile_label") or "")
    copy_from = str(context.get("copy_from") or "")
    copy_label = (
        str(context.get("copy_from_label") or copy_from)
        if copy_from
        else ""
    )
    track_time = bool(context.get("track_time"))
    use_12_hour = bool(context.get("use_12_hour"))

    raw_suggestion_label = str(context.get("suggestion_label") or "")
    if raw_suggestion_label == "Release Date":
        suggestion_label = str(pgettext("date picker shortcut", "Release Date"))
    elif raw_suggestion_label:
        suggestion_label = str(_(raw_suggestion_label))
    else:
        suggestion_label = ""

    mode = context.get("quick_action_mode")
    quick_actions = []
    if mode != "end":
        quick_actions.append({"id": "start-now", "label": str(pgettext("date picker shortcut", "Start Now"))})
    if mode != "start":
        quick_actions.append({"id": "just-finished", "label": str(pgettext("date picker shortcut", "Just Finished"))})
    if mode != "end" or context.get("end_release_shortcut"):
        quick_actions.append({
            "id": "release-date",
            "label": str(pgettext("date picker shortcut", "Release Date")),
            "requiresSuggestion": True,
        })

    extras = []
    for extra in context.get("suggestion_extras") or []:
        date = str(_extra_value(extra, "date") or "")
        label = str(_extra_value(extra, "label") or "")
        if date and label:
            extras.append({"date": date, "label": str(_(label))})

    copy_empty_message = ""
    if copy_from:
        copy_empty_message = str(_("%(label)s is empty") % {"label": copy_label})

    field_name = str(context.get("field_name") or "")
    field_value = str(context.get("field_value") or "")
    props = {
        "fieldName": field_name,
        "fieldId": str(context.get("field_id") or ""),
        "initialValue": field_value,
        "trackTime": track_time,
        "use12Hour": use_12_hour,
        "weekStart": str(context.get("week_start") or "monday"),
        "locale": str(get_language() or ""),
        "defaultNow": bool(context.get("default_now")),
        "suggestionDate": str(context.get("suggestion_date") or ""),
        "suggestionLabel": suggestion_label,
        "suggestionRuntimeMinutes": str(context.get("suggestion_runtime_minutes") or ""),
        "runtimeMinutes": str(context.get("runtime_minutes") or ""),
        "copyFrom": copy_from,
        "copyLabel": copy_label,
        "copyEmptyMessage": copy_empty_message,
        "quickActions": quick_actions,
        "suggestionExtras": extras,
        "labels": {
            "field": field_label,
            "mobileLabel": mobile_label,
            "notSet": str(_("Not set")),
            "openPicker": str(_("Open %(label)s picker") % {"label": field_label}),
            "picker": str(_("%(label)s picker") % {"label": field_label}),
            "quickActions": str(_("%(label)s quick actions") % {"label": field_label}),
            "clear": str(_("Clear date")),
            "close": str(_("Close date picker")),
            "previousMonth": str(_("Previous month")),
            "nextMonth": str(_("Next month")),
            "selectMonth": str(_("Select month")),
            "previousYear": str(_("Previous year")),
            "nextYear": str(_("Next year")),
            "selectYear": str(_("Select year")),
            "previousYears": str(_("Previous years")),
            "nextYears": str(_("Next years")),
            "year": str(_("Year")),
            "back": str(_("Back")),
            "time": str(_("Time")),
            "now": str(_("Now")),
            "none": str(_("None")),
            "copy": str(_("Copy from %(label)s") % {"label": copy_label}) if copy_from else "",
            "suggestedDate": str(_("Suggested date")),
            "hour": str(_("Hour")),
            "minute": str(_("Minute")),
            "second": str(_("Second")),
            "earlierHour": str(_("Earlier hour")),
            "laterHour": str(_("Later hour")),
            "earlierMinute": str(_("Earlier minute")),
            "laterMinute": str(_("Later minute")),
            "earlierSecond": str(_("Earlier second")),
            "laterSecond": str(_("Later second")),
            "activity": str(_("View activity for")),
        },
    }
    props_id = f"date-time-picker-{uuid4().hex}"
    return render_to_string("app/components/date_time_picker_react.html", {
        "props": props,
        "props_id": props_id,
        "field_name": field_name,
        "field_id": props["fieldId"],
        "field_value": field_value,
        "track_time": track_time,
    })


@register.simple_tag(takes_context=True)
def detail_composition(context, part="synopsis"):
    """Render the shared detail header or synopsis with a server fallback."""
    from html import unescape

    from django.utils.html import strip_tags
    from django.utils.translation import gettext as _
    from django.utils.translation import ngettext

    from app.models import MediaTypes
    from app.templatetags.app_tags import (
        alternative_title,
        display_title,
        image_url,
        release_year,
    )

    media = context.get("media") or {}
    media_type = context.get("media_type") or media.get("media_type")
    user = context.get("user")
    public_view = bool(context.get("public_view"))
    details = media.get("details") if isinstance(media.get("details"), dict) else {}
    title = display_title(media, user)
    alt_title = alternative_title(media, user)
    facts = []
    year = release_year(details)
    if year:
        facts.append({"label": str(_("Year")), "value": str(year)})
    runtime = details.get("runtime")
    if runtime:
        facts.append({"label": str(_("Runtime")), "value": str(runtime)})
    episodes = details.get("episodes")
    if isinstance(episodes, (list, tuple)):
        episodes = len(episodes)
    if isinstance(episodes, int) and not isinstance(episodes, bool) and episodes > 0:
        facts.append({
            "label": str(ngettext("Episode", "Episodes", episodes)),
            "value": str(episodes),
        })
    status = details.get("status")
    if status:
        facts.append({"label": str(_("Status")), "value": str(status)})
    subtitle = ""
    if media_type == MediaTypes.SEASON.value:
        subtitle = str(media.get("season_header_title") or "")
    elif media.get("series_name"):
        subtitle = str(media["series_name"])
    props = {
        "part": part,
        "title": title,
        "altTitle": alt_title or "",
        "subtitle": subtitle,
        "artwork": {
            "src": image_url(media.get("image")) or "",
            "alt": title,
            "aspect": "poster",
        },
        "facts": facts,
        "synopsis": {
            "text": unescape(strip_tags(str(media.get("synopsis") or ""))).strip(),
            "previewLines": 3,
        },
        "publicView": public_view,
        "readOnly": public_view,
        "labels": {
            "altTitle": str(_("Show alternative title")),
            "publicView": str(_("Public view")),
            "readMore": str(_("Read more")),
            "showLess": str(_("Show less")),
            "noSynopsis": str(_("No synopsis available.")),
        },
        "actions": None,
        "sections": [],
    }
    return render_to_string("app/components/detail_composition.html", {
        "props": props,
        "props_id": f"detail-composition-{uuid4().hex}",
    })
