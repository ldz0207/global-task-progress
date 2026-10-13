from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from codex_names import TaskConversations
import task_progress as tp

FIRST = "12345678-1234-1234-1234-123456789abc"
SECOND = "12345678-1234-1234-1234-123456789def"


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.db = self.home / "state_5.sqlite"
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("CREATE TABLE threads(id TEXT PRIMARY KEY,name TEXT,title TEXT)")
            db.execute("INSERT INTO threads VALUES(?,?,?)", (FIRST, "原名称", "首次消息"))
            db.commit()
        self.time = 0
        self.cache = TaskConversations(self.home, clock=lambda: self.time)

    def tearDown(self):
        self.temp.cleanup()

    def rename(self, name):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE threads SET name=? WHERE id=?", (name, FIRST))
            db.commit()

    def test_rename_refresh_and_single_query_per_interval(self):
        row = {"task_id": "job", "codex_thread_id": FIRST, "done": 2, "updated_ts": 17}
        with patch.object(self.cache, "_read", wraps=self.cache._read) as read:
            self.assertEqual(self.cache.enrich([row])[0]["codex_conversation"]["name"], "原名称")
            self.rename("用户新名称")
            self.time = 9
            self.assertEqual(self.cache.enrich([row])[0]["codex_conversation"]["name"], "原名称")
            self.time = 10
            result = self.cache.enrich([row])[0]
            self.assertEqual(result["codex_conversation"]["name"], "用户新名称")
            self.assertEqual(read.call_count, 2)
        self.assertEqual(row, {"task_id": "job", "codex_thread_id": FIRST, "done": 2, "updated_ts": 17})
        self.assertEqual(result["done"], 2)
        self.assertEqual(result["updated_ts"], 17)

    def test_unique_prefix_and_ambiguity(self):
        task = {"task_id": "job-12345678"}
        self.assertEqual(self.cache.enrich([task])[0]["codex_conversation"]["id"], FIRST)
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("INSERT INTO threads VALUES(?,?,?)", (SECOND, "第二个", ""))
            db.commit()
        self.time = 10
        self.assertEqual(self.cache.enrich([task])[0]["codex_conversation"]["status"], "unlinked")

    def test_explicit_id_wins_over_prefix_and_title(self):
        result = self.cache.enrich([{"task_id": "job-ffffffff", "title": "原名称", "codex_thread_id": FIRST}])[0]
        self.assertEqual(result["codex_conversation"]["id"], FIRST)
        self.assertEqual(self.cache.enrich([{"task_id": "unrelated", "title": "原名称"}])[0]["codex_conversation"]["status"], "unlinked")

    def test_missing_database_keeps_progress_and_marks_last_name_stale(self):
        row = {"task_id": "job", "codex_thread_id": FIRST, "done": 2}
        self.cache.enrich([row])
        self.time = 10
        with patch.object(self.cache, "_read", side_effect=sqlite3.OperationalError("busy")):
            result = self.cache.enrich([row])[0]
        self.assertEqual(result["codex_conversation"]["status"], "stale")
        self.assertEqual(result["codex_conversation"]["name"], "原名称")
        self.assertEqual(result["done"], 2)
        fresh = TaskConversations(self.home / "missing").enrich([row])[0]
        self.assertEqual(fresh["codex_conversation"]["id"], FIRST)
        self.assertFalse((self.home / "missing").exists())

    def test_new_binding_refreshes_and_removed_names_are_evicted(self):
        self.cache.enrich([{"task_id": "job", "codex_thread_id": FIRST}])
        with patch.object(self.cache, "_read", wraps=self.cache._read) as read:
            self.cache.enrich([])
            read.assert_not_called()
        self.assertEqual(self.cache.names, {})
        self.assertEqual(self.cache.enrich([{"task_id": "new", "codex_thread_id": FIRST}])[0]["codex_conversation"]["name"], "原名称")

    def test_invalid_binding_does_not_break_page(self):
        self.assertEqual(self.cache.enrich([{"task_id": "job", "codex_thread_id": "invalid"}])[0]["codex_conversation"]["status"], "unlinked")

    def test_reporter_captures_environment_and_preserves_existing_binding(self):
        with patch.dict(os.environ, {"CODEX_THREAD_ID": FIRST}):
            r = tp.Reporter("job", "任务", self.home, auto_start=False)
        r.update("工作", 1, 3)
        self.assertEqual(tp.read(r.path)["codex_thread_id"], FIRST)
        tp.Reporter("job", "任务", self.home, auto_start=False, codex_thread_id=SECOND).update("工作", 2, 3)
        self.assertEqual(tp.read(r.path)["codex_thread_id"], FIRST)
        with patch.dict(os.environ, {"CODEX_THREAD_ID": FIRST}):
            r = tp.Reporter("global", "全局任务", self.home, auto_start=False, codex_thread_id="")
            r.update("工作", 0, None)
        self.assertNotIn("codex_thread_id", tp.read(r.path))

    def test_external_registration_captures_binding(self):
        external = self.home / "external.json"
        external.write_text(json.dumps({"done": 1, "total": 2}), encoding="utf-8")
        with patch.object(tp, "ensure"), patch.dict(os.environ, {"CODEX_THREAD_ID": FIRST}):
            tp.register_source("external", "外部任务", external, self.home)
        self.assertEqual(tp.snapshot(self.home)[0]["codex_thread_id"], FIRST)
        external.unlink()
        missing = tp.snapshot(self.home)[0]
        self.assertEqual(missing["status"], "error")
        self.assertEqual(missing["codex_thread_id"], FIRST)


if __name__ == "__main__":
    unittest.main()
