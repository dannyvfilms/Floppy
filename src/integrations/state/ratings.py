"""Explicit rating edits and the shared outbound rating boundary.

Only opted-in UI/API writers enter this scope. Ordinary model saves, imports,
provider updates and replay inheritance therefore cannot publish ratings.
"""

from contextvars import ContextVar
from functools import partial, wraps
from http import HTTPStatus

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.utils import timezone

from app.models import TV, Episode, Movie
from app.services.episode_scores import episode_scores_changed
from integrations.models import RatingSyncEdit
from integrations.state.outbound import enqueue_rating_change

_edits = ContextVar("explicit_rating_edits", default=None)


def record_rating_edit(user_id, item, score):
    """Collect one explicit edit, deduplicating episode play updates."""
    scope = _edits.get()
    if scope is not None and scope["user"].pk == user_id:
        scope["changes"][item.pk] = (item, score)


def rating_edit(view=None, *, implicit_clear=False):
    """Opt a direct rating writer into atomic save and outbound enqueueing."""
    if view is None:
        return partial(rating_edit, implicit_clear=implicit_clear)

    @wraps(view)
    def wrapped(*args, **kwargs):
        request = args[0] if hasattr(args[0], "user") else args[1]
        data = request.data if hasattr(request, "data") else request.POST
        if (
            "score" not in data and not implicit_clear
        ) or not request.user.is_authenticated:
            return view(*args, **kwargs)
        with transaction.atomic():
            # Lock before the view reads its rows, so edit order equals commit
            # order. The export uses this same lock before reading a score.
            user = get_user_model().objects.select_for_update().get(pk=request.user.pk)
            scope = {"user": user, "started": timezone.now(), "changes": {}}
            token = _edits.set(scope)
            try:
                response = view(*args, **kwargs)
                if response.status_code >= HTTPStatus.BAD_REQUEST:
                    transaction.set_rollback(True)
                    return response
                for item, score in scope["changes"].values():
                    RatingSyncEdit.objects.update_or_create(
                        user=user,
                        item=item,
                        defaults={"score": score, "edited_at": timezone.now()},
                    )
                    enqueue_rating_change(user, item, score)
                return response
            finally:
                _edits.reset(token)

    return wrapped


def _before_save(sender, instance, raw=False, update_fields=None, **kwargs):
    """Compare persisted scores while an explicit writer owns the user lock."""
    instance._outbound_rating_changed = False
    scope = _edits.get()
    if (
        raw
        or scope is None
        or (update_fields is not None and "score" not in update_fields)
    ):
        return
    user_id = instance.related_season.user_id if sender is Episode else instance.user_id
    if user_id != scope["user"].pk:
        return
    if instance._state.adding:
        # Replays carry the original scored_at; they are not fresh ratings.
        instance._outbound_rating_changed = instance.score is not None and (
            instance.scored_at is None or instance.scored_at >= scope["started"]
        )
        instance._outbound_rating_previous = None
    else:
        manager = Episode.ratings if sender is Episode else sender.objects
        previous = (
            manager.filter(pk=instance.pk).values_list("score", flat=True).first()
        )
        instance._outbound_rating_previous = previous
        instance._outbound_rating_changed = previous != instance.score


def _after_save(sender, instance, **kwargs):
    """Collect only actual score changes from the opted-in writer."""
    if not getattr(instance, "_outbound_rating_changed", False):
        return
    manager = Episode.ratings if sender is Episode else sender.objects
    # Read storage precision back: API writers may supply floats or extra
    # decimal places, and providers must receive the score actually saved.
    score = manager.filter(pk=instance.pk).values_list("score", flat=True).get()
    if score == instance._outbound_rating_previous:
        return
    user_id = instance.related_season.user_id if sender is Episode else instance.user_id
    record_rating_edit(user_id, instance.item, score)


def record_episode_rating_edits(sender, *, episodes, score, user_id, **kwargs):
    """Collect bulk-update edits only when an explicit writer opted in."""
    scope = _edits.get()
    if scope is None or scope["user"].pk != user_id:
        return
    for episode in (
        episodes.select_related("item").only("item").iterator(chunk_size=500)
    ):
        record_rating_edit(user_id, episode.item, score)


for _model in (Movie, TV, Episode):
    pre_save.connect(
        _before_save, sender=_model, dispatch_uid=f"rating_before_{_model._meta.label}"
    )
    post_save.connect(
        _after_save, sender=_model, dispatch_uid=f"rating_after_{_model._meta.label}"
    )

episode_scores_changed.connect(
    record_episode_rating_edits, dispatch_uid="outbound_episode_ratings"
)
