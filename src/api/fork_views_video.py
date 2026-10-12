"""Upsert a video play. The caller already applied the 45 second bar."""

import datetime
from http import HTTPStatus as HTTP  # noqa: N814
from urllib.parse import urlparse

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework.response import Response
from rest_framework.views import APIView

from app import history_cache
from app.helpers import has_real_image
from app.image_cache import is_approved_url
from app.models import Item, MediaTypes, Status, Video, VideoPlay

from .helpers import check_source_type

# Largest value a PositiveIntegerField column stores.
MAX_SECONDS = 2_147_483_647
MAX_EXTERNAL_ID_LENGTH = 255
MAX_THUMBNAIL_URL_LENGTH = 2048
MAX_DESCRIPTION_LENGTH = 5000


def _end_date_from_external_id(external_id):
    """Use the trailing YYYY-MM-DD on the external id, else now.

    @param external_id - `youtube:<videoId>:<day>`.
    @returns Aware datetime at noon UTC on that day, or now.
    """
    day = external_id.rsplit(":", 1)[-1]
    parsed = parse_date(day)
    if not parsed:
        return timezone.now()
    return timezone.make_aware(datetime.datetime.combine(parsed, datetime.time(12, 0)))


def _approved_thumbnail_url(data, media_id):
    """Return a thumbnail URL Floppy may store, or empty.

    Only https URLs on the artwork allowlist that point at this video are kept.
    Anything else is dropped, so this endpoint never fetches a caller-supplied
    URL and one video cannot be given another video's poster.

    @param data - Request body.
    @param media_id - YouTube video id from the request path.
    @returns Approved URL, or "".
    """
    raw = data.get("thumbnailUrl") or data.get("thumbnail_url") or ""
    url = str(raw).strip()
    if not url or len(url) > MAX_THUMBNAIL_URL_LENGTH:
        return ""
    # An http:// poster would be blocked as mixed content on an https install.
    if not url.lower().startswith("https://") or not is_approved_url(url):
        return ""
    # YouTube thumbnails live at /vi/<videoId>/<name>.jpg.
    parts = urlparse(url).path.strip("/").split("/")
    if len(parts) < 2 or parts[0] not in ("vi", "vi_webp") or parts[1] != media_id:  # noqa: PLR2004
        return ""
    return url


def _invalidate_history_for_other_viewers(item, user):
    """Refresh History for everyone else who watched this shared item.

    The poster lives on the shared item, so another user's cached days keep the
    placeholder until their cache expires. The caller's own days are refreshed
    by the play being saved.
    """
    days_by_user = {}
    plays = VideoPlay.objects.filter(video__item=item).exclude(video__user=user)
    for user_id, end_date in plays.values_list("video__user_id", "end_date"):
        days_by_user.setdefault(user_id, set()).add(
            history_cache.history_day_key(end_date)
        )
    for user_id, day_keys in days_by_user.items():
        history_cache.invalidate_history_days(
            user_id,
            day_keys=day_keys,
            logging_styles=("sessions", "repeats"),
            reason="video_poster_change",
        )


class VideoPlayView(APIView):
    """POST /api/v1/videos/<source>/<media_id>/plays/."""

    def post(self, request, source, media_id):
        """Create the video if needed and upsert the play by external id."""
        if not check_source_type(MediaTypes.VIDEO.value, source):
            return Response(
                {"detail": f"Cannot query `{source}` for video media type"},
                status=HTTP.BAD_REQUEST,
            )

        external_id = str(request.data.get("externalId") or request.data.get("external_id") or "").strip()
        title = str(request.data.get("title") or "").strip()
        if not external_id or not title:
            return Response(
                {"detail": "title and externalId are required"},
                status=HTTP.BAD_REQUEST,
            )
        if len(external_id) > MAX_EXTERNAL_ID_LENGTH:
            return Response(
                {"detail": "externalId is too long"},
                status=HTTP.BAD_REQUEST,
            )
        try:
            progress_seconds = int(request.data.get("progressSeconds") or request.data.get("progress_seconds") or 0)
            length_seconds = int(request.data.get("lengthSeconds") or request.data.get("length_seconds") or 0)
        except (TypeError, ValueError):
            return Response({"detail": "seconds must be integers"}, status=HTTP.BAD_REQUEST)
        # Negative seconds count as zero and huge ones as the column maximum,
        # so a bad value never reaches the database.
        progress_seconds = min(max(progress_seconds, 0), MAX_SECONDS)
        length_seconds = min(max(length_seconds, 0), MAX_SECONDS)

        # Cut to the column sizes so a long value is stored, not a 500.
        channel = str(request.data.get("channel") or "")[:255]
        watch_url = str(request.data.get("url") or "")[:500]

        # The item is shared by every user who tracks this video, so a later
        # post never renames it.
        item, _created = Item.objects.get_or_create(
            media_id=media_id,
            source=source,
            media_type=MediaTypes.VIDEO.value,
            library_media_type=MediaTypes.VIDEO.value,
            defaults={"title": title},
        )

        # History reads item.image. Set it once, from an allowlisted host,
        # and never replace a poster that is already there.
        thumbnail_url = _approved_thumbnail_url(request.data, media_id)
        if thumbnail_url and not has_real_image(item.image):
            item.image = thumbnail_url
            item.save(update_fields=["image"])
            _invalidate_history_for_other_viewers(item, request.user)

        # The description shows on the details page. It is set once, like the
        # poster, because the item is shared.
        description = str(request.data.get("description") or "").strip()
        if description and not item.synopsis:
            item.synopsis = description[:MAX_DESCRIPTION_LENGTH]
            item.save(update_fields=["synopsis"])

        # The upload date puts the video on the Calendar. It is set once, so a
        # later report never moves the event.
        published_at = parse_datetime(
            str(request.data.get("publishedAt") or request.data.get("published_at") or ""),
        )
        if published_at and not item.release_datetime:
            if timezone.is_naive(published_at):
                published_at = timezone.make_aware(published_at)
            item.release_datetime = published_at
            # Due again on the next Calendar reload, so the event appears.
            item.calendar_checked_at = None
            item.save(update_fields=["release_datetime", "calendar_checked_at"])

        video, _video_created = Video.objects.get_or_create(
            item=item,
            user=request.user,
            defaults={
                # The model defaults to Completed, which would fill the
                # progress bar on creation. The first report decides.
                "status": Status.IN_PROGRESS.value,
                "channel": channel,
                "watch_url": watch_url,
                "length_seconds": length_seconds,
            },
        )
        video.channel = channel or video.channel
        video.watch_url = watch_url or video.watch_url
        if length_seconds:
            video.length_seconds = length_seconds

        play, created = video.upsert_play(
            external_id,
            progress_seconds,
            end_date=_end_date_from_external_id(external_id),
        )
        return Response(
            {"status": video.status, "external_id": play.external_id},
            status=HTTP.CREATED if created else HTTP.OK,
        )
