"""Which media card each page shows, and why it differs from the default.

Every poster grid renders ``app/components/media_card.html`` through
``{% media_card "<surface>" item=... media=... %}``. A surface's differences
from the default card are declared here, each with its reason, so a difference
that is not listed is drift. See docs/architecture/media-card.md.
"""

from dataclasses import asdict, dataclass
from uuid import uuid4


@dataclass(frozen=True)
class CardSurface:
    """The card flags one surface sets. Names match the template variables."""

    show_status_chip: bool = True
    show_release_year_placeholder: bool = True
    show_next_event_chip: bool = False
    show_next_event_subtitle: bool = False
    show_episode_identity: bool = False
    show_episode_queue: bool = False
    hover_action_mode: str = "standard"
    is_recommend_mode: bool = False
    rating_read_only: bool = False
    secondary_color: bool = False


SURFACES = {
    "library": CardSurface(),
    "collection": CardSurface(),
    "related": CardSurface(),
    "seasons": CardSurface(),
    "list_recommendations": CardSurface(),
    # Upcoming shelves lead with the next release instead of the status.
    "home": CardSurface(show_next_event_chip=True, show_next_event_subtitle=True),
    # Home card with the Behind or countdown chip in the next-episode slot.
    "up_next": CardSurface(
        show_next_event_chip=True,
        show_next_event_subtitle=True,
        show_episode_queue=True,
    ),
    # A list can hold single episodes; S01E02 says which one.
    "list": CardSurface(show_episode_identity=True),
    # A tile on a tier board: the board owns clicks and drags, so no hover
    # actions, and no status chip or release year to load for a small poster.
    "tier": CardSurface(
        show_status_chip=False,
        show_release_year_placeholder=False,
        hover_action_mode="none",
    ),
    # A person's or studio's titles: the shared card plus what that person did
    # on each one (role line, watched runtime).
    "credit": CardSurface(),
    # A game franchise/series tile: the poster and subtitle come from the group,
    # not one tracked game, so there is no status chip or hover action.
    "group": CardSurface(
        show_status_chip=False,
        show_release_year_placeholder=False,
        hover_action_mode="none",
        rating_read_only=True,
    ),
    # Provider results are not saved items, so there is no release year to load.
    "search": CardSurface(show_release_year_placeholder=False),
    # Picking an item inside a modal: a click previews it, no hover actions.
    "search_modal": CardSurface(
        show_release_year_placeholder=False,
        is_recommend_mode=True,
        secondary_color=True,
    ),
    # Candidates are untracked by definition; hover offers plan/hide/list.
    "discover": CardSurface(
        show_status_chip=False,
        show_release_year_placeholder=False,
        hover_action_mode="discover",
    ),
    # The subtitle is the date it was hidden, not the release year.
    "discover_hidden": CardSurface(
        show_status_chip=False,
        show_release_year_placeholder=False,
    ),
}

# Values that belong to one card. Unset ones are cleared so a value from the
# surrounding page (another card, the detail page's own item) never leaks in.
CARD_VALUES = frozenset(
    {
        "item",
        "media",
        "video_landscape",
        "credit",
        "title",
        "card_media_type",
        "current_sort",
        "image_override",
        "image_source",
        "subtitle_override",
        "subtitle_match_percent",
        "subtitle_match_label",
        "provenance_text",
        "matched_title",
        "season_card_title_override",
        "collection_completeness",
        "use_podcast_show",
        "podcast_show",
        "show_played_chip",
        "show_media_type_chip",
        "media_type_chip_type",
        "active",
    },
)

# Values that belong to the page. Unset ones are inherited from it, which is how
# a public detail page hides the hover actions on its related cards.
PAGE_VALUES = frozenset(
    {
        "public_view",
        "public_list_reference",
        "list_ordering_enabled",
        "enable_bulk_select",
        "home_row_id",
        "return_url",
        "recommend_list_id",
        "search_preview_url",
        "search_modal_target",
        "discover_active_media_type",
        "discover_show_more",
        "discover_row_key",
        "discover_debug",
    },
)


def card_context(page_context, surface, values):
    """Return the template context for one card on ``surface``."""
    if surface not in SURFACES:
        msg = f"Unknown media card surface {surface!r}; add it to SURFACES."
        raise ValueError(msg)
    unknown = set(values) - CARD_VALUES - PAGE_VALUES
    if unknown:
        msg = (
            f"Unknown media card value(s) {sorted(unknown)}; declare them in "
            "app.card_surfaces instead of passing ad-hoc flags."
        )
        raise TypeError(msg)
    rendered_context = {
        **page_context,
        **dict.fromkeys(CARD_VALUES),
        **asdict(SURFACES[surface]),
        "from_grid": True,
        # Two cards for one item (two copies in a Collection, a detail page's
        # own item in its related grid) must not share their modal targets.
        "card_uid": uuid4().hex[:8],
        **values,
    }
    if surface == "library" and rendered_context.get("card_media_type") == "video":
        rendered_context["video_landscape"] = True
    rendered_context.update(_card_render_context(rendered_context))
    return rendered_context


def _card_render_context(rendered_context):
    """Attach the subtitle profile for this card."""
    from users.card_metadata import (
        DISPLAY_HOVER,
        card_lines,
        progress_bar_display,
        resolve_profile,
        show_progress_field,
        subtitle_display,
        title_options,
        uses_line_renderer,
    )

    user = rendered_context.get("user")
    item = rendered_context.get("item")
    media = rendered_context.get("media")
    media_type = rendered_context.get("card_media_type") or rendered_context.get(
        "resolved_media_type"
    )
    if not media_type and item is not None:
        media_type = getattr(item, "media_type", None)
    use_lines = uses_line_renderer(user, media_type)
    # Per-line dormant classes own visibility once the line renderer is on.
    # A card-level always class would reveal the hover lines too.
    display = DISPLAY_HOVER if use_lines else subtitle_display(user, media_type)
    profile = resolve_profile(user, media_type)
    return {
        "card_display": display,
        "card_show_progress": show_progress_field(user, media_type),
        "card_progress_display": progress_bar_display(profile) or "",
        "card_use_lines": use_lines,
        "card_line_list": card_lines(user, media_type, item, media),
        "card_title": title_options(profile),
    }
