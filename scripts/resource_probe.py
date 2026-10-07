"""Read-only Windows process memory/CPU sampling; no shell polling or dependencies."""
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time


class MemoryCounters(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
        (name, ctypes.c_size_t) for name in (
            "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
            "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage", "PrivateUsage",
        )
    ]


class ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def process_rows(kernel):
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for name in ("Process32FirstW", "Process32NextW"):
        call = getattr(kernel, name)
        call.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
        call.restype = wintypes.BOOL
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    rows = []
    try:
        entry = ProcessEntry(dwSize=ctypes.sizeof(ProcessEntry))
        valid = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while valid:
            rows.append({"pid": entry.th32ProcessID, "parent_pid": entry.th32ParentProcessID, "name": entry.szExeFile})
            valid = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    return rows


def sample_process(pid, seconds=10):
    if os.name != "nt":
        raise RuntimeError("此资源采样脚本只适用于 Windows")
    if not 1 <= seconds <= 60:
        raise ValueError("采样时长必须为1至60秒")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(MemoryCounters), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x0410, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())

    def cpu_seconds():
        values = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(item) for item in values)):
            raise ctypes.WinError(ctypes.get_last_error())
        return sum((item.dwHighDateTime << 32) | item.dwLowDateTime for item in values[2:]) / 10_000_000

    samples = []
    descendants = {}
    start = time.monotonic()
    first_cpu = cpu_seconds()
    try:
        while True:
            memory = MemoryCounters(cb=ctypes.sizeof(MemoryCounters))
            if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
                raise ctypes.WinError(ctypes.get_last_error())
            samples.append({"elapsed_seconds": round(time.monotonic()-start, 3), "working_set_bytes": memory.WorkingSetSize, "private_commit_bytes": memory.PrivateUsage})
            rows = process_rows(kernel)
            family = {pid}
            changed = True
            while changed:
                changed = False
                for row in rows:
                    if row["parent_pid"] in family and row["pid"] not in family:
                        family.add(row["pid"])
                        descendants[row["pid"]] = row
                        changed = True
            if time.monotonic()-start >= seconds:
                break
            time.sleep(max(0, min(1, seconds-(time.monotonic()-start))))
        elapsed = time.monotonic()-start
        cpu = max(0, cpu_seconds()-first_cpu)
    finally:
        kernel.CloseHandle(handle)
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(), "pid": pid,
        "duration_seconds": round(elapsed, 3), "samples": samples,
        "working_set_mib_min": round(min(s["working_set_bytes"] for s in samples)/1048576, 2),
        "working_set_mib_max": round(max(s["working_set_bytes"] for s in samples)/1048576, 2),
        "private_commit_mib_max": round(max(s["private_commit_bytes"] for s in samples)/1048576, 2),
        "cpu_seconds": round(cpu, 4), "cpu_percent_of_one_core": round(cpu/elapsed*100, 3),
        "observed_descendants": list(descendants.values()),
        "limitations": "One process only; excludes browser and business workers. Periodic sampling cannot prove no short-lived child ever existed. Working set and private commit are different metrics.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--seconds", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = sample_process(args.pid, args.seconds)
    if args.output:
        if not args.output.is_absolute():
            parser.error("输出位置必须是绝对路径")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "samples"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
