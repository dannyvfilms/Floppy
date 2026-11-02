"""Server adapter and usable fallbacks for the shared React alphabet filter."""

import string
from uuid import uuid4

from django import template
from django.utils.translation import gettext as _

from app.library_query.alphabet import normalize_initial

register = template.Library()
register.filter("alphabet_initial", normalize_initial)


@register.inclusion_tag("app/components/alphabet_filter.html", takes_context=True)
def alphabet_filter(context, form_id="filter-form", mode="rail"):
    """Keep URL/form transport outside the reusable presentation component."""
    request = context["request"]
    initial = normalize_initial(request.GET.get("initial"))
    params = request.GET.copy()
    for name in ("initial", "page", "ug_page"):
        params.pop(name, None)
    other_initial = context.get("alphabet_other_initial")
    if not other_initial and initial == "other":
        other_initial = "\u2026"
    choices = [
        ("", _("All")),
        ("0-9", "#"),
        *((letter, letter.upper()) for letter in string.ascii_lowercase),
    ]
    if other_initial:
        choices.append(("other", other_initial))
    options = []
    for value, label in choices:
        query = params.copy()
        if value:
            query["initial"] = value
        href = request.path + (f"?{query.urlencode()}" if query else "")
        options.append(
            {
                "value": value,
                "label": label,
                "href": href,
                "selected": value == initial,
                "caption": len(label) > 1,
                "accessibilityLabel": (
                    _("All titles")
                    if not value
                    else _("Titles starting with a number")
                    if value == "0-9"
                    else _("Other starting characters")
                    if value == "other"
                    else _("Titles starting with %(letter)s") % {"letter": label}
                ),
            }
        )
    props = {
        "options": options,
        "label": _("Filter by starting character"),
        "emptyTitle": _("No titles match this alphabet filter"),
        "clearLabel": _("Clear alphabet filter"),
        "formId": form_id,
        "mode": mode,
        "resultsSelector": "#items-view"
        if context.get("custom_list")
        else ".media-grid, .media-table, #empty_list",
    }
    return {
        "alphabet": props,
        "initial": initial,
        "props_id": f"alphabet-{uuid4().hex}",
        "show": mode == "rail" or bool(initial),
    }
