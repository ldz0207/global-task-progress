"""Small local worker helpers using standard-library locks, SQLite and threads."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import sqlite3
import threading
import time


class VerificationError(RuntimeError):
    pass


class WorkerBusy(RuntimeError):
    pass


class Cancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    initial_delay: float = 1
    max_delay: float = 10
    max_elapsed: float = 30

    def __post_init__(self):
        if isinstance(self.max_attempts, bool) or not isinstance(self.max_attempts, int) or self.max_attempts < 1:
            raise ValueError("max_attempts 必须是正整数")
        for value in (self.initial_delay, self.max_delay, self.max_elapsed):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError("重试延时和预算必须为有限非负数")
        if self.max_elapsed == 0:
            raise ValueError("重试时间预算必须大于0")


def retry_call(operation, *, retry_if, policy=RetryPolicy(), cancel=None, on_retry=None):
    """Retry only caller-approved safe operations; no new processes or blanket retries."""
    start = time.monotonic()
    for attempt in range(1, policy.max_attempts + 1):
        if cancel is not None and cancel.is_set():
            raise Cancelled("任务已取消")
        try:
            return operation()
        except Exception as error:
            remaining = policy.max_elapsed - (time.monotonic() - start)
            delay = min(policy.max_delay, policy.initial_delay * 2 ** (attempt - 1))
            if attempt == policy.max_attempts or not retry_if(error) or remaining <= delay:
                raise
            if on_retry:
                on_retry(attempt, delay, error)
            if cancel is not None:
                if cancel.wait(delay):
                    raise Cancelled("等待重试时任务已取消") from error
            else:
                time.sleep(delay)


@contextmanager
def worker_guard(path):
    """Hold an OS lock for one task/resource; crash releases it automatically."""
    path = Path(path)
    if not path.is_absolute():
        raise ValueError("worker 锁必须使用绝对路径")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise WorkerBusy("同一任务或资源已有 worker，未启动重复工作") from error
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


class CheckpointStore:
    """Disk-backed per-item evidence; do not load a whole batch into RAM."""
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_absolute() or str(self.path).startswith("\\\\"):
            raise ValueError("检查点必须使用本机绝对路径")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.lock = threading.RLock()
        self.db.execute("CREATE TABLE IF NOT EXISTS completed (stage TEXT, item_id TEXT, evidence TEXT NOT NULL, PRIMARY KEY(stage,item_id))")
        self.db.commit()

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def get(self, stage, item_id):
        with self.lock:
            row = self.db.execute("SELECT evidence FROM completed WHERE stage=? AND item_id=?", (stage, item_id)).fetchone()
            return json.loads(row[0]) if row else None

    def record(self, stage, item_id, evidence):
        raw = json.dumps(evidence, ensure_ascii=False, allow_nan=False)
        with self.lock, self.db:
            self.db.execute("INSERT INTO completed VALUES (?,?,?) ON CONFLICT(stage,item_id) DO UPDATE SET evidence=excluded.evidence", (stage, item_id, raw))

    def run_once(self, stage, item_id, operation, verify):
        """Use worker_guard for the owning task; recheck evidence before skipping."""
        existing = self.get(stage, item_id)
        if existing is not None and verify(existing):
            return existing, True
        evidence = operation()
        if not verify(evidence):
            raise VerificationError("工作结果未通过验证：" + str(item_id))
        self.record(stage, item_id, evidence)
        return evidence, False


def bounded_map(operation, items, *, max_workers=1, max_pending=None):
    """Stream results with a bounded number of futures, including completed ones."""
    if isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers < 1:
        raise ValueError("max_workers 必须是正整数")
    max_pending = max_workers * 2 if max_pending is None else max_pending
    if isinstance(max_pending, bool) or not isinstance(max_pending, int) or max_pending < max_workers:
        raise ValueError("max_pending 必须不小于 max_workers")
    source = iter(items)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        pending = set()

        def fill():
            while len(pending) < max_pending:
                try:
                    item = next(source)
                except StopIteration:
                    break
                pending.add(pool.submit(operation, item))

        fill()
        try:
            while pending:
                ready, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in ready:
                    pending.remove(future)
                    yield future.result()
                fill()
        finally:
            for future in pending:
                future.cancel()
