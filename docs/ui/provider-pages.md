# React provider pages

The Providers directory is also React-owned through
`frontend/providers/Directory.jsx`. It consumes shared catalog cards/grid and
filter toolbar controls. Its authenticated directory URL supports `format=json`
with explicit presentation fields only; filtering remains server-authoritative.
The 300ms debounce cancels stale requests, updates query/capability/media in the
URL, and restores filters/results on Back. Failed requests offer retry, and failed
bundle loads preserve a native GET form and server-rendered cards. See the
[shared component contracts](react-components.md) for container breakpoints.

The Connection filter lists providers with Connection settings and links directly
to that tab. A shared status icon distinguishes available credentials/saved accounts,
missing setup and warnings. Availability includes bundled metadata credentials;
its tooltip explicitly identifies bundled defaults. This describes local setup,
not a live remote health check. The credential fields show masked previews and
identify bundled fallbacks, so an available default cannot look like an unset key.
Editable inputs remain empty: previews are hints, never values submitted by a form.
Saved key previews stay in server-rendered credential fields and are excluded from
React presentation JSON.

AniList is the first complete provider-region port. Its header, media chips, tabs,
Overview, Connection, Import and Activity are rendered by React. The application
shell and settings navigation still come from Django. Other providers retain their
existing implementations until deliberately ported; do not infer support for their
metadata, tracking or outgoing-sync controls from AniList.

## Component and framework ownership

`frontend/providers/ProviderPage.jsx` composes tab components and the shared
`SettingsCard` and the [app-wide controls](react-components.md) from
`frontend/ui/controls.jsx`: fields, selects, buttons, chips, tabs, card grids and
modal dialogs. `web.jsx` only supplies provider context and a thin form adapter.
These shared controls contain no provider logic. They are React-owned DOM controls,
not server HTML inserted into React. The card's React Native presentation remains
reusable; the complete page and its browser controls are not a native implementation.

The provider route serializes a narrow view model from `users/provider_ui.py`
through `json_script`. `provider_detail.html` exposes one `data-provider-root`;
the common loader lazily mounts it through `frontend/providers/mount.jsx`.
Nested legacy header roots are excluded from mounting. React owns the entire
provider region after mount, including all content and interactions.

Legacy markup is a loading/error fallback, not a second running UI. The root has
`x-ignore` and `hx-disable` so Alpine/HTMX cannot initialize its descendants before
or after React takes ownership. Fallback HTML is never a React prop or hydration
source. It preserves readable navigation and Overview plus traditional credential
and public-import submissions; scripted preference editing, help and activity need
the React bundle. Fallback public imports use saved preferences. Drafts typed while
the lazy module loads are captured locally before replacement; entered credential
values stay in current-page browser memory and are never added to serialized server
props, logs or persistent browser storage.

The partial Django card composition remains for other providers and uses the same
runtime, palette and lifecycle. Its server body slot stays outside its header root.
Port those consumers when their complete controls are in scope; do not create a
parallel framework owner inside either kind of root.

## Overview is actual state

AniList has three cards, each a native, keyboard-accessible link to its owning tab.
There are no separate manage/configure/view footers. All three status subtitles
use the same muted typography and omit terminal periods. Tabs retain the active
bottom-border indicator without adding text underlines on hover. The grid responds to available
container width, and shared card headings wrap badges instead of spilling outside.
Hover/focus outlines appear immediately in their theme color; they are excluded
from color/background transitions to avoid a white default-outline flash.


- Connection: effective personal or instance credentials, or neither. All required
  fields must resolve. Personal fields may use instance fallback; this is stated
  in a hover tooltip. The inactive explanation is also a tooltip, keeping the card
  body to one status line. No provider network probe or OAuth login is implied by configuration.
- Automatic import: enabled, recurring AniList schedules owned by the current user.
  A saved frequency preference, disabled schedule or one-time job is not an active
  recurring import. The next date uses the existing schedule helper and user format.
- Last active import: the latest AniList run or newer queued task for this user.
  Runs older than the seven-day Activity window remain eligible. Lost pending tasks
  older than 30 minutes are excluded consistently with existing import history.

These decisions remain in Python. The React components consume explicit values;
they do not inspect credentials, parse database kwargs or recreate scheduling rules.

## Existing writes and safe data

Connection posts to the existing instance/personal save and instance-clear handlers.
Superuser checks and environment locks remain authoritative on the server. No saved
credential values or masked previews are serialized. The view model carries only
field metadata, presence/lock flags and safe presentation text; new values are entered
directly into React-owned browser forms. The web boundary supplies CSRF and safe
local return URLs. Blank values retain/remove the same fallbacks as before.

Import preserves the user's global frequency/time/mode preferences. Auto-save writes
are serialized so a slow earlier request cannot overwrite a newer selection. Failed
saves are visible and retryable. Import submissions carry the currently selected
values and use the existing public username or private OAuth action. Public imports
work without Connection; only private imports require configured client credentials.
Unsupported modes remain disabled. Unmount aborts pending preference work.

The web-only activity contract is the existing authenticated provider URL with
`tab=activity&format=json&page=1`. It is not a new public/native API. It returns
current-user AniList schedules, seven-day task history in pages of 50, the latest
ten runs, and scoped imported-media counts/actions. Paging is bounded to 1,000
pages; other tabs reject this format. Responses are private/no-store. No task kwargs,
OAuth tokens, stored credential values or prepared-import payloads are serialized;
error details pass through the existing redactor.

The existing import-activity reader accepts an optional source/page scope; its
valid legacy formats remain supported. SQL text checks are only prefilters;
reads/actions verify the parsed owner field, including compact JSON and Python-repr
kwargs, so embedded text cannot make user 10's task appear to belong to user 1. Cancel, schedule deletion,
undo and source cleanup keep their existing ownership checks, confirmations and
server-side restrictions. Supplied local `next` destinations return to Activity;
unsafe return URLs fall back to the existing destination.

Activity fetches on entry and polls every five seconds while work remains active.
Opening diagnostic details aborts/pauses refresh, retaining expanded text and copy
controls. Closing the last details section reloads the snapshot. Requests, timers
and copy feedback are disposed on unmount. Loading, failure/retry, empty, progress,
success and cancellation states remain visible. Provider-specific match review and
watched-state sync are not AniList capabilities.

## Build and verification

Use the [shared build and lifecycle commands](settings-cards.md). There is one
React/RNW runtime, separate lazy header/page modules, and committed self-hosted
assets. Provider CSS is shared with the small global settings stylesheet. The
expanded loader/CSS budget is 3 KiB gzip; the full page plus shared runtime remains
under the pilot's 110 KiB gzip JavaScript budget. Pages without islands do not fetch
React. Neither Node at runtime nor a second router/dev server is required.

Relevant checks include `users.tests.views.test_provider_react`, the existing
credential/import/model/OAuth/action tests, and
`users.tests.test_settings_cards_browser` (tagged `slow`, `playwright`). Browser
checks exercise one root across all four tabs, private/public import behavior,
CSRF submissions, Overview state, activity details/actions, HTMX cleanup,
back/forward lifecycle events (retaining drafts in persisted bfcache documents), fallback and responsive theme states. Existing
provider-specific integration tests remain authoritative for importer behavior.

iOS/Android, native forms/transport/secure storage, real provider OAuth and physical
mobile assistive technology are not verified by this browser port. Keep those
limits separate from the accepted React web implementation.
