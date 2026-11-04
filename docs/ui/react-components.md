# Shared React web components

Every component created or edited by an agent, including copy or styling edits,
must follow the [cross-platform contract](../architecture/ui-modernization.md)
with visual and behavioral parity. Modernize by reusable component, keeping
untouched siblings in place. The `frontend/ui/controls.jsx` contracts below
describe legacy web consumers and guide a native-compatible replacement;
universal code must not import that web-only file. Feature adapters supply domain
data and actions and own requests, permissions and platform integration.

| Component | Contract |
| --- | --- |
| `Card`, `CardGrid` | Shared settings frame/header, optional header action, two-column or automatically fitting layout; all card badges stay at the top right while titles wrap |
| `CatalogCard`, `CatalogGrid` | Linked service/resource cards with optional logo and attention state; container-width columns with a maximum of four, retaining two columns at intermediate widths |
| `FilterToolbar` | Search/filter form layout; uses `Field` and `SelectField` with optional visually hidden labels, retaining accessible names |
| `Chip` | Passive, button or link badge with consistent highlight and no underline |
| `AlphabetBar`, `AlphabetEmpty` | Shared RNW Pressable/Text alphabet navigation and filtered empty state in `frontend/ui/AlphabetBar.jsx`; surface adapters supply translated options, active state, URLs and navigation. The slim rail starts at the first poster, fits every entry without scrolling, puts # before A, and displays an actual other-bucket glyph. The web adapter centers glyph ink using font metrics; the empty state reuses Chip |
| `RatingStars` | Star row with hover preview and toggle-to-clear; `scaleMax`, `value`, `label`, `renderStar`, `onSelect`. The web adapter (`mountRatingStars.jsx`) owns the htmx write, CSRF and popup events. `RatingStarIcon.web.jsx` / `.native.jsx` render the star glyph on each platform |
| `RatingChip` | Personal score chip and rating popup for the detail surface; viewer scale, empty/edit states, derived-TV score and coverage. The web adapter (`mountRatingChip.jsx`) owns the htmx write, CSRF, popup anchor, dismissal and theme; native callers supply the same props |
| `DetailComposition`, `DetailHeader`, `DetailSynopsis`, `DetailActions`, `DetailSection` | Native detail hero and composition: artwork, title/subtitle, facts, expandable synopsis, primary actions, ordered sections and public/read-only states. Callers supply concrete palette values and action callbacks; the browser adapter mounts the shared synopsis over the server fallback and leaves htmx title/actions/carousel sections server-owned |
| `ProgressBar`, `ProgressCard`, `ProgressBreakdown` | Watched-once bar with a current-pass glow, the detail “Your Progress” card, and the expandable season/episode breakdown. Callers supply percentages, season/episode view models, labels, palette and navigation/cancel intents. The web adapter (`mountProgressBreakdown.jsx`) keeps the existing htmx modal, out-of-band card refreshes and server fallback |
| `DateTimePicker` | Tracking date/time field with quick actions, optional 12/24-hour time, locale/month/year navigation, six-week grid, marked/selectable days and the hidden value contract; the browser adapter (`mountDateTimePicker.jsx`) owns the hidden input, htmx events, status/paired-date autofill, copy and clear |
| `ToggleChip` | Controlled two-state chip; `value`, `onChange`, `offLabel`, `onLabel`; stable accessible label and `aria-pressed` |
| `Field`, `SelectField` | Labeled input and preference dropdown; semantic panel/border/focus styling, inset arrow and custom option menu matching Preferences; caller supplies IDs, values/options and handlers |
| `FilterDropdown` | Same dropdown interaction with Lists hub styling: funnel icon, filled trigger/menu, purple selected option; visually hidden accessible label; use in filter toolbars rather than preference forms |
| `SearchResults` | Search results surface: media-type/source scope, grid/list layout, local and online sections, matched titles, empty/loading/error states, bounded paging or load more and the online-search action. Callers supply resolved card models, labels, palette and navigation/action/rating callbacks; the browser adapter keeps URLs, card popups and rating writes |
| `FilterBar` | Universal filter toolbar: media-type and status multi-select, sort with direction, layout and saved-view selection, relative/absolute ranges, clear/default, selected/disabled/busy states and responsive sheets. `mountFilterBar.jsx` mirrors Alpine state and reuses the existing form/htmx refresh |
| `Tooltip` | Accessible help trigger with a viewport-clamped portal; usable from a legacy island with a title fallback |
| `ActivityList` | Keyboard-scrollable bounded activity list for long histories |
| `MediaIcon` | Shared media-type glyphs for provider and library rows |
| `StatusIcon` | Accessible success/warning/neutral icon with a descriptive tooltip; feature code supplies the actual meaning |
| `FeatureList` | Shared feature rows with `key`, `label`, optional `note`, `status` and semantic `tone`; leading accessible status icons replace repeated Active text, with other states labeled and no dividers |
| `Button` | Shared React Native `Pressable`/`Text` action with primary, surface, solid danger and ghost danger tones; the browser platform implementation keeps real button/anchor semantics, form submission, links and htmx attributes |
| `Form` | Native POST with explicit action, CSRF and optional local return destination/confirmation |
| `Dialog` | Native modal dialog, Escape/backdrop dismissal and focus restoration; caller supplies translated title/close label |
| `Tabs` | Native navigation links with current-page state and no hover underline |

```jsx
import { Card, Field, SelectField, ToggleChip } from '../ui/controls';

<Card title={t('Import options')} headerAction={
  <ToggleChip value={privateImport} onChange={setPrivateImport}
    offLabel={t('Public')} onLabel={t('Private')} />
}>
  <Field id="profile-name" label={t('Username')} value={username}
    onChange={event => setUsername(event.target.value)} required />
</Card>
```

The chip expresses a choice; it does not grant access or implement authentication.
AniList owns the public-username/private-OAuth distinction and credential gate.
Another import can reuse the chip while keeping its own authentication rules.
Dropdowns share click-away, Escape, Tab, arrow/Home/End navigation and type-to-select
behavior. `SelectField` is for preferences; `FilterDropdown` is for filtering
results. Preserve their distinct appearances when adopting them elsewhere.
Provider `web.jsx` only adapts the shared form to its page's CSRF and return URL.
Do not put provider-specific branches in the shared controls.

`frontend/ui/controls.css` owns web control styling. Use existing semantic surface,
border and text tokens; the established purple action role remains separate from
the theme's general accent. Focus rings must not animate through a white outline.
Interactive chips use `:focus-visible`: keyboard navigation shows a ring; pointer
clicks retain normal focus without leaving a ring behind.
Shared card/chip presentation uses React Native Web; DOM form controls, navigation
and dialogs are explicit browser adapters. No iOS/Android verification is implied.

For adoption on a legacy screen, mount only the component's owned subtree using
the [existing loader and lifecycle](settings-cards.md); keep one React runtime and
one framework owner per subtree. A component port does not require converting the
whole page. Preserve backend action contracts and a useful server fallback. Update
the [register](component-register.md) and [source map](source-map.md) with consumers,
verification and remaining legacy implementations whenever ownership changes.

Layout and breakpoint redesigns require adopting the affected shared React
components in the same change. The Providers directory demonstrates this pattern:
its cards, grid and toolbar are shared controls; `frontend/providers/Directory.jsx`
owns server filtering, request cancellation, retry and URL/Back navigation. The grid
uses container width, with two columns from 24rem, three from 38rem and four from
56rem. Navigation columns therefore cannot force four compressed cards merely
because the viewport crosses a desktop breakpoint. A native GET form and server
cards remain available if the lazy module fails.

Import preferences use `frontend/providers/ImportPreferences.jsx` in both React provider pages and a bounded legacy island. The provider retains its action and authentication logic; the shared controls save existing import mode values and user watchlist preferences. File-only and other one-time imports show a disabled preference dropdown with a separate accessible tooltip, without saving the locked value over the user’s general frequency.

Account-backed connections use `frontend/providers/AccountConnection.jsx`: the provider adapter supplies field metadata, state, messages and existing action URLs. The same module renders manual import actions using shared cards, fields, forms and buttons. Stored credentials and URLs do not enter React props; the server fallback remains usable if the island fails.
