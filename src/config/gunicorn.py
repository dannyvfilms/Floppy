from config.runtime_profile import PROFILE, by_tier, gunicorn_threads, web_concurrency

bind = "localhost:8001"
preload_app = True

# Threaded workers so one slow request can't stall the whole UI.  The
# container also runs nginx, up to three celery workers, and beat, so keep the
# process count low and rely on threads for I/O-bound concurrency.
worker_class = "gthread"

# Sized from the host rather than fixed. One threaded, preloaded worker keeps
# normal-host idle memory down; each extra worker duplicates private Django
# state despite copy-on-write. WEB_CONCURRENCY and GUNICORN_THREADS still win
# when set - see config/runtime_profile.py.
workers = web_concurrency()
threads = gunicorn_threads()

# Recycle workers more aggressively on small hosts: RSS only creeps upward
# within a worker's life, so a lower ceiling caps the steady-state footprint.
max_requests = by_tier(200, 300, 500)
max_requests_jitter = 10
timeout = by_tier(120, 200, 200)

print(  # noqa: T201  # gunicorn has no logger configured this early
    f"[gunicorn] {PROFILE.describe()} -> workers={workers} threads={threads} "
    f"max_requests={max_requests} timeout={timeout}",
)

accesslog = "-"
errorlog = "-"


def pre_fork(server, worker):
    """Close database and Redis pools in the master before workers are forked.

    ``preload_app`` runs ``django.setup()`` (and every ``AppConfig.ready()``)
    once in the master before forking, and ``AppConfig.ready()`` touches the
    Redis cache (startup-task scheduling keys). Psycopg pools own background
    threads and must not be inherited by the preloaded workers (#341); the
    Redis connection likewise must not be inherited, or every forked
    worker/thread shares one raw socket and corrupts each other's commands -
    including session writes, which silently fail to persist (#335).
    """
    from django.core.cache import caches
    from django.db import connections

    connections.close_all()
    for connection in connections.all():
        close_pool = getattr(connection, "close_pool", None)
        if close_pool is not None:
            close_pool()

    for cache in caches.all():
        client = getattr(cache, "client", None)
        do_close_clients = getattr(client, "do_close_clients", None)
        if do_close_clients is not None:
            do_close_clients()


def post_fork(server, worker):
    """Drop database connections inherited from the preloaded master process.

    ``pre_fork`` closes any process-local database/Redis pool before the
    fork; this hook remains as a final guard against inherited database
    connections (issue #335).
    """
    from django.db import connections

    connections.close_all()
