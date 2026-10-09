# AsyncAPI 3.0 Channel Architecture and Queue Contract

This document specifies Floppy's asynchronous message channels, inbound webhook boundaries, Celery execution queues, and worker concurrency profiles.

---

## 1. Core Principles and Wire Truthfulness

1. **Explicit Inbound Channels**:
   - Inbound webhooks from media servers (Plex, Jellyfin, Emby, Kodi, Jellyseerr) and streaming clients (Stremio) arrive over HTTP and are processed asynchronously.
   - Synchronous ingest routes (such as ListenBrainz scrobbling at `/apis/listenbrainz/1/submit-listens`) execute immediately in the request-response lifecycle and do not dispatch to background Celery queues.

2. **Celery Serialization Truthfulness**:
   - Celery tasks in Floppy use `application/x-python-serialize` (pickle).
   - AsyncAPI channel definitions document logical task parameters and metadata under `x-floppy-*` attributes rather than claiming portable JSON Schema definitions for internal Python pickle payloads.

3. **Offline & Air-Gap Compatibility**:
   - The AsyncAPI 3.0 contract is generated locally via `src/api/channel_registry.py` and committed at `src/api/contracts/asyncapi.json`.
   - Served publicly at `/api/asyncapi.json` with HTTP 304 conditional revalidation (`ETag`).

---

## 2. Inbound Webhook Routes and Channels

| Channel Address | Operation ID | Service | Dispatches To Queue | Description |
|---|---|---|---|---|
| `webhook/plex/{token}` | `receivePlexWebhook` | Plex | `celery` | Inbound scrobble/playback and library update payloads from Plex Media Server. |
| `webhook/jellyfin/{token}` | `receiveJellyfinWebhook` | Jellyfin | `celery` | Playback progress, start, stop, user-rating, watched-toggle, and item metadata notifications from Jellyfin. |
| `webhook/emby/{token}` | `receiveEmbyWebhook` | Emby | `celery` | Playback state and library synchronization payloads from Emby Server. |
| `webhook/jellyseerr/{token}` | `receiveJellyseerrWebhook` | Jellyseerr | `celery` | Media request approval, availability, and user issue notifications from Jellyseerr. |
| `webhook/seerr/global/` | `receiveSeerrGlobalWebhook` | Overseerr / Jellyseerr | `celery` | Global non-tokenized webhook notifications from Overseerr instances. |
| `webhook/kodi/{token}` | `receiveKodiWebhook` | Kodi | `celery` | Playback state updates from the Floppy Kodi sync add-on. |
| `stremio-addon/{token}/subtitles/{media_type}/{media_id}.json` | `receiveStremioSubtitlesSignal` | Stremio | `celery` | Lightweight playback start beacon emitted when subtitles are loaded. |
| `stremio-addon/{token}/player/{media_type}/{media_id}/position=0&duration=0.json` | `receiveStremioAddonPlayer` | Stremio | `celery` | Playback position and duration on play, pause, and stop. The only resume-position source for a client that cannot emit a stop. |
| `stremio-addon/{token}/library/{media_type}/{media_id}/action=watched.json` | `receiveStremioAddonLibrary` | Stremio | `celery` | Library change (add, remove, watched, unwatched) for one item, carrying the affected episode ids in `videoId` as one batched request. |
| `apis/listenbrainz/1/submit-listens` | `receiveListenBrainzListens` | ListenBrainz | None | Synchronous standard JSON listen ingest (Multi-Scrobbler, Navidrome, Pano). |

---

## 3. Celery Execution Queues and Priority Matrix

Floppy enforces strict separation between background jobs and interactive user requests to prevent worker head-of-line blocking.

```
+-------------------------------------------------------------------------+
|                        Worker Queue Architecture                        |
+-------------------------------------------------------------------------+
|                                                                         |
|  [ Interactive Queue ] (Priority: 0, Dedicated Worker)                  |
|  └── Single-item refreshes, live playback updates, modal actions        |
|                                                                         |
|  [ Celery Queue ]      (Priority: 5, Background Worker)                 |
|  └── Inbound webhooks, full calendar reloads, bulk library imports     |
|                                                                         |
|  [ Discover Queue ]    (Priority: 9, Low Priority Background Worker)    |
|  └── Heavy cache warming, trending aggregations, recommendation sweeps |
|                                                                         |
+-------------------------------------------------------------------------+
```

### Queue Definitions

1. **`interactive` Queue (Priority 0 - Highest)**:
   - Reserved exclusively for user-triggered operations where the user is actively waiting on UI feedback (e.g. single-item manual metadata refresh, immediate scrobble reconciliation).
   - **Rule**: Never dispatch bulk imports or multi-thousand item tasks to `interactive`.

2. **`celery` Queue (Priority 5 - Standard Default)**:
   - Handles standard asynchronous tasks: webhook payload ingestion, periodic imports (Sonarr, Radarr, Trakt, Goodreads), calendar refreshes, and notification dispatches.

3. **`discover` Queue (Priority 9 - Low Priority Background)**:
   - Dedicated to computational cache rebuilding, statistics aggregations, and recommendations. Runs asynchronously without impacting media playback updates.

---

## 4. Worker Tier Concurrency Profiles

Floppy provides three validated deployment profiles depending on host hardware constraints:

```json
{
  "minimal": {
    "description": "Single-worker footprint for low-memory appliances (<= 1GB RAM)",
    "worker_count": 1,
    "concurrency_per_worker": 2,
    "queue_assignments": ["celery,interactive,discover"]
  },
  "constrained": {
    "description": "Two-worker standard homelab profile (2GB-4GB RAM)",
    "worker_count": 2,
    "concurrency_per_worker": 2,
    "queue_assignments": ["interactive", "celery,discover"]
  },
  "standard": {
    "description": "Production container deployment with isolated workers (>= 4GB RAM)",
    "worker_count": 3,
    "concurrency_per_worker": 4,
    "queue_assignments": ["interactive", "celery", "discover"]
  }
}
```

---

## 5. Drift Verification and CI Gate

To ensure the committed contract never drifts from codebase routing:

```bash
# Check AsyncAPI channel definitions against registered URL patterns
PYTHONPATH=src uv run --no-sync python -m api.channel_registry --check

# Re-render committed schema
PYTHONPATH=src uv run --no-sync python -m api.channel_registry
```

Any modification to webhook URLs, authentication parameters, or Celery queue assignments must be accompanied by an updated `src/api/contracts/asyncapi.json` and validated by `app.tests.test_api_contracts.AsyncAPIContractTests`.
