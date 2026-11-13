# Stalled request watchdog

`slow_request` (see `RequestPerformanceLoggingMiddleware`) is written when a
request finishes, so a request that hangs or whose worker is killed leaves no
trace. `app/stall_watchdog.py` closes that gap.

- Each instrumented request registers on entry and unregisters on exit (a dict
  insert and delete under one lock). One daemon thread per process, started
  lazily and restarted after a gunicorn fork, scans about once a second.
- A request still running after `PERF_STALL_WARN_MS` (default 10000, `0`
  disables) is logged **once** by logger `app.stall_watchdog`:
  `stalled_request method route age_ms pid thread inflight stack`.
- `route` is the URL pattern (`medialist/<str:media_type>`), never the path or
  query, which can carry tokens. `stack` holds `file:line:function` only: no
  locals, arguments or request data. The log redaction factory still applies.
- Volume is capped at `PERF_STALL_MAX_REPORTS_PER_MINUTE` (default 10) per
  process; excess stalls are dropped, not queued.
- If the request later completes, its `slow_request` line is always written,
  so a `stalled_request` can be paired with its final duration. A request with
  no later `slow_request` was killed or is still hanging.
- Reading it: a stack inside `threading.wait`/`sqlite3`/`redis` names the
  blocking boundary. A request queued behind busy threads never reaches Django,
  so it has no `stalled_request`; compare nginx upstream timeouts with the
  `inflight` figure of the stalled lines.
