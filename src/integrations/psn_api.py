"""PlayStation Network API client for played-titles data.

Sony has no public PSN API, so this goes through psnawp, which talks to the
same endpoints the PlayStation app uses. The user authenticates by pasting
their NPSSO token, obtained from https://ca.account.sony.com/api/v1/ssocookie
while signed in to their PSN account. Tokens expire after about two months.

Endpoints used (via psnawp):

- ``me()``                  -> the token owner's profile (account_id, online_id)
- ``me().title_stats()``    -> every played title with cumulative play duration
- ``game_title().get_details()`` -> store concept metadata, used to tell games
  from media apps

PSN exposes no clean purchase library, so "owned" is approximated by every
title the account has played, mirroring the Xbox integration.
"""

import logging
from contextlib import contextmanager

import requests
from psnawp_api import PSNAWP
from psnawp_api.core import psnawp_exceptions
from psnawp_api.models.title_stats import PlatformCategory

from app.log_safety import exception_summary
from integrations.imports.helpers import MediaImportError

logger = logging.getLogger(__name__)

PROVIDER = "PSN"


@contextmanager
def _translated(operation):
    """Translate every psnawp failure into a MediaImportError.

    The messages are constructed from the exception type alone: the importer
    persists them on the account row and the import page renders them, and a
    raw psnawp exception string can embed the request URL or response body.
    """
    try:
        yield
    except MediaImportError:
        raise
    except (
        psnawp_exceptions.PSNAWPAuthenticationError,
        psnawp_exceptions.PSNAWPUnauthorized,
    ) as e:
        logger.warning("PSN %s failed: %s", operation, exception_summary(e))
        msg = (
            "Invalid or expired PSN NPSSO token. "
            "Reconnect your PlayStation account with a fresh token."
        )
        raise MediaImportError(msg) from e
    except psnawp_exceptions.PSNAWPForbidden as e:
        logger.warning("PSN %s failed: %s", operation, exception_summary(e))
        msg = "PSN denied access to this profile. Check its privacy settings."
        raise MediaImportError(msg) from e
    except psnawp_exceptions.PSNAWPTooManyRequests as e:
        logger.warning("PSN %s failed: %s", operation, exception_summary(e))
        msg = "PSN rate limit exceeded. Please try again later."
        raise MediaImportError(msg) from e
    except psnawp_exceptions.PSNAWPServerError as e:
        logger.warning("PSN %s failed: %s", operation, exception_summary(e))
        msg = "PSN is currently unavailable. Please try again later."
        raise MediaImportError(msg) from e
    except psnawp_exceptions.PSNAWPException as e:
        logger.warning("PSN %s failed: %s", operation, exception_summary(e))
        msg = (
            f"PSN request failed ({type(e).__name__}). Check the logs for details."
        )
        raise MediaImportError(msg) from e
    except requests.RequestException as e:
        logger.warning(
            "PSN %s could not be completed: %s",
            operation,
            exception_summary(e),
        )
        msg = "Could not reach PSN. Check your connection and try again later."
        raise MediaImportError(msg) from e


def get_account(npsso):
    """Return ``(account_id, online_id)`` for the owner of the NPSSO token."""
    with _translated("account lookup"):
        client = PSNAWP(npsso).me()
        return str(client.account_id), str(client.online_id)


def get_played_games(npsso):
    """Return every game the account has played, in playback order.

    ``title_stats`` covers PS4 and PS5 titles, media apps (Netflix, Plex, ...)
    included. PSN labels real games with a platform category, but leaves both
    apps and a sizeable slice of games (PS Plus catalogue, cross-gen releases)
    uncategorised, so uncategorised titles are resolved through the store
    concept metadata instead: games carry genres there, apps and interactive
    videos don't. See :func:`_is_game`.
    """
    with _translated("library fetch"):
        psn = PSNAWP(npsso)
        titles = list(psn.me().title_stats())

        games = []
        skipped = []
        for stats in titles:
            if stats.category == PlatformCategory.UNKNOWN and not _is_game(
                psn,
                stats,
            ):
                skipped.append(stats.name)
                continue
            play_duration = stats.play_duration
            games.append(
                {
                    "title_id": stats.title_id,
                    "name": stats.name,
                    "image_url": stats.image_url,
                    "minutes": (
                        int(play_duration.total_seconds() // 60)
                        if play_duration
                        else 0
                    ),
                    "last_played": stats.last_played_date_time,
                    "play_count": stats.play_count,
                },
            )

    if skipped:
        logger.info(
            "Skipping %d non-game PSN titles: %s",
            len(skipped),
            ", ".join(sorted(skipped)),
        )
    logger.info("Found %d played PSN games", len(games))
    return games


def _is_game(psn, stats):
    """Return whether an uncategorised title is a game rather than an app.

    The store concept metadata reports genres for games only -- media apps
    (Netflix, Plex, "My Videos") and interactive videos come back with an
    empty list. A title whose lookup fails is kept: an unavailable signal
    should degrade to the old behaviour, not silently drop a game.
    """
    try:
        details = psn.game_title(
            title_id=stats.title_id,
            account_id="me",
            np_communication_id="",
        ).get_details()
    except (
        psnawp_exceptions.PSNAWPNotFound,
        psnawp_exceptions.PSNAWPBadRequest,
        psnawp_exceptions.PSNAWPForbidden,
        psnawp_exceptions.PSNAWPServerError,
    ) as e:
        logger.warning(
            "PSN concept lookup for %s failed, keeping title: %s",
            stats.title_id,
            exception_summary(e),
        )
        return True

    payload = details[0] if details else {}
    return bool(payload.get("genres"))
