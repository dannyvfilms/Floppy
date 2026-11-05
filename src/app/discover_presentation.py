"""Plain presentation data for the shared Discover surfaces."""

from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from app import card_surfaces

CONTINUE_ROW_KEYS = {
    "continue_all",
    "continue_up_next",
    "next_episode",
    "continue",
    "clear_out_next",
}

MATCH_LABELS = {
    "top_picks_for_you": "Taste match",
    "clear_out_next": "Next up match",
    "comfort_rewatches": "Rewatch confidence",
}


def card_labels():
    """Labels the shared media card uses on Discover."""
    return {
        "altTitle": str(_("Show alternative title")),
        "nextEpisode": str(_("Jump to next episode")),
        "noStatus": str(_("No Status")),
        "rate": str(_("Rate")),
        "close": str(_("Close")),
        "open": str(_("Open")),
    }


def surface_labels():
    """Labels the Discover composition uses on the web and native shell."""
    return {
        "mediaType": str(_("Media type")),
        "showMore": str(_("Show More Rows")),
        "showFewer": str(_("Show Fewer Rows")),
        "refresh": str(_("Refresh recommendations")),
        "refreshing": str(_("Refreshing…")),
        "refreshBackground": str(_("Refreshing recommendations in background...")),
        "refreshDone": str(_("Recommendations refreshed.")),
        "undo": str(_("Undo")),
        "dismiss": str(_("Dismiss")),
        "hiddenTitle": str(_("Hidden From Discover")),
        "hiddenBody": str(
            _("Most recently changed first, so forgotten hides are easy to find again."),
        ),
        "hiddenEmptyTitle": str(_("Nothing hidden right now")),
        "hiddenEmptyBody": str(_("Items you hide from Discover will show up here.")),
        "emptyTitle": str(_("No Discover rows available")),
        "emptyBody": str(_("Try another media type or start tracking more items.")),
        "loadingTitle": str(_("Building Discover rows")),
        "loadingBody": str(
            _("Recommendations are refreshing in the background and will appear automatically."),
        ),
        "rowEmptyContinue": str(
            _("Nothing to continue yet. Track something as in progress and it will appear here."),
        ),
        "rowEmptyDefault": str(_("No items matched this row right now.")),
        "previewEmpty": str(_("No items matched this row right now.")),
        **card_labels(),
    }


def _match_percent(value):
    if value is None:
        return None
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return None
    normalized = max(0.0, min(1.0, normalized))
    return round(normalized * 100)


def _card(context, surface, **values):
    rendered = card_surfaces.card_context(dict(context), surface, values)
    return rendered["react_props"]["model"]


def _candidate_card(context, candidate, row, *, selected_media_type, show_more, discover_debug):
    values = {
        "item": candidate,
        "title": candidate.title,
        "current_sort": None,
        "card_media_type": candidate.media_type,
        "subtitle_override": candidate.release_date,
        "discover_active_media_type": selected_media_type,
        "discover_show_more": show_more,
        "discover_row_key": row.key,
        "discover_debug": discover_debug,
    }
    match_label = MATCH_LABELS.get(row.key)
    if match_label:
        score = candidate.display_score
        if score is None:
            score = candidate.final_score
        values.update(
            {
                "subtitle_match_percent": _match_percent(score),
                "subtitle_match_label": _(match_label),
            },
        )
        if row.key == "top_picks_for_you":
            values["provenance_text"] = candidate.source_reason
    return _card(context, "discover", **values)


def _hidden_card(context, entry):
    item = entry.item
    return _card(
        context,
        "discover_hidden",
        item=item,
        title=item.title,
        current_sort=None,
        card_media_type=getattr(item, "library_media_type", None) or item.media_type,
        subtitle_override=entry.updated_at,
    )


def row_props(
    context,
    row,
    *,
    selected_media_type,
    show_more=False,
    discover_debug=False,
):
    """Turn one Discover row into the shared row/card props."""
    items = [
        _candidate_card(
            context,
            candidate,
            row,
            selected_media_type=selected_media_type,
            show_more=show_more,
            discover_debug=discover_debug,
        )
        for candidate in (row.items or [])
    ]
    continue_row = row.key in CONTINUE_ROW_KEYS
    return {
        "key": row.key,
        "title": str(_(row.title)),
        "why": str(_(row.why)),
        "matchSignal": row.match_signal or "",
        "isStale": bool(row.is_stale),
        "items": items,
        "continueRow": continue_row,
        "emptyLabel": str(
            _("Nothing to continue yet. Track something as in progress and it will appear here.")
            if continue_row
            else _("No items matched this row right now."),
        ),
    }


def hidden_props(context):
    """Turn the hidden Discover entries into the shared hidden-grid props."""
    entries = list(context.get("hidden_discover_entries") or [])
    count = context.get("hidden_discover_count")
    if count is None:
        count = len(entries)
    count_label = ngettext(
        "%(count)s item",
        "%(count)s items",
        count,
    ) % {"count": count}
    return {
        "entries": [_hidden_card(context, entry) for entry in entries],
        "count": count,
        "countLabel": count_label,
    }
