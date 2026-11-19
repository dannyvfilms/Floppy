"""Seed a throwaway Floppy database for scripts/pr_screenshots.py.

Runs inside ``manage.py shell`` on whichever branch is being captured. The
library is the shared sample library (``build_sample_library`` in
``src/app/tests/catalogue_fixtures.py``, the one the every-page test opens).
``pr_screenshots.py`` copies that file from the checkout running it into the
captured worktree as ``shots_library.py``, so the before and after captures
get the same data even when the captured commit predates the builder.
Prints one JSON object mapping a page name to its path; pages a branch lacks
are left out.
"""

# ruff: noqa: T201
import json

from django.contrib.auth import get_user_model
from django.urls import NoReverseMatch, reverse
from django.utils.text import slugify
from shots_library import build_sample_library

USERNAME = "shots"
PASSWORD = "shots-pass-12345"  # noqa: S105 - throwaway local database

user, _ = get_user_model().objects.get_or_create(username=USERNAME)
user.set_password(PASSWORD)
user.save()
library = build_sample_library(user)


def resolve(name, **kwargs):
    """Return the path for a route, or None when this branch lacks it."""
    try:
        return reverse(name, kwargs=kwargs)
    except NoReverseMatch:
        return None


band, album, first_track = library.artist, library.album, library.track
artist_kwargs = {"artist_id": band.id, "artist_slug": slugify(band.name)}
album_kwargs = {
    **artist_kwargs,
    "album_id": album.id,
    "album_slug": slugify(album.title),
}
paths = {
    "home": resolve("home"),
    "library": resolve("medialist", media_type="movie"),
    "history": resolve("history"),
    "podcast-list": resolve("list_detail", list_reference=library.podcast_list.pk),
    "every-type-list": resolve("list_detail", list_reference=library.custom_list.pk),
    "appearance": resolve("appearance"),
    "home-screen-settings": resolve("home_screen"),
    "tile-settings": resolve("tiles"),
    "music-artist": resolve("music_artist_details", **artist_kwargs),
    "music-album": resolve("music_album_details", **album_kwargs),
    "music-track": resolve(
        "music_track_details",
        **album_kwargs,
        track_id=first_track.id,
        track_slug=slugify(first_track.title),
    ),
}
print("SHOTS_PATHS=" + json.dumps({k: v for k, v in paths.items() if v}))
