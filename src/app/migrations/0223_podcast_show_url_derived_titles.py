from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.db import migrations
from django.utils.text import slugify

UNKNOWN_SHOW_TITLE = "Unknown Podcast"


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
    """Replace show titles and slugs GPodder imports derived from a feed URL.

    Only an exact match against the value recomputed from the row's own stored
    feed URL is replaced, so genuine metadata is never touched.
    """
    PodcastShow = apps.get_model("app", "PodcastShow")
    alias = schema_editor.connection.alias
    shows = (
        PodcastShow.objects.using(alias)
        .exclude(rss_feed_url="")
        .only("id", "title", "slug", "rss_feed_url")
        .iterator()
    )
    for show in shows:
        derived_slug = slugify(_normalize_feed_url(show.rss_feed_url))
        if not derived_slug:
            continue
        update_fields = []
        if show.title == derived_slug.replace("-", " ")[:255]:
            show.title = UNKNOWN_SHOW_TITLE
            update_fields.append("title")
        if show.slug == derived_slug[:255]:
            show.slug = slugify(show.title)[:255]
            update_fields.append("slug")
        if update_fields:
            show.save(using=alias, update_fields=update_fields)


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0222_playbackprogress_last_event_at"),
    ]

    operations = [
        migrations.RunPython(clear_url_derived_titles, migrations.RunPython.noop),
    ]
