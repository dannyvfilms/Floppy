from decimal import Decimal
from uuid import UUID

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase

from app.forms import (
    AnimeForm,
    BookForm,
    ComicForm,
    EpisodeForm,
    GameForm,
    MangaForm,
    ManualItemForm,
    SeasonForm,
    TvForm,
)
from app.models import (
    TV,
    Anime,
    Book,
    Comic,
    Episode,
    Item,
    Manga,
    MediaTypes,
    Season,
    Sources,
    Status,
)


class BasicMediaForm(TestCase):
    """Test the standard media form."""

    def setUp(self):
        """Create a user."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

        Item.objects.create(
            media_id="1",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Test Anime",
            image="http://example.com/image.jpg",
        )

        Item.objects.create(
            media_id="1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Test tv",
            image="http://example.com/image.jpg",
        )

    def test_valid_media_form(self):
        """Test the standard media form with valid data."""
        form_data = {
            "media_id": "1",
            "source": Sources.MAL.value,
            "media_type": MediaTypes.ANIME.value,
            "user": self.user.id,
            "score": 7.5,
            "progress": 25,
            "status": Status.PAUSED.value,
            "repeats": 0,
            "start_date": "2023-02-01",
            "end_date": "2023-06-30",
            "notes": "New notes",
        }
        form = AnimeForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_valid_tv_form(self):
        """Test the TV form with valid data."""
        form_data = {
            "media_id": "1",
            "source": Sources.TMDB.value,
            "media_type": MediaTypes.TV.value,
            "user": self.user.id,
            "score": 7.5,
            "status": Status.COMPLETED.value,
            "repeats": 0,
            "notes": "New notes",
        }
        form = TvForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_valid_season_form(self):
        """Test the season form with valid data."""
        form_data = {
            "media_id": "1",
            "source": Sources.TMDB.value,
            "media_type": MediaTypes.SEASON.value,
            "user": self.user.id,
            "score": 7.5,
            "status": Status.COMPLETED.value,
            "repeats": 0,
            "season_number": 1,
            "notes": "New notes",
        }
        form = SeasonForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_valid_episode_form(self):
        """Test the episode form with valid data."""
        form_data = {
            "end_date": "2023-06-01",
        }
        form = EpisodeForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_media_form_saves_entry_source(self):
        """entry_source (how the entry was created) round-trips through the form."""
        form_data = {
            "media_id": "1",
            "source": Sources.MAL.value,
            "media_type": MediaTypes.ANIME.value,
            "user": self.user.id,
            "status": Status.PAUSED.value,
            "progress": 0,
            "entry_source": "Theatre",
        }
        form = AnimeForm(data=form_data, user=self.user)
        self.assertTrue(form.is_valid(), form.errors)
        media = form.save(commit=False)
        self.assertEqual(media.entry_source, "Theatre")

    def test_episode_form_saves_entry_source(self):
        """Episode's own edit form also accepts entry_source."""
        form_data = {
            "end_date": "2023-06-01",
            "entry_source": "jellyfin",
        }
        form = EpisodeForm(data=form_data)
        self.assertTrue(form.is_valid(), form.errors)
        episode = form.save(commit=False)
        self.assertEqual(episode.entry_source, "jellyfin")

    def test_valid_episode_datetime_form(self):
        """Test the episode form with valid data."""
        form_data = {
            "end_date": "2023-06-01T12:00:00Z",
        }
        form = EpisodeForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_episode_create_form_generates_and_preserves_watch_operation_id(self):
        """A rendered create form keeps its UUID when the bound form is retried."""
        first_form = EpisodeForm()
        watch_operation_id = first_form["watch_operation_id"].value()

        self.assertEqual(str(UUID(str(watch_operation_id))), str(watch_operation_id))
        bound_form = EpisodeForm(
            data={
                "end_date": "2023-06-01",
                "watch_operation_id": watch_operation_id,
            },
        )
        self.assertTrue(bound_form.is_valid())
        self.assertEqual(
            str(bound_form.cleaned_data["watch_operation_id"]),
            str(watch_operation_id),
        )
        self.assertNotEqual(
            EpisodeForm()["watch_operation_id"].value(),
            watch_operation_id,
        )

    def test_episode_edit_form_does_not_claim_new_watch_operation_id(self):
        """Existing Episode updates remain row-addressed."""
        form = EpisodeForm(instance=Episode(id=123))

        self.assertIsNone(form["watch_operation_id"].value())

    def test_episode_form_rejects_malformed_watch_operation_id_without_echo(self):
        """Malformed replay identity is a field error and does not echo its value."""
        malformed = "not-a-private-token"
        form = EpisodeForm(
            data={"end_date": "2023-06-01", "watch_operation_id": malformed},
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors.as_data()["watch_operation_id"][0].code, "invalid")
        self.assertNotIn(malformed, form.errors.as_text())


class RatingsDisabledFormTest(TestCase):
    """With ratings disabled the track form has no score field and keeps the score."""

    def setUp(self):
        """Create a user who turned ratings off and an anime they rated 7.5."""
        self.user = get_user_model().objects.create_user(
            username="no-ratings",
            password="12345",
            rating_scale="0",
        )
        item = Item.objects.create(
            media_id="1",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Test Anime",
            image="http://example.com/image.jpg",
        )
        self.anime = Anime.objects.create(
            item=item,
            user=self.user,
            status=Status.PAUSED.value,
            progress=3,
            score=7.5,
        )

    def test_score_field_is_removed_only_when_disabled(self):
        """The score input exists on the 10-point scale and is gone when disabled."""
        self.assertNotIn("score", AnimeForm(user=self.user, instance=self.anime).fields)
        self.user.rating_scale = "10"
        self.assertIn("score", AnimeForm(user=self.user, instance=self.anime).fields)

    def test_saving_does_not_touch_stored_score(self):
        """A submitted score is ignored and the stored one survives the save."""
        form = AnimeForm(
            data={
                "media_id": "1",
                "source": Sources.MAL.value,
                "media_type": MediaTypes.ANIME.value,
                "user": self.user.id,
                "score": 2,
                "progress": 5,
                "status": Status.COMPLETED.value,
            },
            instance=self.anime,
            user=self.user,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.anime.refresh_from_db()
        self.assertEqual(self.anime.progress, 5)
        self.assertEqual(self.anime.score, Decimal("7.5"))


class BasicGameForm(TestCase):
    """Test the game form."""

    def setUp(self):
        """Create a user."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.item = Item.objects.create(
            media_id="1",
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title="Test Game",
            image="http://example.com/image.jpg",
        )

    def test_default_progress(self):
        """Test the game form using the default progress format."""
        form_data = {
            "media_id": "1",
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "user": self.user.id,
            "status": Status.COMPLETED.value,
            "progress": "25:00",
            "repeats": 0,
        }
        form = GameForm(data=form_data)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["progress"], 1500)

    def test_plain_number_progress(self):
        """Test the game form with a plain number for hours (e.g., '5')."""
        form_data = {
            "media_id": "1",
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "user": self.user.id,
            "status": Status.COMPLETED.value,
            "progress": "5",
            "repeats": 0,
        }
        form = GameForm(data=form_data)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["progress"], 300)

    def test_alternate_progress(self):
        """Test the game form using an alternate progress format."""
        form_data = {
            "media_id": "1",
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "user": self.user.id,
            "status": Status.COMPLETED.value,
            "progress": "25h 00min",
            "repeats": 0,
        }
        form = GameForm(data=form_data)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["progress"], 1500)

    def test_second_alternate_progress(self):
        """Test the game form using a second alternate progress format."""
        form_data = {
            "media_id": "1",
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "user": self.user.id,
            "status": Status.COMPLETED.value,
            "progress": "30min",
            "repeats": 0,
        }
        form = GameForm(data=form_data)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["progress"], 30)

    def test_third_alternate_progress(self):
        """Test the game form using a second alternate progress format."""
        form_data = {
            "media_id": "1",
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "user": self.user.id,
            "status": Status.COMPLETED.value,
            "progress": "9h",
            "repeats": 0,
        }
        form = GameForm(data=form_data)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["progress"], 540)

    def test_fourth_alternate_progress(self):
        """Test the game form using a second alternate progress format."""
        form_data = {
            "media_id": "1",
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "user": self.user.id,
            "status": Status.COMPLETED.value,
            "progress": "9h30min",
            "repeats": 0,
        }
        form = GameForm(data=form_data)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["progress"], 570)

    def test_float_progress(self):
        """Test the game form with float progress format (e.g., 1.5 hours)."""
        form_data = {
            "media_id": "1",
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "user": self.user.id,
            "status": Status.COMPLETED.value,
            "progress": "1.5",
            "repeats": 0,
        }
        form = GameForm(data=form_data)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["progress"], 90)

    def test_float_progress_half_hour(self):
        """Test the game form with 0.5 float progress (30 minutes)."""
        form_data = {
            "media_id": "1",
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "user": self.user.id,
            "status": Status.COMPLETED.value,
            "progress": "0.5",
            "repeats": 0,
        }
        form = GameForm(data=form_data)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["progress"], 30)

    def test_invalid_negative_float_progress(self):
        """Test that negative float progress is rejected."""
        form_data = {
            "media_id": "1",
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "user": self.user.id,
            "status": Status.COMPLETED.value,
            "progress": "-1.5",
            "repeats": 0,
        }
        form = GameForm(data=form_data)
        self.assertFalse(form.is_valid())

    def test_invalid_inf_progress(self):
        """Test that infinity progress is rejected."""
        form_data = {
            "media_id": "1",
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "user": self.user.id,
            "status": Status.COMPLETED.value,
            "progress": "inf",
            "repeats": 0,
        }
        form = GameForm(data=form_data)
        self.assertFalse(form.is_valid())

    def test_invalid_nan_progress(self):
        """Test that NaN progress is rejected."""
        form_data = {
            "media_id": "1",
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "user": self.user.id,
            "status": Status.COMPLETED.value,
            "progress": "nan",
            "repeats": 0,
        }
        form = GameForm(data=form_data)
        self.assertFalse(form.is_valid())

    def test_word_minutes_progress(self):
        """Test the game form using a Steam-style minutes string."""
        form_data = {
            "media_id": "1",
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "user": self.user.id,
            "status": Status.COMPLETED.value,
            "progress": "111 minutes",
            "repeats": 0,
        }
        form = GameForm(data=form_data)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["progress"], 111)

    def test_decimal_hours_progress(self):
        """Test the game form using a Steam-style decimal hours string."""
        form_data = {
            "media_id": "1",
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "user": self.user.id,
            "status": Status.COMPLETED.value,
            "progress": "4.3 hours",
            "repeats": 0,
        }
        form = GameForm(data=form_data)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["progress"], 258)

    def test_invalid_progress(self):
        """Test the game form using an invalid default progress format."""
        form_data = {
            "media_id": "1",
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "user": self.user.id,
            "status": Status.COMPLETED.value,
            "progress": "25:00m",
            "repeats": 0,
        }
        form = GameForm(data=form_data)
        self.assertFalse(form.is_valid())

    def test_invalid_minutes(self):
        """Test the game form using an invalid default progress format."""
        form_data = {
            "media_id": "1",
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "user": self.user.id,
            "status": Status.COMPLETED.value,
            "progress": "25h61m",
            "repeats": 0,
        }
        form = GameForm(data=form_data)
        self.assertFalse(form.is_valid())


class ManualItemFormTest(TestCase):
    """Test the manual item form functionality."""

    def setUp(self):
        """Create a user and necessary parent items."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

        # Create a manual TV show
        self.tv_item = Item.objects.create(
            media_id="manual_tv_1",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.TV.value,
            title="Test Manual TV",
            image="http://example.com/tv.jpg",
        )
        self.tv = TV.objects.create(
            item=self.tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

        # Create a manual Season
        self.season_item = Item.objects.create(
            media_id="manual_tv_1",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.SEASON.value,
            title="Test Manual TV",
            season_number=1,
            image="http://example.com/season.jpg",
        )
        self.season = Season.objects.create(
            item=self.season_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

    def test_init_with_user(self):
        """Test form initialization with user parameter."""
        form = ManualItemForm(user=self.user)
        self.assertEqual(form.fields["parent_tv"].queryset.count(), 1)
        self.assertEqual(form.fields["parent_season"].queryset.count(), 1)

    def test_init_without_user(self):
        """Test form initialization without user parameter."""
        form = ManualItemForm()
        self.assertEqual(form.fields["parent_tv"].queryset.count(), 0)
        self.assertEqual(form.fields["parent_season"].queryset.count(), 0)

    def test_valid_standalone_media(self):
        """Test creating a standalone media item (movie, anime, etc.)."""
        form_data = {
            "media_type": MediaTypes.MOVIE.value,
            "title": "Test Manual Movie",
            "image": "http://example.com/movie.jpg",
        }
        form = ManualItemForm(data=form_data, user=self.user)
        self.assertTrue(form.is_valid())

        # Save and verify
        item = form.save()
        self.assertEqual(item.source, Sources.MANUAL.value)
        self.assertTrue(item.media_id)
        self.assertIsNone(item.season_number)
        self.assertIsNone(item.episode_number)

    def test_valid_season_creation(self):
        """Test creating a season for an existing TV show."""
        form_data = {
            "media_type": MediaTypes.SEASON.value,
            "parent_tv": self.tv.id,
            "season_number": 2,
        }
        form = ManualItemForm(data=form_data, user=self.user)
        self.assertTrue(form.is_valid())

        # Save and verify
        item = form.save()
        self.assertEqual(item.source, Sources.MANUAL.value)
        self.assertEqual(item.media_id, self.tv_item.media_id)
        self.assertEqual(item.title, self.tv_item.title)
        self.assertEqual(item.season_number, 2)
        self.assertIsNone(item.episode_number)

    def test_valid_episode_creation(self):
        """Test creating an episode for an existing season."""
        form_data = {
            "media_type": MediaTypes.EPISODE.value,
            "parent_season": self.season.id,
            "episode_number": 5,
        }
        form = ManualItemForm(data=form_data, user=self.user)
        self.assertTrue(form.is_valid())

        # Save and verify
        item = form.save()
        self.assertEqual(item.source, Sources.MANUAL.value)
        self.assertEqual(item.media_id, self.season_item.media_id)
        self.assertEqual(item.title, self.season_item.title)
        self.assertEqual(item.season_number, self.season_item.season_number)
        self.assertEqual(item.episode_number, 5)

    def test_missing_title_for_standalone(self):
        """Test that title is required for standalone."""
        form_data = {
            "media_type": MediaTypes.MOVIE.value,
        }
        form = ManualItemForm(data=form_data, user=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn("title", form.errors)

    def test_missing_parent_for_season(self):
        """Test that parent TV is required for seasons."""
        form_data = {
            "media_type": MediaTypes.SEASON.value,
            "season_number": 3,
        }
        form = ManualItemForm(data=form_data, user=self.user)
        self.assertFalse(form.is_valid())

    def test_missing_parent_for_episode(self):
        """Test that parent season is required for episodes."""
        form_data = {
            "media_type": MediaTypes.EPISODE.value,
            "episode_number": 2,
        }
        form = ManualItemForm(data=form_data, user=self.user)
        self.assertFalse(form.is_valid())

    def test_default_image(self):
        """Test that default image is used when none provided."""
        form_data = {
            "media_type": MediaTypes.BOOK.value,
            "title": "Test Manual Book",
        }
        form = ManualItemForm(data=form_data, user=self.user)
        self.assertTrue(form.is_valid())

        # Save and verify
        item = form.save()
        self.assertEqual(item.image, settings.IMG_NONE)

    def test_manual_id_generation(self):
        """Test that unique manual IDs are generated."""
        # Create first item
        form1 = ManualItemForm(
            data={"media_type": MediaTypes.ANIME.value, "title": "Test Anime 1"},
            user=self.user,
        )
        self.assertTrue(form1.is_valid())
        item1 = form1.save()

        # Create second item
        form2 = ManualItemForm(
            data={"media_type": MediaTypes.ANIME.value, "title": "Test Anime 2"},
            user=self.user,
        )
        self.assertTrue(form2.is_valid())
        item2 = form2.save()

        # IDs should be different
        self.assertNotEqual(item1.media_id, item2.media_id)
        self.assertTrue(item1.media_id)
        self.assertTrue(item2.media_id)


class ReadingTimeFormTest(TestCase):
    """Books, comics and manga take a reading time; audiobooks do not."""

    def setUp(self):
        """Create a user and one item per reading type."""
        self.user = get_user_model().objects.create_user(
            username="reader",
            password="12345",
        )
        self.items = {
            MediaTypes.BOOK.value: Item.objects.create(
                media_id="1",
                source=Sources.OPENLIBRARY.value,
                media_type=MediaTypes.BOOK.value,
                title="Dune",
            ),
            MediaTypes.COMIC.value: Item.objects.create(
                media_id="2",
                source=Sources.COMICVINE.value,
                media_type=MediaTypes.COMIC.value,
                title="Saga",
            ),
            MediaTypes.MANGA.value: Item.objects.create(
                media_id="3",
                source=Sources.MAL.value,
                media_type=MediaTypes.MANGA.value,
                title="Berserk",
            ),
        }

    def data(self, media_type, **extra):
        item = self.items[media_type]
        return {
            "media_id": item.media_id,
            "source": item.source,
            "media_type": media_type,
            "status": Status.COMPLETED.value,
            "progress": 10,
            **extra,
        }

    def test_each_reading_type_parses_the_time(self):
        for media_type, form_class, model in (
            (MediaTypes.BOOK.value, BookForm, Book),
            (MediaTypes.COMIC.value, ComicForm, Comic),
            (MediaTypes.MANGA.value, MangaForm, Manga),
        ):
            with self.subTest(media_type):
                instance = model(item=self.items[media_type], user=self.user)
                form = form_class(
                    self.data(media_type, reading_time="1h 30min"),
                    instance=instance,
                )
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.save().reading_time, 90)

    def test_blank_time_is_zero(self):
        instance = Book(item=self.items[MediaTypes.BOOK.value], user=self.user)
        form = BookForm(self.data(MediaTypes.BOOK.value), instance=instance)

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().reading_time, 0)

    def test_bad_time_is_rejected(self):
        instance = Book(item=self.items[MediaTypes.BOOK.value], user=self.user)
        form = BookForm(
            self.data(MediaTypes.BOOK.value, reading_time="soon"),
            instance=instance,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("reading_time", form.errors)

    def test_saved_time_is_shown_as_hours_and_minutes_not_raw_minutes(self):
        book = Book.objects.create(
            item=self.items[MediaTypes.BOOK.value],
            user=self.user,
            reading_time=125,
        )

        form = BookForm(instance=book)

        self.assertEqual(form.initial["reading_time"], "2h 05min")
        # Saving the untouched form must not turn 125 minutes into 125 hours.
        resubmit = BookForm(
            self.data(
                MediaTypes.BOOK.value,
                reading_time=form.initial["reading_time"],
            ),
            instance=book,
        )
        self.assertTrue(resubmit.is_valid(), resubmit.errors)
        self.assertEqual(resubmit.save().reading_time, 125)

    def test_an_audiobook_has_no_reading_time_field(self):
        item = self.items[MediaTypes.BOOK.value]
        item.format = "audiobook"
        item.save()

        form = BookForm(instance=Book(item=item, user=self.user))

        self.assertNotIn("reading_time", form.fields)
