# Expo build dashboard

A local page that shows, for every screen in the Expo app (`expo/`), how much of it is React Native,
how much is shared with the web build, and how much the owner has signed off. It reads the code and
the registers directly, so it is always as current as the branch it reads. Nothing is stored in it.

## Run it

```bash
python3 scripts/expo_dashboard.py --serve
```

Open <http://127.0.0.1:8765>. By default it reads the `latest` branch from git, so a commit that
reaches `latest` appears on the open page within a few seconds. It needs only Python 3.

| Option | Effect |
| --- | --- |
| `--ref <branch\|tag\|commit>` | Read another ref instead of `latest`. |
| `--worktree` | Read the files on disk in this checkout, uncommitted edits included. Use it to preview a register change before merging. |
| `--fetch` | Fetch the ref from its remote at most once a minute, so a stale local `latest` catches up. |
| `--port`, `--no-open` | Change the port; do not open a browser. |
| (no `--serve`) | Write a one-off snapshot to `.floppy/expo-dashboard.html` and open it. |

The script is `scripts/expo_dashboard.py` with its page in `scripts/expo_dashboard.template.html`.

## What the bars mean

Each page has three stacked bars, weighted by lines of code (switchable to file count). The files
on a page are everything reachable from its Expo screen and shared view, following `.native` and
`.ios` variants the way Metro does. Logic and data files are hidden unless you tick the box.

- **Native conversion**: *React Native* imports `react-native` and has no DOM markup. *Neutral*
  composes other components. *Mixed / DOM* still has HTML tags, `className` or browser globals.
- **Code ownership**: *Shared with web* is a `frontend/` file the web build also imports.
  *Frontend, native only* is in `frontend/` but no web page uses it yet. *Reused native* is code
  under `expo/` used by two or more pages. *Unique native* is code under `expo/` used by one
  page only, which is where a duplicated solution would show up.
- **Sign-off**: *Signed off* is the owner's review, from the component register (below).
  *Registry: iOS + Android* and *one platform* are the verification that agents recorded in
  `docs/ui/architecture-registry.json`; that is evidence, not the owner's sign-off.

A page marked *Legacy page* is one the page registry (`frontend/pages/registry.js`) lists as
`legacy`: the Expo screen owns its own composition instead of rendering a shared view.

## Recording a sign-off

The dashboard reads sign-offs from `docs/ui/component-register.md`. Add one line to the component's
family entry:

```text
- Sign-off: 2026-11-19, owner. Covers `frontend/ui/MediaCard.jsx`, `frontend/ui/MediaCard.web.jsx`. Web: Chrome at 2x. iOS: iOS simulator. Android: not run.
```

- Start with the date (`YYYY-MM-DD`), a comma and who signed off, then a period.
- List every covered file by repository path in backticks. Only listed files count.
- Give per-platform evidence as `Web:`, `iOS:` and `Android:` followed by a short phrase and a period.
- Delete the line to revoke the sign-off.
- If a covered file is changed on a later day than the date, the dashboard shows it as *Re-review*
  and stops counting it until a new line is added.
- A path that is on no page tree (a typo, or a file Expo does not render) appears in a banner at the top.

Only the owner's own statement creates a sign-off. An agent records what it ran under
`Verification` and in the architecture registry, and does not add or edit a `- Sign-off:` line.
The rule is repeated in [the register's maintenance section](component-register.md#status-and-maintenance).

## Limits

- Sizes count non-comment lines. Components are detected from imports and JSX, not by running the app.
- The tree stops at another page's screen, so shared screen helpers are listed once under the page that owns them.
- It does not read the web side's server templates, so it cannot show how much of a legacy page's
  web counterpart is still server-rendered; it only marks pages with no web adapter.
- Sign-offs come from the ref being read. A line added on a branch shows after it reaches `latest`,
  or immediately with `--worktree` on that branch.
- This tool can be removed once the Expo migration is finished.
