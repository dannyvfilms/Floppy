"""Let a user say which game a video is about, or that it is about none."""

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST

from app.models import Item, MediaTypes, Video, VideoGameLink
from app.services import youtube_game_watch

SEARCH_LIMIT = 8
MIN_QUERY_LENGTH = 2


def _owned_video(request, item_id):
    """Return the user's Video of this item, or 404."""
    return get_object_or_404(
        Video.objects.select_related("item"),
        user=request.user,
        item_id=item_id,
        item__media_type=MediaTypes.VIDEO.value,
    )


def _panel(request, item):
    return render(
        request,
        "app/components/video_game_panel.html",
        {
            "video_item": item,
            "video_game": youtube_game_watch.game_for_video(request.user, item),
        },
    )


@login_required
@require_GET
def video_game_panel(request, item_id):
    """Show the game a video is about."""
    return _panel(request, _owned_video(request, item_id).item)


@login_required
@require_POST
def video_game_set(request, item_id):
    """Link a video to a game, say it is about none, or go back to the YouTube tag.

    @param request.POST["mode"] - `game`, `none` or `auto`.
    @param request.POST["game_item_id"] - Required for `game`.
    """
    video = _owned_video(request, item_id)
    item = video.item
    mode = request.POST.get("mode", "")
    if mode == "auto":
        VideoGameLink.objects.filter(video=video).delete()
    elif mode == "none":
        VideoGameLink.objects.update_or_create(video=video, defaults={"game_item": None})
    elif mode == "game":
        game = Item.objects.filter(
            pk=request.POST.get("game_item_id") or 0,
            media_type=MediaTypes.GAME.value,
        ).first()
        if game is None:
            return HttpResponseBadRequest("Choose a game from the list.")
        VideoGameLink.objects.update_or_create(video=video, defaults={"game_item": game})
    else:
        return HttpResponseBadRequest("Unknown choice.")
    return _panel(request, item)


@login_required
@require_GET
def video_game_search(request, item_id):
    """List known games whose title contains the search text."""
    item = _owned_video(request, item_id).item
    query = request.GET.get("q", "").strip()
    games = []
    if len(query) >= MIN_QUERY_LENGTH:
        games = list(
            Item.objects.filter(
                media_type=MediaTypes.GAME.value, title__icontains=query
            ).order_by("title")[:SEARCH_LIMIT]
        )
    return render(
        request,
        "app/components/video_game_results.html",
        {"video_item": item, "games": games, "query": query},
    )
