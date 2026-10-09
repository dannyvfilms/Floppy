"""Rapid Rating v2.0.0 - fast movie and TV episode rating queues."""

from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.shortcuts import render
from django.urls import reverse

from app.models import TV, Episode, MediaTypes, Movie, Season

RAPID_RATING_VERSION = "2.0.0"
TV_QUEUE_LIMIT = 500
RATING_SCALE_FIVE = 5

VALID_RATING_STATES = {"unrated", "rated", "all"}
VALID_ORDERS = {"recent", "oldest", "episode", "random"}


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _display_factor(user):
    """Convert stored 10-point score arithmetic to the user's display scale."""
    try:
        return Decimal(1) / 2 if int(user.rating_scale_max) == RATING_SCALE_FIVE else Decimal(1)
    except (TypeError, ValueError, AttributeError):
        return Decimal(1)


def _stats_by_season(user, season_ids):
    if not season_ids:
        return {}

    factor = _display_factor(user)
    rows = (
        Episode.objects.filter(
            related_season__user=user,
            related_season_id__in=season_ids,
            status="Completed",
        )
        .values("related_season_id")
        .annotate(
            total_count=Count("id"),
            rated_count=Count("id", filter=Q(score__isnull=False)),
            score_sum=Sum("score", filter=Q(score__isnull=False)),
        )
    )

    result = {}
    for row in rows:
        raw_sum = row["score_sum"] or Decimal()
        result[row["related_season_id"]] = {
            "total": int(row["total_count"] or 0),
            "rated": int(row["rated_count"] or 0),
            "sum": float(raw_sum * factor),
        }
    return result


def _stats_by_show(user, tv_ids):
    """Show aggregate excludes Season 0 / Specials by design."""
    if not tv_ids:
        return {}

    factor = _display_factor(user)
    rows = (
        Episode.objects.filter(
            related_season__user=user,
            related_season__related_tv__user=user,
            related_season__related_tv_id__in=tv_ids,
            status="Completed",
            item__season_number__gt=0,
        )
        .values("related_season__related_tv_id")
        .annotate(
            total_count=Count("id"),
            rated_count=Count("id", filter=Q(score__isnull=False)),
            score_sum=Sum("score", filter=Q(score__isnull=False)),
        )
    )

    result = {}
    for row in rows:
        raw_sum = row["score_sum"] or Decimal()
        result[row["related_season__related_tv_id"]] = {
            "total": int(row["total_count"] or 0),
            "rated": int(row["rated_count"] or 0),
            "sum": float(raw_sum * factor),
        }
    return result


def _movie_queue(user):
    movies = (
        Movie.objects.filter(
            user=user,
            status="Completed",
            score__isnull=True,
        )
        .select_related("item")
        .order_by("-end_date", "-id")
    )

    queue = []
    for movie in movies:
        item = movie.item
        release_datetime = getattr(item, "release_datetime", None)
        end_date = getattr(movie, "end_date", None)

        queue.append(
            {
                "id": movie.pk,
                "kind": "movie",
                "title": item.title or "Untitled",
                "subtitle": "",
                "show_title": "",
                "year": release_datetime.year if release_datetime else None,
                "genres": item.genres or [],
                "poster": item.image or "",
                "watched": end_date.date().isoformat() if end_date else None,
                "current_score": None,
                "rate_url": reverse(
                    "update_media_score",
                    args=[MediaTypes.MOVIE.value, movie.pk],
                ),
            }
        )

    return queue


def _tv_filter_options(user, selected_show_id):
    shows = (
        TV.objects.filter(
            user=user,
            seasons__episodes__status="Completed",
        )
        .select_related("item")
        .annotate(
            episode_count=Count(
                "seasons__episodes",
                filter=Q(seasons__episodes__status="Completed"),
                distinct=True,
            ),
            rated_episode_count=Count(
                "seasons__episodes",
                filter=Q(
                    seasons__episodes__status="Completed",
                    seasons__episodes__score__isnull=False,
                ),
                distinct=True,
            ),
        )
        .distinct()
        .order_by("item__title", "id")
    )

    show_options = [
        {
            "id": tv.id,
            "title": tv.item.title or "Untitled",
            "episode_count": int(tv.episode_count or 0),
            "rated_count": int(tv.rated_episode_count or 0),
        }
        for tv in shows
    ]

    season_options = []
    if selected_show_id:
        seasons = (
            Season.objects.filter(
                user=user,
                related_tv_id=selected_show_id,
                episodes__status="Completed",
            )
            .select_related("item")
            .annotate(
                episode_count=Count(
                    "episodes",
                    filter=Q(episodes__status="Completed"),
                    distinct=True,
                ),
                rated_episode_count=Count(
                    "episodes",
                    filter=Q(
                        episodes__status="Completed",
                        episodes__score__isnull=False,
                    ),
                    distinct=True,
                ),
            )
            .distinct()
            .order_by("item__season_number", "id")
        )

        for season in seasons:
            number = getattr(season.item, "season_number", None)
            label = "Specials" if number == 0 else f"Season {number}"
            season_options.append(
                {
                    "id": season.id,
                    "number": number,
                    "label": label,
                    "episode_count": int(season.episode_count or 0),
                    "rated_count": int(season.rated_episode_count or 0),
                }
            )

    return show_options, season_options


def _tv_queue(user, selected_show_id, selected_season_id, rating_state, order):
    qs = (
        Episode.objects.filter(
            related_season__user=user,
            related_season__related_tv__user=user,
            status="Completed",
        )
        .select_related(
            "item",
            "related_season__item",
            "related_season__related_tv__item",
        )
    )

    if selected_show_id:
        qs = qs.filter(related_season__related_tv_id=selected_show_id)

    if selected_season_id:
        qs = qs.filter(related_season_id=selected_season_id)

    if rating_state == "unrated":
        qs = qs.filter(score__isnull=True)
    elif rating_state == "rated":
        qs = qs.filter(score__isnull=False)

    total_matches = qs.count()

    if order == "oldest":
        qs = qs.order_by("end_date", "id")
    elif order == "episode":
        if selected_show_id:
            qs = qs.order_by(
                "item__season_number",
                "item__episode_number",
                "end_date",
                "id",
            )
        else:
            qs = qs.order_by(
                "related_season__related_tv__item__title",
                "item__season_number",
                "item__episode_number",
                "id",
            )
    elif order == "random":
        qs = qs.order_by("?")
    else:
        qs = qs.order_by("-end_date", "-id")

    episodes = list(qs[:TV_QUEUE_LIMIT])

    season_ids = {episode.related_season_id for episode in episodes}
    tv_ids = {episode.related_season.related_tv_id for episode in episodes}
    season_stats = _stats_by_season(user, season_ids)
    show_stats = _stats_by_show(user, tv_ids)
    factor = _display_factor(user)

    queue = []
    for episode in episodes:
        item = episode.item
        season = episode.related_season
        tv = season.related_tv
        tv_item = tv.item

        season_number = getattr(item, "season_number", None)
        episode_number = getattr(item, "episode_number", None)
        end_date = getattr(episode, "end_date", None)

        current_score = None
        if episode.score is not None:
            current_score = float(Decimal(episode.score) * factor)

        queue.append(
            {
                "id": episode.pk,
                "kind": "episode",
                "title": item.title or f"Episode {episode_number or '?'}",
                "subtitle": (
                    f"S{season_number:02d}E{episode_number:02d}"
                    if season_number is not None and episode_number is not None
                    else "Episode"
                ),
                "show_title": tv_item.title or "Untitled TV Show",
                "year": None,
                "genres": tv_item.genres or [],
                "poster": tv_item.image or item.image or "",
                "watched": end_date.date().isoformat() if end_date else None,
                "current_score": current_score,
                "rate_url": reverse(
                    "update_media_score",
                    args=[MediaTypes.EPISODE.value, episode.pk],
                ),
                "season_id": season.id,
                "show_id": tv.id,
                "season_number": season_number,
                "episode_number": episode_number,
                "season_stats": season_stats.get(
                    season.id,
                    {"total": 0, "rated": 0, "sum": 0.0},
                ),
                "show_stats": show_stats.get(
                    tv.id,
                    {"total": 0, "rated": 0, "sum": 0.0},
                ),
            }
        )

    return queue, total_matches


@login_required
def rapid_rating(request):
    """Fast keyboard-driven rating queue for movies and TV episodes."""
    media_mode = request.GET.get("media", "movies").strip().lower()
    if media_mode not in {"movies", "tv"}:
        media_mode = "movies"

    rating_state = request.GET.get("state", "unrated").strip().lower()
    if rating_state not in VALID_RATING_STATES:
        rating_state = "unrated"

    order = request.GET.get("order", "recent").strip().lower()
    if order not in VALID_ORDERS:
        order = "recent"

    selected_show_id = _safe_int(request.GET.get("show"))
    selected_season_id = _safe_int(request.GET.get("season"))

    if selected_show_id and not TV.objects.filter(
        pk=selected_show_id,
        user=request.user,
    ).exists():
        selected_show_id = None
        selected_season_id = None

    if selected_season_id:
        season_filter = {
            "pk": selected_season_id,
            "user": request.user,
        }
        if selected_show_id:
            season_filter["related_tv_id"] = selected_show_id
        if not Season.objects.filter(**season_filter).exists():
            selected_season_id = None

    show_options, season_options = _tv_filter_options(
        request.user,
        selected_show_id,
    )

    if media_mode == "tv":
        queue, total_matches = _tv_queue(
            request.user,
            selected_show_id,
            selected_season_id,
            rating_state,
            order,
        )
    else:
        queue = _movie_queue(request.user)
        total_matches = len(queue)

    try:
        rating_scale = int(request.user.rating_scale_max)
    except (TypeError, ValueError, AttributeError):
        rating_scale = 10

    return render(
        request,
        "app/rapid_rating.html",
        {
            "rapid_rating_version": RAPID_RATING_VERSION,
            "rapid_items": queue,
            "rapid_total": total_matches,
            "rapid_loaded": len(queue),
            "rapid_media": media_mode,
            "rapid_rating_state": rating_state,
            "rapid_order": order,
            "rapid_selected_show": selected_show_id,
            "rapid_selected_season": selected_season_id,
            "rapid_show_options": show_options,
            "rapid_season_options": season_options,
            "rapid_rating_scale": rating_scale,
            "rapid_queue_limit": TV_QUEUE_LIMIT,
        },
    )
