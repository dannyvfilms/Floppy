# Incremental cross-platform UI

## Decision and limits

Keep Django's server-rendered web application, backend, domain rules, integrations,
database and API. React Native with Expo and React Native Web (RNW) is the leading
candidate for shared presentation, **pending a separately authorized proof**. No
production component has been migrated or verified on native platforms. This
document establishes migration boundaries and acceptance gates, not an approved
framework rollout. Use the [component register](../ui/component-register.md) for
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
  until the experiment passes.
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
code matters as much as files in `src/static/js/`. `package.json` currently contains
Tailwind development dependencies only; there is no React or native build pipeline.
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
   as a shared component API. Django HTML is not React hydration output.
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

When Phase B is authorized, pin compatible React, React DOM, RN, RNW and Expo
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
acceptance; there are no measured budgets or results yet. One runtime per page is
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
  constraints. Production UI remains on the current stack.
- **B — Architecture proof, separately authorized:** start with the read-only rating
  presentation in `media_card_rating.html`, preserving its unrated/public behavior
  and boundaries with `media_card_rate_button.html` and `rating_picker.html`. It is
  reusable across card surfaces and bounded, yet can expose font/theme/reset and
  native text accessibility differences. Verify the complete island lifecycle and
  both native platforms before accepting a broader standard. If runtime cost is
  disproportionate, keep it as proof evidence and reconsider the production unit;
  do not force adoption. The interactive picker is a subsequent, larger experiment.
- **C — Opportunistic modernization:** once B passes, meaningful UI issues should
  prefer the validated implementation when within scope. Narrow fixes and copy or
  spacing edits may defer migration. Record concrete blockers/opportunities.
- **D — Completion passes:** use register status, affected surfaces and dependencies
  to plan focused consolidation and retire duplicate implementations.
- **E — Native products:** separately approve server-connected native applications;
  evaluate local persistence, offline tracking and synchronization independently.

For meaningful UI work, find the stable component ID, read its contract, assess
scope, preserve behavior, validate the risky changes and update only affected
records/source mappings. Record issue/PR links when known; do not invent owners or
verification. Use Git history when assessing frequently changed components; record
recurring deferrals against their ID so they can inform a focused pass. Never run a
full audit for a small edit. The source map contains a lightweight completeness
check; no new build dependency or CI gate is needed for this documentation.
