"""
List browsing and discovery views: user profile, list browser, and cover image.

These are the read-only discovery entry points — no mutations happen here.
Write operations live in views_list_actions.py; detail views live in
views_list_detail.py and views_smart_list.py.
"""

import hashlib
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_not_required
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Count, Exists, F, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from app import helpers
from integrations.imports import trakt as trakt_imports
from integrations.models import MDBListAccount, TraktAccount
from lists.forms import CustomListForm
from lists.models import CustomList, CustomListItem
from lists.views_helpers import (
    _build_list_url_template,
    _get_list_completed_counts,
    _get_list_last_watched_dates,
    _order_expression,
    _resolve_list_sort_direction,
)
from users.models import ListSortChoices

logger = logging.getLogger(__name__)

User = get_user_model()


def _attach_cached_covers(custom_lists):
    """Reuse resolved covers without doing provider lookups during page render."""
    first_item = CustomListItem.objects.filter(custom_list_id=OuterRef("pk")).order_by(
        "date_added", "pk"
    )
    first_memberships = (
        CustomList.objects.filter(pk__in=[cl.pk for cl in custom_lists])
        .order_by()
        .annotate(first_membership_id=Subquery(first_item.values("pk")[:1]))
        .values("first_membership_id")
    )
    rows = (
        CustomListItem.objects.filter(pk__in=Subquery(first_memberships))
        .order_by()
        .values_list("custom_list_id", "item_id", "item__image")
    )
    keys = {
        pk: "list-cover:v1:" + hashlib.sha256(f"{item_id}:{image}".encode()).hexdigest()
        for pk, item_id, image in rows
    }
    cached = cache.get_many(list(keys.values()))
    for custom_list in custom_lists:
        custom_list.cover_cache_key = keys.get(custom_list.pk)
        custom_list.cached_cover_url = (
            cached.get(custom_list.cover_cache_key)
            if custom_list.cover_cache_key
            else settings.IMG_NONE
        )


@login_not_required
@never_cache
@require_GET
def user_profile(request, username):
    """Return the public profile page showing all public lists for a user."""
    profile_user = get_object_or_404(User, username=username)

    # Get all public lists owned by this user
    # Use a fresh query each time to avoid any caching issues
    public_lists = list(
        CustomList.objects.filter(
            owner=profile_user,
            visibility="public",
        )
        .select_related("owner")
        .annotate(
            items_count=Count("items", distinct=True),
        )
        .prefetch_related("collaborators", "items")
        .order_by("-id")
    )
    _attach_cached_covers(public_lists)

    tag_map = {}
    for custom_list in public_lists:
        tags = [
            tag.strip()
            for tag in (custom_list.tags or [])
            if isinstance(tag, str) and tag.strip()
        ]
        if not tags:
            tag_map.setdefault("Untagged", []).append(custom_list)
            continue
        for tag in tags:
            tag_map.setdefault(tag, []).append(custom_list)

    def _tag_sort_key(tag_name):
        return (tag_name == "Untagged", tag_name.lower())

    tag_sections = [
        {"tag": tag_name, "lists": tag_map[tag_name]}
        for tag_name in sorted(tag_map, key=_tag_sort_key)
    ]

    # Determine if this is the current user's own profile
    is_own_profile = request.user.is_authenticated and request.user == profile_user

    # Determine base template: use public template for anonymous users, regular for authenticated
    public_view = not request.user.is_authenticated
    base_template = "base_public.html" if public_view else "base.html"

    return render(
        request,
        "lists/user_profile.html",
        {
            "profile_user": profile_user,
            "custom_lists": public_lists,
            "tag_sections": tag_sections,
            "is_own_profile": is_own_profile,
            "public_view": public_view,
            "base_template": base_template,
            "profile_username": username,
        },
    )


@never_cache
@require_GET
def lists(request):
    """Return the custom list page."""
    # Get parameters from request
    search_query = request.GET.get("q", "")
    page = request.GET.get("page", 1)
    previous_sort = getattr(request.user, "lists_sort", ListSortChoices.LAST_ITEM_ADDED)
    sort_by = request.user.update_preference("lists_sort", request.GET.get("sort"))
    if sort_by not in ListSortChoices.values:
        sort_by = ListSortChoices.LAST_ITEM_ADDED
    direction_param = request.GET.get("direction")
    direction_pref = getattr(request.user, "lists_direction", None)
    if direction_param is not None:
        direction = _resolve_list_sort_direction(sort_by, direction_param)
    elif sort_by != previous_sort or direction_pref is None:
        direction = _resolve_list_sort_direction(sort_by, None)
    else:
        direction = _resolve_list_sort_direction(sort_by, direction_pref)
    request.user.update_preference("lists_direction", direction)
    enabled_media_types = request.user.get_enabled_media_types()
    selected_media_type = request.GET.get("media_type", "all")

    if selected_media_type != "all" and selected_media_type not in enabled_media_types:
        selected_media_type = "all"

    # Count memberships separately: grouping the outer query also groups every
    # selected owner preference for every membership in large lists.
    item_counts = (
        CustomListItem.objects.filter(custom_list_id=OuterRef("pk"))
        .order_by()
        .values("custom_list_id")
        .annotate(total=Count("pk"))
        .values("total")
    )
    custom_lists = (
        CustomList.objects.filter(Q(owner=request.user) | Q(collaborators=request.user))
        .select_related("owner")
        .annotate(
            items_count=Coalesce(Subquery(item_counts), 0),
        )
        .distinct()
    )

    if search_query:
        custom_lists = custom_lists.filter(
            Q(name__icontains=search_query) | Q(description__icontains=search_query),
        )

    if selected_media_type != "all":
        custom_lists = (
            custom_lists.annotate(
                has_media_type=Exists(
                    CustomListItem.objects.filter(
                        custom_list_id=OuterRef("pk"),
                        item__media_type=selected_media_type,
                    ),
                ),
            )
            .filter(has_media_type=True)
            .distinct()
        )

    custom_lists = custom_lists.prefetch_related("collaborators")

    if sort_by == ListSortChoices.NAME:
        custom_lists = custom_lists.order_by(_order_expression("name", direction))
    elif sort_by == ListSortChoices.ITEMS_COUNT:
        custom_lists = custom_lists.order_by(
            _order_expression("items_count", direction),
            F("name").asc(),
        )
    elif sort_by == ListSortChoices.NEWEST_FIRST:
        custom_lists = custom_lists.order_by(_order_expression("id", direction))
    elif sort_by == ListSortChoices.LAST_WATCHED:
        # This sort needs every candidate's scalar key, but full list/card
        # models are still loaded only after pagination below.
        sorted_rows = list(custom_lists.values_list("id", "name"))
        list_last_watched = _get_list_last_watched_dates(
            request.user,
            [row[0] for row in sorted_rows],
        )
        sorted_rows.sort(
            key=lambda row: (
                list_last_watched.get(row[0]) is None,
                (
                    list_last_watched[row[0]].timestamp()
                    * (1 if direction == "asc" else -1)
                )
                if row[0] in list_last_watched
                else 0,
                row[1].casefold(),
                row[0],
            ),
        )
    else:  # last_item_added is the default
        # Get the latest update date for each list
        custom_lists = custom_lists.annotate(
            latest_update=Subquery(
                CustomListItem.objects.filter(
                    custom_list=OuterRef("pk"),
                )
                .order_by("-date_added")
                .values("date_added")[:1],
            ),
        ).order_by(_order_expression("latest_update", direction), F("name").asc())

    items_per_page = 20
    if sort_by == ListSortChoices.LAST_WATCHED:
        paginator = Paginator([row[0] for row in sorted_rows], items_per_page)
        lists_page = paginator.get_page(page)
        cards = {card.id: card for card in custom_lists.filter(pk__in=lists_page)}
        lists_page.object_list = [cards[list_id] for list_id in lists_page]
        for card in lists_page:
            card.last_watched_at = list_last_watched.get(card.id)
    else:
        paginator = Paginator(custom_lists, items_per_page)
        lists_page = paginator.get_page(page)

    available_tags = CustomListForm._normalize_tags(
        tag
        for tags in CustomList.objects.filter(
            Q(owner=request.user) | Q(collaborators=request.user),
        )
        .values_list("tags", flat=True)
        .iterator(chunk_size=500)
        for tag in (tags or [])
    )

    # Compute completion percentages for each list (titles completed / total titles)
    page_list_ids = [custom_list.id for custom_list in lists_page]
    completed_counts = _get_list_completed_counts(request.user, page_list_ids)
    for cl in lists_page:
        cl.completed_count = completed_counts.get(cl.id, 0)
        cl.completion_percent = (
            round(cl.completed_count / cl.items_count * 100) if cl.items_count else None
        )

    # The edit form (with its select2 widgets) is fetched lazily via
    # list_edit_form when the user opens the modal, so only compute the
    # cheap permission flag here.
    for custom_list in lists_page:
        custom_list.can_edit = custom_list.user_can_edit(request.user)
    _attach_cached_covers(lists_page)

    # Add timestamp to context for cache busting
    import time

    cache_buster = int(time.time())

    # Boosted navigation still sends HX-Request but needs the full page
    if helpers.is_htmx_fragment(request):
        response = render(
            request,
            "lists/components/list_grid.html",
            {
                "custom_lists": lists_page,
                "current_sort": sort_by,
                "current_direction": direction,
                "cache_buster": cache_buster,
                "list_url_template": _build_list_url_template(request),
            },
        )
        # Explicitly set cache control headers for HTMX responses
        response["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response["Pragma"] = "no-cache"
        response["Expires"] = "0"
        response["Vary"] = "Cookie, HX-Request, HX-Boosted"
        response["X-Cache-Buster"] = str(cache_buster)
        return response

    create_list_form = CustomListForm(
        user=request.user,
        available_tags=available_tags,
    )
    # Trakt refuses non-HTTPS redirect URIs, so this instance may only be able to
    # connect through the device code flow, which registers the OOB value (#681).
    trakt_redirect_uri = request.build_absolute_uri(reverse("trakt_lists_callback"))
    trakt_device_flow = not helpers.supports_oauth_redirect(trakt_redirect_uri)
    if trakt_device_flow:
        trakt_redirect_uri = trakt_imports.TRAKT_OOB_REDIRECT_URI
    trakt_account = TraktAccount.objects.filter(user=request.user).first()
    mdblist_account = MDBListAccount.objects.filter(user=request.user).first()

    response = render(
        request,
        "lists/custom_lists.html",
        {
            "custom_lists": lists_page,
            "form": create_list_form,
            "current_sort": sort_by,
            "current_direction": direction,
            "sort_choices": ListSortChoices.choices,
            "media_types": enabled_media_types,
            "current_media_type": selected_media_type,
            "trakt_redirect_uri": trakt_redirect_uri,
            "trakt_device_flow": trakt_device_flow,
            "trakt_account": trakt_account,
            "trakt_has_credentials": bool(
                trakt_account and trakt_account.is_configured
            ),
            "mdblist_account": mdblist_account,
            "cache_buster": cache_buster,
            "list_url_template": _build_list_url_template(request),
        },
    )
    # Explicitly set cache control headers for Safari compatibility
    # @never_cache should handle this, but Safari can be aggressive with caching
    response["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    response["Vary"] = "Cookie"
    response["X-Cache-Buster"] = str(cache_buster)
    return response


@login_not_required
@require_GET
def list_cover_image(request, list_id):
    """Resolve a cold list cover after page render, then remember its URL.

    Called per-card via hx-trigger="revealed" so the expensive IGDB/TMDB
    backdrop lookups happen after the page has already rendered.
    """
    custom_list = get_object_or_404(CustomList, id=list_id)
    if not custom_list.user_can_view(request.user):
        return HttpResponseForbidden()
    _attach_cached_covers([custom_list])
    image_url = custom_list.cached_cover_url
    if image_url is None:
        image_url = custom_list.image
        cache.set(custom_list.cover_cache_key, image_url, 60 * 60)
    return render(
        request,
        "lists/components/list_cover_image.html",
        {"image_url": image_url, "name": custom_list.name},
    )
