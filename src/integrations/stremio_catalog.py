"""Local catalog projection for the Stremio addon."""

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, unquote

from app.models import MediaTypes, Sources
from lists.models import CustomList, CustomListItem

PAGE_SIZE = 100
IMDB_ID_PATTERN = re.compile(r"^tt[0-9]+$")


@dataclass(frozen=True)
class CatalogSpec:
    """Stable Stremio catalog configuration and its local source rule."""

    stremio_type: str
    catalog_id: str
    media_type: str
    preferred_list_name: str


CATALOG_SPECS = (
    CatalogSpec(
        stremio_type="movie",
        catalog_id="floppy-watchlist-movies",
        media_type=MediaTypes.MOVIE.value,
        preferred_list_name="Movies",
    ),
    CatalogSpec(
        stremio_type="series",
        catalog_id="floppy-watchlist-series",
        media_type=MediaTypes.TV.value,
        preferred_list_name="Series",
    ),
)


def get_catalog_spec(stremio_type, catalog_id):
    """Return the matching supported catalog, if any."""
    return next(
        (
            spec
            for spec in CATALOG_SPECS
            if (spec.stremio_type, spec.catalog_id)
            == (stremio_type, catalog_id)
        ),
        None,
    )


def select_source_list(user, spec):
    """Select the oldest owned preferred list, then the oldest owned Watchlist."""
    owned_lists = CustomList.objects.filter(owner=user)
    source_list = (
        owned_lists.filter(name__iexact=spec.preferred_list_name)
        .order_by("id")
        .first()
    )
    if source_list is not None:
        return source_list

    return owned_lists.filter(name__iexact="Watchlist").order_by("id").first()


def manifest_catalogs(user):
    """Build manifest catalogs from the same source rules used for projection."""
    catalogs = []
    for spec in CATALOG_SPECS:
        source_list = select_source_list(user, spec)
        source_name = (
            source_list.name if source_list is not None else spec.preferred_list_name
        )
        catalogs.append(
            {
                "type": spec.stremio_type,
                "id": spec.catalog_id,
                "name": f"Floppy: {source_name}",
                "extra": [{"name": "skip", "isRequired": False}],
            }
        )
    return catalogs


def parse_skip(extra):
    """Parse the optional Stremio extra segment and return a non-negative skip."""
    if not extra:
        return 0

    try:
        pairs = parse_qsl(
            unquote(extra),
            keep_blank_values=True,
            strict_parsing=True,
        )
    except ValueError as error:
        message = "Malformed catalog extra arguments"
        raise ValueError(message) from error

    if len(pairs) != 1 or pairs[0][0] != "skip":
        message = "Only one skip argument is supported"
        raise ValueError(message)

    value = pairs[0][1]
    if not value.isdecimal():
        message = "skip must be a non-negative integer"
        raise ValueError(message)

    try:
        return int(value)
    except ValueError as error:
        message = "skip must be a non-negative integer"
        raise ValueError(message) from error


def local_imdb_id(item):
    """Resolve an item's IMDb id without network, cache, or database writes."""
    if item.source == Sources.IMDB.value:
        media_id = str(item.media_id)
        if IMDB_ID_PATTERN.fullmatch(media_id):
            return media_id

    imdb_id = str((item.provider_external_ids or {}).get("imdb_id") or "")
    if IMDB_ID_PATTERN.fullmatch(imdb_id):
        return imdb_id

    return None


def project_catalog(user, spec, skip):
    """Return one page of publishable metas and the scanned unresolved count."""
    source_list = select_source_list(user, spec)
    if source_list is None:
        return [], 0

    memberships = (
        CustomListItem.objects.filter(
            custom_list=source_list,
            item__media_type=spec.media_type,
        )
        .select_related("item")
        .order_by("-date_added", "-id")
    )

    metas = []
    publishable_seen = 0
    unresolved_count = 0
    for membership in memberships.iterator():
        item = membership.item
        imdb_id = local_imdb_id(item)
        if imdb_id is None:
            unresolved_count += 1
            continue

        if publishable_seen < skip:
            publishable_seen += 1
            continue

        meta = {"id": imdb_id, "type": spec.stremio_type, "name": item.title}
        if item.image:
            meta["poster"] = item.image
        metas.append(meta)
        if len(metas) == PAGE_SIZE:
            break

    return metas, unresolved_count
