# Podcast plays

A podcast listen is a `PodcastPlay` row. Its `id` is the `consumption_id` the
API returns, and it stays the same from In Progress to Completed.

## Why

A `Podcast` row is the per-user tracker of an episode: score, notes and the
current state. Listens used to be its `simple_history` records, so every save
(a start date, a note, a progress poll) wrote another record, and History,
Statistics and the show page counted each one that shared an `end_date` as a
play. Editing a start date showed the episode twice, and deleting one entry
removed both (#1874). A play is now its own row, so none of that can happen.

| Record | Holds |
|---|---|
| `Podcast` | The tracker: status, score, notes, and the current dates and progress. More than one row per user and episode is possible (importers add a row per repeat) |
| `PodcastPlay` | One listen: `status` (In progress or Completed), `start_date`, `end_date`, `progress` (minutes), `played_up_to_seconds`, `external_id`, `entry_source` |
| `HistoricalPodcast` | Audit of tracker edits only. Nothing reads it to count plays |

## One writer

`app/services/podcast_plays.py` creates, updates and deletes plays. The web
play form, the REST API, mark-all-played and the History delete route all call
it, and after each change it brings the tracker back in step with its plays
(`sync_tracker`): an open play is the current state, otherwise the newest
completed play is, and with none the tracker returns to Planning.

- `create_play` returns `(play, created)`. A completed play within five
  minutes of another, a repeated `external_id`, or a second In progress play
  returns the existing play with `created` false.
- `update_play` changes a play in place and never adds one. Completing it
  without an `end_date` ends it now; reopening it clears the end date.
- `delete_play` removes only that play.

## Direct tracker saves

Importers, webhooks and the track form write the `Podcast` row. A `post_save`
receiver (`keep_podcast_plays_in_step`) carries that save onto the play it
describes: the open play, or the one that ended at the tracker's previous
`end_date`, is updated; with none a play is created. Saving a tracker at a new
`end_date` therefore **moves** its play. A repeat listen is created with
`create_play`, or as a new tracker row by an importer. Rows written with
`bulk_create` send no signal, so the writer calls
`podcast_plays.create_plays_for_trackers`. The service's own saves are marked
with `service_write()` so the receiver skips them.

`PodcastPlay.save()` and `.delete()` also re-sync the tracker, so the admin and
the generic history API stay consistent.

## Readers

History (`history_cache*`), Statistics (`stats_podcast`, `statistics_*`), the
show page, the track modal and the activity timeline read `PodcastPlay`. The
History entry key is the play id, which the History delete route takes.

## API

- `POST /api/v1/podcasts/episodes/plays/` takes `status` (default Completed),
  `start_date`, `end_date`, `progress` (minutes), `played_up_to_seconds` and
  `external_id`. The response carries `consumption_id` (the play id) and
  `tracker_id`.
- `GET`, `PATCH` and `DELETE /api/v1/podcasts/episodes/plays/<consumption_id>/`
  read, change and delete one listen.
- `GET /api/v1/media/podcast/<source>/<media_id>/history/` lists plays, and the
  `history/<consumption_id>/` routes resolve play ids.

## Backfill

Migration `0224_podcastplay` turns each distinct completed `(tracker, end_date)`
in `HistoricalPodcast` into one play, taking the newest values. A tracker with
no history gets a play from its own row. Planning rows get none. The step is
safe to run twice.
