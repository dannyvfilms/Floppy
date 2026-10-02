# Music listen hooks

A scrobble that has a `Music` row fires `music_listen_recorded` once, from `record_music_playback`, after the existing MusicBrainz genre fill. Every ingest path that calls that function gets the signal. Core code does not branch on the source.

## Signal

```python
music_listen_recorded.send(sender=Music, music=music, event=event)
```

`event` is the `MusicPlaybackEvent`. `event.origin_url` is the ListenBrainz `additional_info.origin_url` when the client sent one, otherwise `""`.

## Receivers must not block

A receiver enqueues work and returns. The signal runs on the request that recorded the play. A receiver that does network I/O stalls every scrobble.

## Drop-in directory

`MUSIC_HOOKS_DIR` (default empty) is a directory of `*.py` files. On startup each file is imported. Import is registration: the file connects itself with `@receiver(music_listen_recorded)`. An empty or missing directory loads nothing.

Hook files are not part of this repo. Point the setting at a directory on the host.
