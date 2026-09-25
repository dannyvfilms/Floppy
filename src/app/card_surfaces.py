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
    hover_action_mode: str = "standard"
    is_recommend_mode: bool = False
    secondary_color: bool = False


SURFACES = {
    "library": CardSurface(),
    "collection": CardSurface(),
    "related": CardSurface(),
    "seasons": CardSurface(),
    "list_recommendations": CardSurface(),
    # Upcoming shelves lead with the next release instead of the status.
    "home": CardSurface(show_next_event_chip=True, show_next_event_subtitle=True),
    # A list can hold single episodes; S01E02 says which one.
    "list": CardSurface(show_episode_identity=True),
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
    return {
        **page_context,
        **dict.fromkeys(CARD_VALUES),
        **asdict(SURFACES[surface]),
        "from_grid": True,
        # Two cards for one item (two copies in a Collection, a detail page's
        # own item in its related grid) must not share their modal targets.
        "card_uid": uuid4().hex[:8],
        **values,
    }
