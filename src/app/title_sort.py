"""The one title sort key: lower-cased, with a leading "The ", "A " or "An " dropped.

The displayed title never changes; only the value a title sort orders by does.
The trailing space is required, so "Therapy" and "Andor" stay under T and A.
``title_sort_key`` (Python) and ``title_sort_expr`` (SQL) must agree, because
keyset paging compares one against the other.
"""

from django.db.models import Case, CharField, F, Value, When
from django.db.models.functions import Left, Lower, Substr
from django.db.models.lookups import Exact

LEADING_ARTICLES = ("the ", "a ", "an ")


def title_sort_key(title) -> str:
    """Return the lower-cased title without a leading English article."""
    lowered = (title or "").lower()
    for article in LEADING_ARTICLES:
        if lowered.startswith(article):
            return lowered[len(article) :]
    return lowered


def title_sort_expr(field="title"):
    """Return the SQL expression equal to ``title_sort_key`` of ``field``."""
    lowered = Lower(field if not isinstance(field, str) else F(field))
    return Case(
        *(
            When(
                Exact(Left(lowered, len(article)), Value(article)),
                then=Substr(lowered, len(article) + 1, output_field=CharField()),
            )
            for article in LEADING_ARTICLES
        ),
        default=lowered,
        output_field=CharField(),
    )
