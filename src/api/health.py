"""Keep the Celery ping health check from blocking every health request.

``control.ping(timeout=N)`` always waits the full timeout for worker replies, so
each poll of /api/v1/health/ held a web thread for about a second. The verdict
is cached briefly instead; error semantics and response shape are unchanged.
"""

from django.core.cache import cache
from health_check.contrib.celery_ping.backends import CeleryPingHealthCheck
from health_check.exceptions import ServiceUnavailable

CACHE_KEY = "api_health_celery_ping"
CACHE_SECONDS = 15


def install_cached_celery_ping() -> None:
    """Wrap ``CeleryPingHealthCheck.check_status`` with a short-lived cache."""
    if getattr(CeleryPingHealthCheck.check_status, "_floppy_cached", False):
        return
    original = CeleryPingHealthCheck.check_status

    def check_status(self):
        cached = cache.get(CACHE_KEY)
        if cached is not None:
            for message in cached:
                self.add_error(ServiceUnavailable(message))
            return
        original(self)
        cache.set(
            CACHE_KEY,
            [getattr(error, "message", str(error)) for error in self.errors],
            CACHE_SECONDS,
        )

    check_status._floppy_cached = True
    CeleryPingHealthCheck.check_status = check_status
