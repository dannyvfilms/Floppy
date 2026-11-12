"""Pending account-link state for browser and device-code connects.

Device-code logins (Trakt, Storyteller) and redirect logins (Trakt, Plex, SIMKL,
AniList, MyAnimeList, TMDb) need a little server-side state between "start" and
"finish". It lives in the cache, keyed per user, so a web page and the native
app's API calls read the same record and neither depends on a browser session.
Redirect state is keyed by its unguessable state token and bound to one user.
"""

from urllib.parse import urlsplit

from django.core.cache import cache

# The native app's registered URL scheme (native-proof/app.json "scheme").
NATIVE_APP_SCHEME = "floppy-native-proof"
STATE_TTL_SECONDS = 15 * 60


def _device_key(provider, user_id):
    return f"pending-auth:{provider}:{user_id}"


def _state_key(user_id, token):
    return f"pending-auth-state:{user_id}:{token}"


def _claim(key):
    """Read and consume one cache entry; only one concurrent caller gets it.

    `delete()` reports whether this call removed the key, and the cache
    backend makes that a single atomic step, so a get alone is never trusted.
    """
    entry = cache.get(key)
    if entry is None or not cache.delete(key):
        return None
    return entry


def put(provider, user_id, data, ttl=STATE_TTL_SECONDS):
    """Remember one pending device login for this user and provider."""
    cache.set(_device_key(provider, user_id), data, timeout=ttl)


def get(provider, user_id):
    """Return the pending device login, or None."""
    data = cache.get(_device_key(provider, user_id))
    return data if isinstance(data, dict) else None


def clear(provider, user_id):
    """Forget the pending device login."""
    cache.delete(_device_key(provider, user_id))


def take(provider, user_id):
    """Consume the pending device login: one caller receives it, the rest None."""
    data = _claim(_device_key(provider, user_id))
    return data if isinstance(data, dict) else None


def stash_state(request, token, data):
    """Store redirect-flow state for the callback.

    A browser start keeps it in the session as before. A native API start has
    no browser session, so it goes to the cache bound to the signed-in user.
    """
    if getattr(request, "native_connect", False):
        cache.set(
            _state_key(request.user.pk, token),
            {"user_id": request.user.pk, "data": data},
            timeout=STATE_TTL_SECONDS,
        )
    else:
        request.session[token] = data


def pop_state(request, token):
    """Consume redirect-flow state: the session first, then a native start."""
    if not token:
        return None
    data = request.session.pop(token, None)
    if isinstance(data, dict):
        return data
    # The key carries the user, so another user's callback never touches this entry.
    entry = _claim(_state_key(request.user.pk, token))
    if not isinstance(entry, dict) or not isinstance(entry.get("data"), dict):
        return None
    return entry["data"]


def is_native_return(url):
    """Report whether this is a deep link into this app: its exact scheme only."""
    if not isinstance(url, str) or any(char in url for char in "\r\n\\ "):
        return False
    parts = urlsplit(url)
    return parts.scheme == NATIVE_APP_SCHEME and not parts.username
