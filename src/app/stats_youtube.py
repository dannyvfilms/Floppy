"""YouTube watch time from VideoPlay.progress, in minutes.

Kept out of stats_video.py, which already means TV and movie runtime.
"""

from django.utils import timezone

from app.models import VideoPlay


def youtube_thumbnail_url(media_id):
    """Return the YouTube poster for a video id.

    @param media_id - YouTube video id.
    @returns mqdefault URL, or "" when there is no id.
    """
    if not media_id:
        return ""
    return f"https://img.youtube.com/vi/{media_id}/mqdefault.jpg"


def iter_video_play_minutes(user, start_date, end_date):
    """Yield one (local date, minutes) pair per play in range.

    Minutes are progress seconds floored to whole minutes. A play under
    60 seconds contributes 0 and is skipped.

    @param user - Owner of the videos.
    @param start_date - Inclusive range start, or None for all time.
    @param end_date - Inclusive range end, or None for all time.
    """
    if user is None:
        return
    plays = VideoPlay.objects.filter(video__user=user, progress__gt=0)
    if start_date is not None and end_date is not None:
        plays = plays.filter(end_date__gte=start_date, end_date__lte=end_date)
    for end_date_value, progress in plays.values_list("end_date", "progress"):
        if not end_date_value:
            continue
        minutes = int(progress) // 60
        if minutes <= 0:
            continue
        yield timezone.localtime(end_date_value).date(), minutes


def video_minutes_total(user, start_date, end_date):
    """Return watched minutes for this user's video plays in range.

    @param user - Owner of the videos.
    @param start_date - Inclusive range start, or None for all time.
    @param end_date - Inclusive range end, or None for all time.
    """
    return sum(
        minutes for _, minutes in iter_video_play_minutes(user, start_date, end_date)
    )
