"""Tests for scripts/merge_train.py, the queue that keeps approved PRs up to date.

``scripts/`` is not a package, so the script is loaded by path, as in
test_migration_order.
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import yaml

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "merge_train.py"
_spec = importlib.util.spec_from_file_location("merge_train", _SCRIPT)
train = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = train  # dataclasses look their module up here
_spec.loader.exec_module(train)

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
LATEST_SHA = "a" * 40


class _Clock(datetime):
    """datetime whose now() is the fixed NOW, so fixtures never age."""

    @classmethod
    def now(cls, _tz=None):
        return NOW


def _iso(delta=timedelta()):
    return (NOW - delta).isoformat()


def running(minutes=10):
    """All required checks queued or running, started `minutes` ago."""
    started = _iso(timedelta(minutes=minutes))
    return [
        ("lint", "IN_PROGRESS", None, started, None),
        ("test (3.12)", "IN_PROGRESS", None, started, None),
        ("migration-order", "IN_PROGRESS", None, started, None),
    ]


def passed(minutes_ago=5):
    """All required checks finished green `minutes_ago` minutes ago."""
    done = _iso(timedelta(minutes=minutes_ago))
    return [
        ("lint", "COMPLETED", "SUCCESS", done, done),
        ("test (3.12)", "COMPLETED", "SUCCESS", done, done),
        ("migration-order", "COMPLETED", "SUCCESS", done, done),
    ]


def pr(
    number,
    enabled="2026-10-05T01:00:00Z",
    state="BLOCKED",
    draft=False,
    checks=None,
    fork=False,
    editable=True,
    mergeable="MERGEABLE",
    committed=timedelta(minutes=5),
    author="o",
    comments=(),
):
    """Build a PR as the GraphQL query returns it (enabled=None: no auto-merge)."""
    return {
        "number": number,
        "body": "Example PR description",
        "isDraft": draft,
        "isCrossRepository": fork,
        "maintainerCanModify": editable,
        "mergeable": mergeable,
        "mergeStateStatus": state,
        "headRefOid": f"sha{number}",
        "headRefName": f"branch-{number}",
        "author": {"login": author},
        "comments": {"nodes": list(comments)},
        "autoMergeRequest": {"enabledAt": enabled} if enabled else None,
        "commits": {
            "nodes": [
                {
                    "commit": {
                        "committedDate": _iso(committed),
                        "statusCheckRollup": {
                            "contexts": {
                                "nodes": [
                                    {
                                        "name": n,
                                        "status": s,
                                        "conclusion": c,
                                        "startedAt": t,
                                        "completedAt": d,
                                    }
                                    for n, s, c, t, d in (
                                        running() if checks is None else checks
                                    )
                                ]
                            }
                        },
                    }
                }
            ]
        },
    }


def green_at(minutes_ago):
    return passed(minutes_ago=minutes_ago)


def picks(prs, behind, migrating=None, depth=3, now=NOW):
    """Return (PR numbers refreshed now, the Plan). Default: nothing touches migrations."""
    if migrating is None:
        migrating = {p["number"]: False for p in prs}
    result = train.plan(prs, behind, migrating, now, depth)
    chosen = [
        p["number"]
        for lane in (train.NORMAL, train.MIGRATION)
        for p in result.ranked[lane][: result.free[lane]]
    ]
    return chosen, result


class PlanTests(TestCase):
    """Several approved PRs are refreshed at once; nothing in flight holds them back."""

    def test_empty_queue_is_idle(self):
        chosen, result = picks([], {})
        self.assertEqual((chosen, result.queued, result.in_flight), ([], 0, 0))

    def test_drafts_and_unapproved_prs_are_never_touched(self):
        chosen, result = picks([pr(1, enabled=None), pr(2, draft=True)], {1: 3, 2: 3})
        self.assertEqual((chosen, result.queued, result.notes), ([], 0, []))

    def test_in_flight_pr_does_not_hold_back_green_prs(self):
        """The old stall: one PR's turn kept green PRs sitting. Now they all refresh."""
        prs = [pr(1), pr(2, checks=passed()), pr(3, checks=passed())]
        chosen, result = picks(prs, {1: 0, 2: 4, 3: 4})
        self.assertEqual(chosen, [2, 3])
        self.assertEqual(result.in_flight, 1)
        self.assertIn("#1 in flight (normal lane)", result.notes[0])

    def test_two_green_contributor_forks_refresh_beside_an_owner_pr_in_flight(self):
        """The #1986 / #1982 / #1970 queue from 2026-11-14, with no owner PR needed."""
        prs = [
            pr(1986, enabled="2026-11-14T20:00:00Z"),
            pr(1982, enabled="2026-11-14T18:00:00Z", fork=True, checks=passed()),
            pr(1970, enabled="2026-11-14T17:00:00Z", fork=True, checks=passed()),
        ]
        chosen, _ = picks(
            prs, {1986: 0, 1982: 5, 1970: 5}, now=_iso_dt("2026-11-14T21:00:00Z")
        )
        self.assertEqual(sorted(chosen), [1970, 1982])

    def test_depth_caps_parallel_refreshes_and_in_flight_prs_count(self):
        prs = [pr(n, checks=green_at(n)) for n in (1, 2, 3, 4)]
        self.assertEqual(len(picks(prs, dict.fromkeys((1, 2, 3, 4), 2))[0]), 3)
        self.assertEqual(picks(prs, {1: 0, 2: 0, 3: 2, 4: 2})[0], [4])
        chosen, result = picks(prs, {1: 0, 2: 0, 3: 0, 4: 2})
        self.assertEqual(chosen, [])
        self.assertEqual(result.ranked[train.NORMAL][0]["number"], 4)

    def test_depth_one_is_the_old_serial_train(self):
        prs = [pr(1, checks=green_at(9)), pr(2, checks=green_at(5))]
        self.assertEqual(picks(prs, {1: 2, 2: 2}, depth=1)[0], [1])

    def test_first_green_goes_first_whatever_the_approval_order(self):
        prs = [
            pr(1, enabled="2026-10-05T11:00:00Z", checks=green_at(5)),
            pr(2, enabled="2026-10-05T11:30:00Z", checks=green_at(40)),
        ]
        self.assertEqual(picks(prs, {1: 2, 2: 2}, depth=1)[0], [2])

    def test_green_beats_a_recent_unproven_pr(self):
        prs = [
            pr(1, enabled="2026-10-05T11:15:00Z"),
            pr(2, enabled="2026-10-05T11:30:00Z", checks=passed()),
        ]
        self.assertEqual(picks(prs, {1: 3, 2: 2}, depth=1)[0], [2])

    def test_aging_rule_prevents_starving_old_pending_pr(self):
        prs = [
            pr(1, enabled="2026-10-05T09:45:00Z"),
            pr(2, enabled="2026-10-05T11:30:00Z", checks=passed()),
        ]
        self.assertEqual(picks(prs, {1: 3, 2: 2}, depth=1)[0], [1])

    def test_old_red_retry_goes_after_green_work(self):
        old = pr(
            1,
            checks=[
                (
                    "lint",
                    "COMPLETED",
                    "FAILURE",
                    _iso(timedelta(hours=3)),
                    _iso(timedelta(hours=3)),
                ),
            ],
        )
        old["_latest_date"] = "2026-10-05T10:00:00Z"
        prs = [old, pr(2, checks=passed())]
        self.assertEqual(picks(prs, {1: 3, 2: 2}, depth=1)[0], [2])
        self.assertEqual(picks(prs, {1: 3, 2: 2}, depth=2)[0], [2, 1])

    def test_stale_branch_is_refreshed_whatever_github_calls_the_state(self):
        for state in ("BLOCKED", "UNKNOWN", "UNSTABLE", "BEHIND"):
            with self.subTest(state=state):
                front = pr(1, state=state, mergeable="UNKNOWN")
                self.assertEqual(picks([front], {1: 3})[0], [1])

    def test_behind_state_does_not_override_a_current_head(self):
        chosen, result = picks([pr(1, state="BEHIND")], {1: 0})
        self.assertEqual((chosen, result.in_flight), ([], 1))

    def test_unknown_behindness_is_skipped_not_waited_on(self):
        chosen, result = picks([pr(1), pr(2)], {1: None, 2: 1}, depth=1)
        self.assertEqual(chosen, [2])
        self.assertIn("#1 skipped: could not tell", result.notes[0])

    def test_unsettled_flags_a_queued_pr_with_unknown_mergeability(self):
        self.assertTrue(train.unsettled([pr(1, mergeable="UNKNOWN")]))
        self.assertFalse(train.unsettled([pr(1, mergeable="UNKNOWN", enabled=None)]))
        self.assertFalse(train.unsettled([pr(1)]))

    def test_conflicted_failed_and_hung_prs_are_skipped(self):
        done = _iso(timedelta(minutes=5))
        prs = [
            pr(1, state="DIRTY"),
            pr(2, mergeable="CONFLICTING"),
            pr(3, checks=[("test (3.12)", "COMPLETED", "FAILURE", done, done)]),
            pr(4, checks=running(minutes=180)),
            pr(5),
        ]
        chosen, result = picks(prs, {1: 1, 2: 1, 3: 0, 4: 0, 5: 1})
        self.assertEqual(chosen, [5])
        text = "\n".join(result.notes)
        for expected in (
            "#1 skipped: merge conflict",
            "#2 skipped: merge conflict",
            "'test (3.12)' failed",
            "pending for hours",
        ):
            self.assertIn(expected, text)

    def test_failed_migration_order_parks_the_pr(self):
        done = _iso(timedelta(minutes=5))
        clash = pr(
            1,
            checks=[
                *running(),
                ("migration-order", "COMPLETED", "FAILURE", done, done),
            ],
        )
        chosen, result = picks([clash], {1: 0}, {1: True})
        self.assertEqual((chosen, result.in_flight, result.manual_only), ([], 0, False))

    def test_failed_optional_check_does_not_block(self):
        done = _iso(timedelta(minutes=5))
        ok = pr(1, checks=[*running(), ("build", "COMPLETED", "FAILURE", done, done)])
        self.assertEqual(picks([ok], {1: 0})[1].in_flight, 1)

    def test_fresh_commit_without_checks_is_in_flight_but_ignored_commit_is_skipped(
        self,
    ):
        self.assertEqual(
            picks([pr(1, checks=[], committed=timedelta(minutes=2))], {1: 0})[
                1
            ].in_flight,
            1,
        )
        _, result = picks([pr(1, checks=[], committed=timedelta(hours=5))], {1: 0})
        self.assertIn("never started", result.notes[0])

    def test_partially_missing_required_checks_eventually_park(self):
        partial = pr(1, checks=passed()[:-1], committed=timedelta(hours=3))
        self.assertEqual(picks([partial], {1: 0})[1].in_flight, 0)

    def test_green_pr_github_has_not_merged_yet_is_in_flight_until_it_stalls(self):
        self.assertEqual(
            picks([pr(1, state="CLEAN", checks=passed(3))], {1: 0})[1].in_flight, 1
        )
        _, result = picks([pr(1, state="BLOCKED", checks=passed(60))], {1: 0})
        self.assertIn("still reports BLOCKED", result.notes[0])

    def test_fork_permission_boundary_is_a_manual_handoff(self):
        chosen, result = picks([pr(1, fork=True, editable=False)], {1: 3})
        self.assertEqual((chosen, result.manual_only), ([], True))
        self.assertIn("the contributor has to", result.notes[0])

    def test_editable_fork_is_refreshed_like_an_owner_pr(self):
        self.assertEqual(picks([pr(1, fork=True), pr(2)], {1: 3, 2: 3})[0], [1, 2])


def _iso_dt(value):
    return datetime.fromisoformat(value)


class MigrationLaneTests(TestCase):
    """PRs that change migrations go one at a time, in approval order."""

    def test_only_the_oldest_migration_pr_is_refreshed(self):
        prs = [
            pr(1, enabled="2026-10-05T03:00:00Z", checks=green_at(50)),
            pr(2, enabled="2026-10-05T02:00:00Z"),
            pr(3, enabled="2026-10-05T04:00:00Z"),
        ]
        chosen, result = picks(prs, {1: 2, 2: 2, 3: 2}, {1: True, 2: True, 3: True})
        self.assertEqual(chosen, [2])
        self.assertEqual(
            [p["number"] for p in result.ranked[train.MIGRATION]], [2, 1, 3]
        )

    def test_migration_pr_in_flight_blocks_other_migrations_not_normal_prs(self):
        prs = [pr(1), pr(2, checks=passed()), pr(3, checks=passed())]
        chosen, _ = picks(prs, {1: 0, 2: 3, 3: 3}, {1: True, 2: True, 3: False})
        self.assertEqual(chosen, [3])

    def test_unknown_migration_status_fails_closed_to_the_migration_lane(self):
        prs = [pr(1, checks=passed()), pr(2, checks=passed())]
        chosen, result = picks(prs, {1: 2, 2: 2}, {})
        self.assertEqual(chosen, [1])
        self.assertEqual(result.ranked[train.NORMAL], [])


class CompareTests(TestCase):
    """Behind count and migration detection come from one compare call."""

    def compare(self, payload=None, error=False):
        def fake(*args):
            if error:
                raise subprocess.CalledProcessError(1, args, stderr="HTTP 502")
            return json.dumps(payload)

        with patch.object(train, "_gh", fake):
            return train._compare("o", "r", LATEST_SHA, "sha1")

    def test_plain_change_is_not_a_migration(self):
        self.assertEqual(
            self.compare({"behind": 4, "files": ["src/app/views.py"], "count": 1}),
            (4, False),
        )

    def test_added_deleted_or_renamed_migrations_are_detected(self):
        for files in (
            ["src/app/migrations/0100_x.py"],
            ["src/app/old.py", "src/app/migrations/0100_x.py"],  # renamed into
            ["src/app/attic/0100_x.py", "src/app/migrations/0100_x.py"],  # out of
            ["src/users/migrations/README"],
        ):
            with self.subTest(files=files):
                self.assertEqual(
                    self.compare({"behind": 1, "files": files, "count": 1}), (1, True)
                )

    def test_truncated_diff_fails_closed(self):
        payload = {"behind": 1, "files": ["a.py"], "count": train.COMPARE_FILE_LIMIT}
        self.assertEqual(self.compare(payload), (1, True))

    def test_api_error_is_unknown_and_fails_closed(self):
        self.assertEqual(self.compare(error=True), (None, True))


class _FakeGh:
    """Stands in for the gh CLI: GraphQL, compare and update-branch calls."""

    def __init__(self, prs, behind, refuse=(), migrating=()):
        self.prs, self.behind, self.refuse = prs, behind, dict(refuse)
        self.migrating = set(migrating)
        self.updated = []
        self.calls = []
        self.comments = []
        self.pr_files = ["src/app/x.py"]
        self.latest_files = ["src/app/y.py"]

    def __call__(self, *args):
        self.calls.append(args)
        if args[:2] == ("api", "graphql"):
            data = {
                "repository": {
                    "ref": {
                        "target": {
                            "oid": LATEST_SHA,
                            "committedDate": "2026-10-05T10:00:00Z",
                        }
                    },
                    "pullRequests": {"nodes": self.prs},
                }
            }
            return json.dumps({"data": data})
        if args[1].endswith(f"...{LATEST_SHA}"):  # latest's changes since the PR
            return json.dumps(
                {"files": self.latest_files, "count": len(self.latest_files)}
            )
        if args[1].endswith("/comments"):
            self.comments.append(args[-1].removeprefix("body="))
            return json.dumps({"id": 99})
        if args[1].startswith(f"repos/o/r/compare/{LATEST_SHA}..."):
            head = args[1].rsplit("...", 1)[1]
            number = next(p["number"] for p in self.prs if p["headRefOid"] == head)
            behind = self.behind[number]
            if behind is None:
                raise subprocess.CalledProcessError(1, args, stderr="boom")
            files = (
                ["src/app/migrations/0200_x.py", *self.pr_files]
                if number in self.migrating
                else self.pr_files
            )
            return json.dumps({"behind": behind, "files": files, "count": len(files)})
        if args[2] == "PATCH":
            number = int(args[3].split("/")[-1])
            next(pr for pr in self.prs if pr["number"] == number)["body"] = args[
                -1
            ].removeprefix("body=")
            return "{}"
        number = int(args[3].split("/")[4])
        if number in self.refuse:
            raise subprocess.CalledProcessError(1, args, stderr=self.refuse[number])
        self.updated.append(number)
        return "{}"


OLD_LINT_FAILURE = [
    (
        "lint",
        "COMPLETED",
        "FAILURE",
        _iso(timedelta(hours=3)),
        _iso(timedelta(hours=3)),
    ),
    ("test (3.12)", "COMPLETED", "SUCCESS", _iso(), _iso()),
    ("migration-order", "COMPLETED", "SUCCESS", _iso(), _iso()),
]
FORBIDDEN = "gh: user doesn't have permission (HTTP 403)"


class MainTests(TestCase):
    """The whole run: what it calls on GitHub and what exit code it reports."""

    def run_train(
        self,
        prs,
        behind,
        refuse=(),
        argv=(),
        migrating=(),
        env=None,
        pr_files=None,
        latest_files=None,
    ):
        fake = _FakeGh(prs, behind, refuse, migrating)
        if pr_files:
            fake.pr_files = pr_files
        if latest_files:
            fake.latest_files = latest_files
        self.fake = fake
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "output"
            code = self._run(fake, argv, {**(env or {}), "GITHUB_OUTPUT": str(out)})
            self.ui_refresh = (
                json.loads(out.read_text().split("ui_refresh=", 1)[1].splitlines()[0])
                if out.exists()
                else None
            )
        return code, fake

    def _run(self, fake, argv, env):
        with (
            patch.object(train, "_gh", fake),
            patch.object(train, "time"),
            patch.object(train, "datetime", _Clock),
            patch.dict("os.environ", {"GH_REPO": "o/r", **env}),
        ):
            return train.main(["merge_train.py", *argv])

    def test_stale_branch_is_updated_and_the_run_succeeds(self):
        code, fake = self.run_train([pr(1, state="UNKNOWN")], {1: 2})
        self.assertEqual((code, fake.updated), (0, [1]))

    def test_green_prs_refresh_in_parallel_while_one_is_in_flight(self):
        prs = [
            pr(1),
            pr(2, checks=passed()),
            pr(3, checks=passed()),
            pr(4, checks=passed()),
        ]
        code, fake = self.run_train(prs, {1: 0, 2: 2, 3: 2, 4: 2})
        self.assertEqual((code, sorted(fake.updated)), (0, [2, 3]))

    def test_depth_comes_from_the_environment(self):
        prs = [pr(n, checks=passed()) for n in (1, 2, 3)]
        for depth, count in (("1", 1), ("2", 2), ("junk", 3), ("", 3)):
            with self.subTest(depth=depth):
                _, fake = self.run_train(
                    prs, dict.fromkeys((1, 2, 3), 2), env={"MERGE_TRAIN_DEPTH": depth}
                )
                self.assertEqual(len(fake.updated), count)

    def test_migration_prs_refresh_one_at_a_time_beside_normal_prs(self):
        prs = [
            pr(1, enabled="2026-10-05T01:00:00Z"),
            pr(2, enabled="2026-10-05T02:00:00Z"),
            pr(3),
        ]
        code, fake = self.run_train(prs, {1: 1, 2: 1, 3: 1}, migrating={1, 2})
        self.assertEqual((code, sorted(fake.updated)), (0, [1, 3]))

    def test_only_branch_updates_are_ever_written(self):
        """No PR, branch, merge or auto-merge call: only update-branch (and a body marker)."""
        prs = [pr(1), pr(2, checks=passed()), pr(3, checks=OLD_LINT_FAILURE)]
        _, fake = self.run_train(prs, {1: 0, 2: 2, 3: 2})
        writes = [c for c in fake.calls if "-X" in c]
        self.assertTrue(writes)
        for call in writes:
            self.assertTrue(
                call[3].endswith("/update-branch") or call[2] == "PATCH", call
            )
        self.assertFalse([c for c in fake.calls if "mutation" in " ".join(c)])

    def test_old_failed_check_is_refreshed_after_latest_advances(self):
        old = pr(1, checks=OLD_LINT_FAILURE)
        body = old["body"]
        code, fake = self.run_train([old], {1: 2})
        self.assertEqual((code, fake.updated), (0, [1]))
        self.assertEqual(old["body"], body)  # no PR edit, so no extra train wakeup

    def test_legacy_attempt_marker_still_blocks_a_second_retry_on_the_same_base(self):
        old = pr(1, checks=OLD_LINT_FAILURE)
        old["_latest_oid"] = LATEST_SHA
        old["_latest_date"] = "2026-10-05T10:00:00Z"
        old["body"] += f"\n<!-- merge-train-base:{LATEST_SHA} -->"
        self.assertEqual(train.judge(old, 2, NOW)[0], "skip")

    def test_refusal_does_not_park_a_pr_until_latest_moves(self):
        """#1923 on 2026-11-16: one 403 used to skip it for the whole base."""
        old = pr(1, fork=True, checks=OLD_LINT_FAILURE)
        old["_latest_oid"] = LATEST_SHA
        old["_latest_date"] = "2026-10-05T10:00:00Z"
        old["body"] += f"\n<!-- merge-train-base:{LATEST_SHA}:refused -->"
        self.assertEqual(train.judge(old, 2, NOW)[0], "update")
        body = old["body"]
        code, fake = self.run_train([old], {1: 2}, {1: FORBIDDEN})
        self.assertEqual((code, fake.updated, old["body"]), (0, [], body))
        code, fake = self.run_train([old], {1: 2})
        self.assertEqual((code, fake.updated), (0, [1]))

    def test_refusal_reports_githubs_own_reason(self):
        stderr = (
            "gh: Resource not accessible by personal access token (HTTP 403)\n{...}"
        )
        line = train._refusal(stderr)
        self.assertIn(
            "GitHub said: Resource not accessible by personal access token (HTTP 403)",
            line,
        )
        self.assertNotIn("{...}", line)

    def test_dry_run_updates_nothing(self):
        code, fake = self.run_train([pr(1), pr(2)], {1: 2, 2: 2}, argv=["--dry-run"])
        self.assertEqual((code, fake.updated), (0, []))

    def test_ci_event_on_obsolete_or_unapproved_head_is_ignored(self):
        for head in ("obsolete", "sha2"):
            with self.subTest(head=head):
                code, fake = self.run_train(
                    [pr(1), pr(2, enabled=None)], {1: 2}, env={"CI_HEAD": head}
                )
                self.assertEqual((code, fake.updated), (0, []))

    def test_ci_failure_on_current_head_advances_others(self):
        done = _iso(timedelta(minutes=5))
        failed = pr(1, checks=[("test (3.12)", "COMPLETED", "FAILURE", done, done)])
        code, fake = self.run_train(
            [failed, pr(2, checks=passed())], {1: 0, 2: 2}, env={"CI_HEAD": "sha1"}
        )
        self.assertEqual((code, fake.updated), (0, [2]))

    def test_empty_queue_succeeds(self):
        self.assertEqual(self.run_train([pr(1, enabled=None)], {})[0], 0)

    def test_in_flight_pr_succeeds_even_with_a_conflicted_pr(self):
        code, fake = self.run_train([pr(1), pr(2, state="DIRTY")], {1: 0, 2: 1})
        self.assertEqual((code, fake.updated), (0, []))

    def test_refused_fork_update_moves_on_and_is_a_manual_handoff(self):
        code, fake = self.run_train(
            [pr(1, fork=True), pr(2)],
            {1: 1, 2: 1},
            {1: FORBIDDEN},
            env={"MERGE_TRAIN_DEPTH": "1"},
        )
        self.assertEqual((code, fake.updated), (0, [2]))
        code, fake = self.run_train([pr(1, fork=True)], {1: 1}, {1: FORBIDDEN})
        self.assertEqual((code, fake.updated), (0, []))

    def test_refused_local_branch_remains_an_error(self):
        code, fake = self.run_train([pr(1)], {1: 1}, {1: FORBIDDEN})
        self.assertEqual((code, fake.updated), (1, []))

    def test_fork_permission_skip_does_not_hide_an_unrelated_conflict(self):
        code, fake = self.run_train(
            [pr(1, fork=True, editable=False), pr(2, state="DIRTY")], {1: 1, 2: 1}
        )
        self.assertEqual((code, fake.updated), (1, []))

    def test_conflict_found_while_updating_is_reported(self):
        refuse = {1: "gh: merge conflict between base and head (HTTP 422)"}
        self.assertEqual(self.run_train([pr(1)], {1: 1}, refuse)[0], 1)

    def test_queue_of_only_conflicted_prs_fails_the_run(self):
        code, fake = self.run_train([pr(1, state="DIRTY")], {1: 1})
        self.assertEqual((code, fake.updated), (1, []))

    def test_unsettled_mergeability_is_asked_again(self):
        code, fake = self.run_train([pr(1, mergeable="UNKNOWN")], {1: 1})
        graphql = [c for c in fake.calls if c[:2] == ("api", "graphql")]
        self.assertEqual(len(graphql), 1 + train.UNKNOWN_RETRIES)
        self.assertEqual((code, fake.updated), (0, [1]))

    def test_compare_failure_does_not_block_the_next_pr(self):
        code, fake = self.run_train([pr(1), pr(2)], {1: None, 2: 1})
        self.assertEqual((code, fake.updated), (0, [2]))


UI_ENV = {"MERGE_TRAIN_REBUILD_UI": "true"}
UI_FILES = ["frontend/ui/x.jsx", "src/static/ui/chunk-AAAA.js"]


def marker(head, kind, minutes=5, author="o"):
    return {
        "body": f"<!-- merge-train-ui:{head}:{LATEST_SHA}:{kind} -->",
        "createdAt": _iso(timedelta(minutes=minutes)),
        "author": {"login": author},
    }


class UiRefreshTests(MainTests):
    """Eligible PRs go to the isolated rebuild; everything else keeps the API path."""

    HEAD = "b" * 40

    def ui_pr(self, number=1, **kw):
        record = pr(number, **kw)
        record["headRefOid"] = self.HEAD
        return record

    def go(self, prs, behind=None, **kw):
        kw.setdefault("env", UI_ENV)
        kw.setdefault("pr_files", UI_FILES)
        kw.setdefault("latest_files", ["src/static/ui/chunk-BBBB.js"])
        return self.run_train(prs, behind or {1: 2}, **kw)

    def test_overlapping_ui_changes_are_rebuilt_not_api_updated(self):
        code, fake = self.go([self.ui_pr()])
        self.assertEqual((code, fake.updated), (0, []))
        self.assertEqual(
            self.ui_refresh,
            [
                {
                    "number": 1,
                    "branch": "branch-1",
                    "head": self.HEAD,
                    "base": LATEST_SHA,
                    "started_comment": "99",
                }
            ],
        )
        self.assertIn(
            f"merge-train-ui:{self.HEAD}:{LATEST_SHA}:started", fake.comments[0]
        )

    def test_flag_off_keeps_the_existing_behaviour(self):
        code, fake = self.go([self.ui_pr()], env={})
        self.assertEqual((code, fake.updated, self.ui_refresh), (0, [1], []))
        self.assertFalse(
            any(c[1].endswith(f"...{LATEST_SHA}") for c in fake.calls if len(c) > 1)
        )

    def test_non_ui_refresh_stays_on_the_api_path_without_node(self):
        code, fake = self.go([self.ui_pr()], pr_files=["src/app/x.py"])
        self.assertEqual((fake.updated, self.ui_refresh), ([1], []))

    def test_ui_change_only_on_one_side_is_an_ordinary_refresh(self):
        _, fake = self.go([self.ui_pr()], latest_files=["src/app/y.py"])
        self.assertEqual((fake.updated, self.ui_refresh), ([1], []))

    def test_conflicted_ui_pr_is_attempted_instead_of_parked(self):
        code, fake = self.go([self.ui_pr(state="DIRTY", mergeable="CONFLICTING")])
        self.assertEqual((code, fake.updated, len(self.ui_refresh)), (0, [], 1))

    def test_conflict_without_ui_changes_stays_manual(self):
        code, fake = self.go([self.ui_pr(state="DIRTY")], pr_files=["src/app/x.py"])
        self.assertEqual((code, self.ui_refresh), (1, []))

    def test_forks_drafts_and_other_authors_are_never_rebuilt(self):
        for label, record in {
            "fork": self.ui_pr(fork=True),
            "author": self.ui_pr(author="stranger"),
        }.items():
            with self.subTest(label):
                self.go([record])
                self.assertEqual(self.ui_refresh, [])
        _, fake = self.go([self.ui_pr(draft=True)])
        self.assertEqual((fake.updated, self.ui_refresh), ([], []))

    def test_dry_run_requests_and_comments_nothing(self):
        code, fake = self.go([self.ui_pr()], argv=["--dry-run"])
        self.assertEqual(
            (code, fake.updated, self.ui_refresh, fake.comments), (0, [], [], [])
        )

    def test_migration_prs_keep_the_serial_lane(self):
        prs = [self.ui_pr(1), self.ui_pr(2, enabled="2026-10-05T02:00:00Z")]
        prs[1]["headRefOid"] = "c" * 40
        self.go(prs, {1: 2, 2: 2}, migrating={1, 2})
        self.assertEqual([r["number"] for r in self.ui_refresh], [1])

    def test_depth_still_bounds_parallel_refreshes(self):
        prs = [self.ui_pr(n, enabled=f"2026-10-05T0{n}:00:00Z") for n in (1, 2, 3)]
        for n, p in enumerate(prs, 1):
            p["headRefOid"] = str(n) * 40
        self.go(prs, {1: 2, 2: 2, 3: 2}, env={**UI_ENV, "MERGE_TRAIN_DEPTH": "2"})
        self.assertEqual([r["number"] for r in self.ui_refresh], [1, 2])

    def test_running_refresh_is_in_flight_and_not_repeated(self):
        prs = [self.ui_pr(comments=[marker(self.HEAD, "started")])]
        code, fake = self.go(prs)
        self.assertEqual(
            (code, fake.updated, self.ui_refresh, fake.comments), (0, [], [], [])
        )

    def test_failed_or_expired_refresh_falls_back_to_the_api_once(self):
        for kind, minutes in (("failed", 5), ("started", 45)):
            with self.subTest(kind):
                prs = [self.ui_pr(comments=[marker(self.HEAD, kind, minutes)])]
                _, fake = self.go(prs)
                self.assertEqual((fake.updated, self.ui_refresh), ([1], []))

    def test_failed_conflicted_refresh_is_parked_like_before(self):
        prs = [self.ui_pr(state="DIRTY", comments=[marker(self.HEAD, "failed")])]
        code, _ = self.go(prs)
        self.assertEqual((code, self.ui_refresh), (1, []))

    def test_only_the_owners_markers_count(self):
        prs = [self.ui_pr(comments=[marker(self.HEAD, "failed", author="stranger")])]
        self.go(prs)
        self.assertEqual(len(self.ui_refresh), 1)

    def test_marker_for_another_head_is_ignored(self):
        self.go([self.ui_pr(comments=[marker("d" * 40, "failed")])])
        self.assertEqual(len(self.ui_refresh), 1)

    def test_failed_pr_does_not_starve_the_next_one(self):
        second = self.ui_pr(2)
        second["headRefOid"] = "c" * 40
        prs = [self.ui_pr(1, comments=[marker(self.HEAD, "failed")]), second]
        self.go(prs, {1: 2, 2: 2})
        self.assertEqual(
            (self.fake.updated, [r["number"] for r in self.ui_refresh]), ([1], [2])
        )


class WorkflowTests(TestCase):
    """The workflow wakes on queue changes and never runs a fork's code."""

    @classmethod
    def setUpClass(cls):
        """Load the workflow once. PyYAML reads the bare key `on` as True."""
        super().setUpClass()
        path = _SCRIPT.parents[1] / ".github" / "workflows" / "merge-train.yml"
        cls.workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        cls.triggers = cls.workflow[True]

    def test_runs_on_events_not_only_on_the_schedule(self):
        """Approval, ready, push and close events advance the queue at once."""
        self.assertLessEqual(
            {"push", "schedule", "pull_request_target", "workflow_dispatch"},
            set(self.triggers),
        )
        self.assertEqual(self.triggers["workflow_run"]["types"], ["completed"])
        self.assertEqual(
            set(self.triggers["workflow_run"]["workflows"]),
            {"App Tests", "Lint", "Migration Order"},
        )
        gate = self.workflow["jobs"]["merge-train"]["if"]
        self.assertIn("github.event.workflow_run.event == 'pull_request'", gate)
        self.assertNotIn("conclusion", gate)
        self.assertIn(
            "auto_merge_enabled", self.triggers["pull_request_target"]["types"]
        )

    def test_never_checks_out_pull_request_code(self):
        """pull_request_target has secrets, so only latest's own code may run."""
        steps = self.workflow["jobs"]["merge-train"]["steps"]
        for step in steps:
            if str(step.get("uses", "")).startswith("actions/checkout"):
                self.assertEqual(step.get("with", {}).get("ref"), "latest")

    def test_no_batch_mode_left(self):
        env = self.workflow["jobs"]["merge-train"]["steps"][-1]["env"]
        self.assertNotIn("MERGE_TRAIN_BATCH", env)
        self.assertIn("MERGE_TRAIN_DEPTH", env)

    def test_ui_build_is_isolated_from_secrets_and_publish_trusts_only_latest(self):
        jobs = self.workflow["jobs"]
        build, publish = jobs["ui-build"], jobs["ui-publish"]
        self.assertEqual(build["permissions"], {"contents": "read"})
        text = json.dumps(build)
        self.assertNotIn("secrets.", text)
        for step in build["steps"]:
            if str(step.get("uses", "")).startswith("actions/checkout"):
                self.assertIs(step["with"]["persist-credentials"], False)
        self.assertEqual(build["steps"][0]["with"]["ref"], "latest")  # trusted script
        for step in publish["steps"]:
            if str(step.get("uses", "")).startswith("actions/checkout"):
                self.assertEqual(step["with"]["ref"], "latest")
            self.assertNotIn("npm", step.get("run", ""))
            self.assertNotIn("setup-node", str(step.get("uses", "")))
        self.assertIn("AUTO_MERGE_TOKEN", json.dumps(publish))
        self.assertNotIn("AUTO_MERGE_TOKEN", text)

    def test_planner_job_runs_no_node_and_the_flag_is_a_variable(self):
        planner = self.workflow["jobs"]["merge-train"]
        self.assertIn("ui_refresh", planner["outputs"])
        env = planner["steps"][-1]["env"]
        self.assertIn("vars.MERGE_TRAIN_REBUILD_UI", env["MERGE_TRAIN_REBUILD_UI"])
        self.assertNotIn("npm", json.dumps(planner))
        self.assertEqual(planner["concurrency"]["group"], "merge-train")
