from django.db import models
from django.utils.translation import gettext_noop


class Sources(models.TextChoices):
    """Choices for the source of the item."""

    TMDB = "tmdb", "The Movie Database"
    TVDB = "tvdb", "TheTVDB"
    MAL = "mal", "MyAnimeList"
    MANGAUPDATES = "mangaupdates", "MangaUpdates"
    IGDB = "igdb", "Internet Game Database"
    IMDB = "imdb", "IMDb"
    OPENLIBRARY = "openlibrary", "Open Library"
    HARDCOVER = "hardcover", "Hardcover"
    GOOGLEBOOKS = "googlebooks", "Google Books"
    COMICVINE = "comicvine", "Comic Vine"
    BGG = "bgg", "BoardGameGeek"
    MUSICBRAINZ = "musicbrainz", "MusicBrainz"
    POCKETCASTS = "pocketcasts", "Pocket Casts"
    GPODDER = "gpodder", "GPodder"
    AUDIOBOOKSHELF = "audiobookshelf", "Audiobookshelf"
    STORYTELLER = "storyteller", "Storyteller"
    PLEX = "plex", "Plex"
    MANUAL = "manual", gettext_noop("Manual")


class MediaTypes(models.TextChoices):
    """Choices for the media type of the item."""

    TV = "tv", gettext_noop("TV Show")
    SEASON = "season", gettext_noop("TV Season")
    EPISODE = "episode", gettext_noop("Episode")
    MOVIE = "movie", gettext_noop("Movie")
    ANIME = "anime", gettext_noop("Anime")
    MANGA = "manga", gettext_noop("Manga")
    GAME = "game", gettext_noop("Game")
    BOOK = "book", gettext_noop("Book")
    COMIC = "comic", gettext_noop("Comic")
    COMIC_ISSUE = "comicissue", gettext_noop("Comic Issue")
    BOARDGAME = "boardgame", gettext_noop("Board Game")
    MUSIC = "music", gettext_noop("Music")
    PODCAST = "podcast", gettext_noop("Podcast")


class ProviderMetadataStatus(models.TextChoices):
    """Flags for provider metadata states that need UI handling."""

    LOCAL_ONLY_MISSING_SEASON = (
        "local_only_missing_season",
        gettext_noop("Local only: missing season metadata"),
    )


class Status(models.TextChoices):
    """Choices for item status."""

    COMPLETED = "Completed", gettext_noop("Completed")
    IN_PROGRESS = "In progress", gettext_noop("In Progress")
    PLANNING = "Planning", gettext_noop("Planning")
    PAUSED = "Paused", gettext_noop("Paused")
    DROPPED = "Dropped", gettext_noop("Dropped")
