"""Errors that carry a message written for the person."""

from django.test import SimpleTestCase

from app.collection_fields import (
    CollectionFieldNotFoundError,
    CollectionFieldValidationError,
)
from app.fork_services_history import HistoryDeletionError
from app.history_cache_utils import UnsupportedHistoryMediaTypeError
from app.local_covers import CoverError
from app.media_list_filters import MediaListFilterError
from app.models.tv import RewatchAlreadyCompleteError
from app.public_errors import PublicMessageError
from app.services.podcast_import import PodcastImportError
from config.server_port import ServerPortError
from integrations.imports.helpers import MediaImportError
from integrations.match_corrections import (
    InvalidMatchCorrectionError,
    MissingEpisodeMappingError,
    StaleCorrectionPreviewError,
)
from integrations.oauth_models import DeviceAuthorizationStateError
from integrations.seerr_api import SeerrError
from integrations.stremio_catalog import CatalogSkipError, parse_skip
from lists.tiers import TierError, clean_tiers


class PublicMessageErrorTests(SimpleTestCase):
    """``message`` is the text the error was raised with."""

    def test_message_is_the_first_argument(self):
        for error_class in (
            PublicMessageError,
            CollectionFieldNotFoundError,
            CollectionFieldValidationError,
            HistoryDeletionError,
            CoverError,
            RewatchAlreadyCompleteError,
            PodcastImportError,
            MediaImportError,
            InvalidMatchCorrectionError,
            MissingEpisodeMappingError,
            StaleCorrectionPreviewError,
            DeviceAuthorizationStateError,
            SeerrError,
            CatalogSkipError,
            TierError,
            ServerPortError,
        ):
            with self.subTest(error_class=error_class.__name__):
                error = error_class("Written for the person.")
                self.assertEqual(error.message, "Written for the person.")
                self.assertEqual(str(error), "Written for the person.")

    def test_errors_with_their_own_arguments_keep_the_message(self):
        filter_error = MediaListFilterError("sort", "Unknown sort.")
        self.assertEqual(filter_error.message, "Unknown sort.")
        self.assertEqual(str(filter_error), "Unknown sort.")
        history_error = UnsupportedHistoryMediaTypeError("vhs")
        self.assertEqual(history_error.message, "Unsupported history media type: vhs")
        self.assertEqual(str(history_error), history_error.message)

    def test_narrowed_errors_are_still_value_errors(self):
        with self.assertRaises(ValueError) as tiers:
            clean_tiers([])
        self.assertIsInstance(tiers.exception, TierError)
        with self.assertRaises(ValueError) as skip:
            parse_skip("genre=x")
        self.assertIsInstance(skip.exception, CatalogSkipError)
        self.assertEqual(skip.exception.message, "Only one skip argument is supported")
        for error_class in (
            UnsupportedHistoryMediaTypeError,
            HistoryDeletionError,
            DeviceAuthorizationStateError,
        ):
            self.assertTrue(issubclass(error_class, (ValueError, RuntimeError)))
