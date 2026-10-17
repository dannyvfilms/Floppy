"""Import the authenticated user's owned itch.io library as custom games."""
import logging
from collections import defaultdict
from http import HTTPStatus
import requests
import app
from app.models import Item, MediaTypes, Sources, Status
from app.providers import credentials
from integrations.imports import helpers
from integrations.imports.helpers import ConnectionAuthError, MediaImportError

logger = logging.getLogger(__name__)
ITCHIO_OWNED_KEYS_URL = "https://api.itch.io/profile/owned-keys"
IMPORT_NOTE = "Imported from itch.io"

def importer(_identifier, user, mode):
    """Import owned itch.io games directly as Floppy custom entries."""
    return ItchioImporter(user, mode).import_data()

class ItchioImporter:
    """Fetch owned keys and create manual game records without IGDB matching."""
    def __init__(self, user, mode):
        self.user = user
        self.mode = mode
        self.token = credentials.get("itchio", "api_key", user=user)
        if not self.token:
            raise MediaImportError("itch.io API key is not configured.")
        self.existing_media = helpers.get_existing_media(user)
        self.bulk_media = defaultdict(list)
        self.to_update_items = []
        self.warnings = []

    def import_data(self):
        games = self._get_owned_games()
        for game in games:
            self._process_game(game)
        helpers.bulk_create_media(self.bulk_media, self.user)
        if self.to_update_items:
            Item.objects.bulk_update(self.to_update_items, fields=["title", "image", "source_url"])
        created = len(self.bulk_media[MediaTypes.GAME.value])
        updated = len(self.to_update_items)
        counts = {MediaTypes.GAME.value: created, "created": created, "updated": updated}
        logger.info("itch.io import completed for user %s: %s", self.user.username, counts)
        return counts, "\n".join(self.warnings)

    def _get_owned_games(self):
        games = []
        seen_ids = set()
        page = 1
        while True:
            try:
                response = requests.get(
                    ITCHIO_OWNED_KEYS_URL,
                    headers={"Authorization": f"Bearer {self.token}"},
                    params={"page": page, "per_page": 500},
                    timeout=30,
                )
            except requests.RequestException as error:
                raise MediaImportError(
                    f"Could not reach itch.io ({type(error).__name__})."
                ) from error
            if response.status_code in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
                raise ConnectionAuthError("itch.io API key is invalid or unauthorized.")
            if response.status_code >= HTTPStatus.BAD_REQUEST:
                raise MediaImportError(f"itch.io request failed ({response.status_code}).")
            try:
                payload = response.json()
            except ValueError as error:
                raise MediaImportError("itch.io returned invalid JSON.") from error
            if payload.get("errors"):
                raise MediaImportError("itch.io API returned an error.")
            owned_keys = payload.get("owned_keys")
            if not isinstance(owned_keys, list):
                raise MediaImportError("itch.io returned an unexpected owned-keys response.")
            if not owned_keys:
                break
            for owned_key in owned_keys:
                game = owned_key.get("game") or {}
                game_id = game.get("id") or owned_key.get("game_id")
                title = (game.get("title") or "").strip()
                if not game_id or not title or str(game_id) in seen_ids:
                    continue
                seen_ids.add(str(game_id))
                games.append({
                    "id": str(game_id),
                    "title": title,
                    "url": game.get("url") or "",
                    "image": game.get("cover_url") or "",
                })
            page += 1
        return games

    def _process_game(self, game):
        media_id = f"itchio-{game['id']}"
        media = self.existing_media[MediaTypes.GAME.value][Sources.MANUAL.value].get(media_id)
        if media:
            if self.mode == "overwrite":
                item = media.item
                changed = False
                for field, value in (
                    ("title", game["title"]),
                    ("image", game["image"]),
                    ("source_url", game["url"]),
                ):
                    if value and getattr(item, field) != value:
                        setattr(item, field, value)
                        changed = True
                if changed:
                    self.to_update_items.append(item)
            return
        item, _ = Item.objects.get_or_create(
            media_id=media_id,
            source=Sources.MANUAL.value,
            media_type=MediaTypes.GAME.value,
            library_media_type=MediaTypes.GAME.value,
            defaults={
                "title": game["title"],
                "image": game["image"],
                "source_url": game["url"],
            },
        )
        self.bulk_media[MediaTypes.GAME.value].append(
            app.models.Game(
                item=item,
                user=self.user,
                status=Status.PLANNING.value,
                score=None,
                progress=0,
                notes=IMPORT_NOTE,
                start_date=None,
                end_date=None,
                entry_source="itch.io",
            )
        )
