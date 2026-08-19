# FORK: shared movie-tracking domain logic for the REST API's movie watch/
# unwatch endpoints (api.fork_views_tracking.MediaMovieWatchView).
import logging

from app.models import Item, MediaTypes, Movie, Status
from app.providers import services

logger = logging.getLogger(__name__)


def resolve_or_create_movie(user, media_id, source):
    """Return the user's tracked Movie row, creating it if it doesn't exist.

    Mirrors resolve_or_create_season's auto-create behavior: a missing
    movie is created In Progress with metadata-derived title/image.
    """
    movie = Movie.objects.filter(
        item__media_id=media_id,
        item__source=source,
        item__media_type=MediaTypes.MOVIE.value,
        user=user,
    ).first()
    if movie is not None:
        return movie

    metadata = services.get_media_metadata(MediaTypes.MOVIE.value, media_id, source)

    item, _ = Item.objects.get_or_create(
        media_id=media_id,
        source=source,
        media_type=MediaTypes.MOVIE.value,
        defaults={
            "image": metadata.get("image") or "",
            **Item.title_fields_from_metadata(metadata),
        },
    )

    movie = Movie.objects.create(
        item=item,
        user=user,
        score=None,
        status=Status.IN_PROGRESS.value,
        notes="",
    )
    logger.info("%s did not exist, it was created successfully.", movie)
    return movie
