from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import example_worker as demo
from task_progress import Reporter, read
from worker_helpers import VerificationError


class ExampleWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="demo-test-", dir=SCRIPTS.parent.parent)
        root = Path(self.temp.name)
        self.args = SimpleNamespace(work_dir=root/"demo",state_dir=root/"state",task_id="test-demo",resume=False)
        self.parser = SimpleNamespace(error=lambda message: self.fail(message))
        self.reporters = patch.object(demo, "Reporter", side_effect=lambda *args, **kwargs: Reporter(*args, **kwargs, auto_start=False))
        self.reporters.start()

    def tearDown(self):
        self.reporters.stop()
        self.temp.cleanup()

    def test_successful_resume_does_not_call_copy_again(self):
        demo.run(self.args,self.parser)
        self.args.resume=True
        with patch.object(demo.shutil,"copy2",side_effect=AssertionError("verified copy must not repeat")):
            demo.run(self.args,self.parser)
            demo.run(self.args,self.parser)
        row=read(self.args.state_dir/"任务/test-demo.json")
        self.assertEqual(row["status"],"complete")
        self.assertEqual(len(read(self.args.work_dir/"manifest.json")),5)

    def test_partial_failure_resumes_only_remaining_files(self):
        original=demo.shutil.copy2
        copied=[]
        def fail_third(source,destination):
            if len(copied)==2:
                raise PermissionError("permanent failure")
            copied.append(source.name)
            return original(source,destination)
        with patch.object(demo.shutil,"copy2",side_effect=fail_third),self.assertRaises(PermissionError):
            demo.run(self.args,self.parser)
        row=read(self.args.state_dir/"任务/test-demo.json")
        self.assertEqual(row["status"],"failed")
        self.assertEqual(row["done"],2)
        self.args.resume=True
        with patch.object(demo.shutil,"copy2",wraps=original) as copies:
            demo.run(self.args,self.parser)
        self.assertEqual(copies.call_count,3)
        self.assertEqual(read(self.args.state_dir/"任务/test-demo.json")["status"],"complete")

    def test_corrupt_completed_copy_fails_without_false_completion(self):
        demo.run(self.args,self.parser)
        (self.args.work_dir/"copied/sample-0.bin").write_bytes(b"corrupt")
        self.args.resume=True
        with self.assertRaises(VerificationError):
            demo.run(self.args,self.parser)
        row=read(self.args.state_dir/"任务/test-demo.json")
        self.assertEqual(row["status"],"failed")
        self.assertIsNone(row["eta_seconds"])


if __name__=="__main__":
    unittest.main()
