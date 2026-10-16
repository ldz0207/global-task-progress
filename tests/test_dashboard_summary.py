import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import task_progress as progress


class DashboardSummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1].parent)
        self.state = Path(self.temp.name)
        self.cache = progress.TaskFiles()
        for task_id in ("main", "finished", "service"):
            reporter = progress.Reporter(task_id, task_id, self.state, auto_start=False)
            reporter.update("verify", 1, 1, status="complete" if task_id == "finished" else "running")
        progress.atomic(self.state / "服务配置.json", {"identity": progress.IDENTITY, "port": 8790, "dashboard": {"background_task_ids": ["service"]}})

    def tearDown(self):
        self.temp.cleanup()

    def test_default_keeps_counts_but_does_not_send_history_services_or_stages(self):
        result = progress.dashboard_snapshot(self.state, self.cache, {})
        self.assertEqual([row["task_id"] for row in result["tasks"]], ["main"])
        self.assertEqual(result["tasks"][0]["stages"], {})
        self.assertEqual(result["counts"], {"total": 2, "running": 1, "waiting": 0, "complete": 1})
        self.assertEqual((result["history_count"], result["background_count"]), (1, 1))

    def test_expand_fetches_exact_original_detail_and_background_is_explicit(self):
        result = progress.dashboard_snapshot(self.state, self.cache, {"history": ["1"], "background": ["1"], "details": ["finished"]})
        rows = {row["task_id"]: row for row in result["tasks"]}
        self.assertEqual(set(rows), {"main", "finished", "service"})
        self.assertEqual(rows["service"]["display_group"], "background")
        self.assertEqual(rows["finished"]["stages"]["verify"]["done"], 1)
        self.assertEqual(rows["main"]["stages"], {})
        self.assertNotIn("details_available", rows["finished"])

    def test_unchanged_files_are_reused_and_writer_updates_are_visible(self):
        progress.dashboard_snapshot(self.state, self.cache, {})
        with patch.object(progress, "read", wraps=progress.read) as reads:
            progress.dashboard_snapshot(self.state, self.cache, {})
            self.assertEqual(reads.call_count, 0)
            reporter = progress.Reporter("main", "main", self.state, auto_start=False)
            reporter.update("work", 3, 10)
            reads.reset_mock()
            result = progress.dashboard_snapshot(self.state, self.cache, {})
            self.assertEqual(reads.call_count, 1)
        self.assertEqual(result["tasks"][0]["done"], 3)
        self.assertEqual(len(progress.snapshot(self.state, files=self.cache)[0]["stages"]), 2)

    def test_external_cache_does_not_mutate_source_and_lost_source_stays_an_error(self):
        source = self.state / "source.json"
        value = {"done": 2, "total": 4, "status": "running", "stage": "copy", "updated_ts": progress.time.time()}
        progress.atomic(source, value)
        progress.atomic(self.state / "外部来源.json", {"external": {"path": str(source), "title": "external"}})
        result = progress.dashboard_snapshot(self.state, self.cache, {})
        self.assertIn("external", {row["task_id"] for row in result["tasks"]})
        self.assertEqual(self.cache.read(source), value)
        source.unlink()
        result = progress.dashboard_snapshot(self.state, self.cache, {})
        self.assertEqual(next(row for row in result["tasks"] if row["task_id"] == "external")["status"], "error")


if __name__ == "__main__":
    unittest.main()
