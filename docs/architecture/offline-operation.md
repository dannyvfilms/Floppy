# Offline and air-gapped operation

## Status

This document defines the first supported offline foundation for Floppy.

It covers two failure cases:

1. The Floppy server can reach its database, but metadata providers are unavailable or blocked.
2. An installed PWA cannot reach the Floppy server.

It does not claim that private account data is available in the browser when the Floppy server is down. That capability needs an encrypted local store and a conflict-safe synchronization design.

## Provider network modes

Set `FLOPPY_NETWORK_MODE` on every web and worker process.

| Mode | Behavior |
| --- | --- |
| `online` | Allow all metadata providers. This is the default. |
| `offline` | Block every request that uses the shared metadata-provider HTTP boundary. |
| `restricted` | Allow only exact provider identifiers in `FLOPPY_NETWORK_ALLOWLIST`. |

Example offline configuration:

```env
FLOPPY_NETWORK_MODE=offline
```

Example restricted configuration:

```env
FLOPPY_NETWORK_MODE=restricted
FLOPPY_NETWORK_ALLOWLIST=tmdb,tvdb
```

The allowlist is case-insensitive. It uses exact provider identifiers. It does not accept URLs, host suffixes, or partial matches.

The legacy variable names `YAMTRACK_NETWORK_MODE` and `YAMTRACK_NETWORK_ALLOWLIST` remain accepted when the Floppy names are not set.

### Fail-closed behavior

An invalid mode or allowlist entry stops the request before the HTTP session runs. The error does not include the URL, query string, request body, token, or provider response.

`offline` mode also stops provider retries because the first request is denied before a socket call.

## Existing server data

The provider guard is installed during Django application startup. Web processes and Celery processes use the same shared provider boundary.

When a detail path already handles `ProviderAPIError`, a denied provider request follows the existing stored-metadata fallback without waiting for a network timeout. Local database reads and writes do not need a metadata provider.

This foundation does not yet route every direct HTTP client through the shared boundary. RSS fetches and separately implemented integration clients need follow-up guards before `FLOPPY_NETWORK_MODE=offline` can be treated as a process-wide no-egress control. Until that work is complete, disable configured integrations and scheduled jobs that make direct network calls in a strict air gap.

Track the remaining work in issue #778.

## PWA behavior

The service worker derives the application root from its registration scope. The same files therefore support these forms:

- `https://floppy.example/`
- `https://floppy.example/floppy/`

The manifest uses relative URLs for its application identity, scope, start page, icons, and shortcuts.

### Cached data

The service worker may cache only these public resources:

- The public offline status page.
- Same-origin files under the application's static-file path.
- The public web app manifest and icons.

The service worker does not cache:

- Authenticated HTML.
- Navigation responses.
- API responses.
- HTMX fragments.
- POST, PUT, PATCH, or DELETE requests.
- Cross-origin responses.
- Opaque responses.

This boundary prevents one account from exposing rendered private data to another account that uses the same browser profile.

### When the Floppy server is unavailable

A normal navigation first uses the network. If the network request fails, the service worker shows a public status page with one action: **Try again**.

The status page is self-contained. It supports keyboard focus, narrow screens, zoom, dark mode, and reduced motion. It does not auto-refresh or create repeated alerts.

The status page does not show a user's library, history, lists, collections, credentials, or account state.

## Full private-data offline mode

A later phase can make private data available while the server is unavailable. It must include all of these controls:

1. An encrypted local database with per-user and per-device separation.
2. A revocable device credential with the minimum required scope.
3. An idempotent outbox for offline writes.
4. Conflict detection and a visible resolution policy.
5. Server-side replay protection.
6. Logout, account-switch, and device-revocation purges.
7. Storage quotas and safe migration rules.
8. Multi-device tests for ordering, duplication, deletion, and clock drift.

Do not implement this capability by caching rendered authenticated pages.

## FloppyDesktop contract

FloppyDesktop consumes Floppy downstream. This foundation uses Django and standard browser APIs only. It does not require a cloud service, CDN, browser extension, or desktop-only branch.

A downstream release must still validate:

- The packaged application origin and service-worker scope.
- Static-file paths in development and production packages.
- Upgrade behavior from the earlier `floppy-v2` cache.
- Logout and account-switch behavior.
- Provider policy variables in each packaged web and worker process.

## Validation checklist

### Provider policy

- Set `FLOPPY_NETWORK_MODE=offline`.
- Open an item that already has stored metadata.
- Confirm that the page does not wait for the provider timeout.
- Confirm that the provider HTTP session records zero calls.
- Confirm that logs do not contain a URL, query string, token, or response body.

### Restricted mode

- Allow one provider.
- Confirm that the named provider can connect.
- Confirm that a similar or partial provider name remains blocked.
- Confirm that an invalid identifier fails closed.

### PWA

- Install at `/` and at `/floppy/`.
- Load the app once while the server is available.
- Stop the Floppy server.
- Open a normal page and confirm that the public offline page appears.
- Confirm that **Try again** receives keyboard focus and reloads the requested page.
- Inspect Cache Storage and confirm that no authenticated document or API response exists.
- Test 320 px and 375 px widths, 200% zoom, keyboard-only input, dark mode, and reduced motion.

## Recovery

To restore unrestricted provider access:

1. Set `FLOPPY_NETWORK_MODE=online` or remove the variable.
2. Restart every web and worker process.
3. Confirm that one defined provider request succeeds.
4. Review logs for configuration errors before enabling scheduled refresh work.

The installed PWA updates its public cache when the new service worker activates. It deletes only obsolete caches for its own application scope and the known legacy `floppy-v2` cache.

## Post-mortem

### What happened

Floppy persisted metadata, but some read paths still contacted a provider before they used the stored record. A provider outage or air gap therefore created timeouts and partial pages for data that already existed locally.

The first service worker correctly avoided dynamic-page caching, but it stopped at static files. It used root-only paths and had no application fallback when the Floppy server was unavailable.

### Why it happened

Provider availability, local data, background refresh work, PWA installation, and downstream packaging were treated as separate implementation details. They did not share one explicit offline contract.

### Controls added

- One provider request boundary with online, offline, and restricted modes.
- Exact allowlist matching and fail-closed configuration.
- Tests that prove denied requests make zero HTTP calls.
- Scope-derived PWA and manifest paths.
- A public offline page that contains no account data.
- Tests that prevent navigation and HTMX responses from entering the cache.

### Remaining controls

- Route every direct HTTP client through a defined egress policy.
- Suppress network-only scheduled work while the instance is offline.
- Build the encrypted local-data and synchronization phase.
- Run the downstream packaging and upgrade matrix in FloppyDesktop.
