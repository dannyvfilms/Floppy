"""Write an episode rating.

A rating belongs to the episode, not to one viewing of it, so every play row
of the episode carries the same score (``Episode.save`` copies it onto a new
replay). The season page and the media-server webhooks all write through here
so they agree on that rule and on the History refresh it needs.
"""

import logging

from django.dispatch import Signal
from django.utils import timezone

from app import history_cache
from app.models import Episode, Status

logger = logging.getLogger(__name__)
episode_scores_changed = Signal()


def tracked_episode_plays(user, media_id, source, season_number, episode_number):
    """Return the user's play rows of one episode, across library buckets."""
    return Episode.objects.filter(
        related_season__user=user,
        item__media_id=str(media_id),
        item__source=source,
        item__season_number=season_number,
        item__episode_number=episode_number,
    )


def set_episode_score(episodes, score, user_id):
    """Set ``score`` on every play in ``episodes``; return how many changed.

    ``update()`` skips post_save, so the Episode signal that refreshes the
    History cache never fires. Invalidate the affected days here instead.
    """
    # Only plays whose score differs, so a retried request is not a new rating.
    episodes = episodes.exclude(score=score)
    episode_scores_changed.send(
        Episode, episodes=episodes, score=score, user_id=user_id
    )
    end_dates = list(episodes.values_list("end_date", flat=True))
    updated = episodes.update(score=score, scored_at=timezone.now())

    day_keys = [history_cache.history_day_key(end_date) for end_date in end_dates]
    day_keys = [day_key for day_key in day_keys if day_key]
    if day_keys:
        history_cache.invalidate_history_days(
            user_id,
            day_keys=day_keys,
            logging_styles=("sessions", "repeats"),
            reason="episode_score_change",
        )
    return updated


def rate_episode(season, episode_number, score):
    """Rate one episode of ``season``, whether or not anyone has watched it.

    Every play carries the score. An episode with no play gets one rating-only
    row, which is not a watch (see ``Episode.rating_only``); clearing the score
    drops that row again. Returns False when there is nothing to clear.
    """
    rows = Episode.ratings.filter(
        related_season=season,
        item__episode_number=int(episode_number),
    )
    if rows.exists():
        if score is None:
            episode_scores_changed.send(
                Episode,
                episodes=rows.filter(rating_only=True),
                score=None,
                user_id=season.user_id,
            )
            rows.filter(rating_only=True).delete()
        set_episode_score(rows.filter(rating_only=False), score, season.user_id)
        rating_rows = rows.filter(rating_only=True).exclude(score=score)
        episode_scores_changed.send(
            Episode, episodes=rating_rows, score=score, user_id=season.user_id
        )
        rating_rows.update(
            score=score,
            scored_at=timezone.now(),
        )
        return True
    if score is None:
        return False
    Episode.ratings.create(
        related_season=season,
        item=season.get_episode_item(int(episode_number)),
        status=Status.PLANNING.value,
        rating_only=True,
        score=score,
    )
    return True
