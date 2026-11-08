# Log levels

A bug report is only as useful as the log attached to it. The worst failures,
a process that hangs or a request that times out, raise no error. The log shows
them only as a silence: work that started and never finished. This page sets
what each level means, so a log can answer "what was it doing, and where did it
stop?"

## What each level means

| Level | Use it for | Example |
| --- | --- | --- |
| `ERROR` | Work failed and was not completed. | An import stopped on a provider error. |
| `WARNING` | Work continued, but degraded, skipped, retried or slower than expected. | A provider call was retried; a show was skipped for missing metadata. |
| `INFO` | The life of work that takes time: it started, it is still going, it finished. | `sync_started`, a progress count, `sync_finished duration_ms=...`. |
| `DEBUG` | Detail for one developer chasing one bug. Off in production. | A parsed payload, a cache key. |

The log file keeps `INFO` and above. The console shows `WARNING` and above
unless `DEBUG` is on. Do not put something at `WARNING` to make it show on the
console: that makes real warnings harder to find.

## What a long-running process must log

A process is anything that can outlast a request: a Celery task, an import, a
sync, a webhook handler, a startup step, a call to a provider. Each one logs
through `app.progress_log.progress()`, which writes an `INFO` line with a
`[progress]` tag (see "How the logs are read"):

1. **Start.** One line with the name of the work and its safe identifiers.
2. **Progress,** if it can run longer than about a minute. A line every
   batch or every 30 seconds, with a count, such as `processed=400 total=1200`.
   This is the line that proves a slow process was still alive.
3. **Finish.** One line with the outcome and `duration_ms`, and a count of what
   it did.

Every start needs a finish on every path, including the early return and the
`except` block. A start with no finish is how a reader spots a hang, so a path
that skips the finish line makes a healthy run look stuck. The webhook log
contract in `webhook-delivery.md` is the model: `webhook_started`,
`webhook_finished`, and `webhook_slow_queue` when it ran long.

Give every outbound call a timeout and log the timeout at `WARNING` or `ERROR`.
A call with no timeout can hang for ever, and then there is nothing to log.

## Choosing a level when you write a log line

Ask what a reader needs when something has gone wrong and nothing has failed:

- Would this line tell them that work is still going, or where it stopped?
  Use `INFO`.
- Did something go wrong that the code recovered from? Use `WARNING`, and say
  what was skipped or retried.
- Did the work not finish? Use `ERROR`, and include `exception_summary()` from
  `app.log_safety`.
- Is it only useful with the code open beside you? Use `DEBUG`.

Write progress lines as safe identifiers only, because the diagnostic report
shows them to every signed-in user. Ordinary `INFO` lines stay on the module
logger and stay private to administrators.

Do not log a hot loop line by line at `INFO`. One line per item in a 10,000 item
import buries the start and finish lines. Log a count every batch instead.

## What a line may contain

Every line passes through the redaction in `log-redaction.md`, but redaction is
a safety net. Write lines that need none of it:

- Log safe identifiers: ids, counts, durations, provider names, task names.
- Do not log usernames, email addresses, titles a person tracks, or tokens. Use
  `safe_url()` and `mapping_keys()` from `app.log_safety` for URLs and payloads.
- Keep the same words in the same order, such as `name key=value key=value`, so
  a line can be searched for.

## How the logs are read

Two downloads exist in Settings > Advanced:

- **Download Sanitized Logs** is every level, for superusers only, because the
  file covers the whole instance.
- **Download Diagnostic Report** is for any signed-in user. It is built in
  `src/users/diagnostics.py` and holds:
  - server details: version, commit, Python, database, last unclean shutdown;
  - an activity timeline: when the newest line of each level was written, the
    last line per process, and line counts per level in 10-minute blocks for
    the last 6 hours. It never contains message text. A hung process shows as a
    gap, and a slow one as steady counts;
  - the `[progress]` lines, word for word;
  - the recent `WARNING`, `ERROR` and `CRITICAL` records with tracebacks;
  - the end of the restart, supervisor and crash logs.

  Every kept line has secrets, email addresses and account names removed.
  Other `INFO` lines are left out, because they can name what an account
  watched.

A report from a non-admin account therefore answers "did it fail?", "was it
still working?" and "where did it stop?" without exposing another account's
activity. To make a new process visible in it, give the process progress lines.
