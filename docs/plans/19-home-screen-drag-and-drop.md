# Home Screen drag and drop

[Issue #19](https://github.com/crimsonsunset/Floppy/issues/19). Branch `bugfix/19-home-screen-drag-and-drop`, cut from `origin/latest` @ `0480b605`.

## Flow state

| Field | Value |
|---|---|
| Gate | 5 (pushed, PR not opened) |
| Ticket | 19 |
| Branch | bugfix/19-home-screen-drag-and-drop |
| Repos | floppy |
| Isolation | worktree |
| Worktrees | /Users/joe/Desktop/Repos/Personal/floppy-wt/19/floppy |
| Base | origin/latest @ 0480b605 |
| QA mode | browser-qa |
| Gates | all |
| Updated | 2026-10-02 |

## Overview

Reordering on `/settings/home-screen` is unreliable. The reported symptom is section reorder (the seven media-type bars). Row reorder inside an expanded section may be broken the same way. The cause is not confirmed yet. Phase 1 reproduces it before anything is changed.

The page builds two nested Sortable lists inside the `homeScreenSettings()` Alpine component: the section list and one row list per section. Three things in `src/templates/users/home_screen.html` look wrong:

- Row lists are bound once on page load while their sections are collapsed (`x-show="section.expanded"`, default `expanded: false`). Sortable on a `display:none` container is unreliable.
- Neither `onEnd` re-binds Sortable. Each one reassigns `this.sections` or `section.rows`, and Alpine's keyed `x-for` then re-orders the same DOM nodes Sortable just moved.
- Both grips are `hidden lg:inline-flex`, and neither Sortable has a touch delay. Below 1024px there is no way to drag.

This does not change what any row queries, how the order is saved, or the sidebar media-type order, which uses its own static list.

Same defect on Danny's repo: the code is identical on `upstream/latest` after his merge of #1373 as [#1425](https://github.com/dannyvfilms/Floppy/pull/1425). The PR goes to `crimsonsunset/Floppy` first, like #9.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Base | `origin/latest` | Same drag code as `upstream/latest`. Fork-first PR flow. |
| Repro first | Phase 1 reproduces in a browser and records what fails before any edit | The cause is inferred from code. A wrong guess costs a phase. |
| Re-binding | Call `initSortables()` in `$nextTick` after each `onEnd`, and when a section is expanded | `initSortables()` already destroys and recreates. Adding the calls is the whole mechanism. |
| Lazy row lists | Keep `x-show` on the section body, bind rows when it opens | Matches `savedViews.js`, which binds when its list becomes visible. No markup restructure. |
| Touch | `delay: 100, delayOnTouchOnly: true` on both Sortables | Same options as `list_detail.html`. Stops a scroll swipe from starting a drag. |
| Grips below `lg` | Remove `hidden … lg:inline-flex`, show the grip at every width | Phones had no grip at all. `section.expanded` toggling already works by tap on the header button. |
| Drag affordance | Add `ghostClass` and `chosenClass`, styled in `input.css` | Today only `animation: 150` is set, so a drag shows no feedback. |
| Restructure | No | The sidebar-style static list would be a rewrite. Take it only if Phase 1 shows the re-bind cannot fix it. |
| Test | Markup assertions only. No Playwright drag test | Decided in scoping. Drag stays covered by the browser pass in Phase 3. |

## Scope

In:

- Section reorder, row reorder, and the re-bind and touch fixes above.
- Grip visibility and drag styling on this page.
- Updating the markup assertions in `test_home_screen.py` that lock the grip classes.

Out:

- A Playwright drag test. Scoping decision. The page's markup tests plus the Phase 3 browser pass cover it.
- Sidebar media-type order, saved views, collection custom fields, list manual order. Different pages and they work.
- Save format and server code in `src/users/home_screen.py`. `prepareSubmit()` already reads Alpine state in array order. Revisit only if Phase 1 shows a saved-order mismatch, in which case it becomes a new phase.
- The `test_tv_manual` Playwright failure on #1370. Different PR, tracked there.

## Architecture

`init()` waits one `$nextTick`, calls `ensureSortable()` (checks the global from `base.html`), then `initSortables()`. That function destroys any existing instances, then creates one Sortable on `[data-home-section-list]` and one per `[data-home-row-list]`. Each `onEnd` reads the new DOM order and rewrites the Alpine array. On save, `prepareSubmit()` serializes `this.sections` into the hidden `home_screen_sections` field, and `save_home_screen_configuration()` writes section order to `user.home_screen_media_type_order` and row order to `position`.

The fix leaves that flow alone. It changes when `initSortables()` runs: after each drop, and when a section opens. Phase 1 checks whether the Alpine re-render, the hidden containers, or both are the cause.

## Files

| Path | Change |
|---|---|
| `src/templates/users/home_screen.html` | Re-bind in `$nextTick` from both `onEnd` handlers and from the expand toggle (line 37). Add `delay`, `delayOnTouchOnly`, `ghostClass`, `chosenClass`. Remove `hidden … lg:inline-flex` from the two grips (lines 30 and 79). |
| `src/static/css/input.css` | Ghost and chosen drag styles. |
| `src/static/css/main.css` | Regenerated Tailwind output. |
| `src/users/tests/views/test_home_screen.py` | Update the grip class assertions (around lines 88 to 99). |
| `docs/architecture/` | Nothing planned. No doc covers this page's drag. |

## Phasing

### Phase 1: reproduce and pin the cause (about 30 min)

- Run the app per the `run-floppy` skill. Log in. Open `/settings/home-screen`.
- Drag a section on desktop. Drag a second one. Expand a section and drag a row. Resize below 1024px.
- Record console errors and whether the DOM order matches the Alpine order before save.
- Save, reload, and compare to what was dragged.

**Outcome:** a written note in this doc naming which of the three suspects fails (hidden row lists, no re-bind, no grip on small screens) and whether any saved-order mismatch exists. If something else fails, this plan gets amended before Phase 2.

### Phase 2: fix (about 1 hr)

- Re-bind in `$nextTick` after each drop and on expand.
- Add touch delay and drag classes. Show the grips at every width.
- Update the markup assertions.

**Outcome:** on desktop, dragging section A below B, then C above A, in one session, keeps the page order, and a reload after Save shows the same order. Rows reorder inside an expanded section on the first drag after opening it.

### Phase 3: browser QA and ship (about 30 min)

- Repeat the Phase 1 script at 1280, 768, and 390 widths, light and dark.
- Run `scripts/test.sh users.tests.views.test_home_screen` and `uv run --no-sync ruff check src`.
- Open the fork PR with before and after screenshots.

**Outcome:** the same drag script that failed in Phase 1 passes at all three widths. Targeted tests and ruff are clean.

## Key files referenced

| File | Note |
|---|---|
| `src/templates/users/home_screen.html` | All drag code. `initSortables()` at line 827. Handles at lines 30 and 79. |
| `src/templates/base.html` | Loads vendored Sortable 1.15.3 before `{% block js %}`. |
| `src/templates/users/components/_media_type_order_js.html` | Sidebar reorder. Static list, one Sortable, works. Reference pattern. |
| `src/static/js/savedViews.js` | Binds Sortable when the list opens, destroys on close. Reference for lazy binding. |
| `src/templates/lists/list_detail.html` | Uses `delay: 100, delayOnTouchOnly: true`. Reference for touch. |
| `src/users/home_screen.py` | Save path. Section order to `home_screen_media_type_order`, row order to `position`. |
| `src/users/tests/views/test_home_screen.py` | Markup assertions for the grips and the Sortable script. |

## Related documentation

- [Issue #19](https://github.com/crimsonsunset/Floppy/issues/19)
- [7-home-screen-settings-usable.md](7-home-screen-settings-usable.md): shipped the vendored Sortable and the current layout.
- [PR #1373](https://github.com/dannyvfilms/Floppy/pull/1373) and [#1425](https://github.com/dannyvfilms/Floppy/pull/1425): Danny's merge of that work.

## Implementation notes

- Reproduced in the browser. Sortable moved the node, then Alpine's `x-for` moved it again, so the visible order and `this.sections` diverged after every drop. `onEnd` records the new order, puts the node back, and lets Alpine do the only reorder. Re-init still runs on the next tick.
- The media-type bar (`.section-drag-row`) is the section handle. A click that does not move still expands it. `lastDragAt` ignores the click that follows a drop.
- An inner row drags from the article except the name field and `.home-settings-row-controls`.
- `0196_merge_0195_merge_20261002_2211_0195_video` and the ruff fixes are a separate commit. `origin/latest` had two `0195` leaves and 4 ruff errors from the video type (PR #18). Not part of this fix.
- `users.tests.views.test_home_screen` has 35 baseline errors on `origin/latest`: the tests set `video_enabled`, which `User` does not define. The new markup assertions sit in one of those tests, so they were checked with a throwaway render test instead. Fix belongs with the video type work.
