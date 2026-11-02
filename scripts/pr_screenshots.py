"""Capture before/after screenshots of a PR and optionally put them in its description.

    uv run --no-sync python scripts/pr_screenshots.py 1370 1373 [--post]

For each PR it checks out the head and the merge-base in throwaway worktrees,
seeds a fresh database, serves the app, and screenshots the PR's pages at
desktop and phone width in light and dark. Nothing touches your working tree.
Output lands in .floppy/pr-shots/<pr>/<before|after>/.

--post uploads the images to your fork (GitHub only accepts uploads from a repo
you can push to) and rewrites a marked section of the PR description.
"""

# ruff: noqa: INP001, T201, S603, S607, S108
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "scripts" / "pr_screenshots_seed.py"
REDIS_PORT = 6391
CREDENTIALS = ("shots", "shots-pass-12345")
VIEWPORTS = {"desktop": (1280, 900), "phone": (390, 844)}
SCHEMES = ("light", "dark")
DEFAULT_PAGES = ("home", "library", "history")
# Add a PR here when its screenshots need pages beyond the defaults.
PR_PAGES = {
    1370: ("tile-settings", "home", "library", "history", "music-artist"),
    1373: ("home-screen-settings", "home"),
    1374: ("music-album",),
    1375: ("home",),
    1372: ("music-track",),
    1311: ("music-artist", "music-album", "music-track"),
}
MARK_START, MARK_END = "<!-- pr-screenshots:start -->", "<!-- pr-screenshots:end -->"


def run(cmd, cwd=ROOT, env=None, check=True):
    """Run a command and return its stripped stdout."""
    result = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=check,
    )
    return result.stdout.strip()


def gh_json(*args):
    """Return parsed JSON from a gh command."""
    return json.loads(run(["gh", *args]))


def pr_refs(repo, number):
    """Return (head_sha, merge_base_sha) for a PR, fetching both locally."""
    info = gh_json(
        "pr",
        "view",
        str(number),
        "--repo",
        repo,
        "--json",
        "headRefName,headRefOid,baseRefName",
    )
    head = info["headRefOid"]
    base = gh_json(
        "api",
        f"repos/{repo}/compare/{info['baseRefName']}...{head}",
    )["merge_base_commit"]["sha"]
    for sha, remote in ((head, "origin"), (base, "upstream")):
        if (
            subprocess.run(
                ["git", "cat-file", "-e", sha], cwd=ROOT, check=False
            ).returncode
            == 0
        ):
            continue
        run(["git", "fetch", remote, info["headRefName"] if sha == head else sha])
    return head, base


class Server:
    """A seeded Floppy instance serving one commit from a throwaway worktree."""

    def __init__(self, sha, workdir, port):
        """Create the worktree and the settings module for this run."""
        self.workdir, self.port = workdir, port
        run(["git", "worktree", "add", "--detach", str(workdir), sha])
        self.src = workdir / "src"
        (self.src / "local_serve.py").write_text(
            "from config.settings import *  # noqa: F403\n"
            "IS_PROD = False\n"
            "ALLAUTH_TRUSTED_CLIENT_IP_HEADER = None\n",
        )
        self.env = {
            **os.environ,
            "SECRET": "pr-shots",
            "DEBUG": "False",
            "DJANGO_SETTINGS_MODULE": "local_serve",
            "REDIS_URL": f"redis://localhost:{REDIS_PORT}",
            "FLOPPY_DB_PATH": str(workdir / "db.sqlite3"),
            "FLOPPY_PROCESS_ROLE": "web",
            "WEB_CONCURRENCY": "1",
            "GUNICORN_THREADS": "4",
        }
        self.process = None

    def manage(self, *args, stdin=None):
        """Run manage.py in the worktree using the main checkout's virtualenv."""
        cmd = [
            "uv",
            "run",
            "--project",
            str(ROOT),
            "--no-sync",
            "python",
            "manage.py",
            *args,
        ]
        result = subprocess.run(
            cmd,
            cwd=self.src,
            env=self.env,
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            sys.exit(f"manage.py {args[0]} failed:\n{result.stderr[-1500:]}")
        return result.stdout

    def start(self):
        """Migrate, seed, collect static, serve, and return the seeded paths."""
        self.manage("migrate", "--noinput")
        seeded = self.manage("shell", stdin=SEED.read_text())
        self.manage("collectstatic", "--noinput")
        self.process = subprocess.Popen(
            [
                "uv",
                "run",
                "--project",
                str(ROOT),
                "--no-sync",
                "gunicorn",
                "--bind",
                f"localhost:{self.port}",
                "--config",
                "python:config.gunicorn",
                "config.wsgi:application",
            ],
            cwd=self.src,
            env=self.env,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(90):
            try:
                urllib.request.urlopen(
                    f"http://localhost:{self.port}/health/", timeout=2
                )
                break
            except OSError:
                time.sleep(1)
        else:
            sys.exit("server never became healthy")
        line = next(x for x in seeded.splitlines() if x.startswith("SHOTS_PATHS="))
        return json.loads(line.removeprefix("SHOTS_PATHS="))

    def stop(self):
        """Stop gunicorn by process group, then drop the worktree."""
        if self.process:
            os.killpg(self.process.pid, signal.SIGTERM)
            self.process.wait()
        run(["git", "worktree", "remove", "--force", str(self.workdir)], check=False)


def capture(browser, base_url, paths, pages, out_dir):
    """Screenshot each page at every viewport and scheme; return the files written."""
    written = []
    for viewport, (width, height) in VIEWPORTS.items():
        for scheme in SCHEMES:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                color_scheme=scheme,
            )
            page = context.new_page()
            page.goto(f"{base_url}/accounts/login/")
            page.fill("#id_login", CREDENTIALS[0])
            page.fill("#id_password", CREDENTIALS[1])
            page.click('button[type="submit"]')
            page.wait_for_load_state("networkidle")
            for name in pages:
                if name not in paths:
                    continue
                page.goto(f"{base_url}{paths[name]}")
                page.wait_for_load_state("networkidle")
                target = out_dir / f"{name}-{viewport}-{scheme}.png"
                page.screenshot(path=str(target), full_page=True)
                written.append(target)
            context.close()
    return written


def upload(path, repository_id, token):
    """Upload one image to GitHub and return its user-attachments URL."""
    query = urllib.parse.urlencode(
        {
            "name": path.name,
            "content_type": "image/png",
            "repository_id": repository_id,
        },
    )
    request = urllib.request.Request(
        f"https://uploads.github.com/user-attachments/assets?{query}",
        data=path.read_bytes(),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request) as response:  # noqa: S310 - fixed https endpoint
        return json.load(response)["url"]


def post(repo, number, out_dir, pages):
    """Upload the shots and rewrite the marked section of the PR description."""
    origin = run(["git", "remote", "get-url", "origin"]).removesuffix(".git")
    fork = "/".join(origin.replace(":", "/").split("/")[-2:])
    repository_id = gh_json("api", f"repos/{fork}")["id"]
    token = run(["gh", "auth", "token"])
    sections = []
    for name in pages:
        rows = []
        for viewport in VIEWPORTS:
            for scheme in SCHEMES:
                cells = []
                for label in ("before", "after"):
                    shot = out_dir / label / f"{name}-{viewport}-{scheme}.png"
                    if not shot.exists():
                        cells.append("n/a")
                        continue
                    cells.append(
                        f'<img src="{upload(shot, repository_id, token)}" width="360">'
                    )
                if any(c != "n/a" for c in cells):
                    rows.append(f"| {viewport}, {scheme} | " + " | ".join(cells) + " |")
        if rows:
            header = "| | Before | After |\n|---|---|---|\n"
            sections.append(
                f"<details><summary>{name}</summary>\n\n{header}"
                + "\n".join(rows)
                + "\n\n</details>"
            )
    block = (
        f"{MARK_START}\n## Screenshots\n\n" + "\n\n".join(sections) + f"\n{MARK_END}"
    )
    body = (
        gh_json("pr", "view", str(number), "--repo", repo, "--json", "body")["body"]
        or ""
    )
    if MARK_START in body:
        head, _, rest = body.partition(MARK_START)
        body = head + block + rest.partition(MARK_END)[2]
    else:
        body = f"{body.rstrip()}\n\n{block}\n"
    subprocess.run(
        ["gh", "pr", "edit", str(number), "--repo", repo, "--body-file", "-"],
        input=body,
        text=True,
        check=True,
    )


def redis_up():
    """Start a private redis for the run; return True when this call started it."""
    probe = ["redis-cli", "-p", str(REDIS_PORT), "ping"]
    if subprocess.run(probe, capture_output=True, check=False).returncode == 0:
        return False
    run(
        [
            "redis-server",
            "--port",
            str(REDIS_PORT),
            "--daemonize",
            "yes",
            "--save",
            "",
            "--dir",
            "/tmp",
        ]
    )
    return True


def main():
    """Capture each requested PR, before and after, then optionally post."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("prs", nargs="+", type=int)
    parser.add_argument("--repo", default="dannyvfilms/Floppy")
    parser.add_argument("--pages", help="comma list overriding the PR's pages")
    parser.add_argument("--no-before", action="store_true")
    parser.add_argument("--post", action="store_true")
    parser.add_argument("--port", type=int, default=8299)
    args = parser.parse_args()

    started_redis = redis_up()
    root_out = ROOT / ".floppy" / "pr-shots"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            for number in args.prs:
                pages = (
                    tuple(args.pages.split(","))
                    if args.pages
                    else PR_PAGES.get(number, DEFAULT_PAGES)
                )
                head, base = pr_refs(args.repo, number)
                targets = [("after", head)] + (
                    [] if args.no_before else [("before", base)]
                )
                for label, sha in targets:
                    out_dir = root_out / str(number) / label
                    shutil.rmtree(out_dir, ignore_errors=True)
                    out_dir.mkdir(parents=True)
                    server = Server(
                        sha, root_out / "work" / f"{number}-{label}", args.port
                    )
                    try:
                        paths = server.start()
                        files = capture(
                            browser,
                            f"http://localhost:{args.port}",
                            paths,
                            pages,
                            out_dir,
                        )
                        print(f"#{number} {label}: {len(files)} shots in {out_dir}")
                    finally:
                        server.stop()
                if args.post:
                    post(args.repo, number, root_out / str(number), pages)
                    print(f"#{number}: description updated")
            browser.close()
    finally:
        if started_redis:
            run(["redis-cli", "-p", str(REDIS_PORT), "shutdown", "nosave"], check=False)


if __name__ == "__main__":
    main()
