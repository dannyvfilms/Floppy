# PlayStation Network sync

How `integrations/imports/psn.py` turns PSN's lifetime playtime into game entries.

## What PSN reports

Per title: lifetime play duration, first and last played time. Nothing per session, so Floppy
cannot know *when* within a sync window the time was played. PS4 and PS5 releases of one game
resolve to the same IGDB game and are summed before anything is written.

## How a game's time is logged

Each play of a game in Floppy is one `Game` row: start date, end date, minutes. History's
**Repeats** mode spreads a row's minutes evenly across its date range; **Sessions** mode shows
the row as one entry. Both read the same rows, so the importer only has to write sensible dates.

`PlaytimeSnapshot` remembers the lifetime total PSN gave at each sync. A sync then does, per game:

| Situation | Result |
| --- | --- |
| Total grew since the last sync | One new row: start = previous sync, end = PSN's last played time (or now), minutes = the difference. Behaves like a scrobble. |
| Total unchanged, or lower | Nothing is logged. A lower total (a sibling title ID failed to match) never lowers the remembered one. |
| First time the game is seen, already tracked | The total becomes the starting point and existing rows are never edited. The one exception is play since the account's previous sync (an account that synced before totals were remembered): if PSN launched the game since then and its total exceeds the hours tracked by no more than the tracked hours, the difference is logged as one entry from the previous sync to PSN's last played time. A bigger difference is a library that was never in step with PSN, so it is not logged. |
| First time seen, not tracked, setup choice "Import it" | One row from first played to last played with the whole lifetime total. No dates from PSN means a dateless row, which History skips and statistics don't spread across a year. |
| First time seen, not tracked, "Only track new play" | Nothing is logged; the game appears with its first new play. |

The setup choice is labelled "Import Backlog and Scrobble New Data" (the default) or "Scrobble New Data
Only" and lives on `PSNAccount.import_existing_playtime`. "Only Sync New Items" and
"Sync New Items and Overwrite Existing" behave the same for PSN: a sync only adds rows, so there
is nothing to overwrite.

A game deleted in Floppy stays deleted; its snapshot still advances so the old time is not
logged later.

A scheduled sync is skipped when the cache is unreachable, because without the lock an overlapping sync
could log the same play twice; the next run picks up the same growth. Sync Now still runs.

Two guards keep the remembered totals honest. Syncs for one user are serialized with a cache lock
(`_run_psn_import`), so Sync Now and the schedule can't both log the same growth, and the new rows
and the snapshots are saved in one transaction. Snapshots belong to one PSN account: they are
deleted on disconnect and when a different PSN account connects (which also clears the account's last sync time).

## When it syncs

There is no frequency setting. Connecting, or pressing Sync Now, runs a sync and keeps one
recurring task per user every `SYNC_EVERY_HOURS` (3) hours, at a minute derived from the user id
so users don't all hit PSN together (`_ensure_psn_schedule` in `integrations/views.py`). It also
replaces any older daily/2-day schedule a user chose before this. The 3 hours is a guess: we
have not measured how often PSN refreshes `title_stats`. Each sync only records the time a total
grew, so a shorter cadence would give a closer time of day; change the constant if PSN turns out to
update sooner. Titles PSN leaves uncategorised need a store lookup to tell games from apps, so
`psn_api._is_game` caches the answer (30 days) to keep frequent syncs cheap.

## The card

The PlayStation card builds its fields from `users/components/game_sync_fields.html`: a
"Syncs automatically every N hours" line, the playtime choice above, and a read-only "Game Logging"
line that shows the user's Repeats or Sessions style (`User.game_logging_style`). Each has its own
short tooltip (`users/components/info_tip.html`). Xbox and Steam should include the same
component when they move onto `PlaytimeSnapshot`, so every game source reads the same way.

## The result message

The task reports `created` (new rows), `skipped` (unchanged games) and `baseline` (games whose total was
only remembered, so the first sync after updating doesn't read as "nothing happened"). Any created row also
triggers the History and Statistics cache refresh. Xbox and Steam report `updated` for the hours
they overwrite for the same reason.

## Not done yet

Xbox and Steam still overwrite lifetime hours on one row. Moving them onto
`PlaytimeSnapshot` (new dated entry per sync) is the same change.
