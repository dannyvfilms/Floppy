"""Alphabet view filtering, shared by item queries and named tracker views."""

import string
from dataclasses import replace

from django.db.models import CharField, F, Q, Value
from django.db.models.functions import Coalesce, NullIf, Substr, Trim
from django.db.models.lookups import In


def normalize_initial(value):
    """Unknown URL values mean All; only ASCII letters are letter buckets."""
    value = str(value or "").strip()
    if len(value) == 1 and value in string.ascii_letters:
        return value.lower()
    return value if value in ("0-9", "other") else ""


def alphabet_title(user=None, *, prefix="", name_field=None):
    """Use the same displayed title for bucket matching and its representative glyph."""
    if name_field:
        return Coalesce(F(name_field), Value(""), output_field=CharField())
    fields = ["localized_title", "title", "original_title"]
    if getattr(user, "title_display_preference", "localized") == "original":
        fields = ["original_title", "localized_title", "title"]
    return Coalesce(
        *(NullIf(Trim(F(f"{prefix}{field}")), Value("")) for field in fields),
        Value(""),
        output_field=CharField(),
    )


def initial_condition(initial, user=None, *, prefix="", name_field=None):
    """Compile ASCII buckets without database-specific Unicode case folding."""
    initial = normalize_initial(initial)
    if not initial:
        return Q()
    first = Substr(
        Trim(alphabet_title(user, prefix=prefix, name_field=name_field)), 1, 1
    )
    if initial == "other":
        return ~Q(In(first, list(string.ascii_letters + string.digits)))
    letters = string.digits if initial == "0-9" else initial + initial.upper()
    return Q(In(first, list(letters)))


def first_other_initial(queryset, user=None, *, name_field=None):
    """Read one narrow title value, never a library of hydrated objects."""
    entry = (
        queryset.filter(initial_condition("other", user, name_field=name_field))
        .annotate(
            _alphabet_title=NullIf(
                Trim(alphabet_title(user, name_field=name_field)), Value("")
            )
        )
        .order_by(F("_alphabet_title").asc(nulls_last=True), "pk")
        .values("_alphabet_title")
        .first()
    )
    return (entry["_alphabet_title"] or "\u2026")[0] if entry else None


def query_other_initial(user, query, *, display_user=None):
    """Sample the authorized matching scope independently of the selected letter."""
    from app.library_query.executor import LibraryQueryExecutor
    from app.models import Item

    display_user = user if display_user is None else display_user
    if query.within is None:
        query = replace(query, filters=replace(query.filters, initial="other"))
    else:
        # Keep a list's explicit membership scope, including untracked members,
        # while reading titles with its viewer's preference rather than its owner.
        candidates = Item.objects.filter(pk__in=query.within).filter(
            initial_condition("other", display_user)
        )
        query = replace(
            query,
            within=candidates.values("pk"),
            filters=replace(query.filters, initial=""),
        )
    matches = LibraryQueryExecutor(user, query).matches()
    return first_other_initial(Item.objects.filter(pk__in=matches), display_user)
