# How the React migration is measured

The headline percentage on the migration planning page comes from three counts that
anyone can re-run. Everything is read from the repository; nothing is estimated by
hand. From the repository root:

```bash
python3 scripts/ui_migration_metrics.py            # all three measures
python3 scripts/ui_migration_metrics.py --areas    # the by-area table
python3 scripts/ui_migration_metrics.py --entries  # React islands each register entry mounts
python3 scripts/ui_migration_metrics.py --templates  # every template that hosts an island
python3 scripts/ui_migration_metrics.py --reach    # pattern counts behind the next-items list
python3 scripts/check_ui_docs.py                   # register and source map agree with the code
```

`--json` prints the first form as JSON. The scripts use only the Python standard library.

## 1. Register: entries by status

Source: `docs/ui/component-register.md`. Every `### ID` entry has one `- Status:` line
from the vocabulary at the top of the register.

- Score = `Web Migrated` 1 point, `Partial / coexisting` 0.5, `Legacy` and
  `Deferred (blocker)` 0. `Existing (no UI work needed)` (design tokens) is left out of
  the denominator.
- The 0.5 for a partial entry is a convention, not a measurement; a partial entry can be
  anywhere from a menu to most of a page. Every entry counts the same whatever its size.

## 2. Templates: how many host a React island

Universe: every `src/templates/**/*.html` file. There are no email templates, and icons
(`*.svg`) and the two message `*.txt` files are not HTML, so nothing else is excluded.

A template **hosts an island** when it:

1. contains a `data-*-root` marker that the loader mounts (the list is read from the
   `selector` in `frontend/settings/index.js`, currently 26 markers), or
2. calls a template tag that renders an island: `settings_card`, `settings_link_chip`,
   `rating_stars`, `spinner`, `badge`, `button` (`users/templatetags/ui_tags.py`),
   `alphabet_filter` (`app/templatetags/alphabet_tags.py`), `media_card`,
   `history_card_react`, `media_row_react`, `global_search_react` and `sidebar_react`
   (`app/templatetags/app_tags.py`), or
3. `{% include %}`s a template that hosts an island, followed all the way down. `extends`
   is not followed, so a page does not count just because `base.html` (which mounts the
   sidebar, search bar and popup host) is its parent.

Hosting is a presence count. A template that hosts one island can still be mostly legacy
markup. Two figures are given: any island, and "substantive" islands, which leaves out the
four single-control atoms (`spinner`, `badge`, `button` and the link chip), because a
template whose only island is a Save button is nearly all legacy. The line share is the
lines of the hosting templates over all template lines (`wc -l` counting).

## 3. Code size

- React: `frontend/**/*.jsx`, `*.js` and `*.css` (`wc -l`).
- Template lines: all `src/templates/**/*.html`.
- First-party JavaScript: `src/static/js/*.js` at the top level. Excluded: `libraries/`
  (vendored), `i18n/` (vendored locale files), `*.selfcheck.mjs` (tests) and
  `src/static/ui/` (generated bundles).
- Share = React lines over React + template + first-party JavaScript lines. Template
  lines include the inline Alpine and CSS written in them. Raw lines understate React,
  because a React line replaces more than one template line, so this is the low end.

Cross-check without the script:

```bash
cat $(git ls-files 'frontend/*.jsx' 'frontend/*.js') | wc -l
cat $(git ls-files 'frontend/*.css') | wc -l
cat $(git ls-files 'src/templates/*.html') | wc -l
cat $(git ls-files 'src/static/js/*.js' | grep -v '/libraries/\|/i18n/') | wc -l
```

## 4. Native readiness (a separate measure)

The three measures above say how much of the *web* UI React owns. They do not say how
much of that React could run on iOS or Android. A component can be 100% React on the web
and 0% ready for a phone, so this measure is reported on its own and must never be
added to, or read as part of, the migration percentage.

- **Presentation files:** every `frontend/**/*.jsx` file except web adapters. A web
  adapter is a `mount*.jsx`, `web.jsx` or loader file that draws nothing (it sets no
  `className`). A mount file that does draw UI, such as the bulk toolbar and dock,
  counts as presentation.
- **`rn` file:** imports `react-native` (rendered by react-native-web in the browser).
  **`dom` file:** writes HTML tags with CSS classes. The headline of this measure is
  the share of presentation lines in `rn` files, and the share that are also free of
  browser-only APIs (`window`, `document`, `htmx`, `localStorage`, `fetch`, event
  listeners, `querySelector`, `classList`, observers).
- **Limits:** it counts files, not verified behavior. `rn` means *can* be rendered by
  react-native-web; only a run on both an iOS and an Android simulator or device
  makes a component `Ready` (see the verification gate in
  [ui-modernization](../architecture/ui-modernization.md)). A `rn` file can still be
  fed by server-rendered props only. The per-entry judgment is the `Native readiness`
  line in the register.

Run `python3 scripts/ui_migration_metrics.py --native` for the per-file list, or read
the `native_*` keys of the full report.

Result, 3 Nov 2026: 27 presentation files, 2,864 lines; 4 `rn` files (123 lines,
**4.3%**), all four free of browser APIs; 23 `dom` files with 216 browser-API
references and 352 `className` uses; no component verified on iOS or Android.

## Headline and range

Headline = the register score (measure 1). Range = the lowest to the highest of the
other two: code size at the low end, templates hosting a substantive island at the high
end. The count of templates hosting any island is shown beside them but not used for the
range, since it counts every Save button.

## Results, 3 Nov 2026 (`f2ef6eba1`)

| Measure | Earlier audit | Now |
| --- | --- | --- |
| Register entries | 62 (7 Web Migrated, 4 partial) | 65 (4 Web Migrated, 15 partial, 44 legacy, 1 deferred, 1 no-UI-work) |
| Register score | 15% | 18% (11.5 of 64) |
| Templates hosting any island | 26 of 419 (6%) | 134 of 422 (32%); 95 mount directly, 39 through an include |
| Templates hosting a substantive island | not measured | 91 of 422 (22%), holding 36% of template lines |
| React lines | 2,680 | 3,780 (3,253 JS and JSX, 527 CSS) |
| Template lines | 51,319 | 49,863 |
| First-party JavaScript lines | 8,540 | 8,474 (27 files) |
| Code-size share | 4% | 6% |
| Headline | 19% (11% to 26%) | 18% (6% to 22%) |

The earlier numbers are not directly comparable. That method was not written down, and
the three views were not re-run after the spinner, badge, button, media card, Add-to-lists
and bulk changes. The template count then looked only at files that name an island
directly; this count also follows tags and includes. The register is stricter too:
`Web Migrated` now needs React to own the family on every surface, so six entries that
carried that label (FORM-CONTROLS, BADGE, SET-PROVIDERS, SET-METADATA, SET-IMPORT,
SET-ACTIVITY) are `Partial / coexisting` because named legacy consumers remain. Compare
future runs with this table, not with the earlier one.

By area (register score, `--areas`):

| Area | Score |
| --- | --- |
| Media card | 1 of 1 (100%) |
| Shell and header search | 1 of 2 (50%) |
| Shared building blocks | 4 of 9 (44%) |
| Provider pages and integrations | 2.5 of 9 (28%) |
| Popups and tracking forms | 0.5 of 2 (25%) |
| Library, collection, search results | 1.5 of 9 (17%) |
| History, Statistics, Calendar | 0.5 of 3 (17%) |
| Other settings pages | 0.5 of 9 (6%) |
| Home and Discover | 0 of 3 |
| Media details | 0 of 10 |
| Lists, smart lists, tiers | 0 of 4 |
| Sign-in, errors, onboarding | 0 of 3 |

Which entry belongs to which area is the `AREAS` table in `scripts/ui_migration_metrics.py`.
A 0% area can still show React on its pages (Home and Discover draw the React media
card); the score counts what the area's own components own. Re-run after any
status change in the register.
