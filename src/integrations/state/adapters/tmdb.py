"""TMDb rating transport, scale conversion and exact item identity."""

from decimal import ROUND_HALF_UP, Decimal

from cryptography.fernet import InvalidToken
from django.db import transaction

from app.models import MediaTypes, Sources
from integrations import connection_health
from integrations.imports.helpers import decrypt
from integrations.models import CAPABILITY_RATING_PUSH, TMDbAccount
from integrations.state.adapters.base import (
    RemoteRating,
    TerminalAdapterError,
    TransientAdapterError,
)
from integrations.tmdb_api import TMDbAuthError, TMDbClient


class TMDbRatingAdapter:
    """Sync a personal rating without changing Floppy's stored score."""

    CAPABILITIES = frozenset({CAPABILITY_RATING_PUSH})

    def __init__(self, account):
        """Use one account's encrypted session."""
        self.account = account
        try:
            session_id = decrypt(account.session_id)
        except InvalidToken:
            session_id = ""
        self.client = TMDbClient(account.user, session_id)

    def resolve_external_id(self, item):
        """Use only native TMDb identities and native episode numbering."""
        if item.source != Sources.TMDB.value or getattr(item, "episode_order_id", None):
            return None
        if not str(item.media_id).isdigit():
            return None
        if item.media_type == MediaTypes.MOVIE.value:
            return f"movie/{item.media_id}"
        if item.media_type == MediaTypes.TV.value:
            return f"tv/{item.media_id}"
        if (
            item.media_type == MediaTypes.EPISODE.value
            and item.season_number is not None
            and item.season_number >= 0
            and item.episode_number is not None
            and item.episode_number > 0
        ):
            return f"tv/{item.media_id}/season/{item.season_number}/episode/{item.episode_number}"
        return None

    def normalize_rating(self, score):
        """Round half up in 0.5-point steps, preserving a genuine clear."""
        if score is None:
            return None
        rounded = (Decimal(str(score)) * 2).quantize(
            Decimal(1), rounding=ROUND_HALF_UP
        ) / 2
        return max(Decimal("0.5"), min(Decimal(10), rounded))

    def _request(self, method, path, **kwargs):
        """Record connection health only at the personal API boundary."""
        if not self.client.session_id:
            message = "TMDb session cannot be decrypted. Reconnect your account."
            raise TerminalAdapterError(message)
        try:
            result = self.client.request(method, path, **kwargs)
        except (TerminalAdapterError, TransientAdapterError) as error:
            self._record_health(error)
            raise
        self._record_health()
        return result

    @transaction.atomic
    def _record_health(self, error=None):
        """Record health only while the request's credentials remain connected."""
        account = (
            TMDbAccount.objects.select_for_update()
            .filter(
                pk=self.account.pk,
                session_id=self.account.session_id,
            )
            .first()
        )
        if account is None:
            return
        if error is None:
            connection_health.record_success(account)
        else:
            connection_health.record_failure(
                account, str(error), auth=isinstance(error, TMDbAuthError)
            )

    def read_rating(self, external_id):
        """Missing or malformed state is unknown; rated=false is known unrated."""
        result = self._request("GET", f"{external_id}/account_states")
        rated = result.get("rated")
        if rated is False:
            return RemoteRating(None)
        if isinstance(rated, dict) and "value" in rated:
            try:
                score = Decimal(str(rated["value"]))
            except ArithmeticError:
                return None
            if score.is_finite() and Decimal("0.5") <= score <= Decimal(10):
                return RemoteRating(score)
        return None

    def write_rating(self, external_id, *, score):
        """Set or delete the TMDb rating idempotently."""
        if score is None:
            self._request("DELETE", f"{external_id}/rating")
        else:
            self._request("POST", f"{external_id}/rating", json={"value": float(score)})


def build_adapter(binding):
    """Return an adapter only for the exact connected TMDb profile."""
    account = TMDbAccount.objects.filter(
        user=binding.user,
        account_id=binding.profile_key,
    ).first()
    if account is None or not account.session_id:
        return None
    return TMDbRatingAdapter(account)
