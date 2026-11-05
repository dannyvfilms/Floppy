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
    from app.media_card_model import progress_changer_model

    return render_to_string("users/components/progress_changer.html", {
        "props": progress_changer_model(media, csrf_token),
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


def _people_plain_text(value):
    """Turn provider-authored HTML into the plain text the shared hero renders."""
    import re
    from html import unescape

    from django.utils.html import strip_tags

    with_breaks = re.sub(r"<br\s*/?>", "\n", str(value or ""), flags=re.IGNORECASE)
    return unescape(strip_tags(with_breaks)).strip()


def _people_labels():
    """Keep hero copy localized on the server while the shared view stays prop-driven."""
    from django.utils.translation import gettext as _

    return {
        "showMore": str(_("Show more")),
        "showLess": str(_("Show less")),
        "viewReads": str(_("View Reads in History")),
        "viewPlays": str(_("View Plays in History")),
        "visitWebsite": str(_("Visit Website")),
        "source": str(_("Source")),
        "born": str(_("Born")),
        "died": str(_("Died")),
        "placeOfBirth": str(_("Place of Birth")),
        "founded": str(_("Founded")),
        "titles": str(_("Titles")),
        "developed": str(_("Developed")),
        "published": str(_("Published")),
        "overview": str(_("Overview")),
        "playTrailer": str(_("Play trailer")),
        "viewFullSize": str(_("View full size")),
        "fitImage": str(_("Fit image")),
        "fillFrame": str(_("Fill frame")),
        "previous": str(_("Previous")),
        "next": str(_("Next")),
        "close": str(_("Close")),
        "timeToBeat": str(_("Time to Beat")),
        "submissions": str(_("submissions")),
        "timeToBeatPending": str(_("Fetching cached time-to-beat data in the background.")),
        "timeToBeatEmpty": str(_("Time-to-beat data is not available yet.")),
        "watchedOnYouTube": str(_("Watched on YouTube")),
        "started": str(_("Started")),
        "youtubeEstimate": str(
            _("Estimated from how far you got in each video. Your playtime is not affected."),
        ),
        "readingActivity": str(_("Reading Activity")),
        "listeningTime": str(_("Listening Time")),
        "mostRead": str(_("Most Read")),
        "topAuthors": str(_("Top Authors")),
        "noReadingData": str(_("No reading data available.")),
        "noTitles": str(_("No titles available.")),
        "watchedContent": str(_("Watched Content")),
        "readContent": str(_("Read Content")),
        "filmography": str(_("Filmography")),
        "bibliography": str(_("Bibliography")),
        "noFilmography": str(_("No filmography available.")),
        "noBibliography": str(_("No bibliography available.")),
        "noWatched": str(_("No watched titles yet.")),
        "noRead": str(_("No read titles yet.")),
    }


def _people_island(context, root, props, body):
    """Render one shared People island with the server markup as its fallback."""
    return render_to_string("app/components/people_island.html", {
        "root": root,
        "props": props,
        "props_id": f"people-{root}-{uuid4().hex}",
        "body": body,
    }, request=context.get("request"))


def _people_cast_props(context, row, source, collapse_key):
    """Shape one cast or crew row for the shared person card rail."""
    from app.templatetags.app_tags import image_url
    from app.templatetags.app_tags import slug as slug_value

    items = []
    for person in row.get("items") or []:
        name = person.get("name") or "Unknown Person"
        person_id = person.get("person_id")
        role = person.get("role") or ""
        department = person.get("department") or ""
        href = ""
        if person_id and source:
            href = reverse(
                "person_detail",
                kwargs={
                    "source": source,
                    "person_id": person_id,
                    "name": slug_value(name),
                },
            )
        items.append({
            "id": f"{source}:{person_id}" if person_id else name,
            "name": name,
            "subtitle": role,
            "lines": [department] if department and department != role else [],
            "imageUrl": image_url(person.get("image") or ""),
            "personId": str(person_id) if person_id else "",
            "source": source or "",
            "slug": slug_value(name),
            "href": href,
        })
    view_all = None
    if row.get("view_all_url") and row.get("view_all_text"):
        view_all = {
            "label": str(row["view_all_text"]),
            "href": row["view_all_url"],
        }
    return {
        "kind": "cast",
        "title": str(row.get("title") or ""),
        "items": items,
        "viewAll": view_all,
        "collapseKey": collapse_key or "",
        "labels": _people_labels(),
    }


def _people_game_lengths_props(game_lengths, pending):
    """Shape the game length cards for the shared medium extras view."""
    from django.utils.translation import gettext as _

    if not game_lengths:
        return {
            "available": False,
            "pending": bool(pending),
            "cards": [],
        }
    cards = [
        {
            "label": str(_(card.get("label") or "")),
            "value": card.get("value") or "",
            "count": card.get("count"),
            "glyph": "◷",
        }
        for card in game_lengths.get("cards") or []
    ]
    return {
        "sourceLabel": str(_(game_lengths.get("source_label") or "")),
        "sourceUrl": game_lengths.get("source_url") or "",
        "available": bool(game_lengths.get("available")),
        "pending": bool(pending) and not game_lengths.get("available"),
        "cards": cards,
    }


def _people_youtube_props(youtube_watch):
    """Shape the YouTube watch summary for the shared medium extras view."""
    if not youtube_watch:
        return None
    return {
        "seconds": youtube_watch.get("seconds"),
        "hoursLabel": youtube_watch.get("hours_label") or "",
        "videos": youtube_watch.get("videos") or 0,
    }


def _people_section_visible(context, family, zone, section):
    """Match the server's section visibility so the shared hero keeps user layout choices."""
    from users.appearance import resolved_detail_layouts

    user = context.get("user")
    layouts = resolved_detail_layouts(
        getattr(user, "detail_page_layouts", {}) if getattr(user, "is_authenticated", False) else {},
    )
    return section in layouts.get(family, {}).get(zone, [])


def _person_hero_props(context):
    """Shape the person page's existing values into the shared hero contract."""
    from django.conf import settings
    from django.utils.translation import gettext as _
    from django.utils.translation import ngettext

    from app.templatetags.app_tags import image_url, source_readable
    from users.templatetags.user_tags import user_date_format

    person = context.get("person") or {}
    user = context.get("user")
    is_author = bool(context.get("is_author"))
    counts = []
    tracked_plays_count = context.get("tracked_plays_count")
    if tracked_plays_count is not None:
        if is_author:
            count = context.get("watched_book_count") or 0
            counts.append({
                "label": ngettext(
                    "%(value_1)s book", "%(value_1)s books", count,
                ) % {"value_1": count},
            })
        else:
            count = context.get("watched_movie_count") or 0
            counts.append({
                "label": ngettext(
                    "%(value_1)s movie", "%(value_1)s movies", count,
                ) % {"value_1": count},
            })
            count = context.get("watched_show_count") or 0
            counts.append({
                "label": ngettext(
                    "%(value_1)s show", "%(value_1)s shows", count,
                ) % {"value_1": count},
            })
        counts.append({
            "label": ngettext(
                "%(count)s tracked read" if is_author else "%(count)s tracked play",
                "%(count)s tracked reads" if is_author else "%(count)s tracked plays",
                tracked_plays_count,
            ) % {"count": tracked_plays_count},
        })
        tracked_hours_count = context.get("tracked_hours_count")
        if tracked_hours_count:
            counts.append({"label": str(tracked_hours_count)})

    return {
        "kind": "person",
        "headingLevel": 1,
        "person": {
            "name": str(person.get("name") or _("Unknown Person")),
            "imageUrl": image_url(person.get("image") or settings.IMG_NONE),
            "biography": _people_plain_text(person.get("biography")),
            "knownForDepartment": person.get("known_for_department") or "",
            "birthDate": user_date_format(person.get("birth_date"), user)
            if person.get("birth_date") else "",
            "deathDate": user_date_format(person.get("death_date"), user)
            if person.get("death_date") else "",
            "placeOfBirth": person.get("place_of_birth") or "",
            "sourceLabel": source_readable(context.get("source")),
            "sourceUrl": context.get("source_url") or "",
            "isAuthor": is_author,
        },
        "counts": counts,
        "historyUrl": context.get("history_filter_url") or "",
        "canViewHistory": True,
        "showBiography": _people_section_visible(context, "person", "hero", "biography"),
        "labels": _people_labels(),
    }


def _studio_hero_props(context):
    """Shape the studio page's existing values into the shared hero contract."""
    from django.conf import settings
    from django.utils.translation import gettext as _
    from django.utils.translation import ngettext

    from app.templatetags.app_tags import (
        image_url,
        media_type_readable,
        media_type_readable_plural,
        source_readable,
    )
    from users.templatetags.user_tags import user_date_format

    studio = context.get("studio")
    user = context.get("user")
    source = context.get("source")
    credited_media_type = context.get("credited_media_type")
    title_count = context.get("studio_games_count") or 0
    developed_count = context.get("studio_developed_count")
    published_count = context.get("studio_published_count")
    media_label = (
        media_type_readable_plural(credited_media_type)
        if credited_media_type else str(_("Titles"))
    )
    counts = []
    if credited_media_type:
        label = (
            media_type_readable(credited_media_type) if title_count == 1
            else media_type_readable_plural(credited_media_type)
        )
        counts.append({"label": f"{title_count} {label.lower()}"})
    else:
        counts.append({
            "label": ngettext(
                "%(value_1)s title", "%(value_1)s titles", title_count,
            ) % {"value_1": title_count},
        })
    if developed_count is not None:
        counts.append({"label": _("%(value_1)s developed") % {"value_1": developed_count}})
    if published_count is not None:
        counts.append({"label": _("%(value_1)s published") % {"value_1": published_count}})

    founded = context.get("studio_founded")
    return {
        "kind": "studio",
        "headingLevel": 1,
        "sourcePlacement": "facts",
        "studio": {
            "name": str(getattr(studio, "name", "") or _("Unknown Studio")),
            "logoUrl": image_url(
                (getattr(studio, "logo", "") if studio else "") or settings.IMG_NONE,
            ),
            "description": _people_plain_text(context.get("studio_description")),
            "founded": user_date_format(founded, user) if founded else "",
            "mediaLabel": media_label,
            "titleCount": title_count,
            "developedCount": developed_count,
            "publishedCount": published_count,
            "sourceLabel": source_readable(source),
            "websiteUrl": context.get("studio_source_url") or "",
        },
        "counts": counts,
        "showBiography": _people_section_visible(context, "studio", "hero", "overview"),
        "labels": _people_labels(),
    }


@register.tag
def people_hero(parser, token):
    """Wrap the server hero fallback in the shared person/studio mount."""
    _, *args = token.split_contents()
    kind = args[0].strip("\"'") if args and not args[1:] else ""
    if kind not in {"person", "studio"}:
        message = 'people_hero requires exactly "person" or "studio"'
        raise template.TemplateSyntaxError(message)
    body = parser.parse(("endpeople_hero",))
    parser.delete_first_token()
    return PeopleHeroNode(kind, body)


class PeopleHeroNode(template.Node):
    """Render shared hero props and keep the server markup as the fallback."""

    def __init__(self, kind, body):
        """Store the profile kind and its fallback body."""
        self.kind = kind
        self.body = body

    def render(self, context):
        """Render the hero island or leave the existing server markup intact."""
        props = (
            _person_hero_props(context) if self.kind == "person"
            else _studio_hero_props(context)
        )
        return render_to_string("app/components/people_hero.html", {
            "props": props,
            "props_id": f"people-hero-{uuid4().hex}",
            "body": self.body.render(context),
        })


@register.tag
def people_cast(parser, token):
    """Wrap a cast or crew row in the shared person card rail."""
    bits = token.split_contents()
    options = token_kwargs(bits[1:], parser)
    allowed = {"row", "source", "collapse_key"}
    if "row" not in options or set(options) - allowed or any("=" not in bit for bit in bits[1:]):
        message = "people_cast requires row= and optional source=/collapse_key= only"
        raise template.TemplateSyntaxError(message)
    body = parser.parse(("endpeople_cast",))
    parser.delete_first_token()
    return PeopleCastNode(options, body)


class PeopleCastNode(template.Node):
    """Render cast card props beside the existing server row."""

    def __init__(self, options, body):
        """Keep the compiled row/source values and fallback body."""
        self.options = options
        self.body = body

    def render(self, context):
        """Render the shared rail when the row has people, else the fallback."""
        row = self.options["row"].resolve(context)
        if not row or not row.get("items"):
            return self.body.render(context)
        source = (
            self.options["source"].resolve(context)
            if "source" in self.options else context.get("source")
        )
        collapse_key = (
            str(self.options["collapse_key"].resolve(context))
            if "collapse_key" in self.options else ""
        )
        return _people_island(
            context,
            "cast",
            _people_cast_props(context, row, source, collapse_key),
            self.body.render(context),
        )


@register.tag
def people_extras(parser, token):
    """Wrap one medium-extras section in the shared extras mount."""
    bits = token.split_contents()
    part = bits[1].strip("\"'") if len(bits) > 1 else ""
    if part not in {"game_lengths", "youtube"}:
        message = 'people_extras requires "game_lengths" or "youtube"'
        raise template.TemplateSyntaxError(message)
    body = parser.parse(("endpeople_extras",))
    parser.delete_first_token()
    return PeopleExtrasNode(part, body)


class PeopleExtrasNode(template.Node):
    """Render medium-extra props beside the existing server section."""

    def __init__(self, part, body):
        """Store which extras section this block wraps."""
        self.part = part
        self.body = body

    def render(self, context):
        """Render the shared extras view when this section has data."""
        if self.part == "game_lengths":
            if not _people_section_visible(context, "game", "content", "game_lengths"):
                return self.body.render(context)
            game_lengths = context.get("game_lengths")
            props = {
                "kind": "extras",
                "gameLengths": _people_game_lengths_props(
                    game_lengths,
                    context.get("game_lengths_pending"),
                ),
                "labels": _people_labels(),
            }
            if not game_lengths:
                return self.body.render(context)
            return _people_island(context, "extras", props, self.body.render(context))
        youtube_watch = _people_youtube_props(context.get("youtube_watch"))
        if not youtube_watch:
            return self.body.render(context)
        return _people_island(
            context,
            "extras",
            {
                "kind": "extras",
                "youtubeWatch": youtube_watch,
                "labels": _people_labels(),
            },
            self.body.render(context),
        )
