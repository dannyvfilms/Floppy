"""Sources a user has recorded on their entries, offered as suggestions."""

from collections import Counter

from django.apps import apps
from django.db.models import Count

from app.models import Episode, Media, MoviePlay


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
    spellings = {}
    for value, total in _source_counts(user):
        text = value.strip()
        if text:
            spellings.setdefault(text.casefold(), Counter())[text] += total
    ranked = sorted(
        spellings.values(),
        key=lambda counter: (-sum(counter.values()), min(counter).casefold()),
    )
    return [counter.most_common(1)[0][0] for counter in ranked]
