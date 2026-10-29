#!/usr/bin/env python3
"""Seed an isolated, synthetic Floppy SQLite DB at a chosen library size.

  SCALE_DB=/path/size_1000.sqlite3 PYTHONPATH=scripts:src \
      python scripts/scaling_seed.py --items 1000 [--shape big_show|big_list|one_day|ratings|unicode]

``--items`` is the number of tracked entries (movies, shows, games, books);
episodes, plays and lists scale with it. Never touches src/db. Prints the
username that scripts/scaling_sweep.py logs in with.
"""
# ruff: noqa: INP001, T201, S311
import argparse
import os
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "src")]
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("SECRET", "scaling-test")

parser = argparse.ArgumentParser()
parser.add_argument("--items", type=int, required=True)
parser.add_argument("--db", default=os.environ.get("SCALE_DB"))
parser.add_argument("--shape", action="append", default=[])
args = parser.parse_args()
if not args.db:
    sys.exit("--db or SCALE_DB required")
os.environ["SCALE_DB"] = args.db

import django  # noqa: E402
from django.conf import settings  # noqa: E402

settings.DATABASES["default"]["NAME"] = args.db
django.setup()
from django.contrib.auth import get_user_model  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.db import connection  # noqa: E402

call_command("migrate", verbosity=0)
with connection.cursor() as c:
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=OFF")

from app.models import Episode, Item, Movie, MoviePlay, Season, TV  # noqa: E402
from app.models import Game  # noqa: E402
from lists.models import CustomList, CustomListItem  # noqa: E402

rnd = random.Random(7)
now = datetime.now(UTC)
GENRES = ["Drama", "Comedy", "Action", "Sci-Fi", "Horror", "Romance", "Thriller"]
USER = "scale"
user, _ = get_user_model().objects.get_or_create(username=USER)
user.set_password("scale-pass-12345")
user.save()
N = args.items


def mk_items(n, media_type, prefix, **extra):
    objs = [
        Item(
            media_id=f"{prefix}{i}", source="manual", media_type=media_type,
            title=f"{prefix.upper()} Title {i} " + "x" * rnd.randint(0, 30),
            image="none", genres=rnd.sample(GENRES, 2),
            release_datetime=now - timedelta(days=rnd.randint(0, 9000)),
            **extra,
        )
        for i in range(n)
    ]
    Item.objects.bulk_create(objs, batch_size=2000)
    return list(Item.objects.filter(source="manual", media_type=media_type,
                                    media_id__startswith=prefix))


def status():
    return rnd.choice(["Completed", "Completed", "Planning", "In progress"])


n_movie, n_tv, n_game = int(N * 0.6), int(N * 0.15), int(N * 0.25)
movies = mk_items(n_movie, "movie", "m")
Movie.objects.bulk_create(
    [Movie(item=it, user=user, status=status(), score=rnd.randint(1, 10),
           end_date=now - timedelta(days=rnd.randint(0, 3000))) for it in movies],
    batch_size=2000)
mv = list(Movie.objects.filter(user=user))
MoviePlay.objects.bulk_create(
    [MoviePlay(movie=m, end_date=now - timedelta(days=rnd.randint(0, 3000)))
     for m in mv for _ in range(rnd.randint(1, 3))], batch_size=2000)

shows = mk_items(n_tv, "tv", "t")
tvs = TV.objects.bulk_create([TV(item=it, user=user, status=status()) for it in shows],
                             batch_size=2000)
tvs = list(TV.objects.filter(user=user))


def seasons_episodes(tv, n_eps, season_number=1):
    sitem = Item.objects.create(
        media_id=tv.item.media_id, source="manual", media_type="season",
        title=tv.item.title, image="none", season_number=season_number)
    season = Season.objects.create(item=sitem, user=user, related_tv=tv,
                                   status="Completed")
    eitems = Item.objects.bulk_create([
        Item(media_id=tv.item.media_id, source="manual", media_type="episode",
             title=tv.item.title, image="none", season_number=season_number,
             episode_number=e) for e in range(1, n_eps + 1)], batch_size=2000)
    eitems = list(Item.objects.filter(media_id=tv.item.media_id, media_type="episode",
                                      season_number=season_number))
    Episode.objects.bulk_create([
        Episode(item=ei, related_season=season,
                end_date=now - timedelta(days=rnd.randint(0, 3000)))
        for ei in eitems], batch_size=2000)
    return season


for tv in tvs:
    seasons_episodes(tv, rnd.randint(4, 12))

gitems = mk_items(n_game, "game", "g")
Game.objects.bulk_create(
    [Game(item=it, user=user, status=status(), score=rnd.randint(1, 10),
          end_date=now - timedelta(days=rnd.randint(0, 3000))) for it in gitems],
    batch_size=2000)

all_items = movies + gitems
for li in range(min(200, max(1, N // 100))):
    cl = CustomList.objects.create(name=f"List {li}", owner=user)
    CustomListItem.objects.bulk_create(
        [CustomListItem(item=it, custom_list=cl)
         for it in rnd.sample(all_items, min(50, len(all_items)))])

if "big_show" in args.shape:
    tv_item = mk_items(1, "tv", "bigshow")[0]
    tv = TV.objects.create(item=tv_item, user=user, status="In progress")
    seasons_episodes(tv, 3000)
if "big_list" in args.shape:
    cl = CustomList.objects.create(name="Big list", owner=user)
    pool = mk_items(5000, "movie", "bl")
    CustomListItem.objects.bulk_create([CustomListItem(item=it, custom_list=cl) for it in pool],
                                       batch_size=2000)
if "one_day" in args.shape:
    day = now - timedelta(days=1)
    pool = mk_items(200, "movie", "od")
    ms = Movie.objects.bulk_create([Movie(item=it, user=user, status="Completed") for it in pool])
    ms = list(Movie.objects.filter(item__in=pool))
    MoviePlay.objects.bulk_create(
        [MoviePlay(movie=rnd.choice(ms), end_date=day - timedelta(seconds=i)) for i in range(50000)],
        batch_size=2000)
if "ratings" in args.shape:
    pool = mk_items(10000, "movie", "rt")
    Movie.objects.bulk_create(
        [Movie(item=it, user=user, status="Completed", score=rnd.randint(1, 10),
               notes="review " * 50) for it in pool], batch_size=2000)
if "unicode" in args.shape:
    t = "長いタイトル🎬 ñandú " + "Ünïcödé " * 60
    it = Item.objects.create(media_id="uni", source="manual", media_type="movie",
                             title=t, image="none")
    Movie.objects.create(item=it, user=user, status="Completed", score=9)

print(f"seeded {args.db}: user={USER} items={Item.objects.count()} "
      f"plays={MoviePlay.objects.count()} episodes={Episode.objects.count()}")
