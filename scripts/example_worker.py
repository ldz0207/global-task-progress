"""Create a small new demo, copy, SHA-256 verify and publish a manifest."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time
from task_progress import DEFAULT, Reporter


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
    args = parser.parse_args()
    root = args.work_dir
    if not root.is_absolute() or root.exists() and any(root.iterdir()):
        parser.error("演示目录必须为绝对路径且不存在或为空")
    r = Reporter(args.task_id, "统一进度技能真实演示", args.state_dir)
    r.update("准备样例", 0, 5, "仅写入新的演示目录", unit="份")
    try:
        with r.pulse():
            (root / "source").mkdir(parents=True, exist_ok=True)
            (root / "copied").mkdir()
            originals = []
            for index in range(5):
                path = root / "source" / f"sample-{index}.bin"
                path.write_bytes((f"progress-demo-{index}\n".encode()) * 32768)
                originals.append(path)
                r.update("准备样例", index + 1, 5, unit="份")
            r.update("复制", 0, 5, unit="份")
            for index, path in enumerate(originals, 1):
                shutil.copy2(path, root / "copied" / path.name)
                r.update("复制", index, 5, unit="份")
                time.sleep(0.3)
            r.update("完整SHA-256校验", 0, 5, unit="份")
            manifest = []
            for index, path in enumerate(originals, 1):
                source_hash = digest(path)
                if source_hash != digest(root / "copied" / path.name):
                    raise RuntimeError("完整哈希校验不一致：" + path.name)
                manifest.append({"file": path.name, "sha256": source_hash})
                r.update("完整SHA-256校验", index, 5, unit="份")
            r.update("发布清单", 0, 1, unit="项")
            output = root / "manifest.json"
            output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            if json.loads(output.read_text(encoding="utf-8")) != manifest:
                raise RuntimeError("发布清单回读失败")
            r.update("发布清单", 1, 1, "复制、完整校验和清单回读均通过", status="complete", unit="项")
        print(output)
    except Exception as error:
        r.stop("failed", str(error))
        raise


if __name__ == "__main__":
    main()
