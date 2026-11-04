from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.db import migrations
from django.utils.text import slugify

UNKNOWN_SHOW_TITLE = "Unknown Podcast"
PODCAST_MEDIA_TYPE = "podcast"
BATCH_SIZE = 500


def _normalize_feed_url(url):
    """Frozen copy of gpodder_api.normalize_external_url as of this migration."""
    value = (url or "").strip()
    if not value:
        return ""
    parts = urlsplit(value)
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    path = parts.path or ""
    if path.endswith("/"):
        path = path.rstrip("/")
    query_items = [
        (key, val)
        for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    query = urlencode(sorted(query_items))
    return urlunsplit((scheme, netloc, path, query, ""))


def clear_url_derived_titles(apps, schema_editor):
    """Replace show and item titles GPodder imports derived from a feed URL.

    Only an exact match against the value recomputed from the show's own stored
    feed URL is replaced, so genuine metadata is never touched. A tracked show's
    Item copied the show title and only resyncs when the podcast library page
    renders, so matching Item titles are replaced here as well.
    """
    PodcastShow = apps.get_model("app", "PodcastShow")
    alias = schema_editor.connection.alias
    shows = (
        PodcastShow.objects.using(alias)
        .exclude(rss_feed_url="")
        .only("id", "podcast_uuid", "source", "title", "slug", "rss_feed_url")
        .iterator(chunk_size=BATCH_SIZE)
    )
    batch = []
    for show in shows:
        derived_slug = slugify(_normalize_feed_url(show.rss_feed_url))
        if not derived_slug:
            continue
        derived_title = derived_slug.replace("-", " ")[:255]
        update_fields = []
        if show.title == derived_title:
            show.title = UNKNOWN_SHOW_TITLE
            update_fields.append("title")
        if show.slug == derived_slug[:255]:
            show.slug = slugify(show.title)[:255]
            update_fields.append("slug")
        if update_fields:
            show.save(using=alias, update_fields=update_fields)
        batch.append((show, derived_title))
        if len(batch) >= BATCH_SIZE:
            _clear_item_titles(apps, alias, batch)
            batch = []
    if batch:
        _clear_item_titles(apps, alias, batch)


def _clear_item_titles(apps, alias, batch):
    """Give a show's Item the show's title where it holds the URL-derived one."""
    Item = apps.get_model("app", "Item")
    by_key = {(show.podcast_uuid, show.source): (show, title) for show, title in batch}
    items = Item.objects.using(alias).filter(
        media_type=PODCAST_MEDIA_TYPE,
        media_id__in={show.podcast_uuid for show, _ in batch},
    ).only("id", "media_id", "source", "title", "original_title", "localized_title")
    changed = []
    for item in items:
        show, derived_title = by_key.get((item.media_id, item.source), (None, None))
        if show is None:
            continue
        touched = False
        for field in ("title", "original_title", "localized_title"):
            if getattr(item, field) == derived_title:
                setattr(item, field, show.title)
                touched = True
        if touched:
            changed.append(item)
    if changed:
        Item.objects.using(alias).bulk_update(
            changed,
            ["title", "original_title", "localized_title"],
            batch_size=BATCH_SIZE,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0222_playbackprogress_last_event_at"),
    ]

    operations = [
        migrations.RunPython(clear_url_derived_titles, migrations.RunPython.noop),
    ]
