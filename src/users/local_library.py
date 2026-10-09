"""Sample library for local tile and media-type checks.

Rows are keyed by ``tile-seed-*`` media ids. Running this twice updates those
rows and does not touch anything else in the database.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from django.apps import apps
from django.contrib.auth import get_user_model
from django.utils import timezone

from app.models.choices import MediaTypes, Sources, Status
from app.models.item import Item
from users.demo import ensure_demo_user
from users.card_metadata import (
    CARD_FIELDS,
    DISPLAY_DORMANT,
    MAX_LINE_FIELDS,
    PROFILE_TYPES,
    parse_card_metadata,
)

LOCAL_USERNAME = "joe"
LOCAL_PASSWORD = "localtiles"  # noqa: S105
LOCAL_EMAIL = "joe@example.com"
RELEASE = datetime(2024, 3, 12, 12, tzinfo=UTC)
SEED = "tile-seed"
_PROFILE_FIELD_ORDER = (
    "release_year",
    "genres",
    "runtime",
    "status",
    "rating",
    "last_played",
    "progress",
    "synopsis",
    "episode_code",
    "show_name",
    "artist",
    "album",
    "track_number",
    "author",
    "series_position",
    "role",
)

_TRACKED = (
    {
        "media_type": MediaTypes.MOVIE.value,
        "model": "Movie",
        "media_id": f"{SEED}-movie-1",
        "title": "Borat Subsequent Moviefilm: Delivery of Prodigious Bribe to American Regime for Make Benefit Once Glorious Nation of Kazakhstan",
        "image": "https://image.tmdb.org/t/p/w500/3L1Ml5RWjFVfVq3rQENvgFymT0U.jpg",
        "synopsis": "14 years after making a film about his journey across the USA, Borat risks life and limb when he returns to the United States with his young daughter.",
        "genres": ["Comedy"],
        "runtime": 96,
        "year": 2020,
        "progress": 1,
        "status": Status.COMPLETED.value,
    },
    {
        "media_type": MediaTypes.MOVIE.value,
        "model": "Movie",
        "media_id": f"{SEED}-movie-2",
        "title": "Dr. Strangelove or: How I Learned to Stop Worrying and Love the Bomb",
        "image": "https://image.tmdb.org/t/p/w500/gHm96BRW4GoI339rF1vYoYTB6Qe.jpg",
        "synopsis": "After the insane General Jack D. Ripper initiates a nuclear strike on the Soviet Union, a war room full of politicians, generals and a Russian diplomat all frantically try to stop it.",
        "genres": ["Comedy", "War"],
        "runtime": 95,
        "year": 1964,
        "progress": 1,
        "status": Status.COMPLETED.value,
    },
    {
        "media_type": MediaTypes.ANIME.value,
        "model": "Anime",
        "media_id": f"{SEED}-anime-1",
        "title": "I've Been Killing Slimes for 300 Years and Maxed Out My Level",
        "image": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/large/bx112608-T3OKdLhxYUfe.png",
        "synopsis": "An office worker dies from overwork and is reborn as an immortal witch who spends three centuries killing slimes.",
        "genres": ["Fantasy", "Comedy"],
        "runtime": 24,
        "year": 2021,
        "progress": 8,
    },
    {
        "media_type": MediaTypes.ANIME.value,
        "model": "Anime",
        "media_id": f"{SEED}-anime-2",
        "title": "My Next Life as a Villainess: All Routes Lead to Doom!",
        "image": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/large/bx104647-dMGZSavRxHcM.jpg",
        "synopsis": "A girl is reborn as the villainess of the otome game she was playing, and every route ends with her doom.",
        "genres": ["Fantasy", "Comedy"],
        "runtime": 24,
        "year": 2020,
        "progress": 12,
    },
    {
        "media_type": MediaTypes.MANGA.value,
        "model": "Manga",
        "media_id": f"{SEED}-manga-1",
        "title": "Didn't I Say to Make My Abilities Average in the Next Life?!",
        "image": "https://s4.anilist.co/file/anilistcdn/media/manga/cover/large/nx99102-DGXEjeRwT5bi.jpg",
        "synopsis": "A girl who asked for an average life is reborn with so much power that average is nowhere in sight.",
        "genres": ["Fantasy", "Comedy"],
        "runtime": 22,
        "year": 2016,
        "progress": 20,
        "authors": ["FUNA"],
    },
    {
        "media_type": MediaTypes.MANGA.value,
        "model": "Manga",
        "media_id": f"{SEED}-manga-2",
        "title": "Reborn as a Vending Machine, I Now Wander the Dungeon",
        "image": "https://s4.anilist.co/file/anilistcdn/media/manga/cover/large/nx97406-iKOEyJxxPHpV.jpg",
        "synopsis": "A man dies and wakes up as a vending machine in a dungeon, helping adventurers one purchase at a time.",
        "genres": ["Fantasy", "Comedy"],
        "runtime": 22,
        "year": 2016,
        "progress": 42,
        "authors": ["Hirukuma"],
    },
    {
        "media_type": MediaTypes.GAME.value,
        "model": "Game",
        "media_id": f"{SEED}-game-1",
        "title": "The Legend of Heroes: Trails through Daybreak",
        "image": "https://cdn.cloudflare.steamstatic.com/steam/apps/2138610/library_600x900.jpg",
        "synopsis": "A spriggan in the Calvard Republic takes jobs that pull him into a conspiracy reaching the highest offices.",
        "genres": ["RPG"],
        "runtime": 90,
        "year": 2023,
        "progress": 600,
    },
    {
        "media_type": MediaTypes.GAME.value,
        "model": "Game",
        "media_id": f"{SEED}-game-2",
        "title": "Atelier Ryza: Ever Darkness & the Secret Hideout",
        "image": "https://cdn.cloudflare.steamstatic.com/steam/apps/1121560/library_600x900.jpg",
        "synopsis": "Ryza and her friends leave their island routine behind and learn alchemy while a ruined hideout gives up its secrets.",
        "genres": ["RPG"],
        "runtime": 90,
        "year": 2019,
        "progress": 840,
    },
    {
        "media_type": MediaTypes.BOOK.value,
        "model": "Book",
        "media_id": f"{SEED}-book-1",
        "title": "The Girl Who Circumnavigated Fairyland in a Ship of Her Own Making",
        "image": "https://covers.openlibrary.org/b/id/8260451-L.jpg",
        "synopsis": "September is swept from her home to Fairyland, where she has to sail a ship she builds herself.",
        "genres": ["Fantasy"],
        "runtime": 390,
        "year": 2011,
        "progress": 120,
        "authors": ["Catherynne M. Valente"],
        "series_position": 1,
        "number_of_pages": 247,
    },
    {
        "media_type": MediaTypes.BOOK.value,
        "model": "Book",
        "media_id": f"{SEED}-book-2",
        "title": "The Hundred-Year-Old Man Who Climbed Out of the Window and Disappeared",
        "image": "https://covers.openlibrary.org/b/id/12659466-L.jpg",
        "synopsis": "Allan Karlsson climbs out of his nursing-home window on his hundredth birthday and walks into a century of unlikely history.",
        "genres": ["Fiction"],
        "runtime": 412,
        "year": 2009,
        "progress": 180,
        "authors": ["Jonas Jonasson"],
        "series_position": 1,
        "number_of_pages": 384,
    },
    {
        "media_type": MediaTypes.COMIC.value,
        "model": "Comic",
        "media_id": f"{SEED}-comic-1",
        "title": "Something is Killing the Children",
        "image": "https://comicvine.gamespot.com/a/uploads/scale_medium/6/67663/7384691-01.jpg",
        "synopsis": "Erica Slaughter arrives in a town where something in the woods is taking the children, and only she can see it.",
        "genres": ["Horror"],
        "runtime": 28,
        "year": 2019,
        "progress": 4,
        "authors": ["James Tynion IV"],
    },
    {
        "media_type": MediaTypes.COMIC.value,
        "model": "Comic",
        "media_id": f"{SEED}-comic-2",
        "title": "The League of Extraordinary Gentlemen",
        "image": "https://upload.wikimedia.org/wikipedia/en/1/10/League_of_Extraordinary_Gentlemen_%28Absolute_edition%2C_vol._1%29_%28cover_art%29.jpg",
        "synopsis": "Allan Quatermain, Mina Murray, and the rest of a Victorian league are assembled for a mission the Empire will not admit to.",
        "genres": ["Adventure"],
        "runtime": 28,
        "year": 1999,
        "progress": 6,
        "authors": ["Alan Moore"],
    },
    {
        "media_type": MediaTypes.COMIC_ISSUE.value,
        "model": "ComicIssue",
        "media_id": f"{SEED}-comicissue-1",
        "title": "Something is Killing the Children",
        "image": "https://comicvine.gamespot.com/a/uploads/scale_medium/6/67663/7384691-01.jpg",
        "synopsis": "The first issue. Erica Slaughter comes to Archer's Peak because the children there are disappearing.",
        "genres": ["Horror"],
        "runtime": 24,
        "year": 2019,
        "progress": 1,
        "authors": ["James Tynion IV"],
    },
    {
        "media_type": MediaTypes.COMIC_ISSUE.value,
        "model": "ComicIssue",
        "media_id": f"{SEED}-comicissue-2",
        "title": "The League of Extraordinary Gentlemen",
        "image": "https://upload.wikimedia.org/wikipedia/en/1/10/League_of_Extraordinary_Gentlemen_%28Absolute_edition%2C_vol._1%29_%28cover_art%29.jpg",
        "synopsis": "Campion Bond collects the league. Mina Murray is not interested until the terms leave her no other door.",
        "genres": ["Adventure"],
        "runtime": 24,
        "year": 1999,
        "progress": 1,
        "authors": ["Alan Moore"],
    },
    {
        "media_type": MediaTypes.BOARDGAME.value,
        "model": "BoardGame",
        "media_id": f"{SEED}-boardgame-1",
        "title": "Through the Ages: A Story of Civilization",
        "image": "https://upload.wikimedia.org/wikipedia/en/f/f5/Through_the_Ages%2C_A_Story_of_Civilization_board_game_box_cover.jpg",
        "synopsis": "Players build a civilization from antiquity onward, spending actions on government, wonders, and wars.",
        "genres": ["Strategy"],
        "runtime": 120,
        "year": 2006,
        "progress": 3,
    },
    {
        "media_type": MediaTypes.BOARDGAME.value,
        "model": "BoardGame",
        "media_id": f"{SEED}-boardgame-2",
        "title": "Oath: Chronicles of Empire and Exile",
        "image": "https://upload.wikimedia.org/wikipedia/en/7/77/Oath_Chronicles_of_Empire_and_Exile_box_cover.png",
        "synopsis": "One player rules a crumbling empire while the others try to become the chronicle the next game will remember.",
        "genres": ["Strategy"],
        "runtime": 120,
        "year": 2021,
        "progress": 5,
    },
    {
        "media_type": MediaTypes.PODCAST.value,
        "model": "Podcast",
        "media_id": f"{SEED}-podcast-1",
        "title": "My Favorite Murder with Karen Kilgariff and Georgia Hardstark",
        "image": "https://is1-ssl.mzstatic.com/image/thumb/Podcasts211/v4/1b/80/b1/1b80b146-8608-f76f-97e7-7a2317549c35/mza_14115126871478479568.jpg/600x600bb.jpg",
        "synopsis": "Karen Kilgariff and Georgia Hardstark tell each other their favorite murders, and the stories around them.",
        "genres": ["Comedy", "True Crime"],
        "runtime": 60,
        "year": 2016,
        "progress": 20,
    },
    {
        "media_type": MediaTypes.PODCAST.value,
        "model": "Podcast",
        "media_id": f"{SEED}-podcast-2",
        "title": "Just Jack & Will with Sean Hayes and Eric McCormack",
        "image": "https://is1-ssl.mzstatic.com/image/thumb/Podcasts221/v4/3a/d6/18/3ad61842-b530-73d7-f945-b4968ff06f31/mza_13944847449269089789.jpg/600x600bb.jpg",
        "synopsis": "Sean Hayes and Eric McCormack revisit Will & Grace, one episode at a time.",
        "genres": ["Comedy", "TV"],
        "runtime": 50,
        "year": 2024,
        "progress": 28,
    },
)

_SHOWS = (
    {
        "media_id": f"{SEED}-tv-1",
        "title": "The Real Housewives of Beverly Hills",
        "image": "https://image.tmdb.org/t/p/w500/8ktaCSlCgGDMFzgdYc1LYF6CiWq.jpg",
        "synopsis": "A reality series that follows some of the most affluent women in the country as they enjoy the lavish lifestyle that only Beverly Hills can provide.",
        "year": 2010,
        "episodes": (
            {
                "number": 1,
                "title": "Life, Liberty and the Pursuit of Wealthiness",
                "image": "https://image.tmdb.org/t/p/w500/jW5xNaPUvDuKTYHYDUj4xTGMgxL.jpg",
            },
            {
                "number": 2,
                "title": "Chocolate Louboutins",
                "image": "https://image.tmdb.org/t/p/w500/Acczrj1RiLCA359rO1Gi6rPFlfB.jpg",
            },
        ),
    },
    {
        "media_id": f"{SEED}-tv-2",
        "title": "The Adventures of Rocky and Bullwinkle and Friends",
        "image": "https://image.tmdb.org/t/p/w500/9PPb1vcRpkY94D4dpUsteVif8ql.jpg",
        "synopsis": "Rocky, a plucky flying squirrel and Bullwinkle, a bumbling but lovable moose, have a series of ongoing adventures.",
        "year": 1959,
        "episodes": (
            {
                "number": 1,
                "title": "Jet Fuel Formula",
                "image": "https://image.tmdb.org/t/p/w500/vF79lImCtx4SERmDKclIKnOFUxM.jpg",
            },
            {
                "number": 2,
                "title": "Jet Fuel Formula / Puss and Boots",
                "image": "https://image.tmdb.org/t/p/w500/t5UIys2XHe1zb8q9lzfeZOVTGyV.jpg",
            },
        ),
    },
)


def seed_local_library():
    """Upsert the sample library for the demo account and ``joe``.

    Returns the number of sample items touched.
    """
    users = [ensure_demo_user(), _ensure_local_user()]
    played = timezone.now() - timedelta(days=3)
    touched = 0
    profiles = _full_tile_profiles()
    for user in users:
        user.card_metadata = profiles
        user.save(update_fields=["card_metadata"])
        for row in _TRACKED:
            _seed_tracked(user, row, played)
            touched += 1
        for show in _SHOWS:
            _seed_show(user, show, played)
            touched += 1
        _seed_music(user, played)
        touched += 1
    _seed_cast()
    return touched


def _full_tile_profiles():
    """Return a profile that turns on every field each type can show.

    Lines stay visible at rest so a local check does not depend on hover.
    """
    types = {}
    for media_type in PROFILE_TYPES:
        allowed = [
            field_id
            for field_id in _PROFILE_FIELD_ORDER
            if media_type in CARD_FIELDS[field_id]["types"]
        ]
        lines = [
            {
                "fields": allowed[start : start + MAX_LINE_FIELDS],
                "display": DISPLAY_DORMANT,
            }
            for start in range(0, len(allowed), MAX_LINE_FIELDS)
        ]
        types[media_type] = {"display": "always", "lines": lines}
    return parse_card_metadata({"types": types})


def _ensure_local_user():
    """Return the local ``joe`` account, creating it on a fresh database."""
    user_model = get_user_model()
    user, created = user_model.objects.get_or_create(
        username=LOCAL_USERNAME,
        defaults={
            "email": LOCAL_EMAIL,
            "is_active": True,
            "is_demo": False,
            "is_staff": False,
            "is_superuser": False,
        },
    )
    if created:
        user.set_password(LOCAL_PASSWORD)
        user.save(update_fields=["password"])
    return user


def _upsert_item(
    *,
    media_id,
    media_type,
    title,
    genres,
    runtime,
    season_number=None,
    episode_number=None,
    authors=None,
    series_position=None,
    number_of_pages=None,
    image="",
    synopsis="",
    year=None,
):
    """Create or refresh one sample item."""
    released = datetime(year, 1, 1, tzinfo=UTC) if year else RELEASE
    item, _created = Item.objects.update_or_create(
        media_id=media_id,
        source=Sources.MANUAL.value,
        media_type=media_type,
        season_number=season_number,
        episode_number=episode_number,
        defaults={
            "title": title,
            "image": image,
            "genres": genres,
            "runtime_minutes": runtime,
            "synopsis": synopsis,
            "release_datetime": released,
            "authors": authors or [],
            "series_position": series_position,
            "number_of_pages": number_of_pages,
        },
    )
    return item


def _upsert_row(model, lookup, values):
    """Write ``values`` onto the row matching ``lookup``, without ``save()``.

    ``save()`` on a media row asks providers for metadata. Sample data must
    not do that.
    """
    concrete = {field.name for field in model._meta.concrete_fields}
    payload = {key: value for key, value in values.items() if key in concrete}
    row = model.objects.filter(**lookup).only("id").first()
    if row is None:
        model.objects.bulk_create([model(**lookup, **payload)])
        return
    model.objects.filter(pk=row.pk).update(**payload)


def _tracking(played, *, progress, status, score="8.0"):
    """Return the tracking columns a sample row should show."""
    return {
        "status": status,
        "score": Decimal(score),
        "scored_at": played,
        "progress": progress,
        "progressed_at": played,
        "start_date": played - timedelta(days=1),
        "end_date": played,
        "notes": "",
    }


def _seed_tracked(user, row, played):
    """Upsert one non-TV sample and its tracking row."""
    item = _upsert_item(
        media_id=row["media_id"],
        media_type=row["media_type"],
        title=row["title"],
        genres=row["genres"],
        runtime=row["runtime"],
        authors=row.get("authors"),
        series_position=row.get("series_position"),
        number_of_pages=row.get("number_of_pages"),
        image=row.get("image", ""),
        synopsis=row.get("synopsis", ""),
        year=row.get("year"),
    )
    model = apps.get_model("app", row["model"])
    _upsert_row(
        model,
        {"user": user, "item": item},
        _tracking(played, progress=row["progress"], status=row.get("status", Status.IN_PROGRESS.value)),
    )


def _seed_show(user, show, played):
    """Upsert a show, one season, and two completed episodes."""
    show_item = _upsert_item(
        media_id=show["media_id"],
        media_type=MediaTypes.TV.value,
        title=show["title"],
        genres=["Comedy"],
        runtime=43,
        image=show.get("image", ""),
        synopsis=show.get("synopsis", ""),
        year=show.get("year"),
    )
    tv_model = apps.get_model("app", "TV")
    season_model = apps.get_model("app", "Season")
    episode_model = apps.get_model("app", "Episode")
    _upsert_row(
        tv_model,
        {"user": user, "item": show_item},
        _tracking(played, progress=0, status=Status.IN_PROGRESS.value),
    )
    tv = tv_model.objects.get(user=user, item=show_item)
    season_item = _upsert_item(
        media_id=show["media_id"],
        media_type=MediaTypes.SEASON.value,
        title=f"{show['title']}: Season 1",
        genres=["Comedy"],
        runtime=43,
        season_number=1,
        image=show.get("image", ""),
        synopsis=show.get("synopsis", ""),
        year=show.get("year"),
    )
    _upsert_row(
        season_model,
        {"user": user, "item": season_item, "related_tv": tv},
        _tracking(played, progress=0, status=Status.IN_PROGRESS.value),
    )
    season = season_model.objects.get(user=user, item=season_item)
    keep_numbers = [episode["number"] for episode in show["episodes"]]
    Item.objects.filter(
        source=Sources.MANUAL.value,
        media_type=MediaTypes.EPISODE.value,
        media_id=show["media_id"],
    ).exclude(episode_number__in=keep_numbers).delete()
    for episode in show["episodes"]:
        number = episode["number"]
        episode_item = _upsert_item(
            media_id=show["media_id"],
            media_type=MediaTypes.EPISODE.value,
            title=f"{show['title']}: {episode['title']}",
            genres=["Comedy"],
            runtime=44,
            season_number=1,
            episode_number=number,
            image=episode.get("image") or show.get("image", ""),
            synopsis=show.get("synopsis", ""),
            year=show.get("year"),
        )
        _upsert_row(
            episode_model,
            {"related_season": season, "item": episode_item},
            _tracking(
                played,
                progress=0,
                status=Status.COMPLETED.value,
                score="8.0",
            ),
        )


def _seed_music(user, played):
    """Upsert one artist, album, track, and play for this account."""
    artist_model = apps.get_model("app", "Artist")
    album_model = apps.get_model("app", "Album")
    track_model = apps.get_model("app", "Track")
    music_model = apps.get_model("app", "Music")
    tracker_model = apps.get_model("app", "AlbumTracker")
    artist, _created = artist_model.objects.get_or_create(
        musicbrainz_id=f"{SEED}-mina",
        defaults={"name": "David Bowie", "genres": ["Rock"]},
    )
    artist_model.objects.filter(pk=artist.pk).update(
        name="David Bowie",
        image="https://upload.wikimedia.org/wikipedia/commons/e/e8/David-Bowie_Chicago_2002-08-08_photoby_Adam-Bielawski-cropped.jpg",
        genres=["Rock"],
    )
    album, _created = album_model.objects.get_or_create(
        artist=artist,
        musicbrainz_release_group_id=f"{SEED}-room-tone",
        defaults={
            "title": "The Rise and Fall of Ziggy Stardust and the Spiders From Mars",
            "release_date": datetime(1972, 6, 16, tzinfo=UTC).date(),
            "genres": ["Rock", "Glam"],
        },
    )
    album_model.objects.filter(pk=album.pk).update(
        title="The Rise and Fall of Ziggy Stardust and the Spiders From Mars",
        image="https://coverartarchive.org/release-group/6c9ae3dd-32ad-472c-96be-69d0a3536261/front-500",
        release_date=datetime(1972, 6, 16, tzinfo=UTC).date(),
        genres=["Rock", "Glam"],
    )
    track, _created = track_model.objects.get_or_create(
        album=album,
        disc_number=1,
        track_number=1,
        defaults={
            "title": "Rock 'n' Roll Suicide",
            "duration_ms": 177000,
            "genres": ["Rock", "Glam"],
        },
    )
    track_model.objects.filter(pk=track.pk).update(
        title="Rock 'n' Roll Suicide",
        duration_ms=177000,
        genres=["Rock", "Glam"],
    )
    item = _upsert_item(
        media_id=f"{SEED}-music-{user.username}",
        media_type=MediaTypes.MUSIC.value,
        title="The Rise and Fall of Ziggy Stardust and the Spiders From Mars",
        image="https://coverartarchive.org/release-group/6c9ae3dd-32ad-472c-96be-69d0a3536261/front-500",
        synopsis="David Bowie's 1972 album, played here as Rock 'n' Roll Suicide.",
        genres=["Rock", "Glam"],
        runtime=6,
        year=1972,
    )
    _upsert_row(
        music_model,
        {"user": user, "item": item},
        {
            **_tracking(played, progress=3, status=Status.IN_PROGRESS.value, score="8.5"),
            "album": album,
            "artist": artist,
            "track": track,
        },
    )
    _upsert_row(
        tracker_model,
        {"user": user, "album": album},
        _tracking(played, progress=0, status=Status.IN_PROGRESS.value, score="8.0"),
    )


def _seed_cast():
    """Attach one cast credit to each sample movie."""
    person_model = apps.get_model("app", "Person")
    credit_model = apps.get_model("app", "ItemPersonCredit")
    person, _created = person_model.objects.get_or_create(
        source=Sources.MANUAL.value,
        source_person_id=f"{SEED}-ada",
        defaults={
            "name": "Alejandro González Iñárritu",
            "image": "https://upload.wikimedia.org/wikipedia/commons/0/04/MKr386809_Alejandro_Gonz%C3%A1lez_I%C3%B1%C3%A1rritu_%28Amores_Perros%2C_Cannes_2025%29.jpg",
            "known_for_department": "Directing",
            "biography": "Mexican filmmaker. Sample credit so the person tile has a name and a portrait.",
        },
    )
    person_model.objects.filter(pk=person.pk).update(
        name="Alejandro González Iñárritu",
        image="https://upload.wikimedia.org/wikipedia/commons/0/04/MKr386809_Alejandro_Gonz%C3%A1lez_I%C3%B1%C3%A1rritu_%28Amores_Perros%2C_Cannes_2025%29.jpg",
        known_for_department="Directing",
        biography="Mexican filmmaker. Sample credit so the person tile has a name and a portrait.",
    )
    movies = Item.objects.filter(
        source=Sources.MANUAL.value,
        media_type=MediaTypes.MOVIE.value,
        media_id__in=(f"{SEED}-movie-1", f"{SEED}-movie-2"),
    )
    for item in movies:
        credit = credit_model.objects.filter(
            item=item,
            person=person,
            role_type="cast",
        ).only("id").first()
        if credit is None:
            credit_model.objects.bulk_create(
                [
                    credit_model(
                        item=item,
                        person=person,
                        role_type="cast",
                        role="Director",
                        department="Directing",
                    )
                ]
            )
            continue
        credit_model.objects.filter(pk=credit.pk).update(
            role="Director",
            department="Directing",
        )
