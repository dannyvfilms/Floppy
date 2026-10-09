# Webhook write rules

When a media-server webhook may create or change tracking rows (Movie, TV,
Season, Episode). The code is `src/integrations/webhooks/write_policy.py`;
this page explains it. If the two disagree, the module wins.

## The rule

Play, resume and pause only update the Now Playing card. What writes:

| Event | Writes? |
|---|---|
| `media.play`, `media.resume`, `media.pause` | Never |
| `media.stop` | If played, if the position is unknown, or at 60 s or more |
| `media.scrobble` (Plex scrobble, Kodi end) | Always |
| `mark` (a manual watched/unwatched toggle) | Always, behind the user's opt-in |

A stop with an unknown position still writes. A stop is a real end signal,
and dropping it would lose In Progress tracking for a server that does not
report its position. Only a *known* short stop is a skim.

A row created by a stop or scrobble takes its **start date** from Now Playing
(`live_playback.get_session_start`), the time the title was first seen
playing, so a one-sitting watch keeps both dates (#1482). With no cached
session (restart, expiry, or a scrobble that arrives cold) a new In Progress
row starts at the stop time and a Completed one has no start date.

## Why

- **Bunny Ears TV** (`82e424f2`): pseudo-live-TV apps in activity-only mode
  send play and never stop. Writing on play left items stuck In Progress
  forever. Plex was fixed first.
- **#1250**: Jellyfin still wrote on every Play, including the "still
  playing" tick every few seconds, so each tick was another chance to
  write to a mis-resolved show (#1246). Emby and Kodi did the same on
  playback start. All three now follow the one rule.

## One row per integration

`WEBHOOK_WRITE_POLICIES` maps each processor's `SOURCE_LABEL` to a policy
and a reason:

| Source | Policy | Why |
|---|---|---|
| plex | `STOP_ONLY` | Sends stop and scrobble |
| jellyfin | `STOP_ONLY` | Sends stop; manual marks map to `mark` |
| emby | `STOP_ONLY` | Sends `playback.stop` |
| kodi | `STOP_ONLY` | Sends stop and end |
| stremio | `START_ONLY` | The addon's `subtitles` beacon is a start ping; completion comes from the delayed verifier |
| scrobble | `FINAL_ONLY` | The scrobble API only accepts stop/completion events |

`START_ONLY` and `FINAL_ONLY` are the exceptions. They live in the table so
there is one place to look, not a special case inside an integration.

Stremio's addon has a second, separate inbound path: the `player` and
`library` resources it requests, handled by `integrations/stremio_tracker.py`
rather than by `StremioWebhookProcessor`. They carry real positions and
watched flags and merge into the same session the verifier reads. They are not
webhook-processor events, so they get no row here; the tracker's own policy is
`stremio_tracker.apply_observation`, which appends a history play only when an
observation carrying watched evidence completes a session.

## Manual marks and echoes

A manual mark for something Floppy already has as watched adds no play
(`BaseWebhookProcessor._is_manual_mark`). Floppy's own watched-state push
comes back from Jellyfin as a checkmark toggle stamped with the push time,
which the play-time dedupe cannot tell from a new play. See
`docs/architecture/watched-state-sync.md` ("Convergent").

## Adding or changing an integration

1. Give the processor a `SOURCE_LABEL` and add its row to
   `WEBHOOK_WRITE_POLICIES`, with a reason.
2. Map its events to the `media.*` vocabulary above and call
   `self._should_record(event, played=..., position_seconds=...)` before
   `_process_media`.
3. Add it to `ProcessorWiringTests` in
   `src/integrations/tests/test_webhook_write_policy.py`.

You'll notice if you forget. `test_every_processor_has_a_policy_row` fails
for any `BaseWebhookProcessor` subclass without a row, and a missing row
raises `LookupError` at runtime. Both messages point here.

## Users on an old Jellyfin template

The Jellyfin webhook template gained `SaveReason` and the real `Played` flag
in #1250. While `UserDataSaved` events arrive without `SaveReason`, the
Integrations page shows "Webhook template needs updating" on the official
Jellyfin card (a 30-day cache flag, `JELLYFIN_TEMPLATE_OUTDATED_KEY`). When
the template changes again, key the notice to the new field the same way.
