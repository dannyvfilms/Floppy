"""The parallel runner must not be strandable by an undelivered result.

Django's loop waits on ``imap_unordered`` forever, so a result that is produced
but never delivered hangs the whole run. These tests drive
``ResilientParallelTestSuite`` against pools that lose results and pools whose
teardown misbehaves, and assert that the run still completes with every test
accounted for.
"""

from __future__ import annotations

import multiprocessing
import unittest
from io import StringIO
from unittest.mock import patch

from django.test import SimpleTestCase

from config import test_runner
from config.test_runner import ResilientParallelTestSuite


class RunnerTimingTests(SimpleTestCase):
    def test_durations_report_modules_without_changing_results(self):
        stream = StringIO()
        runner = test_runner.ResilientDiscoverRunner(
            durations=5, logger=None, verbosity=1
        )
        with patch("sys.stderr", stream), patch("sys.stdout", stream):
            result = runner.run_suite(unittest.TestSuite([_PassingTest()]))
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(result.testsRun, 1)
        self.assertIn("Slowest test modules", stream.getvalue())
        self.assertIn(__name__, stream.getvalue())
        self.assertNotIn("<unattributed>", stream.getvalue())

    def test_serial_default_and_parallel_opt_in_are_preserved(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(
                test_runner.ResilientDiscoverRunner(parallel=4).parallel, 1
            )
        with patch.dict("os.environ", {"FLOPPY_TEST_PARALLEL": "2"}):
            self.assertEqual(
                test_runner.ResilientDiscoverRunner(parallel=4).parallel, 2
            )


class _PassingTest(unittest.TestCase):
    def runTest(self):  # noqa: N802  # unittest's own naming
        pass


def _subsuites(count):
    return [unittest.TestSuite([_PassingTest()]) for _ in range(count)]


class _FakeIterator:
    """Yields the given results, then times out forever like the real one."""

    def __init__(self, results):
        self._results = list(results)

    def next(self, timeout=None):  # mirrors multiprocessing's API
        if self._results:
            return self._results.pop(0)
        raise multiprocessing.TimeoutError


class _FakeWorker:
    def __init__(self, *, alive=True, join_hangs=False):
        self._alive = alive
        self.join_hangs = join_hangs
        self.joined_with = None
        self.terminated = False

    def is_alive(self):
        return self._alive

    def join(self, timeout=None):
        self.joined_with = timeout
        if not self.join_hangs:
            self._alive = False

    def terminate(self):
        self.terminated = True
        self._alive = False


class _FakePool:
    """A pool that can refuse terminate() the way a real broken one does."""

    def __init__(self, results, *, workers=None):
        self._results = results
        self._pool = workers if workers is not None else [_FakeWorker()]
        self.closed = False
        self.terminate_calls = 0

    def imap_unordered(self, func, args):
        return _FakeIterator(self._results)

    def close(self):
        self.closed = True

    def terminate(self):  # pragma: no cover - must never be called
        self.terminate_calls += 1
        msg = "Pool.terminate() can deadlock in _help_stuff_finish and must not be used"
        raise AssertionError(msg)

    def join(self):  # pragma: no cover - must never be called
        raise AssertionError("pool.join() can block forever and must not be used")


class ResilientParallelTestSuiteTests(SimpleTestCase):
    def _build(self, count, delivered, **pool_kwargs):
        suite = ResilientParallelTestSuite(
            _subsuites(count), processes=2, failfast=False, buffer=False
        )
        suite.initialize_suite = lambda: None
        pool = _FakePool([(index, []) for index in delivered], **pool_kwargs)
        return suite, pool

    def _run(self, suite, pools, stall_timeout="0.3", attempts="1"):
        """Run the suite against a sequence of pools, one per dispatch."""
        if not isinstance(pools, list):
            pools = [pools]
        result = unittest.TestResult()
        with (
            patch("config.test_runner.multiprocessing.Pool", side_effect=pools),
            patch.dict(
                "os.environ",
                {
                    "FLOPPY_TEST_STALL_TIMEOUT": stall_timeout,
                    "FLOPPY_TEST_MAX_DISPATCH_ATTEMPTS": attempts,
                },
            ),
        ):
            suite.run(result)
        return result

    def test_undelivered_results_end_the_run_loudly_not_silently(self):
        """One attempt only, so the two lost subsuites cannot be recovered.

        The run must end -- never hang -- and must fail rather than pretend the
        missing tests passed.
        """
        suite, pool = self._build(4, delivered=[0, 1])

        result = self._run(suite, pool)

        self.assertEqual(len(result.errors), 1)
        self.assertIn("parallel_runner_unrecovered", result.errors[0][1])
        self.assertIn("did NOT run", result.errors[0][1])

    def test_lost_work_is_redispatched_to_a_fresh_pool(self):
        """The preferred recovery: a worker environment, not the parent."""
        suite = ResilientParallelTestSuite(
            _subsuites(4), processes=2, failfast=False, buffer=False
        )
        suite.initialize_suite = lambda: None
        first = _FakePool([(0, []), (1, [])])
        second = _FakePool([(2, []), (3, [])])

        result = self._run(suite, [first, second], attempts="2")

        # Both pools were used, and nothing had to run in this process.
        self.assertTrue(first.closed or first._pool[0].terminated)
        self.assertEqual(result.testsRun, 0)
        self.assertEqual(result.errors, [])

    def test_a_later_attempt_that_succeeds_leaves_no_failure(self):
        """Recovery is silent in the result: retried work is just delivered."""
        suite = ResilientParallelTestSuite(
            _subsuites(3), processes=2, failfast=False, buffer=False
        )
        suite.initialize_suite = lambda: None
        first = _FakePool([(0, [])])
        second = _FakePool([(1, []), (2, [])])

        result = self._run(suite, [first, second], attempts="2")

        self.assertEqual(result.errors, [])
        self.assertEqual(result.testsRun, 0)

    def test_a_complete_run_needs_no_recovery(self):
        suite, pool = self._build(3, delivered=[0, 1, 2])

        result = self._run(suite, pool)

        self.assertTrue(pool.closed)
        self.assertEqual(result.testsRun, 0)

    def test_completion_does_not_wait_for_stopiteration(self):
        """`_FakeIterator` never raises StopIteration, so relying on it would
        block until the stall timeout instead of returning at the last result.
        """
        suite, pool = self._build(2, delivered=[0, 1])

        self._run(suite, pool, stall_timeout="600")

        self.assertTrue(pool.closed)

    def test_tests_are_never_run_in_the_parent_process(self):
        """Running recovered classes in the parent was tried and produces
        tearDownClass TransactionManagementError artefacts. It must not happen.
        """
        suite, pool = self._build(3, delivered=[0])

        result = self._run(suite, pool)

        self.assertEqual(result.testsRun, 0, "no subsuite may run in-process")

    def test_pool_terminate_is_never_used(self):
        """Observed for real: a stalled run detected the stall correctly and
        then blocked forever inside Pool.terminate(), because
        _help_stuff_finish takes the task queue lock that the wedged task
        handler still holds. Killing workers directly is the only safe route.
        """
        suite, pool = self._build(3, delivered=[0])

        result = self._run(suite, pool)

        self.assertEqual(pool.terminate_calls, 0)
        self.assertEqual(len(result.errors), 1)

    def test_a_wedged_worker_is_killed_rather_than_waited_on(self):
        wedged = _FakeWorker(join_hangs=True)
        suite, pool = self._build(1, delivered=[0], workers=[wedged])

        self._run(suite, pool)

        self.assertIsNotNone(wedged.joined_with, "join must be bounded, not blocking")
        self.assertLessEqual(wedged.joined_with, test_runner.POOL_TEARDOWN_TIMEOUT)
        self.assertTrue(wedged.terminated, "a worker that overstays gets killed")

    def test_pool_join_is_never_used_either(self):
        """`_FakePool.join` raises: an earlier version of this runner called
        pool.join() on the healthy path and simply relocated the hang.
        """
        suite, pool = self._build(2, delivered=[0, 1])

        result = self._run(suite, pool)

        self.assertEqual(result.errors, [])

    def test_stall_recovery_can_be_disabled_for_diagnosis(self):
        with patch.dict("os.environ", {"FLOPPY_TEST_STALL_TIMEOUT": "0"}):
            self.assertEqual(test_runner._stall_timeout(), 0.0)

    def test_an_unparseable_stall_timeout_falls_back_to_the_default(self):
        with patch.dict("os.environ", {"FLOPPY_TEST_STALL_TIMEOUT": "banana"}):
            self.assertEqual(
                test_runner._stall_timeout(), test_runner.DEFAULT_STALL_TIMEOUT
            )
