"""Media type groups used by the settings page filters.

Import Data, Integrations and Metadata all filter their cards by the same
handful of groups, so the keys and labels live here once.
"""

from django.utils.translation import gettext_noop

from app.models import MediaTypes

SCREEN = "screen"
ANIME_MANGA = "anime_manga"
READING = "reading"
GAMES = "games"
PODCASTS = "podcasts"
MUSIC = "music"
BACKUP = "backup"

MEDIA_TAGS = (
    (SCREEN, gettext_noop("Movies & TV")),
    (ANIME_MANGA, gettext_noop("Anime & Manga")),
    (READING, gettext_noop("Books & Comics")),
    (GAMES, gettext_noop("Games")),
    (PODCASTS, gettext_noop("Podcasts")),
    (MUSIC, gettext_noop("Music")),
    (BACKUP, gettext_noop("Backups")),
)

MEDIA_TAG_KEYS = frozenset(key for key, _label in MEDIA_TAGS)

# Which filter group each media type falls under.
MEDIA_TYPE_TAGS = {
    MediaTypes.TV.value: SCREEN,
    MediaTypes.SEASON.value: SCREEN,
    MediaTypes.EPISODE.value: SCREEN,
    MediaTypes.MOVIE.value: SCREEN,
    MediaTypes.VIDEO.value: SCREEN,
    MediaTypes.ANIME.value: ANIME_MANGA,
    MediaTypes.MANGA.value: ANIME_MANGA,
    MediaTypes.BOOK.value: READING,
    MediaTypes.COMIC.value: READING,
    MediaTypes.COMIC_ISSUE.value: READING,
    MediaTypes.GAME.value: GAMES,
    MediaTypes.BOARDGAME.value: GAMES,
    MediaTypes.PODCAST.value: PODCASTS,
    MediaTypes.MUSIC.value: MUSIC,
}


def media_tag_for_type(media_type):
    """Return the filter group for a media type, or "" when it has none."""
    return MEDIA_TYPE_TAGS.get(media_type, "")
