from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase
from django.urls import reverse

from app.entry_sources import entry_source_suggestions
from app.models import (
    Episode,
    Game,
    Item,
    MediaTypes,
    Movie,
    MoviePlay,
    Season,
    Sources,
    Status,
)
from app.templatetags.app_tags import entry_source_label
from integrations.imports.helpers import stamp_entry_source
from integrations.models import ImportRun


def make_item(media_id, media_type=MediaTypes.GAME.value, **extra):
    return Item.objects.create(
        media_id=media_id,
        source=Sources.MANUAL.value,
        media_type=media_type,
        title=f"Title {media_id}",
        image="none",
        **extra,
    )


class EntrySourceSuggestionsTests(TestCase):
    """The Source field offers values the user has recorded before."""

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="a", password="x")
        self.other = user_model.objects.create_user(username="b", password="x")

    def game(self, media_id, source, user=None):
        return Game.objects.create(
            user=user or self.user,
            item=make_item(media_id),
            status=Status.COMPLETED.value,
            entry_source=source,
        )

    def test_empty_when_nothing_recorded(self):
        self.game("1", "")
        self.assertEqual(entry_source_suggestions(self.user), [])

    def test_anonymous_user_gets_nothing(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertEqual(entry_source_suggestions(AnonymousUser()), [])

    def test_most_used_first_and_no_duplicates(self):
        self.game("1", "Theatre")
        self.game("2", "plex")
        self.game("3", "plex")
        self.game("4", "plex")
        self.assertEqual(entry_source_suggestions(self.user), ["plex", "Theatre"])

    def test_case_variants_count_once_with_the_most_used_spelling(self):
        self.game("1", "Plex")
        self.game("2", "plex")
        self.game("3", "plex")
        self.assertEqual(entry_source_suggestions(self.user), ["plex"])

    def test_only_the_users_own_values(self):
        self.game("1", "Theatre")
        self.game("2", "Kodi", user=self.other)
        self.assertEqual(entry_source_suggestions(self.user), ["Theatre"])

    def test_values_come_from_every_kind_of_entry(self):
        movie = Movie.objects.create(
            user=self.user,
            item=make_item("m", MediaTypes.MOVIE.value),
            status=Status.COMPLETED.value,
        )
        MoviePlay.objects.create(movie=movie, entry_source="Cinema")
        tv_item = make_item("t", MediaTypes.SEASON.value, season_number=1)
        season = Season.objects.create(
            user=self.user,
            item=tv_item,
            status=Status.IN_PROGRESS.value,
        )
        Episode.objects.create(
            related_season=season,
            item=make_item(
                "t",
                MediaTypes.EPISODE.value,
                season_number=1,
                episode_number=1,
            ),
            entry_source="Airplane",
        )
        self.game("1", "Steam")
        self.assertEqual(
            sorted(entry_source_suggestions(self.user)),
            ["Airplane", "Cinema", "Steam"],
        )

    def test_modal_offers_the_values_and_keeps_the_field_blank(self):
        self.game("1", "Theatre")
        make_item("2")
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "track_modal",
                kwargs={
                    "source": Sources.MANUAL.value,
                    "media_type": MediaTypes.GAME.value,
                    "media_id": "2",
                },
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<datalist id="entry-source-suggestions">')
        self.assertContains(response, '<option value="Theatre">', html=False)
        self.assertContains(response, 'list="entry-source-suggestions"', html=False)
        self.assertNotContains(response, 'name="entry_source" value=')


class StampEntrySourceTests(TestCase):
    """Syncs record their own name only where nothing is recorded."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="a", password="x")

    def game(self, source):
        return Game.objects.create(
            user=self.user,
            item=make_item("1"),
            status=Status.COMPLETED.value,
            entry_source=source,
        )

    def test_fills_a_blank_source(self):
        game = stamp_entry_source(self.game(""), "koreader")
        game.refresh_from_db()
        self.assertEqual(game.entry_source, "koreader")

    def test_never_replaces_a_value(self):
        game = stamp_entry_source(self.game("Theatre"), "koreader")
        game.refresh_from_db()
        self.assertEqual(game.entry_source, "Theatre")

    def test_labels_for_the_new_sources(self):
        self.assertEqual(entry_source_label("audiobookshelf"), "Audiobookshelf")
        self.assertEqual(entry_source_label("gpodder"), "gPodder")
        self.assertEqual(entry_source_label("koreader"), "KOReader")
        self.assertEqual(entry_source_label("youtube"), "YouTube")
        self.assertEqual(entry_source_label("storyteller"), "Storyteller")


class BackfillEntrySourceMigrationTests(TestCase):
    """The migration names the importer on blank entries it wrote."""

    def test_fills_only_blank_entries_with_a_known_run(self):
        from importlib import import_module

        migration = import_module(
            "app.migrations.0216_backfill_entry_source_from_import_run",
        )
        user = get_user_model().objects.create_user(username="a", password="x")
        run = ImportRun.objects.create(user=user, source="trakt")

        def game(media_id, source, import_run):
            return Game.objects.create(
                user=user,
                item=make_item(media_id),
                status=Status.COMPLETED.value,
                entry_source=source,
                import_run=import_run,
            )

        blank_from_run = game("1", "", run)
        typed = game("2", "Theatre", run)
        blank_manual = game("3", "", None)

        executor = MigrationExecutor(connection)
        apps = executor.loader.project_state(
            [("app", "0216_backfill_entry_source_from_import_run")],
        ).apps
        migration.fill_blank_entry_sources(apps, None)

        for obj in (blank_from_run, typed, blank_manual):
            obj.refresh_from_db()
        self.assertEqual(blank_from_run.entry_source, "trakt")
        self.assertEqual(typed.entry_source, "Theatre")
        self.assertEqual(blank_manual.entry_source, "")
