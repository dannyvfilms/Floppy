"""Keep canonical watched state in step with the legacy tracking stores.

Every existing write path ends in a save or delete on one of these models, so
hooking them here catches the UI, the API, the webhooks and the importers
without editing any of them. The one path signals cannot see is ``bulk_create``
(used by ``TV._completed()``), which is why the projection is a recompute:
anything missed can be repaired by calling ``project_watch_state`` again.
"""

from django.core.exceptions import ObjectDoesNotExist
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from app.models import (
    Anime,
    BoardGame,
    Book,
    Comic,
    ComicIssue,
    Episode,
    Game,
    Manga,
    Movie,
    MoviePlay,
    Music,
    Podcast,
)
from app.services.watch_state import project_watch_state_for_change


def _project(user_getter, item_getter):
    """Project unless the rows this state describes are themselves going away.

    Deleting an Item cascades to the tracking rows *and* to their WatchState, and
    Django fires the tracking row's post_delete after the Item is already gone.
    Reprojecting there would resurrect a row for a deleted item, so a missing
    related object means there is nothing left to describe.
    """
    try:
        user = user_getter()
        item = item_getter()
    except ObjectDoesNotExist:
        return
    project_watch_state_for_change(user, item)


@receiver([post_save, post_delete], sender=Movie)
@receiver([post_save, post_delete], sender=Anime)
@receiver([post_save, post_delete], sender=Manga)
@receiver([post_save, post_delete], sender=Book)
@receiver([post_save, post_delete], sender=Comic)
@receiver([post_save, post_delete], sender=ComicIssue)
@receiver([post_save, post_delete], sender=Game)
@receiver([post_save, post_delete], sender=BoardGame)
@receiver([post_save, post_delete], sender=Music)
@receiver([post_save, post_delete], sender=Podcast)
def project_on_media_change(sender, instance, **kwargs):
    """Reproject after a tracking row for a flat media type changes."""
    _project(lambda: instance.user, lambda: instance.item)


@receiver([post_save, post_delete], sender=Episode)
def project_on_episode_change(sender, instance, **kwargs):
    """Reproject after an episode watch is recorded or removed."""
    if instance.item_id is None:
        return
    _project(lambda: instance.related_season.user, lambda: instance.item)


@receiver([post_save, post_delete], sender=MoviePlay)
def project_on_movie_play_change(sender, instance, **kwargs):
    """Reproject after an individual movie play changes.

    A play can be added or removed without the Movie row itself being saved, so
    this is not covered by the media receiver above.
    """
    _project(lambda: instance.movie.user, lambda: instance.movie.item)
