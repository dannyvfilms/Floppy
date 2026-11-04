# Incremental cross-platform UI

## Enforceable architecture contract

Universal presentation is the default for reusable components. Use React Native
primitives, concrete semantic theme values, explicit data and action props, and
accessible behavior. Local React state and hooks are allowed. Keep Django, HTML,
HTMX, Alpine, browser globals, CSS classes/units and networking outside universal
presentation. Shared logic is renderer-independent and communicates through
explicit contracts. HTTP, credentials, persistence, navigation and platform
capabilities belong to data layers or adapters. Browser mounts own DOM and Django
lifecycle; platform-specific implementations may use `.web`, `.native`, `.ios`
and `.android` files where platforms genuinely need different APIs. Implement
equivalent behavior, not a placeholder or a WebView/Expo DOM substitute. Preserve
themes, accessibility, responsive behavior and web parity.

Investigate and solve incompatibilities by extracting logic, using native
primitives and adding genuine platform adapters. Do not downgrade a component,
add a baseline entry, suppress a check, or change a check to make a violation
pass. If reasonable approaches encounter an external blocker, report evidence,
attempts and the unresolved dependency; the work remains incomplete. Existing
web-only components are preserved until their own component is reworked.

Before UI work, identify its classification and existing shared implementation;
for significant conversions write a brief plan covering data, platform APIs,
dependencies and regression risks. Update the component register and source map,
run the relevant checks and report actual platform evidence. Provider pages
continue to use the shared provider model and page components; the web-only
`controls.jsx` is a migration source, not a universal dependency.

`docs/ui/architecture-registry.json` is the machine-readable inventory. Register
universal presentation, shared logic, browser integration adapters and paired
platform files with their owner, component names and separate web/iOS/Android
evidence where applicable. Existing browser-specific presentation is frozen as
legacy; unchanged declarations may coexist, but a changed or added declaration
must be moved to an appropriate shared component or adapter. Browser mount adapters
may change to integrate shared components but cannot define HTML presentation.
They may wrap a directly imported registered shared component in an unstyled
anchor for native browser link semantics; the checker restricts its attributes
and requires the shared component as its only child.
Removing migrated declarations is allowed; reintroducing
them is rejected against the base revision. A legacy module may replace an
existing named component export with a same-name re-export of registered
universal presentation or its registered web adapter; other legacy statements
remain frozen. Never add or change a baseline entry
to pass a check. On initial adoption the registry establishes the baseline; later
PRs compare it with the target branch. A platform-specific implementation needs a
web implementation and a native implementation (or both iOS and Android), and
each must be registered. Use `kind: "adapter"` for paired non-rendering services
and `kind: "presentation"` for platform views; counterparts describe the same
named contract. Check:

```sh
npm run check:ui-architecture
npm run test:ui-architecture
npm run check:ui
cd native-proof && npm ci --ignore-scripts && npm run export -- --platform all
```

For example, a universal registry entry is keyed by its source path and has
`register`, `components`, and `verification` fields. Each platform's verification
value is an object such as `{"status": "unverified", "evidence": "Not exercised"}`;
use `verified` only with actual runtime evidence. Universal and platform view
component names must be direct named exports that render an element. A platform
entry also has `kind` and a concrete `purpose`; a browser integration adapter
uses `web_adapters` with its register ID and purpose. Register each paired file.
Non-rendering adapters must not introduce presentation markup. These checks do
not establish that a rendered element implements the required behavior.

CI runs these checks, an Expo dependency audit and the existing regression gates.
The parser enforces source boundaries and ledger links, not visual equivalence,
behavioral completeness, accessibility, truthful evidence or all transitive
platform dependencies. Review those explicitly. CI compares against the PR base
(`UI_ARCH_BASE`); local checks default to `HEAD`. Protect changes to the validator,
workflow and registry through normal code review and branch protection: a check
controlled by a PR cannot protect itself against a deliberate rewrite.

### Separate acceptance and evidence

- **Web complete:** relevant presentation and interactions are migrated with web
  parity and obsolete legacy consumers removed where safe.
- **Native-compatible candidate:** registered universal implementation passes
  architecture checks and has been assessed for its actual platform contracts.
- **iOS verified** and **Android verified:** each requires exercising the stated
  component and behavior on that runtime and recording environment and limits.
- **Production-ready:** applicable workflows, server integration, authentication,
  interaction, accessibility and regression checks have been validated.

These statuses are independent. An import, static check or Metro export is not
runtime verification. A component rendering in the native shell does not verify the
production web card or its actions. Native verification on both platforms does not
by itself establish production readiness.

## Native app shell and next gate

`native-proof/` is a development Expo app, not a production client. `native-proof/App.js`
renders a production-shaped shell: a bottom `TabBar` for Home, Discover, Library,
Calendar and Settings, plus a stack for Detail, Lists, History, Statistics and Search.
`app/screens/*` compose the real screens; `app/components/Screen.jsx` supplies the
header, back action and sections; `app/components/Note.jsx` renders the note for a
surface that is not ported.

Finished ports render in place: `ButtonSlot` in the Settings save bar and Library
actions, `SettingsCardSlot` on Settings, `MediaCardSlot` on Home, Discover and
Library, `RatingSlot` on Detail, `RailsSlot` on Home and Discover, `SearchSlot` on
Home, Discover, Library and Search, `SearchResultsSlot` on Search, `FiltersSlot` on
Library, `ProgressSlot` on Detail, `DateTimeSlot` on Calendar, `ListCard` in the
Lists hub, `ListHeader` in list detail, `HistoryFeed` on History, and
`DetailComposition` on Detail. The screens use realistic labels and demo content
only where a finished screen would show it. Unported surfaces remain `Note` entries
with `surface.id`, `surface.title`, `surface.where` and `surface.status`; they are
not replaced by fake controls or a gallery. The stack screens (Detail, Lists,
History, Statistics and Search) are intentionally not tabs: Settings rows, a card
press or a search suggestion reach them, and pages without ported controls (release
calendar, statistics, list detail results and tiers, detail children, tables,
settings navigation and the parent pickers) stay as notes until their controls are
ported.

Recorded runtime evidence is deliberately narrow. The Android 15 Pixel 7 AVD
reached Home, Library, Calendar, Settings, Search results, Lists, History and Detail
and rendered the shared search, filters, media cards, list cards, history rows,
detail composition, settings card/chip, buttons, rating chip, progress card and
date-time field; Android demo images did not load. The iOS 17.2 simulator rendered
Home with search, cards and rails. Neither pass included VoiceOver/TalkBack or a
full interaction pass, and each registry entry carries that limit separately.

The Django esbuild configuration aliases `react-native` to React Native Web; the
shell's Metro configuration resolves shared imports to the app's single React and
React Native installation. Run `npm ci` and `npm run export -- --platform all`
inside `native-proof/` for a compile check. An export is not runtime verification:
it does not establish iOS or Android behavior. The shell renders local demo data
and does not authenticate or read the API, so native transport, secure credential
storage, revocation and server identity remain undesigned. `export:django` still
writes the web export under the ignored `src/static/native-proof/`; that directory
and `native-proof/` stay outside Docker's build context. `npm audit --audit-level=high`
runs in CI; the Expo dependency tree currently has five moderate advisories.

The next gate is interaction and accessibility evidence on both iOS and Android
for each ported component, then the remaining action adapters (media-card popups,
bulk selection, list detail results and tiers, parent pickers and statistics).
`controls.jsx` remains a migration source, not a universal dependency: DOM events,
focus, popups, CSS variables and server-owned interactions still need platform
contracts. Translate semantic theme tokens at each platform boundary; never pass
browser CSS values, HTML or stored credentials as native props.

### Adding the next port

A follow-up port replaces its slot note in
`native-proof/app/surfaces/<Name>Slot.jsx` with the shared component, keeping
`surface.id`, `surface.title` and `surface.where` accurate. Set `surface.status` to
`'in_progress'` in the first commit and `'ported'` only when the placement is
complete; if only part of the surface is ported, leave `'in_progress'` and say what
remains. Unfinished surfaces stay as `Note` entries rather than placeholder controls.
Record implementation status in the component register and source map and keep
iOS/Android runtime evidence separate; an Expo export is only a build check.

## Decision and limits

Keep Django's server-rendered web application, backend, domain rules, integrations,
database and API. The shared settings-card shell on provider Connection and Import
is the first authorized React/React Native Web browser pilot. Its implementation
and coexistence boundary are documented in [settings cards](../ui/settings-cards.md).
AniList now extends that shared shell into a [fully React-owned provider
region](../ui/provider-pages.md): Overview, Connection, Import and Activity. The
global Django shell remains server-owned. Every provider now uses the same React
header, tabs and data-driven Overview cards; unported tab bodies remain separate
server-owned siblings under that shared shell.
Every component created or edited by an agent, including copy or styling changes,
must migrate to the shared React pattern in the same change. Incremental migration
prepares reusable presentation for eventual native iOS and Android apps and reduces
a future bulk migration. Users should not notice the framework change: preserve
appearance, interactions, responsive behavior, accessibility and performance.
Reuse or extend existing shared components before introducing a new one; keep
domain logic, permissions and transport in feature adapters. Only a concrete
external blocker leaves the work incomplete and must be reported with evidence
and attempted solutions. Task size and trivial edits are not exemptions.
Every change updates the component register and source map for each affected
surface, including ownership state, remaining legacy consumers and retirement
conditions. Browser and actual iOS/Android verification remain separate. Shared
controls with recorded iOS and Android runtime evidence include Spinner, Badge and
ProgressChanger. The second wave adds render-only evidence on Android for
GlobalSearch, FilterBar, MediaCardView, ProgressCard/ProgressBar, DateTimePicker,
Button, RatingChip and SettingsCard/Chip, and on iOS for GlobalSearch, MediaCardView
and Rail. The third wave adds Android render evidence for SearchResults, ListCard,
HistoryFeed and DetailComposition; ListHeader, MediaCardActions, MediaCardActionHost,
ProgressBreakdown and RatingStars remain unverified. Render evidence is not an
interaction or accessibility pass. Native products remain separately scoped.
The migration unit is the reusable component, not a provider or page. Use the
[shared controls](../ui/react-components.md) as the starting point for fields,
selects, buttons, chips, tabs, dialogs and card layouts; migrate a touched legacy
control rather than importing its web-only implementation into universal code. Feature code
supplies domain behavior; a bounded component adoption needs no whole-page rewrite.
Use the [component register](../ui/component-register.md) for
component status and the [source map](../ui/source-map.md) for ownership.

The product direction supports the existing self-hosted web experience, eventual
genuine iOS/Android clients connected to a Floppy server, and possible standalone
manual tracking later. A hosted service is optional. Native applications, device
storage, data migration and synchronization each need separate authorization and
design. Server integrations, webhooks, scheduled jobs and some metadata services
remain server capabilities; a local client must communicate those limits.

## Why this candidate, and what is still uncertain

RNW renders React Native primitives through React DOM and supports server rendering.
It warns that document-wide CSS can interfere with component styles.
[RNW rendering](https://necolas.github.io/react-native-web/docs/rendering/).
React supports mounting multiple roots into selected portions of an existing page
and requires unmounting roots before external code removes their containers.
[React createRoot](https://react.dev/reference/react-dom/client/createRoot).
Together these support investigating Django-hosted islands; they do **not** prove
Floppy's HTMX lifecycle, Alpine ownership, Tailwind reset or deployment compatibility.

Expo supports web builds and platform-specific modules.
[Expo web](https://docs.expo.dev/workflow/web/),
[platform modules](https://docs.expo.dev/router/advanced/platform-specific-modules/).
Use shared React Native primitives for native candidates. Conventional React DOM,
HTML, Tailwind classes and jQuery widgets do not become native UI through JSX.
Expo DOM components use a WebView on native and cannot satisfy the genuine native
requirement by themselves.
[Expo DOM components](https://docs.expo.dev/guides/dom-components/).
RNW provides accessibility APIs; actual keyboard, semantics and assistive technology
behavior still require platform testing.
[RNW accessibility](https://necolas.github.io/react-native-web/docs/accessibility/).

### Alternatives

- Continue Django/HTMX/Alpine: smallest current maintenance burden and good server
  rendering, but offers no shared native view implementation. Untouched legacy
  components remain in place until their affected unit is migrated.
- React DOM islands alone: workable web composition, but their DOM views need
  native replacements; they are not universal presentation.
- Whole Expo web application or SPA: potentially shares more screens, but adds
  routing, authentication and rendering migration before it solves a component
  need. Outside this initiative's scope.
- Separate native views with shared data contracts: less presentation reuse, but
  a valid fallback if RNW islands cannot preserve desktop semantics, performance
  or maintenance simplicity. Document the failed gates before adopting it.

## Existing seams and constraints

`src/templates/base.html` owns navigation, search, common scripts, HTMX boost,
authentication redirects, CSRF injection, modal containers and response events.
`base_public.html` supplies a distinct public/authentication shell. Inline Alpine
code matters as much as files in `src/static/js/`. `package.json` pins React,
React DOM, RNW and esbuild alongside Tailwind. `npm run build:ui` emits committed,
self-hosted assets under `src/static/ui`; `npm run check:ui` checks reproducibility.
The tiny page loader fetches the shared React runtime when an island appears. The
header search form is an island on every signed-in page, so the runtime (about 97 KB
gzipped plus 5 KB of CSS) loads on each of them. This is deliberate: the application
is moving to React page by page, and a runtime that loads everywhere is the end state.
There is no production native application or native release pipeline; the
native shell above is a development experiment.
The deployed stylesheet is `src/static/css/main.css`, generated from `input.css`.

Media cards already have one contract in `app/card_surfaces.py` and a template tag;
do not create a parallel card system. The library query engine already normalizes
filters and bounded results. Preserve those backend boundaries. Read the existing
[media card](media-card.md), [library query](library-query.md),
[theming](theming.md), [API scopes](api-scopes.md),
[local covers](local-covers.md) and [statistics sync](statistics-sync.md) contracts.

Potentially shared: artwork framing, rating/status/progress presentation, labels,
simple controls, filter state transformations and display formatting. Sharing
Python domain logic would require a service call or a separately designed local
equivalent; never silently duplicate authoritative rules in JavaScript.

Platform boundaries remain for browser links/SEO, document focus/portals, large
tables, file upload and download, camera/barcode access, date inputs, clipboard,
drag-and-drop, navigation/deep links, charts, credentials, storage and background
work. Chart.js, Select2, SortableJS, marked, lazySizes, ZXing browser decoding and
the service worker are web implementations, not native dependencies. Keep shared
models/intent where useful and choose platform renderers only when needed.

## Rules for migrated components and the native shell

### Ownership and coexistence

1. Django retains routes, page shell, public content and permissions. Mount a
   bounded island into an explicit container; React owns its descendants. Alpine
   and HTMX must not mutate those descendants. Avoid nested duplicate state owners.
2. Initialize idempotently on full load and HTMX insertion. Unmount before cleanup
   or replacement, release listeners/timers/requests and prevent duplicate roots.
   Exercise boosted navigation, back/forward, partial and out-of-band swaps.
3. Pass escaped, serializable props using Django's `json_script` or an equivalent
   existing safe serialization boundary. Never embed raw template context or HTML
   as a shared component API. Django HTML is not React hydration output. For the
   retained partial settings-card consumers, a Django block tag composes a React-owned header and a
   **sibling** Django-owned body slot. The latter is intentionally partial migration,
   not HTML injected into React. Its controls retain their existing owners until
   separately ported. No React root contains an Alpine/HTMX form.
   AniList uses one full provider root, with React-owned forms and dialogs posting
   to the existing Django handlers. Its legacy descendants are a fallback replaced
   before interaction; they are not initialized by Alpine/HTMX within that root.
4. Preserve useful server-rendered content and links on public/indexable pages.
   Do not introduce a JavaScript-only public replacement. Choose fallback or
   separately justified SSR only if the experiment demonstrates a need; do not
   introduce a JavaScript server alongside Django by default.
5. Replace the affected legacy call sites when the new component is accepted.
   Temporary coexistence requires named surfaces, reason, owner/related work and
   a concrete retirement condition in the register. Share one bundle/runtime
   across islands; do not create a second independently maintained web app.

### Presentation and data

Use explicit values and callbacks expressing user intent. Presentation must not
read Django contexts, construct server URLs, import ORM concepts or hold transport
credentials. A web boundary may map existing server data and callbacks; add adapters
only for the actual component, not a speculative repository/provider framework.

Web session requests keep CSRF, same-origin and existing permission enforcement.
Native transport will need a chosen server URL, secure credential storage, supported
authentication/scopes, expiry/revocation and TLS handling. Existing APIs in
`src/api/urls.py`, `fork_urls.py` and `contracts/openapi.yaml` are starting evidence,
not a promise of parity with every template form. Check required fields, pagination,
errors, ownership and writes against their contract tests before choosing an island.
HTMX fragments and cache polling endpoints are not portable data contracts.

Keep provider/source/media identity separate from navigation URLs and database row
identity. Represent dates/timezones, nullable ratings, progress units and repeat or
session identity explicitly. Preserve server normalization and validation. Avoid
assuming every capability is available, every write has network access, or a server
URL is permanent. These constraints leave room for local tracking; they do not
establish offline queues, conflict rules, stable local IDs or a sync protocol.

Use semantic theme values from the existing palette, radius and motion contract.
For an experiment, map only the tokens it needs to RN styles; do not establish an
independent native palette or add a styling framework. CSS variables, `rem`, SVG
includes and Tailwind breakpoints need explicit native equivalents. Share design
meaning, not an untested claim of identical styling syntax. Keep localization,
pluralization, title preferences and accessible names supplied explicitly.

### Smallest tooling experiment

For native Phase B work, pin compatible React, React DOM, RN, RNW and Expo
versions after checking their supported combination. First try one web entry with
a small build command and a `react-native` to RNW alias, emitted through Django's
existing static asset path and container collection. The development Expo app
can verify the same source on iOS and Android; it must not become a second product.
Select the bundler based on this experiment, rather than adding Vite, Metro, a monorepo,
Expo Router, a UI kit or a native styling layer to production now.

Verify deterministic locked builds, source-run development, cache busting, static
collection, offline/self-hosted deployment without a CDN, and publication workflow
requirements. Measure compressed/transferred JS, parse/execution, layout shift,
mount latency and repeated-navigation memory before/after on representative mobile
and desktop browsers. Set explicit acceptable budgets in the experiment before
acceptance; the browser pilot's budgets/results are in its component guide. One runtime per page is
required; loading cost may make a tiny component an unsuitable production island.

## Behavioral parity and verification gate

Migration never authorizes redesign. Preserve controls, appearance, responsive
layout, loading/empty/success/error states, validation, permissions, keyboard,
mouse/touch, focus restoration, accessible semantics and performance. An approved
redesign may change only what its issue specifies. Never remove difficult behavior
to claim parity. Do not treat an existing accessibility gap as permission to regress.

For the affected component record existing screenshots/states and relevant targeted
tests, then compare the replacement at phone/tablet/desktop widths and theme states
required by the theming contract. Exercise interaction, failure, slow responses,
auth expiry, repeated swaps and public/read-only surfaces. Use browser automation
where behavior merits it; follow repository test tags and commands. A future native
claim requires running the same component source on **both iOS and Android** with
platform/version, simulator/device, interactions, accessibility checks and result
recorded. A successful build, JSX or a web preview is insufficient.

Keep implementation status separate from verification. If a gate fails, retain the
working component, record the blocker and reassess the architecture. Do not set
`Ready` until the foundation and component-specific assessment pass.

## Progression and maintenance

- **A — Inventory/preparation:** maintain the register, source ownership and these
  constraints. Unchanged components retain their existing implementations.
- **B — Architecture proof:** the user authorized provider Connection/Import cards
  as the first browser pilot, replacing the proposed rating-only starting point.
  Validate the island lifecycle, existing form ownership, themes, fallback and
  deployment before extending the pattern. Native parity remains unverified;
  verify the same source on iOS and Android before native acceptance. If runtime
  cost is disproportionate, record it and reassess rather than force adoption.
- **C — Incremental modernization:** every component creation or edit, including
  copy and spacing, includes the shared React implementation in the same task.
  Reuse the card pilot's web boundary; do not create a parallel app or bundle/runtime
  per component. Native runtime verification is not a blocker for browser ports. Deferral requires
  an evidenced compatibility blocker, a reopening condition in the register and
  explicit reporting to the user; task size is not an exemption.
- **D — Completion passes:** use register status, affected surfaces and dependencies
  to plan focused consolidation and retire duplicate implementations.
- **E — Native products:** separately approve server-connected native applications;
  evaluate local persistence, offline tracking and synchronization independently.

For every UI change, find the stable component ID, read its contract, assess
scope, preserve behavior, validate the risky changes and update only affected
records/source mappings. Record issue/PR links when known; do not invent owners or
verification. Use Git history when assessing frequently changed components; record
recurring deferrals against their ID so they can inform a focused pass. Never run a
full audit for a small edit. The source map contains a lightweight completeness
check; no new build dependency or CI gate is needed for this documentation.
