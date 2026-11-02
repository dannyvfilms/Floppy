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
The tiny page loader fetches the shared React runtime only when an island appears.
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
  per component. Native proof is not a blocker for browser ports. Deferral requires
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
