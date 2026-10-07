"""A real, resumable copy/verification demo; no shell loop or extra services."""
import argparse
import hashlib
from pathlib import Path
import shutil
from task_progress import DEFAULT, Reporter, atomic, read, task_id_check
from worker_helpers import CheckpointStore, RetryPolicy, VerificationError, WorkerBusy, retry_call, worker_guard


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT)
    parser.add_argument("--task-id", default="progress-example")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    task_id_check(args.task_id)
    if not args.work_dir.is_absolute():
        parser.error("演示目录必须为绝对路径")
    try:
        with worker_guard(args.state_dir / "锁" / (args.task_id + "-worker.lock")):
            run(args, parser)
    except WorkerBusy as error:
        parser.exit(2, str(error) + "\n")


def run(args, parser):
    root = args.work_dir
    if root.exists() and any(root.iterdir()) and not args.resume:
        parser.error("目录非空；接续本演示时显式使用 --resume，同一任务沿用原ID")
    if args.resume and not (root / "checkpoints.sqlite3").exists():
        parser.error("缺少本演示的检查点，不将任意非空目录当成可恢复任务")
    r = Reporter(args.task_id, "统一进度技能真实演示", args.state_dir)
    if args.resume:
        r.begin_stage_attempt("恢复核验", 0, 1, "接续核验", reason="重新核对接续条件", unit="项")
    else:
        r.update("准备样例", 0, 5, "准备新样例", unit="份")
    try:
        with r.pulse(), CheckpointStore(root / "checkpoints.sqlite3") as checkpoints:
            source = root / "source"
            destination = root / "copied"
            source.mkdir(exist_ok=True)
            destination.mkdir(exist_ok=True)
            if not args.resume:
                for index in range(5):
                    (source / f"sample-{index}.bin").write_bytes((f"progress-demo-{index}\n".encode()) * 32768)
                    r.progress("准备样例", index + 1, 5, unit="份")
            originals = [source / f"sample-{index}.bin" for index in range(5)]
            if not all(path.is_file() for path in originals):
                raise VerificationError("样例不完整，保留原目录以便核对")
            if args.resume:
                r.update("恢复核验", 1, 1, unit="项")
            r.update("准备样例", 5, 5, unit="份")

            def valid_receipt(receipt):
                original, copied = Path(receipt["source"]), Path(receipt["copied"])
                return original.is_file() and copied.is_file() and digest(original) == receipt["sha256"] == digest(copied)

            def copy_verified(original):
                copied = destination / original.name
                shutil.copy2(original, copied)
                return {"source": str(original), "copied": str(copied), "sha256": digest(original)}

            for stage in ("复制", "完整SHA-256校验"):
                verified, missing = [], []
                for original in originals:
                    receipt = checkpoints.get(stage, original.name)
                    if receipt is not None and valid_receipt(receipt):
                        verified.append(receipt)
                    else:
                        missing.append(original)
                previous = read(r.path).get("stages", {}).get(stage, {}) if r.path.exists() else {}
                if len(verified) < previous.get("done", 0):
                    raise VerificationError("已有检查点验证失败，已报告完成量不再可信，需核对旧尝试")
                done = len(verified)
                r.update(stage, done, 5, "复用已重新核验的完成结果", unit="份")
                for original in missing:
                    def operation():
                        if stage == "复制":
                            return retry_call(lambda: copy_verified(original), retry_if=lambda error: isinstance(error, (ConnectionError, TimeoutError)), policy=RetryPolicy())
                        receipt = {"source": str(original), "copied": str(destination / original.name), "sha256": digest(original)}
                        if not valid_receipt(receipt):
                            raise VerificationError("完整哈希不一致：" + original.name)
                        return receipt
                    receipt, _ = checkpoints.run_once(stage, original.name, operation, valid_receipt)
                    verified.append(receipt)
                    done += 1
                    r.progress(stage, done, 5, unit="份")
            manifest = [{"file": Path(item["source"]).name, "sha256": item["sha256"]} for item in sorted(verified, key=lambda item: item["source"])]
            output = root / "manifest.json"
            existing = checkpoints.get("发布清单", "manifest")

            def publication_valid(receipt):
                return output.is_file() and read(output) == manifest and receipt.get("manifest_sha256") == digest(output)

            published = bool(existing is not None and publication_valid(existing))
            r.update("发布清单", int(published), 1, unit="项")

            def publish():
                atomic(output, manifest)
                return {"manifest_sha256": digest(output)}
            checkpoints.run_once("发布清单", "manifest", publish, publication_valid)
            r.update("发布清单", 1, 1, "复制、完整校验、检查点和清单回读均通过", status="complete", unit="项")
        print(output)
    except Exception as error:
        if r.path.exists():
            r.stop("failed", str(error))
        raise


if __name__ == "__main__":
    main()
