import io
import json
import zipfile
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from app.models import Item, MediaTypes, Sources, Status, Video, VideoPlay
from integrations import import_progress
from integrations.imports import youtube_takeout
from integrations.imports.helpers import MediaImportError


def watch(video_id, time, title="Watched A Video", channel="A Channel", **extra):
    """Build one Takeout watch record."""
    record = {
        "header": "YouTube",
        "title": title,
        "titleUrl": f"https://www.youtube.com/watch?v={video_id}",
        "subtitles": [{"name": channel, "url": "https://www.youtube.com/channel/x"}],
        "time": time,
        "products": ["YouTube"],
    }
    record.update(extra)
    return record


def as_file(records):
    """Return an upload-like file holding the records as JSON."""
    return BytesIO(json.dumps(records).encode())


class YouTubeTakeoutParsingTests(TestCase):
    """Pure parsing rules."""

    def test_youtube_task_is_tracked_in_import_activity(self):
        from app.signals import _is_tracked_task
        from integrations import tasks

        self.assertTrue(_is_tracked_task(tasks.import_youtube_takeout.name))

    def test_video_id_from_the_url_shapes_takeout_uses(self):
        """Watch, shorts and youtu.be URLs give the id. Posts and junk give none."""
        self.assertEqual(
            youtube_takeout.video_id_from_url(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
            ),
            "dQw4w9WgXcQ",
        )
        self.assertEqual(
            youtube_takeout.video_id_from_url(
                "https://www.youtube.com/shorts/dQw4w9WgXcQ"
            ),
            "dQw4w9WgXcQ",
        )
        self.assertEqual(
            youtube_takeout.video_id_from_url("https://youtu.be/dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )
        self.assertEqual(
            youtube_takeout.video_id_from_url("https://www.youtube.com/post/Ugkx123"),
            "",
        )
        self.assertEqual(
            youtube_takeout.video_id_from_url(
                "https://example.com/watch?v=dQw4w9WgXcQ"
            ),
            "",
        )
        self.assertEqual(youtube_takeout.video_id_from_url(None), "")

    def test_non_watches_are_left_out(self):
        """Music, ads, removed videos and posts are not watches."""
        good = watch("dQw4w9WgXcQ", "2026-03-01T18:00:00.000Z")
        self.assertIsNotNone(youtube_takeout.entry_from_record(good))
        music = {**good, "header": "YouTube Music"}
        ad = {**good, "details": [{"name": "From Google Ads"}]}
        removed = {
            "header": "YouTube",
            "title": "Watched a video that has been removed",
            "time": good["time"],
        }
        bad_time = {**good, "time": "soon"}
        for record in (music, ad, removed, bad_time, "text", None):
            self.assertIsNone(youtube_takeout.entry_from_record(record))

    def test_title_loses_the_watched_prefix(self):
        """Takeout writes 'Watched ' before every English title."""
        entry = youtube_takeout.entry_from_record(
            watch("dQw4w9WgXcQ", "2026-03-01T18:00:00Z", title="Watched Rick Roll"),
        )
        self.assertEqual(entry["title"], "Rick Roll")
        self.assertEqual(entry["channel"], "A Channel")


class YouTubeTakeoutImportTests(TestCase):
    """Importing writes videos and one play per video and day."""

    def setUp(self):
        """Create the user."""
        self.user = get_user_model().objects.create_user(username="t", password="x")

    def run_import(self, records):
        """Import the records for the user."""
        return youtube_takeout.importer(as_file(records), self.user, "new")

    def test_reports_reading_before_loading_history(self):
        def load(_file):
            progress = import_progress.get_progress("youtube-task")
            self.assertEqual(progress["current"], 0)
            self.assertIsNone(progress["total"])
            self.assertEqual(progress["label"], "Reading YouTube history")
            return []

        with import_progress.tracking("youtube-task"), patch.object(
            youtube_takeout, "load_records", side_effect=load
        ):
            self.run_import([])

    def test_creates_completed_videos_and_plays(self):
        """Each video is Completed with a channel, URL and poster, one play per day."""
        counts, report = self.run_import(
            [
                watch("vidAAAAAAAA", "2026-03-02T10:00:00Z", title="Watched B"),
                watch("vidAAAAAAAA", "2026-03-01T10:00:00Z", title="Watched B"),
                watch("vidBBBBBBBB", "2026-03-01T09:00:00Z", title="Watched C"),
                {
                    "header": "YouTube Music",
                    "title": "Watched Song",
                    "time": "2026-03-01T09:00:00Z",
                },
            ],
        )
        self.assertEqual(counts["created"], 2)
        self.assertEqual(Video.objects.filter(user=self.user).count(), 2)
        self.assertEqual(VideoPlay.objects.count(), 3)
        video = Video.objects.get(item__media_id="vidAAAAAAAA")
        self.assertEqual(video.status, Status.COMPLETED.value)
        self.assertEqual(video.channel, "A Channel")
        self.assertEqual(video.watch_url, "https://www.youtube.com/watch?v=vidAAAAAAAA")
        self.assertEqual(video.end_date.isoformat()[:10], "2026-03-02")
        self.assertEqual(video.item.title, "B")
        self.assertIn("i.ytimg.com/vi/vidAAAAAAAA/", video.item.image)
        self.assertEqual(report, "")

    def test_same_day_repeats_make_one_play(self):
        """Two views on one day are one play, as with the plays API."""
        self.run_import(
            [
                watch("vidAAAAAAAA", "2026-03-01T10:00:00Z"),
                watch("vidAAAAAAAA", "2026-03-01T11:00:00Z"),
            ],
        )
        self.assertEqual(VideoPlay.objects.count(), 1)

    def test_importing_twice_adds_nothing(self):
        """A second run of the same file changes nothing and says so."""
        records = [watch("vidAAAAAAAA", "2026-03-01T10:00:00Z")]
        self.run_import(records)
        counts, report = self.run_import(records)
        self.assertEqual(counts[MediaTypes.VIDEO.value], 0)
        self.assertEqual(VideoPlay.objects.count(), 1)
        self.assertNotIn("created", counts)
        self.assertNotIn("updated", counts)

    def test_new_plays_on_a_tracked_video_are_added(self):
        """A later export adds plays without touching the video's status or rating."""
        self.run_import([watch("vidAAAAAAAA", "2026-03-01T10:00:00Z")])
        video = Video.objects.get()
        video.status = Status.DROPPED.value
        video.score = 7
        video.save()
        counts, _ = self.run_import(
            [
                watch("vidAAAAAAAA", "2026-03-05T10:00:00Z"),
                watch("vidAAAAAAAA", "2026-03-01T10:00:00Z"),
            ],
        )
        video.refresh_from_db()
        self.assertEqual(VideoPlay.objects.count(), 2)
        self.assertEqual(counts["updated"], 1)
        self.assertEqual(video.status, Status.DROPPED.value)
        self.assertEqual(video.score, 7)
        self.assertEqual(video.end_date.isoformat()[:10], "2026-03-05")

    def test_shares_plays_with_the_plays_api_key(self):
        """A play the API already stored for that day is not duplicated."""
        item = Item.objects.create(
            media_id="vidAAAAAAAA",
            source=Sources.YOUTUBE.value,
            media_type=MediaTypes.VIDEO.value,
            library_media_type=MediaTypes.VIDEO.value,
            title="B",
        )
        video = Video.objects.create(
            item=item, user=self.user, status=Status.IN_PROGRESS.value
        )
        day = timezone.localtime(
            youtube_takeout.parse_time("2026-03-01T10:00:00Z"),
        ).date()
        VideoPlay.objects.create(
            video=video,
            external_id=f"youtube:vidAAAAAAAA:{day}",
            end_date=timezone.now(),
        )
        self.run_import([watch("vidAAAAAAAA", "2026-03-01T10:00:00Z")])
        self.assertEqual(VideoPlay.objects.count(), 1)

    def test_accepts_the_takeout_zip(self):
        """watch-history.json inside any folder of a zip is found."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(
                "Takeout/YouTube and YouTube Music/history/search-history.json", "[]"
            )
            archive.writestr(
                "Takeout/YouTube and YouTube Music/history/watch-history.json",
                json.dumps([watch("vidAAAAAAAA", "2026-03-01T10:00:00Z")]),
            )
        buffer.seek(0)
        counts, _ = youtube_takeout.importer(buffer, self.user, "new")
        self.assertEqual(counts["created"], 1)

    def test_imports_html_directly_and_from_zip(self):
        html = b"""<html><body><div class="outer-cell"><div>
        <div class="header-cell">YouTube<br></div>
        <div class="content-cell mdl-typography--body-1">Watched&nbsp;
        <a href="https://www.youtube.com/watch?v=vidAAAAAAAA">A &amp; B</a><br>
        <a href="https://www.youtube.com/channel/abc">Channel</a><br>
        Jan 9, 2023, 11:45:14&#8239;AM CDT<br></div></div></div></body></html>"""
        counts, _ = youtube_takeout.importer(BytesIO(html), self.user, "new")
        self.assertEqual(counts["created"], 1)
        video = Video.objects.get()
        self.assertEqual(video.item.title, "A & B")
        self.assertEqual(
            VideoPlay.objects.get().end_date,
            youtube_takeout.parse_time("2023-01-09T16:45:14Z"),
        )
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("Takeout/history/watch-history.html", html)
        buffer.seek(0)
        youtube_takeout.importer(buffer, self.user, "new")
        self.assertEqual(VideoPlay.objects.count(), 1)

    def test_html_rejects_an_unrecognized_watch_timestamp(self):
        html = b"""<html><div class="outer-cell"><div class="header-cell">YouTube</div>
        <div class="content-cell mdl-typography--body-1">
        Watched <a href="https://www.youtube.com/watch?v=vidAAAAAAAA">Video</a><br>
        Jan 9, 2023, 11:45:14 AM XYZ</div></div></html>"""
        with self.assertRaisesMessage(
            MediaImportError, "Could not read a YouTube watch timestamp"
        ):
            youtube_takeout.load_records(BytesIO(html))

    def test_zip_is_opened_in_place_not_read_whole(self):
        """A big export is never loaded into memory just to find the history."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(
                "Takeout/history/watch-history.json",
                json.dumps([watch("vidAAAAAAAA", "2026-03-01T10:00:00Z")]),
            )
        buffer.seek(0)

        class NoFullRead(io.BytesIO):
            def read(self, size=-1):
                if (size is None or size < 0) and self.tell() == 0:
                    msg = "read the whole upload"
                    raise AssertionError(msg)
                return super().read(size)

        upload = NoFullRead(buffer.getvalue())
        counts, _ = youtube_takeout.importer(upload, self.user, "new")
        self.assertEqual(counts["created"], 1)

    def test_import_locks_the_video_before_adding_plays(self):
        """The plays API takes the same row lock, so a day is never added twice."""
        locked = []
        original = youtube_takeout.Video.objects.select_for_update

        def spy(*args, **kwargs):
            locked.append(True)
            return original(*args, **kwargs)

        with patch.object(youtube_takeout.Video.objects, "select_for_update", spy):
            self.run_import([watch("vidAAAAAAAA", "2026-03-01T10:00:00Z")])
        self.assertTrue(locked)
        self.assertEqual(VideoPlay.objects.count(), 1)

    def test_bad_files_get_plain_errors(self):
        """Unrelated files and a zip without history fail clearly."""
        for payload, text in (
            (b"<html></html>", "isn't a YouTube watch history"),
            (b'{"a": 1}', "isn't a YouTube watch history"),
        ):
            with self.assertRaisesMessage(MediaImportError, text):
                youtube_takeout.importer(BytesIO(payload), self.user, "new")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("other.txt", "x")
        buffer.seek(0)
        with self.assertRaisesMessage(MediaImportError, "No watch-history.json"):
            youtube_takeout.importer(buffer, self.user, "new")
        with self.assertRaises(MediaImportError):
            youtube_takeout.importer(BytesIO(b"PK\x03\x04junk"), self.user, "new")

    def test_empty_history_imports_nothing(self):
        """An empty list is a valid file with nothing to add."""
        counts, _ = self.run_import([])
        self.assertEqual(Video.objects.count(), 0)
        self.assertEqual(counts[MediaTypes.VIDEO.value], 0)


class YouTubeTakeoutViewTests(TestCase):
    """The settings upload queues the task."""

    def setUp(self):
        """Sign in."""
        self.user = get_user_model().objects.create_user(username="v", password="x")
        self.client.force_login(self.user)

    def test_upload_queues_the_import(self):
        """A posted file is staged and queued with the user and mode."""
        from unittest.mock import patch

        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.urls import reverse

        from integrations.upload_staging import discard_staged_upload

        upload = SimpleUploadedFile("watch-history.json", b"[]")
        with patch("integrations.views.tasks.import_youtube_takeout.delay") as delay:
            response = self.client.post(
                reverse("import_youtube_takeout"),
                {"youtube_takeout": upload, "mode": "new"},
            )
        self.assertEqual(response.status_code, 302)
        kwargs = delay.call_args.kwargs
        self.addCleanup(discard_staged_upload, kwargs["file"])
        self.assertEqual(kwargs["user_id"], self.user.id)
        self.assertEqual(kwargs["mode"], "new")

    def test_missing_file_is_refused(self):
        """No file queues nothing."""
        from unittest.mock import patch

        from django.urls import reverse

        with patch("integrations.views.tasks.import_youtube_takeout.delay") as delay:
            response = self.client.post(
                reverse("import_youtube_takeout"), {"mode": "new"}
            )
        self.assertEqual(response.status_code, 302)
        delay.assert_not_called()
