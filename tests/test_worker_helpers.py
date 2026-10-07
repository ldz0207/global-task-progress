import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import worker_helpers as workers
import task_progress as progress


class WorkerHelperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="worker-test-", dir=SCRIPTS.parent.parent)
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_retry_transient_failure_with_bounded_backoff(self):
        calls, sleeps = [], []
        def action():
            calls.append(1)
            if len(calls) < 3:
                raise ConnectionError("temporary")
            return "ok"
        policy = workers.RetryPolicy(initial_delay=1, max_delay=10)
        with patch.object(workers.time, "sleep", side_effect=sleeps.append):
            self.assertEqual(workers.retry_call(action, retry_if=lambda error: isinstance(error, ConnectionError), policy=policy), "ok")
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [1, 2])

    def test_permanent_verification_failure_is_not_retried(self):
        calls = []
        def action():
            calls.append(1)
            raise workers.VerificationError("hash mismatch")
        with self.assertRaises(workers.VerificationError):
            workers.retry_call(action, retry_if=lambda error: isinstance(error, ConnectionError))
        self.assertEqual(len(calls), 1)

    def test_retry_limit_and_wait_budget_stop(self):
        calls = []
        def action():
            calls.append(1)
            raise TimeoutError("temporary")
        with patch.object(workers.time, "sleep"), self.assertRaises(TimeoutError):
            workers.retry_call(action, retry_if=lambda error: True, policy=workers.RetryPolicy(max_attempts=3))
        self.assertEqual(len(calls), 3)
        calls.clear()
        with self.assertRaises(TimeoutError):
            workers.retry_call(action, retry_if=lambda error: True, policy=workers.RetryPolicy(max_elapsed=0.1, initial_delay=1))
        self.assertEqual(len(calls), 1)

    def test_cancelled_retry_never_starts_operation(self):
        cancel = threading.Event()
        cancel.set()
        with patch("worker_helpers.time.sleep") as sleep, self.assertRaises(workers.Cancelled):
            workers.retry_call(lambda: self.fail("must not execute"), retry_if=lambda error: True, cancel=cancel)
        sleep.assert_not_called()

    def test_checkpoint_survives_restart_and_skips_verified_operation(self):
        path = self.root / "checkpoints.sqlite3"
        with workers.CheckpointStore(path) as store:
            evidence, reused = store.run_once("copy", "one", lambda: {"hash": "good"}, lambda value: value["hash"] == "good")
            self.assertFalse(reused)
        with workers.CheckpointStore(path) as store:
            _, reused = store.run_once("copy", "one", lambda: self.fail("verified work must not repeat"), lambda value: value["hash"] == "good")
            self.assertTrue(reused)

    def test_invalid_checkpoint_is_rechecked_and_unverified_output_not_saved(self):
        with workers.CheckpointStore(self.root / "checkpoints.sqlite3") as store:
            store.record("copy", "one", {"hash": "old"})
            _, reused = store.run_once("copy", "one", lambda: {"hash": "new"}, lambda value: value["hash"] == "new")
            self.assertFalse(reused)
            with self.assertRaises(workers.VerificationError):
                store.run_once("verify", "two", lambda: {"hash": "bad"}, lambda value: False)
            self.assertIsNone(store.get("verify", "two"))

    def test_worker_guard_prevents_duplicate_process_and_releases(self):
        lock = self.root / "worker.lock"
        code = "import sys;sys.path.insert(0," + repr(str(SCRIPTS)) + ");from worker_helpers import worker_guard,WorkerBusy\ntry:\n with worker_guard(sys.argv[1]):print('ACQUIRED')\nexcept WorkerBusy:print('BUSY')"
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        with workers.worker_guard(lock):
            child = subprocess.run([sys.executable, "-B", "-c", code, str(lock)], capture_output=True, text=True, timeout=10, creationflags=flags)
            self.assertEqual(child.returncode, 0, child.stderr)
            self.assertEqual(child.stdout.strip(), "BUSY")
        with workers.worker_guard(lock):
            pass

    def test_guard_releases_after_exception(self):
        lock = self.root / "worker.lock"
        with self.assertRaises(ValueError):
            with workers.worker_guard(lock):
                raise ValueError("business failed")
        with workers.worker_guard(lock):
            pass

    def test_large_input_is_not_eagerly_queued(self):
        consumed, active = [], []
        release = threading.Event()
        began = threading.Event()
        def source():
            for item in range(100_000):
                consumed.append(item)
                yield item
        def action(item):
            active.append(item)
            began.set()
            release.wait(2)
            return item
        stream = workers.bounded_map(action, source(), max_workers=2, max_pending=4)
        results = []
        thread = threading.Thread(target=lambda: results.append(next(stream)))
        thread.start()
        self.assertTrue(began.wait(1))
        time.sleep(0.03)
        self.assertLessEqual(len(consumed), 4)
        self.assertLessEqual(len(active), 2)
        release.set()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        stream.close()


class BufferedProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="buffer-test-", dir=SCRIPTS.parent.parent)
        self.root = Path(self.temp.name)
        self.reporter = progress.Reporter("buffer-job", "buffer", self.root, auto_start=False)

    def tearDown(self):
        self.temp.cleanup()

    def test_high_frequency_counters_are_coalesced_without_processes(self):
        with patch.object(progress.time, "monotonic", return_value=100), patch.object(progress.subprocess, "Popen") as spawn, patch.object(progress, "atomic", wraps=progress.atomic) as writes:
            self.reporter.update("copy", 0, 1000)
            for done in range(1, 1000):
                self.reporter.progress("copy", done, 1000)
            self.assertEqual(writes.call_count, 1)
            self.reporter.flush()
            self.assertEqual(writes.call_count, 2)
        self.assertEqual(progress.read(self.reporter.path)["done"], 999)
        spawn.assert_not_called()

    def test_stage_boundary_flushes_pending_actual_count(self):
        with patch.object(progress.time, "monotonic", return_value=100):
            self.reporter.update("copy", 0, 10)
            self.reporter.progress("copy", 4, 10)
            self.reporter.update("verify", 0, 10)
        self.assertEqual(progress.read(self.reporter.path)["stages"]["copy"]["done"], 4)

    def test_exception_preserves_pending_count_and_halts_eta(self):
        with patch.object(progress.time, "monotonic", return_value=100):
            self.reporter.update("copy", 0, 10)
            self.reporter.progress("copy", 4, 10)
            self.reporter.stop("failed", "business error")
        row = progress.read(self.reporter.path)
        self.assertEqual(row["done"], 4)
        self.assertEqual(row["status"], "failed")
        self.assertIsNone(row["eta_seconds"])

    def test_pulse_flushes_during_long_next_operation_and_on_exit(self):
        reporter = progress.Reporter("pulse-job", "pulse", self.root, auto_start=False, flush_interval=0.03)
        reporter.update("copy", 0, 10)
        with reporter.pulse(seconds=1):
            reporter.progress("copy", 1, 10)
            deadline = time.monotonic() + 1
            while progress.read(reporter.path)["done"] != 1 and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(progress.read(reporter.path)["done"], 1)
            reporter.progress("copy", 2, 10)
        self.assertEqual(progress.read(reporter.path)["done"], 2)

    def test_sampling_memory_is_bounded_and_completed_phase_is_compact(self):
        samples = []
        for index in range(10_000):
            samples, rate = progress.measured_rate(samples, index / 100, index)
        self.assertLessEqual(len(samples), 62)
        self.reporter.update("copy", 10, 10)
        self.assertEqual(progress.read(self.reporter.path)["stages"]["copy"]["_samples"], [])

    def test_pending_regression_is_rejected(self):
        with patch.object(progress.time, "monotonic", return_value=100):
            self.reporter.update("copy", 0, 10)
            self.reporter.progress("copy", 4, 10)
            with self.assertRaises(ValueError):
                self.reporter.progress("copy", 3, 10)
            self.reporter.stop("paused")
        self.assertEqual(progress.read(self.reporter.path)["done"], 4)

    def test_explicit_stage_attempt_retains_history_and_resets_only_requested_stage(self):
        self.reporter.update("copy", 10, 10)
        self.reporter.update("verify", 10, 10, status="complete")
        self.reporter.begin_stage_attempt("verify", 0, 10, reason="explicit revalidation")
        row=progress.read(self.reporter.path)
        self.assertEqual(row["stages"]["copy"]["done"],10)
        self.assertEqual(row["stages"]["verify"]["done"],0)
        self.assertEqual(row["attempts"][-1]["done"],10)
        self.assertEqual(row["attempts"][-1]["reason"],"explicit revalidation")


if __name__ == "__main__":
    unittest.main()
