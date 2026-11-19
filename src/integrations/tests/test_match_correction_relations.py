"""A match correction handles every user-owned table that points at an Item.

`match_corrections._move_relations` is a hand-written list. A new table with
a foreign key to `Item` that carries a user (directly, or through a list, tag
or season) fails this test until it is either moved or named below with the
reason it stays behind.
"""

import inspect

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase

from app.models import Item
from integrations import external_references, match_corrections

# relation -> the function that moves it. The model's class name must appear
# in that function's source.
MOVED = {
    "app.TV.item": (match_corrections._move_tv, "TV"),
    "app.Season.item": (match_corrections._move_tv, "Season"),
    "app.Episode.item": (match_corrections._move_tv, "Episode"),
    "app.Movie.item": (match_corrections._move_movie, "Movie"),
    "app.CollectionEntry.item": (match_corrections._move_relations, "CollectionEntry"),
    "app.PlaybackProgress.item": (
        match_corrections._move_relations,
        "PlaybackProgress",
    ),
    "app.WatchState.item": (match_corrections._move_relations, "WatchState"),
    "app.ProgressChange.item": (match_corrections._move_relations, "ProgressChange"),
    "app.WatchStateChange.item": (
        match_corrections._move_relations,
        "WatchStateChange",
    ),
    "app.DiscoverFeedback.item": (
        match_corrections._move_relations,
        "DiscoverFeedback",
    ),
    "app.ItemTag.item": (match_corrections._move_relations, "ItemTag"),
    "lists.CustomListItem.item": (match_corrections._move_relations, "CustomListItem"),
    # The list's many-to-many runs through CustomListItem.
    "lists.CustomList.items": (match_corrections._move_relations, "CustomListItem"),
    "lists.ListRecommendation.item": (
        match_corrections._move_relations,
        "ListRecommendation",
    ),
    "integrations.ExternalReference.corrected_item": (
        external_references.save_correction,
        "corrected_item",
    ),
}

_NOT_A_CORRECTION_TYPE = "Corrections cover movies and shows only."
_SYNC_BOOKKEEPING = "Sync bookkeeping for the old item; the next sync rebuilds it."

NOT_MOVED_BECAUSE = {
    "app.BasicMedia.item": _NOT_A_CORRECTION_TYPE,
    "app.Manga.item": _NOT_A_CORRECTION_TYPE,
    "app.Anime.item": _NOT_A_CORRECTION_TYPE,
    "app.Anime.migrated_to_item": _NOT_A_CORRECTION_TYPE,
    "app.Game.item": _NOT_A_CORRECTION_TYPE,
    "app.BoardGame.item": _NOT_A_CORRECTION_TYPE,
    "app.Book.item": _NOT_A_CORRECTION_TYPE,
    "app.Comic.item": _NOT_A_CORRECTION_TYPE,
    "app.ComicIssue.item": _NOT_A_CORRECTION_TYPE,
    "app.Music.item": _NOT_A_CORRECTION_TYPE,
    "app.Podcast.item": _NOT_A_CORRECTION_TYPE,
    "app.Video.item": _NOT_A_CORRECTION_TYPE,
    "app.HardcoverEditionPreference.item": _NOT_A_CORRECTION_TYPE,
    "integrations.KomgaBookLink.item": _NOT_A_CORRECTION_TYPE,
    "integrations.KavitaLink.item": _NOT_A_CORRECTION_TYPE,
    "integrations.KoreaderDocumentLink.item": _NOT_A_CORRECTION_TYPE,
    "app.MetadataProviderPreference.item": (
        "Chooses whose metadata to show for that exact item; it does not "
        "describe the corrected title."
    ),
    "lists.ListActivity.item": "A log of past list edits: history, not state.",
    "integrations.ExternalReference.matched_item": (
        "Evidence of what the import matched; the correction is recorded in "
        "corrected_item."
    ),
    "integrations.PlexWatchlistSyncItem.item": _SYNC_BOOKKEEPING,
    "integrations.CollectionSourceState.item": _SYNC_BOOKKEEPING,
    "integrations.ProviderStateObservation.item": _SYNC_BOOKKEEPING,
    "integrations.StateConflict.item": _SYNC_BOOKKEEPING,
    "integrations.OutboundStateDelivery.item": _SYNC_BOOKKEEPING,
    "integrations.RatingSyncEdit.item": _SYNC_BOOKKEEPING,
    "integrations.PlexWatchedPush.item": (
        "A log of watched marks already sent to Plex: history, not state. The "
        "echo filter matches on machine_identifier and rating_key, not item."
    ),
    "users.User.notification_excluded_items": (
        "Known gap: a notification exclusion stays on the old item. Moving it "
        "changes correction behaviour, so it is left for its own change."
    ),
}


def _owns_user_data(model) -> bool:
    names = {field.name for field in model._meta.get_fields()}
    return model is get_user_model() or "user" in names or "owner" in names


def _user_relations() -> set[str]:
    """Every relation to Item whose rows belong to a user, directly or one hop away."""
    found = set()
    for relation in Item._meta.related_objects:
        model = relation.related_model
        via_owner = any(
            field.is_relation
            and field.related_model not in (None, Item)
            and _owns_user_data(field.related_model)
            for field in model._meta.concrete_fields
        )
        if _owns_user_data(model) or via_owner:
            found.add(f"{model._meta.label}.{relation.field.name}")
    return found


class MatchCorrectionRelationCoverageTests(SimpleTestCase):
    def test_every_user_relation_is_moved_or_explained(self):
        relations = _user_relations()
        unhandled = relations - set(MOVED) - set(NOT_MOVED_BECAUSE)
        self.assertFalse(
            unhandled,
            "Match corrections neither move nor explain these relations to "
            f"Item: {sorted(unhandled)}. Move them in "
            "integrations/match_corrections.py or name them here with a reason.",
        )
        stale = (set(MOVED) | set(NOT_MOVED_BECAUSE)) - relations
        self.assertFalse(stale, f"These relations no longer exist: {sorted(stale)}")
        self.assertFalse(set(MOVED) & set(NOT_MOVED_BECAUSE))

    def test_moved_relations_are_named_by_their_mover(self):
        for relation, (mover, name) in MOVED.items():
            with self.subTest(relation=relation):
                self.assertIn(name, inspect.getsource(mover))
