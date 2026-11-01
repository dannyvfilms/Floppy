"""Keep canonical watched state in step with the legacy tracking stores.

Every existing write path ends in a save or delete on one of these models, so
hooking them here catches the UI, the API, the webhooks and the importers
without editing any of them. The one path signals cannot see is ``bulk_create``
(used by ``TV._completed()``), which is why the projection is a recompute:
anything missed can be repaired by calling ``project_watch_state`` again.
"""

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save
from django.dispatch import receiver

from app.models import (
    TV,
    Anime,
    BoardGame,
    Book,
    Comic,
    ComicIssue,
    Episode,
    Game,
    Item,
    Manga,
    Movie,
    MoviePlay,
    Music,
    PlaybackProgress,
    Podcast,
    ProgressChange,
    Season,
    WatchStateChange,
)
from app.services.sync_lock import invalidate_item_contexts, lock_sequence
from app.services.watch_state import project_watch_state_for_change


@receiver(pre_delete, sender=Movie)
@receiver(pre_delete, sender=Anime)
@receiver(pre_delete, sender=Manga)
@receiver(pre_delete, sender=Book)
@receiver(pre_delete, sender=Comic)
@receiver(pre_delete, sender=ComicIssue)
@receiver(pre_delete, sender=Game)
@receiver(pre_delete, sender=BoardGame)
@receiver(pre_delete, sender=Music)
@receiver(pre_delete, sender=Podcast)
@receiver(pre_delete, sender=TV)
@receiver(pre_delete, sender=Season)
@receiver(pre_delete, sender=PlaybackProgress)
@receiver(pre_delete, sender=Episode)
@receiver(pre_delete, sender=MoviePlay)
@receiver(pre_delete, sender=Item)
def serialize_tracking_delete(sender, instance, **kwargs):
    """Django's deletion collector already supplies the enclosing transaction."""
    if _user_is_being_deleted(kwargs.get("origin")):
        return
    if sender in {Movie, Anime, Manga, Book, Comic, ComicIssue, Game, BoardGame,
                  Music, Podcast, TV, Season, PlaybackProgress}:
        lock_sequence(instance.user_id)
    elif sender is Episode:
        lock_sequence(instance.related_season.user_id)
    elif sender is MoviePlay:
        lock_sequence(instance.movie.user_id)
    elif sender is Item:
        invalidate_item_contexts([instance.pk])


@receiver(pre_save, sender=PlaybackProgress)
def remember_progress(sender, instance, **kwargs):
    """Avoid turning a repeated identical position into another movement."""
    fields = ("position_seconds", "duration_seconds", "completed")
    instance._sync_previous_progress = (
        sender.objects.filter(pk=instance.pk).values_list(*fields).first()
        if instance.pk else None
    )


@receiver(post_save, sender=PlaybackProgress)
def publish_progress(sender, instance, raw=False, **kwargs):
    """All model writers share the same ordered progress sink."""
    from app.services.progress_changes import record_progress_change

    values = (instance.position_seconds, instance.duration_seconds, instance.completed)
    if not raw and values != getattr(instance, "_sync_previous_progress", None):
        record_progress_change(
            instance.user, instance.item, position_seconds=values[0],
            duration_seconds=values[1], completed=values[2],
        )


@receiver(post_delete, sender=PlaybackProgress)
def publish_progress_delete(sender, instance, origin=None, **kwargs):
    """Publish explicit clears; invalidate contexts for Item cascades instead."""
    from app.services.progress_changes import record_progress_deletion

    if _user_is_being_deleted(origin):
        return
    if not _item_is_being_deleted(origin, instance.item_id) and Item.objects.filter(pk=instance.item_id).exists():
        record_progress_deletion(instance.user, instance.item)


@receiver(pre_delete, sender=WatchStateChange)
@receiver(pre_delete, sender=ProgressChange)
def remember_removed_history(sender, instance, **kwargs):
    """Even complete removal or an administrative ORM delete leaves evidence."""
    if _user_is_being_deleted(kwargs.get("origin")):
        return
    row = lock_sequence(instance.user_id)
    field = "watched_cursor_floor" if sender is WatchStateChange else "progress_cursor_floor"
    pruned = "watched_pruned_through" if sender is WatchStateChange else "progress_pruned_through"
    for boundary in (field, pruned):
        if instance.sequence > getattr(row, boundary):
            setattr(row, boundary, instance.sequence)
            row.save(update_fields=[boundary])


def _user_is_being_deleted(origin):
    """Do not recreate per-user protocol rows during an account cascade."""
    model = getattr(origin, "model", type(origin))
    return getattr(getattr(model, "_meta", None), "label_lower", None) == settings.AUTH_USER_MODEL.lower()


def _item_is_being_deleted(origin, item_id):
    """Do not append events after a collector has already planned its FK updates."""
    if isinstance(origin, Item):
        return origin.pk == item_id
    if getattr(origin, "model", None) is Item:
        deleting = getattr(origin, "_sync_deleting_item_ids", None)
        if deleting is not None:
            return item_id in deleting
        return origin.filter(pk=item_id).exists()
    return False


def _project(user_getter, item_getter, *, deleting=False, origin=None):
    """Project unless the rows this state describes are themselves going away.

    Deleting an Item cascades to the tracking rows *and* to their WatchState, and
    Django fires the tracking row's post_delete after the Item is already gone.
    Reprojecting there would resurrect a row for a deleted item, so a missing
    related object means there is nothing left to describe.
    """
    if _user_is_being_deleted(origin):
        return
    try:
        user = user_getter()
        item = item_getter()
    except ObjectDoesNotExist:
        return
    if deleting and (_item_is_being_deleted(origin, item.pk) or not Item.objects.filter(pk=item.pk).exists()):
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
    _project(lambda: instance.user, lambda: instance.item, deleting="origin" in kwargs, origin=kwargs.get("origin"))


@receiver([post_save, post_delete], sender=Episode)
def project_on_episode_change(sender, instance, **kwargs):
    """Reproject after an episode watch is recorded or removed."""
    if instance.item_id is None:
        return
    _project(lambda: instance.related_season.user, lambda: instance.item, deleting="origin" in kwargs, origin=kwargs.get("origin"))


@receiver([post_save, post_delete], sender=MoviePlay)
def project_on_movie_play_change(sender, instance, **kwargs):
    """Reproject after an individual movie play changes.

    A play can be added or removed without the Movie row itself being saved, so
    this is not covered by the media receiver above.
    """
    _project(lambda: instance.movie.user, lambda: instance.movie.item, deleting="origin" in kwargs, origin=kwargs.get("origin"))
