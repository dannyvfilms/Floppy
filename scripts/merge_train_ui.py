#!/usr/bin/env python3
# ruff: noqa: T201, EM101, EM102, TRY003, TRY301, S603, S607
"""Rebuild the committed UI bundles when the merge train refreshes a PR branch.

Parallel frontend PRs conflict in content-hashed bundles under src/static/ui/
even when their source merges cleanly, and a clean merge can leave stale bundles.
For an eligible PR (see merge_train.py) the train asks for a refresh that is done in
three separated steps, so no privileged token ever runs PR code:

1. ``build`` (unprivileged job, read-only token, no secrets): merge the exact PR head
   and latest SHAs, allow conflicts only inside src/static/ui/, rebuild that directory
   from scratch with ``npm ci --ignore-scripts``, ``npm run build:ui`` and
   ``npm run check:ui``, and write the result as plain files plus a manifest.
2. ``publish`` (trusted job): treat that output as untrusted data. Re-check that the
   PR is still eligible and both SHAs are current, redo the merge itself, and
   compare the merged non-generated tree with the one the build reported. Only then
   write the validated files into src/static/ui/ and push one merge commit (parents:
   PR head, latest) to the PR branch with a plain, non-forced push. The push is
   refused if the branch moved, so newer work is never overwritten. Nothing from
   the artifact is executed.
3. The ordinary required checks run on the pushed commit; GitHub merges it only if they
   pass. Nothing here merges, creates branches or PRs, or bypasses a check.

Usage:
  merge_train_ui.py build   --work DIR --out DIR --number N --head SHA --base SHA
  merge_train_ui.py publish --artifacts DIR     (PLAN, GH_REPO, GH_TOKEN in the environment)
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

GENERATED = "src/static/ui"
SHA = re.compile(r"^[0-9a-f]{40}$")
BRANCH = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
FILE_NAME = re.compile(r"^[A-Za-z0-9._-]{1,200}$")
ALLOWED_SUFFIXES = {".js", ".css", ".txt", ".map"}
MAX_FILES = 2000
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 150 * 1024 * 1024
RESULT = "result.json"
FILES = "files"
SAFE_GIT = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false"]
BOT = [
    "-c",
    "user.name=floppy-merge-train",
    "-c",
    "user.email=merge-train@users.noreply.github.com",
]


class RefreshError(Exception):
    """The refresh cannot or must not go ahead; the message says what to do."""


def git(repo: Path, *args: str, check: bool = True, env: dict | None = None) -> str:
    """Run git without hooks; with check=False return the exit code, a newline, then stdout."""
    result = subprocess.run(
        ["git", *SAFE_GIT, *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env or {})},
    )
    if check and result.returncode:
        raise RefreshError(f"git {args[0]} failed: {result.stderr.strip()[:300]}")
    return result.stdout if check else f"{result.returncode}\n{result.stdout}"


def _in_generated(path: str) -> bool:
    return path == GENERATED or path.startswith(GENERATED + "/")


def merge_heads(repo: Path, head: str, base: str) -> str:
    """Merge base into head without committing; return the merged non-generated tree.

    Only conflicts entirely inside src/static/ui/ are tolerated; any other unmerged
    path (including deleted or renamed ones) aborts. No ours/theirs strategy is
    used, so every source change that merged cleanly is kept. The generated
    directory is dropped from the index, ready to be replaced.
    """
    for sha in (head, base):
        if not SHA.match(sha) or git(repo, "cat-file", "-t", sha).strip() != "commit":
            raise RefreshError(f"{sha[:12]} is not a commit in the checkout")
    git(repo, "checkout", "-q", "--detach", head)
    status = git(
        repo,
        "merge",
        "--no-commit",
        "--no-ff",
        base,
        check=False,
        env={"GIT_MERGE_AUTOEDIT": "no"},
    )
    if int(status.split("\n", 1)[0]):
        unmerged = {
            path
            for path in git(repo, "ls-files", "-u", "-z").split("\0")
            for path in [path.split("\t", 1)[-1]]
            if path
        }
        if not unmerged:
            raise RefreshError(f"merge failed without a conflict list: {status[:200]}")
        outside = sorted(p for p in unmerged if not _in_generated(p))
        if outside:
            shown = ", ".join(outside[:5])
            raise RefreshError(
                f"conflicts outside {GENERATED}/ need a manual merge ({len(outside)}: {shown})"
            )
    git(repo, "rm", "-r", "-q", "-f", "--ignore-unmatch", "--", GENERATED)
    return git(repo, "write-tree").strip()


def sha256(path: Path) -> str:
    """Hex SHA-256 of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_files(directory: Path, manifest: list[dict]) -> list[Path]:
    """Check an untrusted output directory against its manifest; return its files."""
    if not directory.is_dir() or directory.is_symlink():
        raise RefreshError("artifact has no files directory")
    entries = list(directory.iterdir())
    if len(entries) > MAX_FILES or len(manifest) != len(entries):
        raise RefreshError("artifact file count does not match its manifest")
    wanted = {}
    for item in manifest:
        name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(name, str) or not FILE_NAME.match(name) or name in wanted:
            raise RefreshError(f"unexpected artifact file name {str(name)[:60]!r}")
        if Path(name).suffix not in ALLOWED_SUFFIXES:
            raise RefreshError(f"unexpected artifact file type: {name}")
        wanted[name] = item
    total = 0
    for entry in entries:
        item = wanted.get(entry.name)
        if item is None or entry.is_symlink() or not entry.is_file():
            raise RefreshError(f"unexpected artifact entry {entry.name[:60]!r}")
        size = entry.stat().st_size
        total += size
        if size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES or size != item.get("size"):
            raise RefreshError(
                f"artifact file {entry.name} is out of bounds or changed size"
            )
        if sha256(entry) != item.get("sha256"):
            raise RefreshError(
                f"artifact file {entry.name} does not match its checksum"
            )
    return sorted(entries)


def run_build(repo: Path) -> None:
    """Clean install and rebuild, exactly as AGENTS.md describes."""
    for command in (
        ["npm", "ci", "--ignore-scripts"],
        ["npm", "run", "build:ui"],
        ["npm", "run", "check:ui"],
    ):
        result = subprocess.run(
            command, cwd=repo, capture_output=True, text=True, check=False
        )
        if result.returncode:
            tail = (result.stdout + result.stderr).strip()[-600:]
            raise RefreshError(f"`{' '.join(command)}` failed: {tail}")


def _outside_changes(repo: Path) -> list[str]:
    changed = git(repo, "diff", "--name-only", "-z").split("\0")
    untracked = git(repo, "ls-files", "--others", "--exclude-standard", "-z").split(
        "\0"
    )
    return sorted(p for p in changed + untracked if p and not _in_generated(p))


def build(work: Path, out: Path, number: int, head: str, base: str) -> dict:
    """Merge, rebuild and describe the result. Never raises: failures are reported."""
    result = {"number": number, "head": head, "base": base}
    try:
        source_tree = merge_heads(work, head, base)
        shutil.rmtree(work / GENERATED, ignore_errors=True)
        run_build(work)
        touched = _outside_changes(work)
        if touched:
            raise RefreshError(
                f"the build modified source files: {', '.join(touched[:5])}"
            )
        built = work / GENERATED
        files = (
            sorted(p for p in built.iterdir() if p.is_file()) if built.is_dir() else []
        )
        if not files or len(files) > MAX_FILES:
            raise RefreshError("the build produced no usable files")
        shutil.rmtree(out / FILES, ignore_errors=True)
        (out / FILES).mkdir(parents=True)
        manifest = []
        for path in files:
            shutil.copyfile(path, out / FILES / path.name)
            manifest.append(
                {"name": path.name, "size": path.stat().st_size, "sha256": sha256(path)}
            )
        validate_files(out / FILES, manifest)
        result |= {"status": "ok", "source_tree": source_tree, "files": manifest}
    except (RefreshError, OSError) as error:
        result |= {"status": "failed", "reason": str(error)[:700]}
    out.mkdir(parents=True, exist_ok=True)
    (out / RESULT).write_text(json.dumps(result), encoding="utf-8")
    return result


# --- publication (trusted job) -------------------------------------------------


def _gh_json(*args: str) -> dict:
    """Run gh and parse its JSON output."""
    result = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if result.returncode:
        raise RefreshError(f"GitHub request failed: {result.stderr.strip()[:200]}")
    return json.loads(result.stdout or "{}")


def check_current(repo_name: str, entry: dict) -> None:
    """Fail unless the PR is still eligible and both SHAs are still current."""
    owner = repo_name.split("/")[0]
    pull = _gh_json("api", f"repos/{repo_name}/pulls/{entry['number']}")
    problems = []
    if pull.get("state") != "open" or pull.get("draft") or not pull.get("auto_merge"):
        problems.append("it is no longer an open, non-draft PR with auto-merge on")
    if pull["head"]["sha"] != entry["head"]:
        problems.append("its branch has new commits")
    if (pull["head"].get("repo") or {}).get("full_name") != repo_name:
        problems.append("it comes from a fork")
    if (pull.get("user") or {}).get("login") != owner:
        problems.append("it is not owner-authored")
    if pull["head"]["ref"] != entry["branch"]:
        problems.append("its branch name changed")
    if pull["base"]["ref"] != "latest":
        problems.append("it no longer targets latest")
    latest = _gh_json("api", f"repos/{repo_name}/git/ref/heads/latest")["object"]["sha"]
    if latest != entry["base"]:
        problems.append("latest moved")
    if problems:
        raise StaleError("; ".join(problems))


class StaleError(RefreshError):
    """The plan is out of date. Not a failure: the next run plans again."""


def _auth_env(token: str) -> dict:
    """Git config (via environment, not argv) that authenticates fetch and push."""
    header = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    print(f"::add-mask::{header}")
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
        "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {header}",
    }


def publish_one(
    repo_name: str,
    token: str,
    entry: dict,
    artifacts: Path,
    push_env: dict | None = None,
    remote_url: str = "",
) -> str:
    """Publish one refresh; return a summary line. Raises RefreshError or Stale."""
    result_path = artifacts / f"ui-{entry['number']}" / RESULT
    if not result_path.is_file():
        raise RefreshError("the build job produced no result")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result.get("status") != "ok":
        raise RefreshError(f"build failed: {result.get('reason', 'unknown reason')}")
    if any(result.get(k) != entry[k] for k in ("number", "head", "base")):
        raise RefreshError("the build result is for a different head or base")
    files_dir = result_path.parent / FILES
    paths = validate_files(files_dir, result.get("files") or [])
    check_current(repo_name, entry)
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        env = push_env if push_env is not None else _auth_env(token)
        url = remote_url or f"https://github.com/{repo_name}.git"
        git(repo, "init", "-q")
        git(repo, "remote", "add", "origin", url)
        git(
            repo,
            "fetch",
            "-q",
            "--filter=blob:none",
            "--no-tags",
            "origin",
            entry["head"],
            entry["base"],
            env=env,
        )
        source_tree = merge_heads(repo, entry["head"], entry["base"])
        if source_tree != result.get("source_tree"):
            raise RefreshError("the merged source differs from the one that was built")
        (repo / GENERATED).mkdir(parents=True, exist_ok=True)
        for path in paths:
            shutil.copyfile(path, repo / GENERATED / path.name)
        git(repo, "add", "-A", "--", GENERATED)
        message = f"Merge latest into {entry['branch']} and rebuild UI bundles\n\nMerge train refresh of src/static/ui/."
        git(repo, *BOT, "-c", "commit.gpgsign=false", "commit", "-q", "-m", message)
        if (
            git(repo, "rev-parse", "HEAD^1").strip() != entry["head"]
            or git(repo, "rev-parse", "HEAD^2").strip() != entry["base"]
        ):
            raise RefreshError("merge commit parents are not the PR head and latest")
        new = git(repo, "rev-parse", "HEAD").strip()
        check_current(repo_name, entry)  # last look before the push
        # Plain push: refused unless the commit fast-forwards the branch, so a
        # push that landed meanwhile is never overwritten.
        git(
            repo, "push", "-q", "origin", f"{new}:refs/heads/{entry['branch']}", env=env
        )
    return f"#{entry['number']} refreshed: merged latest and rebuilt UI bundles in {new[:12]}"


def _comment(repo_name: str, number: int, body: str) -> None:
    subprocess.run(
        [
            "gh",
            "api",
            f"repos/{repo_name}/issues/{number}/comments",
            "-f",
            f"body={body}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def _delete_comment(repo_name: str, comment_id) -> None:
    if comment_id:
        subprocess.run(
            [
                "gh",
                "api",
                "-X",
                "DELETE",
                f"repos/{repo_name}/issues/comments/{comment_id}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )


def publish(
    plan: list[dict], artifacts: Path, repo_name: str, token: str
) -> tuple[list[str], bool]:
    """Publish every planned refresh independently; return (summary lines, any failed)."""
    lines, failed = [], False
    for entry in plan:
        number = entry.get("number")
        try:
            if not (
                isinstance(number, int)
                and SHA.match(entry.get("head", ""))
                and SHA.match(entry.get("base", ""))
                and BRANCH.match(entry.get("branch", ""))
            ):
                raise RefreshError("malformed refresh plan entry")
            lines.append(publish_one(repo_name, token, entry, artifacts))
            _delete_comment(repo_name, entry.get("started_comment"))
        except StaleError as error:
            lines.append(
                f"#{number} not refreshed ({error}); the next run plans it again"
            )
            _delete_comment(repo_name, entry.get("started_comment"))
        except (RefreshError, KeyError, ValueError) as error:
            failed = True
            reason = str(error)
            lines.append(f"#{number} skipped: UI bundle refresh failed: {reason}")
            _delete_comment(repo_name, entry.get("started_comment"))
            if (
                isinstance(number, int)
                and SHA.match(entry.get("head", ""))
                and SHA.match(entry.get("base", ""))
            ):
                _comment(
                    repo_name,
                    number,
                    f"<!-- merge-train-ui:{entry['head']}:{entry['base']}:failed -->\n"
                    f"The merge train could not rebuild the UI bundles: {reason}\n\n"
                    "Merge latest into this branch yourself and run `npm run build:ui`.",
                )
    return lines, failed


def main(argv: list[str]) -> int:
    """Run the build or publish mode."""
    mode, args = argv[1], argv[2:]
    options = dict(zip(args[::2], args[1::2], strict=False))
    if mode == "build":
        result = build(
            Path(options["--work"]),
            Path(options["--out"]),
            int(options["--number"]),
            options["--head"],
            options["--base"],
        )
        print(
            f"UI refresh build for #{result['number']}: {result['status']} {result.get('reason', '')}"
        )
        return 0  # the publisher reports failures, so one PR cannot stop the rest
    if mode == "publish":
        lines, failed = publish(
            json.loads(os.environ["PLAN"]),
            Path(options["--artifacts"]),
            os.environ["GH_REPO"],
            os.environ["GH_TOKEN"],
        )
        for line in lines:
            print(f"::warning::{line}" if "skipped" in line else line)
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary and lines:
            with Path(summary).open("a", encoding="utf-8") as handle:
                handle.write(
                    "### Merge train UI refresh\n"
                    + "\n".join(f"- {x}" for x in lines)
                    + "\n"
                )
        return 1 if failed else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
