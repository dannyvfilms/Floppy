from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import Item, MediaTypes, Movie, Sources, Status
from integrations.imports import helpers
from integrations.models import ImportRun
from integrations.tasks._media_imports import import_media


def _fake_trakt_importer(identifier, user, mode, username=None):
    """Stand in for a real importer: stages one Movie via bulk_create_media."""
    item = Item.objects.create(
        media_id="prov-movie",
        source=Sources.TMDB.value,
        media_type=MediaTypes.MOVIE.value,
        title="Provenance Movie",
    )
    movie = Movie(item=item, user=user, status=Status.COMPLETED.value)
    helpers.bulk_create_media({MediaTypes.MOVIE.value: [movie]}, user)
    return {MediaTypes.MOVIE.value: 1}, []


# Give the stub the same module identity import_media derives "source" from,
# without actually living in integrations.imports.trakt.
_fake_trakt_importer.__module__ = "integrations.imports.trakt"


def _fake_failing_importer(identifier, user, mode, username=None):
    msg = "boom"
    raise helpers.MediaImportError(msg)


class ImportRunProvenanceTests(TestCase):
    """Tests for ImportRun creation and row tagging in import_media()."""

    def setUp(self):
        """Set up a test user."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

    def test_import_media_creates_completed_run_and_tags_rows(self):
        """A successful import creates an ImportRun and tags the rows it made."""
        import_media(_fake_trakt_importer, None, self.user.id, "new")

        run = ImportRun.objects.get(user=self.user)
        self.assertEqual(run.source, "trakt")
        self.assertEqual(run.status, ImportRun.Status.COMPLETED)
        self.assertEqual(run.created_count, 1)
        self.assertIsNotNone(run.finished_at)

        movie = Movie.objects.get(user=self.user)
        self.assertEqual(movie.import_run_id, run.id)

    def test_import_media_marks_run_failed_on_exception(self):
        """A raised MediaImportError still finalizes the run as failed."""
        with self.assertRaises(helpers.MediaImportError):
            import_media(_fake_failing_importer, None, self.user.id, "new")

        run = ImportRun.objects.get(user=self.user)
        self.assertEqual(run.status, ImportRun.Status.FAILED)
        self.assertIsNotNone(run.finished_at)

    def test_bulk_create_media_leaves_import_run_null_outside_tracking(self):
        """Calling bulk_create_media directly (no import_media wrapper) tags nothing."""
        item = Item.objects.create(
            media_id="prov-movie-2",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Untracked Movie",
        )
        movie = Movie(item=item, user=self.user, status=Status.COMPLETED.value)
        helpers.bulk_create_media({MediaTypes.MOVIE.value: [movie]}, self.user)

        row = Movie.objects.get(item=item, user=self.user)
        self.assertIsNone(row.import_run_id)
