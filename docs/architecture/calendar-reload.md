# Calendar reload work boundaries

`events.views.reload_calendar` queues `Reload calendar` for the current user.
The task resolves global or user-scoped selection once, then processes at most
`CALENDAR_RELOAD_CHUNK_SIZE` items. Continuations carry the remaining IDs and,
for a user refresh, that user's ID. Selection order is retained; missing items
are skipped when resolving continuation IDs. A missing user stops that task.
Setting the chunk size to zero retains a single-pass refresh.

Each slice uses the normal calendar fetch/save/check-stamp path. Provider
failures leave affected items unstamped for a later reload. A raised slice
failure does not publish its continuation. Replaying completed work updates
existing events rather than creating duplicates. Global auto-pause and metadata
backfill dispatch remain global-only; user continuations never trigger them.

Calendar tasks retain the background queue and priority. Yielding between
slices lets higher-priority bulk work run on the existing single worker;
playback and the statistics reconciler already use the dedicated interactive
queue. An item-count slice does not bound selection or an individual provider
call's elapsed time, and does not preempt other long-running tasks. Worker
counts, memory ceilings and task time limits are unchanged.
