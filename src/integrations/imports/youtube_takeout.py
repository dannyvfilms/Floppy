"""Importer for YouTube watch history from Google Takeout.

Takeout writes watch history in JSON or HTML format.
Each entry is one view with a title, a watch URL, the channel and a UTC time.
It carries no video length, so completion cannot be inferred: every video in
the history counts as watched, which is what the history means.

Plays follow the same rule as the plays API: one per video and day, keyed
``youtube:<id>:<day>``, so importing twice or alongside a live client never
doubles a play.
"""

import gzip
import json
import logging
import re
import tarfile
import tempfile
import zipfile
from collections import defaultdict
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import parse_qs, urlparse

from django.db import transaction
from django.utils import timezone

from app.helpers import has_real_image
from app.models import Item, MediaTypes, Sources, Status, Video, VideoPlay
from app.video_helpers import approved_thumbnail_url, set_channel_as_author
from integrations import import_progress
from integrations.imports.helpers import MediaImportError

logger = logging.getLogger(__name__)

VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
WATCHED_PREFIX = "Watched "
# Takeout writes several products into one history file.
YOUTUBE_HEADER = "YouTube"
HISTORY_FILE_PREFIX = "watch-history"
MAX_TITLE_LENGTH = 255
MAX_CHANNEL_LENGTH = 255
PLAY_BATCH_SIZE = 500
MAX_HISTORY_FILE_BYTES = 512 * 1024 * 1024
MAX_TGZ_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_TGZ_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
MAX_TGZ_MEMBERS = 10_000
TGZ_SPOOL_MEMORY_BYTES = 8 * 1024 * 1024
TGZ_READ_CHUNK_BYTES = 1024 * 1024
HTML_STREAM_CHUNK_SIZE = 64 * 1024


def video_id_from_url(url):
    """Return the 11 character video id in a watch, shorts or youtu.be URL."""
    try:
        parsed = urlparse(str(url or ""))
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    candidate = ""
    if host == "youtu.be":
        candidate = parsed.path.strip("/")
    elif host in ("youtube.com", "music.youtube.com"):
        parts = parsed.path.strip("/").split("/")
        if parts[0] == "watch":
            candidate = (parse_qs(parsed.query).get("v") or [""])[0]
        elif parts[0] in ("shorts", "live") and len(parts) > 1:
            candidate = parts[1]
    return candidate if VIDEO_ID_PATTERN.match(candidate) else ""


def parse_time(value):
    """Parse a Takeout ISO time (``2025-03-01T18:22:10.123Z``) into an aware datetime."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        date_text, separator, zone = text.rpartition(" ")
        offsets = {
            "UTC": "+0000",
            "GMT": "+0000",
            "EST": "-0500",
            "EDT": "-0400",
            "CST": "-0600",
            "CDT": "-0500",
            "MST": "-0700",
            "MDT": "-0600",
            "PST": "-0800",
            "PDT": "-0700",
        }
        if not separator or zone not in offsets:
            return None
        try:
            return datetime.strptime(
                f"{date_text.replace(chr(0x202F), ' ')} {offsets[zone]}",
                "%b %d, %Y, %I:%M:%S %p %z",
            )
        except ValueError:
            return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, UTC)
    return parsed


def clean_title(title):
    """Drop the ``Watched `` prefix Takeout puts on every English title."""
    text = str(title or "").strip()
    return text.removeprefix(WATCHED_PREFIX).strip()[:MAX_TITLE_LENGTH]


AD_DETAIL = "From Google Ads"


def _is_ad(details):
    """Whether Takeout's ``details`` say the entry is "From Google Ads"."""
    if isinstance(details, str):
        details = [details]
    for detail in details if isinstance(details, list) else []:
        name = detail.get("name") if isinstance(detail, dict) else detail
        if AD_DETAIL in " ".join(str(name or "").split()):
            return True
    return False


def _html_details(card):
    """Return the ``Details:`` value in this card's caption, or ``[]`` when absent."""
    caption = card.select_one(".content-cell.mdl-typography--caption")
    if not caption:
        return []
    text = " ".join(caption.get_text(" ").split())
    match = re.search(r"Details:(.*?)(?:Why is this here\?|$)", text)
    return [match.group(1).strip()] if match and match.group(1).strip() else []


def entry_from_record(record):
    """Turn one Takeout record into a watch, or ``None`` when it is not one.

    Not watches: YouTube Music plays, ads, community posts, and videos that were
    removed (they have no URL and the title is a placeholder).
    """
    if not isinstance(record, dict) or record.get("header") != YOUTUBE_HEADER:
        return None
    if _is_ad(record.get("details")):
        return None
    video_id = video_id_from_url(record.get("titleUrl"))
    when = parse_time(record.get("time"))
    title = clean_title(record.get("title"))
    if not video_id or not when or not title:
        return None
    subtitles = record.get("subtitles") or []
    channel = ""
    if subtitles and isinstance(subtitles[0], dict):
        channel = str(subtitles[0].get("name") or "")[:MAX_CHANNEL_LENGTH]
    return {"id": video_id, "title": title, "channel": channel, "time": when}


def load_records(file):
    """Read the history list from uploaded JSON, HTML, ZIP, or TGZ."""
    try:
        magic = file.read(2)
        file.seek(0)
    except (AttributeError, OSError) as error:
        msg = "Invalid file. Upload watch-history.json or watch-history.html from Google Takeout."
        raise MediaImportError(msg) from error

    # A zip is opened from the file itself, so a large export is not held in memory.
    if magic == b"PK":
        raw = _history_from_zip(file)
    elif magic == b"\x1f\x8b":
        raw = _history_from_tgz(file)
    else:
        raw = file.read(MAX_HISTORY_FILE_BYTES + 1)
        if len(raw) > MAX_HISTORY_FILE_BYTES:
            msg = "The YouTube watch history file is too large."
            raise MediaImportError(msg)
    try:
        content = raw.decode("utf-8-sig")
        del raw
        if content.lstrip().lower().startswith(("<html", "<!doctype html")):
            return _records_from_html(content)
        records = json.loads(content)
    except (UnicodeDecodeError, ValueError) as error:
        msg = "Couldn't read this file. Upload YouTube watch history in JSON or HTML format."
        raise MediaImportError(msg) from error
    if not isinstance(records, list):
        msg = "This isn't a YouTube watch history. Upload watch-history.json or watch-history.html."
        raise MediaImportError(msg)
    return records


class _OuterCellHTMLParser(HTMLParser):
    """Buffer one Takeout outer-cell fragment at a time from streamed HTML."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self._parts = None
        self._div_depth = 0
        self._ready = []

    def handle_starttag(self, tag, attrs):
        """Start buffering at an outer-cell div and retain markup inside it."""
        start_tag = self.get_starttag_text() or f"<{tag}>"
        if self._parts is None:
            classes = (dict(attrs).get("class", "") or "").split()
            if tag == "div" and "outer-cell" in classes:
                self._parts = [start_tag]
                self._div_depth = 1
            return
        self._parts.append(start_tag)
        if tag == "div":
            self._div_depth += 1

    def handle_startendtag(self, tag, attrs):
        """Retain self-closing markup within the current card."""
        if self._parts is not None:
            self._parts.append(self.get_starttag_text() or f"<{tag}/>")

    def handle_endtag(self, tag):
        """Finish a card when its outermost div closes."""
        if self._parts is None:
            return
        self._parts.append(f"</{tag}>")
        if tag == "div":
            self._div_depth -= 1
            if self._div_depth == 0:
                self._ready.append("".join(self._parts))
                self._parts = None

    def handle_data(self, data):
        """Retain text for the per-card parser."""
        if self._parts is not None:
            self._parts.append(data)

    def handle_entityref(self, name):
        """Retain named entities without changing their HTML meaning."""
        if self._parts is not None:
            self._parts.append(f"&{name};")

    def handle_charref(self, name):
        """Retain numeric entities without changing their HTML meaning."""
        if self._parts is not None:
            self._parts.append(f"&#{name};")

    def handle_comment(self, data):
        """Retain comments inside a card, if any."""
        if self._parts is not None:
            self._parts.append(f"<!--{data}-->")

    def take_cards(self):
        """Return completed card fragments and release their temporary storage."""
        cards, self._ready = self._ready, []
        return cards

    def finish(self):
        """Flush the final incomplete card as HTML parsers do at end-of-file."""
        super().close()
        if self._parts is not None:
            self._ready.append("".join(self._parts))
            self._parts = None
        return self.take_cards()


def _record_from_html_card(card):
    """Convert one parsed Takeout HTML card into a JSON-shaped record."""
    header = card.select_one(".header-cell")
    cell = card.select_one(
        ".content-cell.mdl-typography--body-1:not(.mdl-typography--text-right)"
    )
    if not header or not cell:
        return None
    links = cell.find_all("a")
    lines = cell.get_text("|", strip=True).split("|")
    when = next((line for line in reversed(lines) if parse_time(line)), "")
    if links and video_id_from_url(links[0].get("href")) and not when:
        msg = "Could not read a YouTube watch timestamp in the HTML file."
        raise MediaImportError(msg)
    return {
        "header": header.get_text(strip=True),
        "title": links[0].get_text(strip=True) if links else "",
        "titleUrl": links[0].get("href") if links else "",
        "subtitles": [{"name": links[1].get_text(strip=True)}]
        if len(links) > 1
        else [],
        "time": when,
        "details": _html_details(card),
    }


def _records_from_html(content):
    """Convert Takeout HTML to records without building a document-sized tree."""
    from bs4 import BeautifulSoup

    parser = _OuterCellHTMLParser()
    records = []
    cards_seen = 0

    def process_card(fragment):
        nonlocal cards_seen
        cards_seen += 1
        if cards_seen % 5000 == 0:
            logger.info("YouTube Takeout: read %s HTML cards", cards_seen)
            import_progress.report(cards_seen, None, "Reading YouTube history")
        card = BeautifulSoup(fragment, "html.parser").select_one(".outer-cell")
        if card is None:
            return
        record = _record_from_html_card(card)
        if record is not None:
            records.append(record)

    for offset in range(0, len(content), HTML_STREAM_CHUNK_SIZE):
        parser.feed(content[offset : offset + HTML_STREAM_CHUNK_SIZE])
        for fragment in parser.take_cards():
            process_card(fragment)
    for fragment in parser.finish():
        process_card(fragment)

    if not cards_seen:
        msg = "This isn't a YouTube watch history HTML file."
        raise MediaImportError(msg)
    return records


def _history_from_zip(file):
    """Return the history bytes inside a Takeout zip."""
    try:
        with zipfile.ZipFile(file) as archive:
            names = [
                name
                for name in archive.namelist()
                if PurePosixPath(name).name.startswith(HISTORY_FILE_PREFIX)
                and name.lower().endswith((".json", ".html"))
            ]
            if not names:
                msg = "No watch-history.json or watch-history.html in this zip."
                raise MediaImportError(msg)
            name = min(
                names,
                key=lambda name: (not name.lower().endswith(".json"), len(name)),
            )
            info = archive.getinfo(name)
            if info.file_size > MAX_HISTORY_FILE_BYTES:
                msg = "The YouTube watch history file is too large."
                raise MediaImportError(msg)
            return archive.read(info)
    except zipfile.BadZipFile as error:
        msg = "This zip can't be opened."
        raise MediaImportError(msg) from error


def _history_from_tgz(file):
    """Read a matching history member from a gzip-compressed Takeout tar."""
    try:
        file.seek(0, 2)
        archive_size = file.tell()
        file.seek(0)
        if archive_size > MAX_TGZ_ARCHIVE_BYTES:
            msg = "This tgz archive is too large."
            raise MediaImportError(msg)

        # Bound gzip expansion before tarfile parses headers or caches members.
        # SpooledTemporaryFile keeps ordinary exports in memory and rolls larger
        # archives to disk, with a hard cap on total decompressed bytes.
        with (
            gzip.GzipFile(fileobj=file, mode="rb") as compressed,
            tempfile.SpooledTemporaryFile(
                max_size=TGZ_SPOOL_MEMORY_BYTES,
            ) as expanded,
        ):
            expanded_size = 0
            while chunk := compressed.read(TGZ_READ_CHUNK_BYTES):
                expanded_size += len(chunk)
                if expanded_size > MAX_TGZ_UNCOMPRESSED_BYTES:
                    msg = "This tgz archive is too large after decompression."
                    raise MediaImportError(msg)
                expanded.write(chunk)

            expanded.seek(0)
            with tarfile.open(fileobj=expanded, mode="r|") as archive:
                member_count = 0
                selected = None
                selected_key = None
                selected_size = None
                for member in archive:
                    member_count += 1
                    if member_count > MAX_TGZ_MEMBERS:
                        msg = "This tgz archive contains too many files."
                        raise MediaImportError(msg)
                    if not (
                        member.isfile()
                        and PurePosixPath(member.name).name.startswith(
                            HISTORY_FILE_PREFIX
                        )
                        and member.name.lower().endswith((".json", ".html"))
                    ):
                        continue

                    key = (
                        not member.name.lower().endswith(".json"),
                        len(member.name),
                    )
                    if selected_key is not None and key >= selected_key:
                        continue
                    selected_key = key
                    selected_size = member.size
                    selected = None
                    if member.size > MAX_HISTORY_FILE_BYTES:
                        continue
                    stream = archive.extractfile(member)
                    if stream is None:
                        msg = "The YouTube watch history file can't be read."
                        raise MediaImportError(msg)
                    selected = stream.read(MAX_HISTORY_FILE_BYTES + 1)

        if selected_key is None:
            msg = "No watch-history.json or watch-history.html in this tgz."
            raise MediaImportError(msg)
        if selected_size > MAX_HISTORY_FILE_BYTES or selected is None:
            msg = "The YouTube watch history file is too large."
            raise MediaImportError(msg)
        if len(selected) > MAX_HISTORY_FILE_BYTES:
            msg = "The YouTube watch history file is too large."
            raise MediaImportError(msg)
    except (tarfile.ReadError, tarfile.CompressionError, EOFError, OSError) as error:
        msg = "This tgz can't be opened."
        raise MediaImportError(msg) from error
    else:
        return selected


def importer(file, user, mode):
    """Import a Takeout watch history. ``mode`` does not matter: plays are idempotent."""
    return YouTubeTakeoutImporter(file, user).import_data()


class YouTubeTakeoutImporter:
    """Write one video per id and one play per video and day."""

    def __init__(self, file, user):
        """Keep the upload and the user the history belongs to."""
        self.file = file
        self.user = user
        self.skipped = 0

    def import_data(self):
        """Import every watch and return the counts."""
        logger.info("YouTube Takeout import for user %s: reading history", self.user.id)
        import_progress.report(0, None, "Reading YouTube history")
        records = load_records(self.file)
        logger.info("YouTube Takeout: read %s history records; preparing videos", len(records))
        import_progress.report(0, len(records), "Preparing YouTube history")
        watches = defaultdict(list)
        titles = {}
        for index, record in enumerate(records, start=1):
            if index % 5000 == 0:
                logger.info("YouTube Takeout: prepared %s of %s records", index, len(records))
                import_progress.report(index, len(records), "Preparing YouTube history")
            entry = entry_from_record(record)
            if entry is None:
                self.skipped += 1
                continue
            watches[entry["id"]].append(entry["time"])
            # Entries run newest first, so the first title seen is the latest.
            titles.setdefault(entry["id"], entry)

        total = len(watches)
        logger.info("YouTube Takeout: importing %s videos", total)
        created_videos = 0
        updated_videos = 0
        created_plays = 0
        for index, (video_id, times) in enumerate(watches.items(), start=1):
            import_progress.report(index, total, "YouTube")
            video_created, plays_created = self._import_video(titles[video_id], times)
            created_videos += video_created
            created_plays += plays_created
            updated_videos += int(not video_created and plays_created > 0)

        counts = {MediaTypes.VIDEO.value: created_videos}
        if created_videos:
            counts["created"] = created_videos
        if updated_videos:
            counts["updated"] = updated_videos
        # The second value is shown as errors, and skipped entries are not one.
        logger.info(
            "YouTube Takeout import for user %s: %s videos, %s new plays, %s skipped",
            self.user.id,
            total,
            created_plays,
            self.skipped,
        )
        return counts, ""

    def _import_video(self, entry, times):
        """Create the video if needed and add its missing daily plays."""
        video_id = entry["id"]
        with transaction.atomic():
            item, _ = Item.objects.get_or_create(
                media_id=video_id,
                source=Sources.YOUTUBE.value,
                media_type=MediaTypes.VIDEO.value,
                library_media_type=MediaTypes.VIDEO.value,
                defaults={"title": entry["title"]},
            )
            thumbnail = approved_thumbnail_url(
                f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                video_id,
            )
            if thumbnail and not has_real_image(item.image):
                item.image = thumbnail
                item.save(update_fields=["image"])

            set_channel_as_author(item, entry["channel"])

            watch_url = f"https://www.youtube.com/watch?v={video_id}"
            video, video_created = Video.objects.get_or_create(
                item=item,
                user=self.user,
                defaults={
                    # In the history means watched. No length is known here.
                    "status": Status.COMPLETED.value,
                    "channel": entry["channel"],
                    "watch_url": watch_url,
                    "entry_source": "youtube",
                },
            )
            if not video_created:
                changed = []
                if entry["channel"] and not video.channel:
                    video.channel = entry["channel"]
                    changed.append("channel")
                if not video.watch_url:
                    video.watch_url = watch_url
                    changed.append("watch_url")
                if changed:
                    video.save(update_fields=changed)

            # Lock the video so a plays API call cannot insert the same day meanwhile.
            video = Video.objects.select_for_update().get(pk=video.pk)
            plays_created = self._add_plays(video, video_id, times)
            latest = max(times)
            if not video.end_date or latest > video.end_date:
                video.end_date = latest
                video.save(update_fields=["end_date"])
        return int(video_created), plays_created

    def _add_plays(self, video, video_id, times):
        """Insert one play per day that has none yet. Returns how many were added."""
        by_day = {}
        for when in sorted(times):
            day = timezone.localtime(when).date().isoformat()
            by_day[f"youtube:{video_id}:{day}"] = when
        existing = set(
            VideoPlay.objects.filter(
                video=video,
                external_id__in=list(by_day),
            ).values_list("external_id", flat=True),
        )
        new_plays = [
            VideoPlay(video=video, external_id=external_id, end_date=when)
            for external_id, when in by_day.items()
            if external_id not in existing
        ]
        VideoPlay.objects.bulk_create(new_plays, batch_size=PLAY_BATCH_SIZE)
        return len(new_plays)
