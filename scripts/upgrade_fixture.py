# ruff: noqa: INP001, T201 -- standalone replay script with console output
"""Seed/verify retained data via manage.py shell during the upgrade replay.

Run by replay_upgrade_matrix.sh against each release's own model classes.
Bulk writes deliberately avoid provider requests and background scheduling.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.serializers.json import DjangoJSONEncoder
from simple_history.utils import bulk_create_with_history

from app.models import Item, Movie, MoviePlay
from lists.models import CustomList, CustomListItem

snapshot_path = Path(os.environ["FLOPPY_UPGRADE_SNAPSHOT"])
User = get_user_model()

if os.environ["FLOPPY_UPGRADE_FIXTURE"] == "seed":
    user = User.objects.bulk_create(
        [User(username="upgrade-owner", password=make_password("upgrade-test-only"))]
    )[0]
    item = Item.objects.bulk_create(
        [
            Item(
                media_id="upgrade-movie",
                source="manual",
                media_type="movie",
                title="Retained movie",
            )
        ]
    )[0]
    watched_at = datetime(2026, 9, 1, 12, tzinfo=UTC)
    movie = bulk_create_with_history(
        [
            Movie(
                user=user,
                item=item,
                status="Completed",
                score=7,
                progress=1,
                end_date=watched_at,
            )
        ],
        Movie,
        default_user=user,
    )[0]
    MoviePlay.objects.bulk_create(
        [MoviePlay(movie=movie, end_date=watched_at, external_id="upgrade-play")]
    )
    custom_list = CustomList.objects.bulk_create(
        [CustomList(owner=user, name="Private upgrade list", visibility="private")]
    )[0]
    CustomListItem.objects.bulk_create(
        [CustomListItem(custom_list=custom_list, item=item)]
    )

user = User.objects.get(username="upgrade-owner")
if not user.check_password("upgrade-test-only"):
    message = "Upgrade lost the user's password"
    raise RuntimeError(message)

# Compare stored values, including original identifiers and timestamps, rather
# than just proving that migrations exit zero on an empty database.
snapshot = json.dumps(
    {
        "user": list(
            User.objects.filter(pk=user.pk).values(
                "id", "username", "password", "is_active", "is_superuser", "token"
            )
        ),
        "items": list(
            Item.objects.filter(media_id="upgrade-movie").values(
                "id", "media_id", "source", "media_type", "title"
            )
        ),
        "movies": list(
            Movie.objects.filter(user=user).values(
                "id", "user_id", "item_id", "status", "score", "progress", "end_date"
            )
        ),
        "plays": list(
            MoviePlay.objects.filter(movie__user=user).values(
                "id", "movie_id", "end_date", "external_id"
            )
        ),
        "history": list(
            Movie.history.filter(history_user_id=user.pk)
            .order_by("history_id")
            .values(
                "id",
                "status",
                "score",
                "progress",
                "end_date",
                "history_date",
                "history_type",
                "history_user_id",
            )
        ),
        "lists": list(
            CustomList.objects.filter(owner=user).values(
                "id", "owner_id", "name", "visibility"
            )
        ),
        "membership": list(
            CustomListItem.objects.filter(custom_list__owner=user).values(
                "custom_list_id", "item_id"
            )
        ),
    },
    cls=DjangoJSONEncoder,
    sort_keys=True,
)
if os.environ["FLOPPY_UPGRADE_FIXTURE"] == "seed":
    snapshot_path.write_text(snapshot)
elif snapshot_path.read_text() != snapshot:
    message = "Upgrade changed retained user/library/history/list data"
    raise RuntimeError(message)
print(
    "Upgrade fixture preserved user, password, library, plays, history and private list"
)
