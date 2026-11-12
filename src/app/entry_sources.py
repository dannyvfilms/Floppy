"""Sources a user has recorded on their entries, offered as suggestions."""

from collections import Counter

from django.apps import apps
from django.core.cache import cache
from django.db.models import Count

from app.models import Episode, Media, MoviePlay

# Counting sources reads every tracking table, and the tracking modal asks on
# every open. The list changes only when a new value is first saved, which
# note_saved_source() catches, so a day is safe.
SUGGESTIONS_CACHE_TIMEOUT = 60 * 60 * 24


def _cache_key(user_id):
    return f"entry_source_suggestions:{user_id}"


def _source_counts(user):
    """Yield (value, count) rows from every table that stores a source."""
    for model in apps.get_app_config("app").get_models():
        if not issubclass(model, Media) or model._meta.abstract:
            continue
        yield from (
            model.objects.filter(user=user)
            .exclude(entry_source="")
            .values_list("entry_source")
            .annotate(total=Count("id"))
        )
    yield from (
        MoviePlay.objects.filter(movie__user=user)
        .exclude(entry_source="")
        .values_list("entry_source")
        .annotate(total=Count("id"))
    )
    yield from (
        Episode.objects.filter(related_season__user=user)
        .exclude(entry_source="")
        .values_list("entry_source")
        .annotate(total=Count("id"))
    )


def entry_source_suggestions(user):
    """Return the user's distinct sources, most used first.

    Values that differ only by case ("plex", "Plex") count as one and keep the
    spelling used most often.
    """
    if not getattr(user, "is_authenticated", False):
        return []
    key = _cache_key(user.pk)
    cached = cache.get(key)
    if cached is not None:
        return cached
    spellings = {}
    for value, total in _source_counts(user):
        text = value.strip()
        if text:
            spellings.setdefault(text.casefold(), Counter())[text] += total
    ranked = sorted(
        spellings.values(),
        key=lambda counter: (-sum(counter.values()), min(counter).casefold()),
    )
    suggestions = [counter.most_common(1)[0][0] for counter in ranked]
    cache.set(key, suggestions, SUGGESTIONS_CACHE_TIMEOUT)
    return suggestions


def _owner_id(instance):
    """Return the user id that owns a row carrying ``entry_source``."""
    if isinstance(instance, Media):
        return instance.user_id
    if isinstance(instance, MoviePlay):
        return instance.movie.user_id
    if isinstance(instance, Episode):
        return instance.related_season.user_id
    return None


def note_saved_source(instance):
    """Drop the cached suggestions when a row is saved with a value not in them.

    Most saves repeat a known source (an import stamps thousands of rows with
    one value), so the cache is read first and left alone when the value is
    already offered. Bulk writes skip signals; the timeout covers those.
    """
    value = (getattr(instance, "entry_source", "") or "").strip()
    if not value:
        return
    user_id = _owner_id(instance)
    if user_id is None:
        return
    key = _cache_key(user_id)
    cached = cache.get(key)
    if cached is not None and value.casefold() not in {
        text.casefold() for text in cached
    }:
        cache.delete(key)
