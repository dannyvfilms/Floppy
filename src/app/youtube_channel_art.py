"""Resolve public YouTube video details without blocking the details page."""

import json
import re
from http import HTTPStatus
from urllib.parse import urlparse

import requests
from django.core.cache import cache

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
OWNER_MARKER = '"owner":{"videoOwnerRenderer":'
MAX_PAGE_BYTES = 3 * 1024 * 1024


def video_details(video_id):
    """Return cached public channel artwork and video description, when available."""
    if not VIDEO_ID.fullmatch(str(video_id)):
        return {"avatar": "", "description": ""}
    key = f"youtube-public-details:{video_id}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    image = ""
    description = ""
    try:
        with requests.get(
            f"https://www.youtube.com/watch?v={video_id}",
            timeout=(3, 5),
            stream=True,
            allow_redirects=False,
        ) as response:
            if response.status_code == HTTPStatus.OK:
                chunks = []
                size = 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > MAX_PAGE_BYTES:
                        break
                    chunks.append(chunk)
                page = b"".join(chunks).decode("utf-8", errors="replace")
                start = page.find(OWNER_MARKER)
                if start >= 0:
                    owner, _ = json.JSONDecoder().raw_decode(
                        page[start + len(OWNER_MARKER) :]
                    )
                    thumbnails = owner.get("thumbnail", {}).get("thumbnails", [])
                    for thumbnail in reversed(thumbnails):
                        candidate = thumbnail.get("url", "")
                        parsed = urlparse(candidate)
                        if parsed.scheme == "https" and parsed.hostname in (
                            "yt3.ggpht.com",
                            "yt3.googleusercontent.com",
                        ):
                            image = candidate
                            break
                match = re.search(r"(?:var\s+)?ytInitialPlayerResponse\s*=\s*", page)
                if match:
                    player, _ = json.JSONDecoder().raw_decode(page[match.end() :])
                    video = player.get("videoDetails", {})
                    if video.get("videoId") == video_id:
                        description = str(video.get("shortDescription") or "")[:10000]
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        pass
    result = {"avatar": image, "description": description}
    cache.set(key, result, 86400 if image or description else 900)
    return result
