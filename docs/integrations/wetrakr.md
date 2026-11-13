# WeTrakr outbound sync

Floppy can send what you watch, what you plan or drop, and your ratings to
[WeTrakr](https://api.wetrakr.com/). It is one provider on the shared outbound
engine described in [watched-state-sync](../architecture/watched-state-sync.md);
this page covers only what is specific to WeTrakr.

The runnable half is `src/integrations/tests/test_wetrakr.py`. If this page and
that file disagree, the file is right.

```bash
SECRET=test-only scripts/test.sh integrations.tests.test_wetrakr
```

## Verification status

**Not yet verified against a live WeTrakr account.** Every request and reply
shape in `wetrakr_api.py` and `state/adapters/wetrakr.py` comes from an
unofficial transcription of WeTrakr's documentation (2026-10-01), and the tests
run against a mocked WeTrakr. Do not call this integration complete until a
WeTrakr application key and a consenting test account have confirmed:

- the device-login field name (`code` or `device_code`; Floppy tries both);
- the exact reply buckets (`added`, `notFound`, `errored`) and `play_id`;
- the rate-limit and quota headers;
- that an unrecognised reply is retried rather than lost (it is).

## Connecting

1. Get an application key from WeTrakr and set `WETRAKR_CLIENT_ID`, or paste it
   under Settings > Providers > WeTrakr > Connection. Floppy ships no shared key.
2. Integrations > WeTrakr > Connect. Floppy shows a code; approve it on
   wetrakr.com. Floppy stores the tokens encrypted and refreshes them under a
   lock, because WeTrakr rotates refresh tokens.
3. Connecting sends nothing. Plays, statuses and ratings each have a switch,
   all off.

## What is sent

| Switch | Sent | Never sent |
|---|---|---|
| Plays | A movie or episode you finish, with the date you watched it | Imported history, undated plays, a whole show as watched |
| Remove plays | When you delete a play in Floppy, that exact play (off by default; see below) | The latest play, all plays, anything you removed through an import |
| Statuses | Planning and dropped for movies; planning, paused and dropped for shows | Watching and completed (a play already says so) |
| Ratings | Movie and show ratings, including clearing one | Episode ratings |

Deliveries are Live (within seconds), Hourly or Daily. Hourly and Daily use UTC
boundaries.

## Send existing library

Plays are WeTrakr's activity feed, so imported history never reaches it by
itself. **Send existing library** queues your dated plays, plans, drops and
ratings once, only when you press it. Re-running it never sends the same dated
play twice. Plays without a date are counted on the card and left out, because
WeTrakr would show them as watched today.

## Removing a play

With **Remove a play from WeTrakr when I delete it here** switched on, deleting a
play in Floppy removes that one play from WeTrakr. Floppy keeps the `play_id`
WeTrakr returned for each play it sent and deletes by that id. If WeTrakr did
not return one, it removes by the exact date the play was sent with. A play
WeTrakr no longer has counts as removed. A rewatch that is still in Floppy is
never touched, because each play is matched by its own date. A play that was
queued but not yet sent is simply not sent. Floppy never calls WeTrakr's
remove-all or remove-latest routes.

## Known limits

- Removal only follows a play you delete. Editing a play's date does not change
  what WeTrakr holds.
- A play that is being sent at the very moment you delete it may stay on WeTrakr.
- Un-watching something Floppy never sent leaves WeTrakr alone.
