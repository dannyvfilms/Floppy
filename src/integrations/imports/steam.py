import logging
import time
from datetime import UTC, datetime

import requests
from django.db import transaction

import app
from app.models import MediaTypes, Sources, Status
from app.providers import credentials, services
from app.providers.igdb import ExternalGameSource, describe_credentials, external_game
from integrations.imports import helpers, playtime_sessions
from integrations.imports.helpers import MediaImportError, MediaImportUnexpectedError

logger = logging.getLogger(__name__)

STEAM_API_BASE_URL = "https://api.steampowered.com"
IMPORT_NOTE = "Imported from Steam"
SESSION_NOTE = "Steam play session"
SNAPSHOT_SOURCE = "steam"


def importer(steam_id, user, mode):
    """Import the user's games from Steam."""
    steam_importer = SteamImporter(steam_id, user, mode)
    return steam_importer.import_data()


class SteamImporter:
    """Class to handle importing user game data from Steam."""

    def __init__(self, steam_id, user, mode):
        """Initialize the importer with user details and mode.

        Args:
            steam_id (str): Steam user ID (64-bit SteamID) to import from
            user: Django user object to import data for
            mode (str): Import mode ("new" or "overwrite")
        """
        self.steam_id = steam_id
        self.user = user
        self.mode = mode
        self.warnings = []
        self.api_key = credentials.get("steam", "api_key", user=user)

        if not self.api_key:
            msg = "Steam API key not configured in environment variables"
            raise MediaImportError(msg)

        self.existing_media = helpers.get_existing_media(user)
        self.sessions = playtime_sessions.PlaytimeSessionLogger(
            user,
            source=SNAPSHOT_SOURCE,
            account=steam_id,
            mode=mode,
            import_note=IMPORT_NOTE,
            session_note=SESSION_NOTE,
            existing_media=self.existing_media,
        )
        # Steam titles merged per IGDB game, so two app IDs that resolve to
        # the same game add up instead of logging each other's playtime.
        self.observations = {}

        logger.info(
            "Initialized Steam importer for Steam ID %s with mode %s "
            "(steam_key_from=%s; igdb %s)",
            steam_id,
            mode,
            credentials.source_of("steam", "api_key", user),
            describe_credentials(user),
        )

    def import_data(self):
        """Import user's Steam game library."""
        owned_games = self._get_owned_games()

        if not owned_games:
            logger.info("No games found for Steam user %s", self.steam_id)
            return {}, ""

        for game_data in owned_games:
            self._process_game(game_data)

        for media_id, observation in self.observations.items():
            self.sessions.store(
                media_id,
                observation,
                status=self._determine_game_status(
                    observation.minutes or 0,
                    observation.recent_minutes or 0,
                ),
            )

        # One transaction, so a failed snapshot save can't leave logged play
        # without its remembered total (it would be logged again next sync).
        with transaction.atomic():
            helpers.bulk_create_media(
                {MediaTypes.GAME.value: self.sessions.rows}, self.user
            )
            if self.sessions.to_update:
                app.models.Game.objects.bulk_update(
                    self.sessions.to_update, fields=["progress", "status"]
                )
            self.sessions.save_snapshots()

        updated_items = [
            game.item
            for media_id in self.observations
            if (game := self.sessions.existing_games.get(media_id))
        ]
        if updated_items:
            app.models.Item.objects.bulk_update(
                updated_items, fields=["title", "image"]
            )

        # Updates and sessions are reported too: a sync that only added play
        # otherwise reads as "No media was imported" and skips the cache
        # refresh that makes the new hours show up in History and Statistics.
        imported_counts = self.sessions.counts()

        logger.info(
            "Steam import completed for user %s: %s",
            self.user.username,
            imported_counts,
        )

        return imported_counts, "\n".join(self.warnings) if self.warnings else ""

    def _get_owned_games(self):
        """Fetch owned games from Steam API with retry logic for rate limiting."""
        url = f"{STEAM_API_BASE_URL}/IPlayerService/GetOwnedGames/v0001/"
        params = {
            "key": self.api_key,
            "steamid": self.steam_id,
            "include_appinfo": 1,
            "include_played_free_games": 1,
            "format": "json",
        }

        max_retries = 3
        base_delay = 15

        for attempt in range(max_retries):
            try:
                response = services.api_request("STEAM", "GET", url, params=params)

                if "response" not in response:
                    msg = "Invalid response from Steam API"
                    raise MediaImportError(msg)

                if "games" not in response["response"]:
                    # User might have private profile or no games
                    logger.warning(
                        "No games found in Steam response for user %s",
                        self.steam_id,
                    )
                    return []

                games = response["response"]["games"]
                logger.info(
                    "Found %d games for Steam user %s",
                    len(games),
                    self.steam_id,
                )
                return games  # noqa: TRY300

            except requests.HTTPError as e:
                if e.response.status_code == requests.codes.too_many_requests:
                    if attempt < max_retries - 1:
                        delay = base_delay * (2**attempt)
                        logger.warning(
                            "Steam API rate limited (429). "
                            "Retrying in %d seconds (attempt %d/%d)",
                            delay,
                            attempt + 1,
                            max_retries,
                        )
                        time.sleep(delay)
                        continue
                    msg = "Steam API rate limit exceeded. Please try again later."
                    raise MediaImportError(msg) from e
                if e.response.status_code == requests.codes.forbidden:
                    msg = "Steam profile is private or invalid"
                    raise MediaImportError(msg) from e
                if e.response.status_code == requests.codes.bad_request:
                    msg = "Bad request to Steam API. Please check the Steam ID."
                    raise MediaImportError(msg) from e
                if e.response.status_code == requests.codes.unauthorized:
                    msg = "Invalid Steam API key"
                    raise MediaImportError(msg) from e
                msg = f"Steam API error: {e.response.status_code}"
                raise MediaImportError(msg) from e

        msg = "Steam API request failed after all retries"
        raise MediaImportUnexpectedError(msg)

    def _process_game(self, game_data):
        """Process a single game from Steam API response."""
        appid = str(game_data["appid"])
        name = game_data.get("name", f"Unknown Game {appid}")
        playtime_forever = game_data.get("playtime_forever", 0)  # in minutes
        playtime_2weeks = game_data.get("playtime_2weeks", 0)  # in minutes

        try:
            # Try to match with IGDB
            igdb_game = self._match_with_igdb(name, appid)

            if not igdb_game:
                # Skip games that can't be matched to IGDB
                logger.debug(
                    "Skipping Steam game %s (appid: %s) - no IGDB match found",
                    name,
                    appid,
                )
                self.warnings.append(
                    f"{name} ({appid}): Couldn't find a match in {Sources.IGDB.label}",
                )
                return

            media_id = str(igdb_game["media_id"])
            last_played = game_data.get("rtime_last_played")
            observation = self.observations.setdefault(
                media_id,
                playtime_sessions.PlaytimeObservation(
                    title=igdb_game["title"],
                    image=igdb_game["image"],
                ),
            )
            observation.merge(
                playtime_forever,
                playtime_2weeks,
                datetime.fromtimestamp(int(last_played), tz=UTC)
                if last_played
                else None,
            )

        except services.ProviderAPIError as e:
            msg = str(e).lower()
            is_not_found = "game with id" in msg and "not found" in msg
            if not is_not_found:
                # still raise all other errors
                raise

            logger.debug(
                "Skipping Steam game %s (appid: %s) - IGDB not found: %s",
                name,
                appid,
                e,
            )
            self.warnings.append(
                f"{name} ({appid}): Couldn't find a match in {Sources.IGDB.label}"
            )

        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Failed to process Steam game %s (%s): %s", name, appid, e)
            self.warnings.append(f"{name} ({appid}): {e!s}")

    def _determine_game_status(self, playtime_forever, playtime_2weeks):
        """Determine game status based on Steam playtime data.

        Args:
            playtime_forever (int): Total playtime in minutes
            playtime_2weeks (int): Playtime in last 2 weeks in minutes

        Returns:
            str: Status value from Status choices
        """
        # Games with no playtime are considered "Planning"
        if playtime_forever == 0:
            return Status.PLANNING.value

        # Games played in the last 2 weeks are "In Progress"
        if playtime_2weeks > 0:
            return Status.IN_PROGRESS.value

        # Games with total playtime but no recent activity are "On Hold"
        return Status.PAUSED.value

    def _match_with_igdb(self, game_name, steam_appid):
        """Try to match Steam game with IGDB using External Game endpoint."""
        # Try to find IGDB game by Steam App ID using external_game endpoint

        igdb_game_id = external_game(steam_appid, ExternalGameSource.STEAM)

        if not igdb_game_id:
            return None

        # Get the game details using the IGDB ID
        game_details = services.get_media_metadata(
            MediaTypes.GAME.value,
            str(igdb_game_id),
            Sources.IGDB.value,
        )

        logger.debug(
            "Matched Steam game %s (appid: %s) with IGDB ID %s via external_game",
            game_name,
            steam_appid,
            igdb_game_id,
        )
        return {
            "media_id": igdb_game_id,
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "title": game_details.get("title", game_name),
            "image": game_details["image"],
        }
