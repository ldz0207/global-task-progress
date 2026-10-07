import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import task_progress as progress


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="test-", dir=Path(__file__).resolve().parents[1].parent)
        self.state = Path(self.temp.name)
        self.reporter = progress.Reporter("test-job", "验证任务", self.state, auto_start=False)

    def tearDown(self):
        self.temp.cleanup()

    def record(self):
        return progress.read(self.reporter.path)

    def test_invalid_counts_do_not_create_record(self):
        for done, total in [(True, 2), (float("nan"), 3), (0, float("inf")), (-1, 2), (3, 2)]:
            with self.subTest(done=done, total=total), self.assertRaises(ValueError):
                self.reporter.update("复制", done, total)
        self.assertFalse(self.reporter.path.exists())

    def test_unknown_total_has_no_eta_or_percentage(self):
        self.reporter.update("扫描", 7, None)
        row = progress.snapshot(self.state)[0]
        self.assertEqual(row["done"], 7)
        self.assertIsNone(row["percent"])
        self.assertIsNone(row["eta_seconds"])

    def test_restored_historical_count_does_not_inflate_speed(self):
        with patch.object(progress.time, "time", return_value=1000):
            self.reporter.update("复制", 70, 100)
        self.assertIsNone(self.record()["speed"])
        with patch.object(progress.time, "time", return_value=1010):
            self.reporter.update("复制", 75, 100)
        self.assertEqual(self.record()["speed"], 0.5)
        self.assertEqual(self.record()["eta_seconds"], 50)

    def test_paused_and_resumed_keep_counts_but_reset_rate(self):
        with patch.object(progress.time, "time", return_value=1000):
            self.reporter.update("复制", 5, 20)
        with patch.object(progress.time, "time", return_value=1010):
            self.reporter.update("复制", 10, 20)
            self.reporter.stop("paused", "暂停")
        self.assertIsNone(self.record()["speed"])
        self.assertIsNone(self.record()["eta_seconds"])
        with patch.object(progress.time, "time", return_value=1100):
            self.reporter.update("复制", 10, 20)
        self.assertIsNone(self.record()["speed"])
        self.assertEqual(self.record()["attempts"][0]["done"], 10)

    def test_paused_completed_phase_still_has_no_eta(self):
        self.reporter.update("复制", 5, 5)
        self.reporter.stop("paused", "等待后续验收")
        self.assertIsNone(self.record()["eta_seconds"])

    def test_no_recent_progress_discards_previous_eta(self):
        with patch.object(progress.time, "time", return_value=1000):
            self.reporter.update("复制", 0, 20)
        with patch.object(progress.time, "time", return_value=1010):
            self.reporter.update("复制", 10, 20)
        with patch.object(progress.time, "time", return_value=1080):
            self.reporter.heartbeat()
        self.assertEqual(self.record()["speed"], 0)
        self.assertIsNone(self.record()["eta_seconds"])

    def test_stale_api_clears_rate_and_eta(self):
        with patch.object(progress.time, "time", return_value=1000):
            self.reporter.update("校验", 0, 10)
        with patch.object(progress.time, "time", return_value=1010):
            self.reporter.update("校验", 5, 10)
        with patch.object(progress.time, "time", return_value=1101):
            row = progress.snapshot(self.state)[0]
        self.assertEqual(row["status"], "attention")
        self.assertIsNone(row["speed"])
        self.assertIsNone(row["eta_seconds"])
        self.assertIsNone(row["stages"]["校验"]["speed"])

    def test_phase_completion_is_not_whole_completion(self):
        self.reporter.update("复制", 5, 5)
        self.assertEqual(self.record()["status"], "running")
        self.reporter.update("完整校验", 0, 5)
        with self.assertRaises(ValueError):
            self.reporter.update("发布", 1, 1, status="complete")
        self.reporter.update("完整校验", 5, 5)
        self.reporter.update("发布", 1, 1, status="complete")
        self.assertEqual(self.record()["status"], "complete")
        self.assertEqual(self.record()["stages"]["复制"]["done"], 5)

    def test_checkpoint_regression_and_unit_change_are_rejected(self):
        self.reporter.update("复制", 5, 10, unit="份")
        with self.assertRaises(ValueError):
            self.reporter.update("复制", 4, 10, unit="份")
        with self.assertRaises(ValueError):
            self.reporter.update("复制", 6, 10, unit="字节")
        self.assertEqual(self.record()["done"], 5)

    def test_existing_service_is_reused_without_spawning(self):
        body = json.dumps({"identity": progress.IDENTITY, "state_dir": str(self.state)}).encode()
        with patch.object(progress.urllib.request, "urlopen", return_value=io.BytesIO(body)), patch.object(progress.subprocess, "Popen") as spawn:
            progress.ensure(self.state)
        spawn.assert_not_called()

    def test_foreign_identity_and_other_state_fail_closed(self):
        for value in [{"identity": "other", "state_dir": str(self.state)}, {"identity": progress.IDENTITY, "state_dir": str(self.state / "other")}]:
            with self.subTest(value=value), patch.object(progress.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(value).encode())), patch.object(progress.subprocess, "Popen") as spawn, self.assertRaises(RuntimeError):
                progress.ensure(self.state)
            spawn.assert_not_called()

    def test_terminal_heartbeat_cannot_reanimate_task(self):
        self.reporter.update("复制", 2, 10)
        self.reporter.stop("failed", "实际异常")
        before = self.record()
        self.reporter.heartbeat()
        self.assertEqual(self.record(), before)

    def test_source_file_mtime_is_not_refreshed_by_reads(self):
        source = self.state / "source.json"
        progress.atomic(source, {"done": 2, "total": 10, "stage": "复制", "status": "running", "updated_ts": 1000, "speed": 1, "eta_seconds": 8})
        progress.atomic(self.state / "外部来源.json", {"existing": {"title": "已有来源", "path": str(source)}})
        with patch.object(progress.time, "time", return_value=1100):
            row = progress.snapshot(self.state)[0]
        self.assertEqual(row["status"], "attention")
        self.assertIsNone(row["eta_seconds"])


if __name__ == "__main__":
    unittest.main()
