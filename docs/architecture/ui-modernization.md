# Incremental cross-platform UI

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
compatibility blocker permits deferral, with evidence, a reopening condition and
explicit reporting to the user. Task size and trivial edits are not exemptions.
Every change updates the component register and source map for each affected
surface, including ownership state, remaining legacy consumers and retirement
conditions. Browser and actual iOS/Android verification remain separate. No component
has been verified on iOS or Android, and native products remain separately scoped.
The migration unit is the reusable component, not a provider or page. Use the
[shared controls](../ui/react-components.md) for fields, selects, buttons, chips,
tabs, dialogs and card layouts wherever those elements are reworked. Feature code
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
  rendering, but offers no shared native view implementation. Remains the default
  for untouched components and explicitly documented migration deferrals.
- React DOM islands alone: workable web composition, but their DOM views would
  need native replacements. Useful only for explicitly web-specific exceptions.
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
There is no native application or Expo build pipeline.
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

## Rules for a future proof and migrated components

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
existing static asset path and container collection. A disposable Expo test harness
can verify the same source on iOS and Android; it must not become a second product.
Select the bundler based on this proof, rather than adding Vite, Metro, a monorepo,
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

## From React on the web to native apps

Reaching 100% on the component register means Floppy's web interface runs on React.
It does not produce iOS and Android apps, and it does not even mean the components
could run on a phone. This section records the path, what the code does today, and
the rules that keep a native app from forcing a second rewrite of the components
migrated now. It was written after comparing the plan with an outside review of the
same question; the comparison is below.

### The path

1. **Web React (phases A to D below).** Every interface is a React component mounted
   by Django. Outcome: a modernized web application. Not a native app.
2. **Native-ready presentation and data.** Shared presentation is written with React
   Native primitives and semantic tokens (rendered by react-native-web in the
   browser), takes everything it shows as props, and touches no browser API.
   Browser behavior lives in a thin web adapter. The data a component needs is also
   available as JSON from the API, not only embedded in a server-rendered page.
3. **A native client.** An Expo app (not a second product: see the tooling
   experiment) with a server-address setup step, authentication that does not rely
   on browser sessions, secure credential storage, native navigation and the device
   features Floppy needs (barcode scanning, share, deep links). Platform-specific
   renderers are allowed where the platform differs; sharing logic, tokens and
   models is the goal, not identical code on every platform.
4. **Distribution.** Signed builds, device testing on iOS **and** Android (see the
   verification gate), store or direct distribution.

Steps 1 and 2 overlap on purpose: a component migrated to the web *and* written to
the step-2 rules never needs migrating again. A component migrated to the web only
needs its presentation rewritten later, once per component.

### What the code does today

Measured on 3 Nov 2026 with `python3 scripts/ui_migration_metrics.py --native`
(method in [migration measurement](../ui/migration-measurement.md)):

- Of 27 React presentation files (2,864 lines), **4 files (123 lines, 4%)** import
  `react-native`: `RatingStars`, `AlphabetBar`, `SettingsCard` and `Chip`.
- The other **23 files (96%)** write HTML tags with CSS class names, including the
  shared controls (`controls.jsx`: `Button`, `Badge`, `Spinner`, fields, dialogs),
  the media card (`MediaCard.jsx`), the sidebar, the search bar, the popup host, the
  bulk toolbar and the provider pages. They have 216 references to browser-only APIs
  (`window`, `document`, `htmx`, `fetch`, event listeners) and 352 `className` uses.
- The shared card's data is already a plain props model built in
  `app/media_card_model.py`, which is the right shape. But the model reaches React
  through `json_script` in a server-rendered page, and saves refresh cards through
  HTMX out-of-band fragments. The API in `src/api` does not serve card models.

So the component register's "React-owned" means *React DOM on the web*. This is the
conflict with the plan: the plan says shared presentation should use React Native
primitives and that a native claim needs "the same component source" on both
platforms, yet phase C lets every browser port proceed with no native gate, and most
ports have been written as DOM. Left alone, the finished web migration would need its
presentation rewritten a second time.

### Rules for shared presentation from now on

These replace "prefer React Native primitives" for new and edited shared components.

1. **Presentation is primitives plus tokens.** A shared component draws with
   `react-native` primitives (`View`, `Text`, `Pressable`, `Image`, `TextInput`) and
   style objects built from semantic theme tokens, not HTML tags and Tailwind or CSS
   classes. The build already aliases `react-native` to react-native-web.
2. **Presentation is props-only.** It receives values and callbacks expressing user
   intent. No `window`, `document`, `htmx`, `fetch`, `localStorage` or URL building.
3. **Browser behavior is an adapter.** Mounting, hover, touch reveal, HTMX events,
   Alpine bridges, portals, camera and drag-and-drop live in a `mount*.jsx` or
   `*.web.jsx` file next to the presentation, so a `*.native.jsx` can replace it.
4. **A server-rendered fallback stays on the web.** It is not shared presentation.
5. **Data has a JSON contract.** A component's props come from a model builder that
   returns plain JSON (as `media_card_model.py` does). When a component is touched,
   the same model must be reachable from the API, and its write responses must be
   JSON the component can apply, not an HTMX fragment. HTMX fragments and polling
   endpoints are not portable data contracts.
6. **Web-only is an explicit register state.** Charts, camera and barcode decoding,
   drag-and-drop, large tables and similar web implementations are recorded as
   web-only with a reason and what a native screen would use instead. Expo DOM
   components (a WebView on native) may bridge a web-only screen temporarily. They
   never count as native and are recorded as an exception, never as a migration.
7. **Record native readiness per component.** Each React-owned or partial register
   entry has a `- Native readiness:` line. `Ready` needs primitives, no browser API,
   a JSON data path, and the verification gate below. Until the gate passes the
   most it can say is `Primitives`. `DOM` means a presentation rewrite is still owed.

Converting the shared controls first is the highest-leverage step: the card, popups,
sidebar and provider pages all compose `controls.jsx`, so moving `Spinner`, `Badge`,
`Chip`, `Button` and the fields to primitives moves every consumer at once. After
that, split `MediaCard.jsx` into a props-only view and a web adapter for hover,
touch and HTMX.

### Recommended: one native proof before more DOM ports (needs approval)

The plan keeps native proof out of the way of browser ports. That is the source of
the rework risk, so this section proposes one narrow proof now; it is not yet
authorized, and native products remain separately approved (phase E):

1. A disposable Expo test harness (it must not become a second product) renders one
   shared component from this repository.
2. The first target is the media card view, fed from a new JSON endpoint that serves
   the existing `media_card_model` for real library items on a Floppy server.
3. Run it on an iOS and an Android simulator or device, record platform, version and
   result per the verification gate, and write down every component convention that
   the proof forced to change.

Browser migration continues in the meantime under the rules above; the proof shows
whether the rules are enough before more components are written.

### How this compares with the outside review

| Point in the review | Position in this plan |
| --- | --- |
| 100% React on the web does not give native apps | Already stated here. Added the measured gap above. |
| React components are not React Native components | Already stated. The code did not follow it: 96% of presentation is DOM. Rules 1 to 3 close the gap. |
| Add a second measure for native readiness | Adopted. `ui_migration_metrics.py --native` and the `Native readiness` register lines. The web percentage must not be read as native progress. |
| Start a native proof of concept early | Proposed above and awaiting approval. It changes the old "native proof is not a blocker" stance only for this one proof. |
| Expo DOM components as a bridge | Allowed only as a labelled temporary exception for web-only screens, never counted as native. |
| API-driven data layer instead of server-rendered HTML | Rule 5. Existing APIs are starting evidence, not parity (see Presentation and data). |
| Self-hosted server address, authentication and secure storage first | Already listed under Presentation and data. Needed before any native screen does real work. |
| `apps/` and `packages/` monorepo layout, Expo Router | Not adopted. This plan deliberately avoids a monorepo, Expo Router or a UI kit until the proof selects a bundler. The layout in the review is illustrative. |
| App store review needs more than a repackaged website | Not verified here. Treat a WebView-only app as an open risk. |

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
  per component. Native proof is not a blocker for browser ports, but new and edited
  shared presentation follows the native-ready rules in [From React on the web to
  native apps](#from-react-on-the-web-to-native-apps). Deferral requires
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
