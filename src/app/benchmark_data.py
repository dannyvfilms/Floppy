# ruff: noqa: PLR2004, PERF401 -- explicit synthetic dimensions and nested fixtures
"""Synthetic BENCH-01 data; imported only by the opt-in harness and its tests."""

import random
from datetime import UTC, datetime, timedelta

from django.contrib.auth import get_user_model
from django.db import transaction

from app import models
from integrations.models import ImportRun

EPOCH = datetime(2025, 1, 1, tzinfo=UTC)
TRACKERS = (
    models.TV,
    models.Season,
    models.Movie,
    models.Movie,
    models.Book,
    models.Game,
    models.Music,
    models.Podcast,
    models.Anime,
    models.Manga,
)


def build_dataset(size, seed):
    """Build exactly size tracking rows in an empty, disposable database.

    Bulk writes intentionally bypass providers, signals, cache invalidation and
    task dispatch. This models persisted import outcomes, not importer throughput.
    Return the dependency-ordered models comprising the portable fixture.
    """
    user_model = get_user_model()
    if user_model.objects.exists() or models.Item.objects.exists():
        msg = "BENCH-01 requires an empty disposable database"
        raise ValueError(msg)
    if size < 10 or size % 10:
        msg = "Size must be a positive multiple of 10 (at least 10)"
        raise ValueError(msg)
    rng = random.Random(seed)  # noqa: S311 -- reproducible synthetic data
    exported = []

    def insert(model, rows):
        if model not in exported:
            exported.append(model)
        model.objects.bulk_create(rows, batch_size=500)
        # Remove wall-clock defaults, including MonitorField's pre_save values.
        fixed = {
            field.name: EPOCH
            for field in model._meta.fields
            if getattr(field, "auto_now", False)
            or getattr(field, "auto_now_add", False)
            or field.name in {"progressed_at", "scored_at"}
        }
        if fixed:
            model.objects.filter(pk__in=[row.pk for row in rows]).update(**fixed)
        return rows

    with transaction.atomic():
        users = insert(
            user_model,
            [
                user_model(
                    username=f"bench-user-{i}",
                    password="!bench-disabled",  # noqa: S106 -- unusable password
                    token=f"{i:032x}",
                    date_joined=EPOCH,
                    is_test_account=True,
                )
                for i in range(1, 4)
            ],
        )
        runs = insert(
            ImportRun,
            [
                ImportRun(
                    user=user,
                    source="bench-synthetic",
                    status="completed",
                    finished_at=EPOCH,
                    created_count=0,
                )
                for user in users
            ],
        )
        groups = insert(
            models.CollectionFieldGroup,
            [
                models.CollectionFieldGroup(user=user, name="Synthetic ownership")
                for user in users
            ],
        )
        fields = insert(
            models.CollectionField,
            [
                models.CollectionField(
                    group=group,
                    label="Condition",
                    field_type="select",
                    options=["New", "Used"],
                    media_types=["movie", "book", "music", "podcast"],
                )
                for group in groups
            ],
        )
        artist = insert(models.Artist, [models.Artist(name="Synthetic Artist")])[0]
        album = insert(
            models.Album,
            [
                models.Album(
                    title="Synthetic Album", artist=artist, tracks_populated=True
                ),
            ],
        )[0]
        show = insert(
            models.PodcastShow,
            [
                models.PodcastShow(
                    podcast_uuid="bench-podcast",
                    title="Synthetic Podcast",
                    source="manual",
                ),
            ],
        )[0]
        # Bounded batches: 1,000 primary trackers plus associated episode data.
        for start in range(0, size, 1000):
            buckets = {model: [] for model in dict.fromkeys(TRACKERS)}
            episode_items, episodes, collections = [], [], []
            previous_tv = None
            for index in range(start, min(start + 1000, size)):
                model = TRACKERS[index % 10]
                owner = (index // 10) % len(users)
                day = EPOCH - timedelta(days=rng.randrange(730))
                item = insert(
                    models.Item,
                    [
                        models.Item(
                            media_id=f"bench-{seed}-{index}",
                            source="manual",
                            media_type=model.__name__.lower(),
                            title=f"Synthetic {index:07d}",
                            season_number=1 if model is models.Season else None,
                            genres=["Drama" if index % 2 else "Comedy"],
                            release_datetime=day,
                            runtime_minutes=30,
                            manual_metadata={
                                "title": f"Synthetic {index:07d}",
                                "runtime": 30,
                            },
                        )
                    ],
                )[0]
                status = models.Status.values[(index // 10 + index) % 5]
                kwargs = {
                    "item": item,
                    "user": users[owner],
                    "status": status,
                    "score": rng.randrange(11),
                    "start_date": day,
                    "end_date": day + timedelta(hours=1)
                    if status == models.Status.COMPLETED
                    else None,
                    "entry_source": "bench-synthetic" if index % 2 else "manual",
                    "import_run": runs[owner] if index % 2 else None,
                }
                if model is models.TV:
                    kwargs.pop("start_date")
                    kwargs.pop("end_date")
                    previous_tv = insert(model, [model(**kwargs)])[0]
                    buckets[model].append(previous_tv)
                    continue
                if model is models.Season:
                    kwargs.pop("start_date")
                    kwargs.pop("end_date")
                    row = insert(model, [model(related_tv=previous_tv, **kwargs)])[0]
                    buckets[model].append(row)
                    for number in range(1, 13):
                        ep_item = models.Item(
                            media_id=item.media_id,
                            source="manual",
                            media_type="episode",
                            title=f"Synthetic episode {number}",
                            season_number=1,
                            episode_number=number,
                            runtime_minutes=30,
                        )
                        episode_items.append(ep_item)
                        for repeat in range(2):
                            episodes.append(
                                models.Episode(
                                    related_season=row,
                                    item=ep_item,
                                    status="Completed",
                                    end_date=day + timedelta(days=number + repeat * 30),
                                    external_id=f"bench-{index}-{number}-{repeat}",
                                    entry_source="bench-synthetic",
                                )
                            )
                    continue
                if model is models.Music:
                    track = insert(
                        models.Track,
                        [
                            models.Track(
                                album=album,
                                title=item.title,
                                track_number=index + 1,
                                duration_ms=180000,
                            )
                        ],
                    )[0]
                    kwargs.update(artist=artist, album=album, track=track)
                if model is models.Podcast:
                    episode = insert(
                        models.PodcastEpisode,
                        [
                            models.PodcastEpisode(
                                show=show,
                                episode_uuid=item.media_id,
                                title=item.title,
                                published=day,
                                duration=1800,
                            )
                        ],
                    )[0]
                    kwargs.update(show=show, episode=episode)
                buckets[model].append(model(**kwargs))
                if index % 10 in {2, 4, 6, 7}:
                    collections.append(
                        models.CollectionEntry(
                            user=users[owner],
                            item=item,
                            media_type="digital",
                            custom_field_values={
                                str(fields[owner].pk): "Used" if index % 2 else "New"
                            },
                        )
                    )
            insert(models.Item, episode_items)
            insert(models.Episode, episodes)
            insert(models.CollectionEntry, collections)
            for model, rows in [*buckets.items(), (models.Episode, episodes)]:
                if model not in {models.TV, models.Season, models.Episode}:
                    insert(model, rows)
                historical = model.history.model
                excluded = {
                    "history_id",
                    "history_date",
                    "history_type",
                    "history_user",
                    "history_change_reason",
                }
                history_rows = []
                for row in rows:
                    values = {
                        field.attname: getattr(row, field.attname)
                        for field in historical._meta.fields
                        if field.name not in excluded
                    }
                    for revision in range(2):
                        state = dict(values)
                        if revision == 0:
                            state["status"] = models.Status.IN_PROGRESS.value
                            if "end_date" in state:
                                state["end_date"] = None
                            if "progress" in state:
                                state["progress"] = 0
                        history_rows.append(
                            historical(
                                **state,
                                history_date=EPOCH + timedelta(minutes=revision),
                                history_type="+" if revision == 0 else "~",
                                history_user_id=(
                                    row.related_season.user_id
                                    if model is models.Episode
                                    else row.user_id
                                ),
                                history_change_reason="Synthetic benchmark revision",
                            )
                        )
                insert(historical, history_rows)
        for run in runs:
            count = sum(
                model.objects.filter(import_run=run).count()
                for model in dict.fromkeys(TRACKERS)
            )
            ImportRun.objects.filter(pk=run.pk).update(created_count=count)
    # Dependency order, rather than first-insertion order (episodes need seasons).
    front = [
        user_model,
        ImportRun,
        models.CollectionFieldGroup,
        models.CollectionField,
        models.Artist,
        models.Album,
        models.PodcastShow,
        models.Item,
        models.Track,
        models.PodcastEpisode,
        *dict.fromkeys(TRACKERS),
        models.Episode,
        models.CollectionEntry,
    ]
    return front + [model for model in exported if model not in front]
