# PR screenshots

`scripts/pr_screenshots.py` captures before/after screenshots of a pull request and can put them in the PR description. It exists because UI PRs need visual proof and taking it by hand across several branches does not scale.

## Run it

```bash
uv run --no-sync python scripts/pr_screenshots.py 1370 1373          # capture only
uv run --no-sync python scripts/pr_screenshots.py 1370 --post        # capture, then update the PR description
uv run --no-sync python scripts/pr_screenshots.py 1370 --pages home,library --no-before
```

Output lands in `.floppy/pr-shots/<pr>/before/` and `.../after/` (gitignored). Open the PNGs and look at them before posting.

| Flag | Meaning |
|---|---|
| `--post` | Upload the images and rewrite the screenshot section of the PR description |
| `--no-before` | Skip the merge-base capture (new pages have nothing to compare against) |
| `--pages a,b` | Override the page list for this run |
| `--repo owner/name` | Repository that owns the PRs (default `dannyvfilms/Floppy`) |
| `--port N` | Local port for the temporary server (default 8299) |

## What it does

1. Asks `gh` for the PR head commit and the merge-base with its base branch.
2. Creates a throwaway git worktree per commit under `.floppy/pr-shots/work/`. Your checkout is never touched.
3. In each worktree: migrate a fresh SQLite database, seed it with `scripts/pr_screenshots_seed.py`, collect static files, and start gunicorn. Redis runs privately on port 6391 and is stopped afterwards.
4. Logs in with headless Chromium and screenshots every page at desktop (1280px) and phone (390px) widths, in light and dark.
5. With `--post`, uploads the images and writes them into the PR description between `<!-- pr-screenshots:start -->` and `<!-- pr-screenshots:end -->`. Re-running replaces that block and leaves the rest of the description alone.

A page whose route does not exist at a commit is skipped, so a brand-new page produces after shots only.

## Choosing pages

Pages are named routes resolved in `scripts/pr_screenshots_seed.py`. Which pages a PR gets is the `PR_PAGES` dict at the top of `scripts/pr_screenshots.py`. A PR not in the dict gets `home`, `library` and `history`.

To add a page:

1. Add `"name": resolve("route_name", ...)` to the `paths` dict in the seed script.
2. Add the name to the PR's entry in `PR_PAGES`, or pass `--pages`.

If the page needs data that is not seeded (a configured Home row, a podcast, a TV episode), extend the seed. The seed creates a `shots` user, three movies, and a band with members and an album with three tracks. It runs inside `manage.py shell` on whichever commit is being captured, so it tolerates fields a commit does not have yet (for example `origin_url`).

## Requirements

- `gh` authenticated, version with `gh auth token`.
- `redis-server` on `PATH`.
- Playwright's Chromium already installed (`~/Library/Caches/ms-playwright` on macOS). Do not run `playwright install` from this script.
- Project virtualenv synced (`uv sync --locked`).

## Uploading images

GitHub has no public API for attaching images to a PR. The script uses the undocumented `uploads.github.com/user-attachments/assets` endpoint with your `gh` token. That endpoint only accepts uploads to a repository you can push to, so images go to your fork (`origin`), not the upstream repository, and are then referenced from the upstream PR description. An uploaded asset returns 404 until a description references it, which `--post` does immediately.

`gh` 2.99 adds `gh pr edit --attach`, which would replace the upload code, but it needs write access to the PR's own repository.

## Limits

- Seeded data only. A change that depends on specific library content or a non-default setting needs a seed change to show up.
- Pages are full-page screenshots after `networkidle`. Hover states and open dialogs are not captured.
- Each PR takes about two minutes (two servers). Run several PRs in one invocation and let it work through them.
- The seed relies on Manual-source items, so nothing needs the network.
