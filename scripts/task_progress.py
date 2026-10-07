"""Unified local progress, v1-compatible; Python standard library only."""
import argparse
import contextlib
import copy
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8790
IDENTITY = "agent-global-progress-v1"
DEFAULT = Path(os.environ.get("TASK_PROGRESS_STATE_DIR", "D:/Codex/维护/统一任务进度/运行数据"))
STALE_SECONDS = 90
RATE_WINDOW = 60
STATUSES = {"running", "complete", "paused", "failed", "cancelled"}
HALTED = {"paused", "failed", "cancelled", "attention", "error", "idle"}


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def counts(done, total):
    if not numeric(done) or done < 0:
        raise ValueError("done 必须为有限的非负数")
    if total is not None and (not numeric(total) or total < done):
        raise ValueError("total 必须不小于 done；未知总量使用 None")


def task_id_check(task_id):
    if not task_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in task_id):
        raise ValueError("task_id 只允许英数字、- 和 _")


def state_path(state):
    state = Path(state)
    if not state.is_absolute():
        raise ValueError("state 必须是绝对路径；其他系统请显式指定数据目录")
    if os.name == "nt" and (not state.anchor or not Path(state.anchor).exists()):
        raise RuntimeError("数据目录所在磁盘不可用；不自动迁移到其他磁盘")
    return state.resolve()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".part")
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(6):
            try:
                os.replace(temp, path)
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.1 * (attempt + 1))
    finally:
        if temp.exists():
            temp.unlink()


@contextlib.contextmanager
def file_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0)
        stream.write(b"0")
        stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def port_value(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("端口必须是1至65535的整数")
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError("端口必须在1至65535之间")
    return port


def resolve_port(state=DEFAULT, port=None):
    if port is not None:
        return port_value(port)
    if os.environ.get("TASK_PROGRESS_PORT"):
        return port_value(os.environ["TASK_PROGRESS_PORT"])
    state = Path(state)
    config = state / "服务配置.json"
    if config.exists():
        value = read(config)
        if value.get("identity") != IDENTITY:
            raise ValueError("服务配置身份不匹配，请核对配置")
        return port_value(value.get("port"))
    previous = state / "服务状态.json"
    if previous.exists():
        value = read(previous)
        if value.get("identity") == IDENTITY:
            return port_value(value.get("port", PORT))
    return PORT


def service_url(port):
    return f"http://127.0.0.1:{port_value(port)}/"


def allowed_hosts(port):
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    if port == 80:
        hosts.update({"127.0.0.1", "localhost"})
    return hosts


def port_available(port):
    try:
        with socket.socket() as probe:
            if os.name == "nt":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(("127.0.0.1", port_value(port)))
        return True
    except OSError:
        return False


def free_ports(start=PORT, count=5):
    start = port_value(start)
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 20:
        raise ValueError("候选数量必须在1至20之间")
    available = []
    for candidate in range(start, min(65536, start + 128)):
        if port_available(candidate):
            available.append(candidate)
            if len(available) == count:
                break
    return available


def health(state, port=None):
    port = resolve_port(state, port)
    with urllib.request.urlopen(service_url(port) + "api/health", timeout=2) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise ValueError("所选端口返回的健康状态格式无效")
    if value.get("identity") != IDENTITY:
        raise RuntimeError("所选端口由其他程序占用，请选择空闲端口")
    if not value.get("state_dir") or state_path(value["state_dir"]) != state_path(state):
        raise RuntimeError("所选端口已使用另一数据目录，不创建第二套进度")
    if value.get("port") is not None and value["port"] != port:
        raise RuntimeError("服务响应端口不匹配")
    value["url"] = service_url(port)
    return value


def inspect_port(state=DEFAULT, port=None):
    port = resolve_port(state, port)
    try:
        value = health(state, port)
        return {"ok": True, "status": "reuse", "port": port, "url": service_url(port), "pid": value.get("pid")}
    except urllib.error.HTTPError as error:
        reason = str(error)
    except (ValueError, TypeError, RuntimeError) as error:
        reason = str(error)
    except (urllib.error.URLError, OSError) as error:
        if port_available(port):
            return {"ok": True, "status": "available", "port": port, "url": service_url(port)}
        reason = str(error)
    return {"ok": False, "status": "conflict", "port": port, "url": service_url(port), "error": reason, "available_ports": free_ports()}


def active_service_port(state):
    record = Path(state) / "服务状态.json"
    if not record.exists():
        return None
    try:
        value = read(record)
        if value.get("identity") == IDENTITY:
            port = port_value(value.get("port", PORT))
            health(state, port)
            return port
    except (urllib.error.URLError, OSError, ValueError, RuntimeError):
        pass
    return None


def guard_port_change(state, port):
    active = active_service_port(state)
    if active is not None and active != port:
        raise RuntimeError(f"已有进度服务正在 {service_url(active)} 运行；继续复用，或明确停止旧服务后再切换端口")


def save_port(state, port):
    path = Path(state) / "服务配置.json"
    previous = read(path) if path.exists() else {}
    if not isinstance(previous, dict) or previous.get("identity", IDENTITY) != IDENTITY:
        raise ValueError("服务配置格式或身份不匹配，请先核对")
    value = {**previous, "identity": IDENTITY, "port": port_value(port)}
    if previous != value:
        atomic(path, value)


def configure_port(state=DEFAULT, port=None):
    state = state_path(state)
    port = port_value(port)
    with file_lock(state / "启动.lock"):
        guard_port_change(state, port)
        report = inspect_port(state, port)
        if not report["ok"]:
            raise RuntimeError(f"端口 {port} 不可用；可选空闲端口：{report['available_ports']}")
        save_port(state, port)
        return report


def ensure(state=DEFAULT, port=None):
    state = state_path(state)
    with file_lock(state / "启动.lock"):
        return _ensure(state, resolve_port(state, port))


def _ensure(state, port):
    guard_port_change(state, port)
    try:
        value = health(state, port)
        save_port(state, port)
        return value
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"所选端口被其他HTTP服务占用；空闲候选：{free_ports()}") from error
    except RuntimeError as error:
        raise RuntimeError(f"{error}；空闲候选：{free_ports()}") from error
    except urllib.error.URLError:
        pass
    except (ValueError, KeyError) as error:
        raise RuntimeError("所选端口返回非统一进度数据") from error
    if not port_available(port):
        raise RuntimeError(f"所选端口 {port} 不可用；空闲候选：{free_ports()}；由用户选择，不自动切换")
    state.mkdir(parents=True, exist_ok=True)
    flags = (subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS) if os.name == "nt" else 0
    with (state / "服务日志.txt").open("ab", buffering=0) as log:
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "serve", "--state-dir", str(state), "--port", str(port)],
            stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=flags,
            close_fds=True, start_new_session=os.name != "nt",
        )
    for _ in range(30):
        try:
            value = health(state, port)
            save_port(state, port)
            return value
        except urllib.error.URLError:
            time.sleep(0.2)
    raise RuntimeError("统一进度服务未启动，请检查所选端口与服务日志；不自动换端口")


def measured_rate(samples, stamp, done):
    samples = [list(item) for item in samples]
    if len(samples) > 1 and int(samples[-1][0]) == int(stamp):
        samples[-1] = [stamp, done]
    else:
        samples.append([stamp, done])
    cutoff = stamp - RATE_WINDOW
    while len(samples) > 1 and samples[1][0] <= cutoff:
        samples.pop(0)
    if samples and samples[0][0] < cutoff:
        samples[0][0] = cutoff
    if len(samples) > RATE_WINDOW + 2:
        samples = [samples[0]] + samples[-(RATE_WINDOW + 1):]
    elapsed = stamp - samples[0][0]
    rate = (done - samples[0][1]) / elapsed if elapsed >= 1 else None
    return samples, rate


class Reporter:
    def __init__(self, task_id, title, state=DEFAULT, *, auto_start=True, flush_interval=1, port=None):
        task_id_check(task_id)
        if not numeric(flush_interval) or not 0 <= flush_interval <= 2:
            raise ValueError("flush_interval 必须在0至2秒之间")
        self.state = state_path(state)
        self.port = resolve_port(self.state, port)
        self.url = service_url(self.port)
        self.task_id, self.title = task_id, title
        self.path = self.state / "任务" / (task_id + ".json")
        self.lock_path = self.state / "锁" / (task_id + ".lock")
        self.lock = threading.RLock()
        self.flush_interval = flush_interval
        self._pending = None
        self._last_written = None
        self._last_flush = 0
        if auto_start:
            ensure(self.state, self.port)

    def update(self, stage, done, total, message="", status="running", unit="项", *, restart_reason=None):
        """Immediately publish a stage/status change, preserving pending counts."""
        with self.lock:
            if restart_reason:
                self.flush()
            if self._pending:
                pending = self._pending
                if pending[0] != stage:
                    self.flush()
                elif done < pending[1]:
                    raise ValueError("完成量不能小于尚未刷新的实际完成量")
            self._write(stage, done, total, message, status, unit, restart_reason=restart_reason)
            self._pending = None
            self._last_written = (stage, done, total, status, unit)
            self._last_flush = time.monotonic()

    def begin_stage_attempt(self, stage, done, total, message="", *, reason, unit="项"):
        """Explicitly begin new stage work while retaining the previous attempt."""
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("新的阶段尝试必须说明原因")
        self.update(stage, done, total, message, unit=unit, restart_reason=reason)

    def progress(self, stage, done, total, message="", status="running", unit="项"):
        """Coalesce routine counters; use pulse() to flush during long operations."""
        counts(done, total)
        if status not in STATUSES or not stage or not unit:
            raise ValueError("状态、阶段或计数单位无效")
        with self.lock:
            previous = self._pending
            if previous and previous[0] == stage and done < previous[1]:
                raise ValueError("缓冲完成量不能倒退")
            metadata = self._last_written
            boundary = (
                metadata is None or status != "running" or
                (stage, total, status, unit) != (metadata[0], metadata[2], metadata[3], metadata[4]) or
                total is not None and done == total
            )
            if metadata and metadata[0] == stage and done < metadata[1]:
                raise ValueError("完成量不能倒退")
            if boundary or time.monotonic() - self._last_flush >= self.flush_interval:
                self.update(stage, done, total, message, status, unit)
                return True
            self._pending = (stage, done, total, message, status, unit)
            return False

    def flush(self):
        with self.lock:
            if self._pending:
                self.update(*self._pending)
                return True
            return False

    def _write(self, stage, done, total, message="", status="running", unit="项", *, restart_reason=None):
        counts(done, total)
        if status not in STATUSES or not stage or not unit:
            raise ValueError("状态、阶段或计数单位无效")
        if status == "complete" and (total is None or done != total):
            raise ValueError("完成必须有可核实的当前阶段全部完成量")
        with self.lock, file_lock(self.lock_path):
            stamp = time.time()
            value = read(self.path) if self.path.exists() else {
                "task_id": self.task_id, "started_ts": stamp, "stages": {}, "attempts": [],
            }
            stages = value.setdefault("stages", {})
            previous = copy.deepcopy(stages.get(stage, {}))
            if restart_reason and previous:
                previous.pop("_samples", None)
                value.setdefault("attempts", []).append({**previous, "reason": restart_reason, "superseded_at": now()})
                previous = {}
            if status == "complete" and any(p.get("status") != "complete" for name, p in stages.items() if name != stage):
                raise ValueError("其他阶段尚未完成，不能将整体标记完成")
            if previous and done < previous.get("done", 0):
                raise ValueError("计数不能静默倒退；核对检查点并保留旧尝试记录")
            if previous and previous.get("unit", unit) != unit:
                raise ValueError("同一阶段的计数单位不能改变")
            interrupted = value.get("status") in HALTED or stamp - value.get("updated_ts", stamp) > STALE_SECONDS
            resume = status == "running" and interrupted
            if resume:
                value.setdefault("attempts", []).append({
                    "status": value.get("status"), "stage": value.get("stage"),
                    "done": value.get("done"), "total": value.get("total"),
                    "updated_at": value.get("updated_at"), "message": value.get("message", ""),
                })
            samples = [] if resume else previous.get("_samples", [])
            samples, rate = measured_rate(samples, stamp, done)
            remaining = None if total is None else total - done
            eta = remaining / rate if remaining is not None and rate and rate > 0 else None
            basis = "最近60秒实际完成量增量" if rate is not None else "等待实际完成量增量测量"
            if status in HALTED:
                rate, eta, basis = None, None, "任务已暂停或停止，停止估计"
            phase_complete = total is not None and done == total
            if phase_complete and status not in HALTED:
                eta = 0
            phase = {
                "stage": stage, "done": done, "total": total, "unit": unit,
                "started_ts": stamp if resume else previous.get("started_ts", stamp),
                "status": "complete" if phase_complete and status not in HALTED else status,
                "speed": rate, "speed_basis": basis, "eta_seconds": eta,
                "_samples": [] if phase_complete or status in HALTED else samples,
            }
            stages[stage] = phase
            value.update(
                title=self.title, stage=stage, done=done, total=total, remaining=remaining,
                percent=None if total is None else (100 if total == 0 else round(100 * done / total, 1)),
                status=status, unit=unit, speed=rate, speed_basis=basis, eta_seconds=eta,
                eta_basis="仅估计当前阶段，按近期实际增量更新", message=message,
                updated_ts=stamp, updated_at=now(), pid=os.getpid(),
            )
            atomic(self.path, value)

    def stop(self, status, message=""):
        if status not in {"paused", "failed", "cancelled"}:
            raise ValueError("stop 仅接受 paused/failed/cancelled")
        with self.lock:
            self.flush()
            value = read(self.path)
            self.update(value["stage"], value["done"], value["total"], message, status, value["unit"])

    def heartbeat(self):
        with self.lock:
            self.flush()
            if not self.path.exists():
                return
            value = read(self.path)
            if value.get("status") == "running":
                self.update(value["stage"], value["done"], value["total"], value.get("message", ""), unit=value["unit"])

    @contextlib.contextmanager
    def pulse(self, seconds=10):
        if not numeric(seconds) or not 0 < seconds < STALE_SECONDS:
            raise ValueError("心跳间隔必须大于0且小于90秒")
        stop = threading.Event()
        errors = []

        def loop():
            last_heartbeat = time.monotonic()
            interval = min(seconds, self.flush_interval or seconds)
            try:
                while not stop.wait(interval):
                    self.flush()
                    if time.monotonic() - last_heartbeat >= seconds:
                        self.heartbeat()
                        last_heartbeat = time.monotonic()
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=loop, daemon=True)
        thread.start()
        try:
            yield self
        finally:
            stop.set()
            thread.join()
            self.flush()
        if errors:
            raise RuntimeError("进度心跳写入失败") from errors[0]


def register_source(task_id, title, path, state=DEFAULT, *, port=None):
    task_id_check(task_id)
    state = state_path(state)
    path = Path(path)
    if not path.is_absolute():
        raise ValueError("外部 JSON 必须使用绝对路径")
    if (state / "任务" / (task_id + ".json")).exists():
        raise ValueError("相同 ID 已有本地记录，不能同时注册第二个写入来源")
    with file_lock(state / "注册.lock"):
        target = state / "外部来源.json"
        value = read(target) if target.exists() else {}
        value[task_id] = {"task_id": task_id, "title": title, "path": str(path)}
        atomic(target, value)
    ensure(state, port)


def normalized(value, stamp, fallback_ts=None):
    value = copy.deepcopy(value)
    counts(value.get("done"), value.get("total"))
    ts = value.get("updated_ts")
    if ts is None and value.get("updated_at"):
        parsed = datetime.fromisoformat(value["updated_at"].replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("更新时间缺少时区")
        ts = parsed.timestamp()
    ts = ts if numeric(ts) else fallback_ts
    value["updated_ts"] = ts
    value.setdefault("updated_at", datetime.fromtimestamp(ts, timezone(timedelta(hours=8))).isoformat() if ts else None)
    status = value.get("status", "attention")
    stale = status == "running" and (not numeric(ts) or stamp - ts > STALE_SECONDS or ts > stamp + 5)
    if stale:
        value.update(status="attention", message=(value.get("message") or "") + "；更新时间无效或超过90秒，需核对任务进程。")
    elif status not in STATUSES | HALTED:
        value["status"] = "attention"
    halted = value.get("status") in HALTED
    rate = value.get("speed")
    if halted or not numeric(rate) or rate < 0:
        value["speed"] = None
        value["eta_seconds"] = None
    elif rate == 0:
        value["eta_seconds"] = None
    if value.get("total") is None:
        value.update(remaining=None, percent=None, eta_seconds=None)
    eta = value.get("eta_seconds")
    if eta is not None and (not numeric(eta) or eta < 0):
        value["eta_seconds"] = None
    phases = value.get("stages", {})
    if isinstance(phases, list):
        phases = {p.get("stage", str(i)): p for i, p in enumerate(phases)}
    for phase in phases.values():
        phase.pop("_samples", None)
        if halted and phase.get("status") not in {"complete", "failed", "cancelled"}:
            phase.update(status=value["status"], speed=None, eta_seconds=None)
    value["stages"] = phases
    return value


def snapshot(state):
    state, stamp = Path(state), time.time()
    rows = {}
    for path in (state / "任务").glob("*.json"):
        try:
            rows[path.stem] = normalized(read(path), stamp)
        except Exception as error:
            rows[path.stem] = {"task_id": path.stem, "title": path.stem, "status": "error", "message": str(error), "done": None, "total": None, "speed": None, "eta_seconds": None}
    sources = read(state / "外部来源.json") if (state / "外部来源.json").exists() else {}
    for task_id, source in sources.items():
        if task_id in rows:
            rows[task_id].update(status="error", speed=None, eta_seconds=None, message="相同任务 ID 有两个来源，请核对写入者")
            continue
        try:
            path = Path(source["path"])
            value = read(path)
            value.update(task_id=task_id, title=source["title"], external=True)
            rows[task_id] = normalized(value, stamp, path.stat().st_mtime)
        except Exception as error:
            rows[task_id] = {"task_id": task_id, "title": source["title"], "status": "error", "message": "外部来源无法读取：" + str(error), "done": None, "total": None, "speed": None, "eta_seconds": None}
    return sorted(rows.values(), key=lambda row: (row.get("status") in {"complete", "failed", "cancelled", "idle"}, -float(row.get("updated_ts") or 0)))


def serve(state, port=None):
    state = state_path(state)
    port = resolve_port(state, port)
    guard_port_change(state, port)
    state.mkdir(parents=True, exist_ok=True)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.headers.get("Host") not in allowed_hosts(port):
                self.send_error(403)
                return
            if self.path == "/":
                raw = Path(__file__).with_name("progress_page.html").read_bytes()
                content_type = "text/html; charset=utf-8"
            elif self.path == "/api/health":
                raw = json.dumps({"identity": IDENTITY, "port": port, "url": service_url(port), "pid": os.getpid(), "state_dir": str(state)}).encode()
                content_type = "application/json"
            elif self.path == "/api/tasks":
                try:
                    value = {"tasks": snapshot(state), "observed_at": now(), "updated_at": now()}
                    raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
                except Exception:
                    self.send_error(503, "Cannot read progress sources")
                    return
                content_type = "application/json; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler, bind_and_activate=False)
    try:
        if os.name == "nt":
            server.allow_reuse_address = False
            server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        server.server_bind()
        server.server_activate()
    except Exception:
        server.server_close()
        raise
    save_port(state, port)
    atomic(state / "服务状态.json", {"identity": IDENTITY, "port": port, "pid": os.getpid(), "script": str(Path(__file__).resolve()), "started_at": now()})
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["ensure", "serve", "register", "ports", "configure"])
    parser.add_argument("--state-dir", type=Path, default=DEFAULT)
    parser.add_argument("--port", type=port_value)
    parser.add_argument("--scan-start", type=port_value, default=PORT)
    parser.add_argument("--task-id")
    parser.add_argument("--title")
    parser.add_argument("--file", type=Path)
    args = parser.parse_args()
    if args.command == "serve":
        serve(args.state_dir, args.port)
    elif args.command == "ensure":
        result = ensure(args.state_dir, args.port)
        print(result["url"])
    elif args.command == "ports":
        print(json.dumps({"selected": inspect_port(args.state_dir, args.port), "active_port": active_service_port(args.state_dir), "available_ports": free_ports(args.scan_start)}, ensure_ascii=False, indent=2))
    elif args.command == "configure":
        if args.port is None:
            parser.error("configure 需要 --port，由用户选择端口")
        print(json.dumps(configure_port(args.state_dir, args.port), ensure_ascii=False, indent=2))
    else:
        if not all([args.task_id, args.title, args.file]):
            parser.error("register 需要 --task-id、--title 和 --file")
        register_source(args.task_id, args.title, args.file, args.state_dir, port=args.port)


if __name__ == "__main__":
    main()
