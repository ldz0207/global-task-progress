# 接入与恢复

## 接入已有服务

先读取 `http://127.0.0.1:8790/api/health`，确认 `identity=agent-global-progress-v1` 和 `state_dir`。新 Reporter 的 `state` 必须与该目录一致。已有同身份的服务会被复用；占用冲突直接报错。服务只绑定 `127.0.0.1`，没有远程写入或执行业务的接口。

`Reporter` 写入 `<state>/任务/<task_id>.json`，使用临时文件加原子替换。任务 ID 只用英数字、`-`、`_`。不要让两个业务 worker 同时写同一任务。数据结构兼容 v1；整个任务状态与阶段完成状态分开记录。

```python
import sys
sys.path.insert(0, "/技能所在绝对路径/global-task-progress/scripts")
from task_progress import Reporter

r = Reporter("my-export", "批量导出", state="/已有服务的绝对数据路径")
r.update("导出", done=existing_count, total=actual_total, unit="份")
try:
    with r.pulse(seconds=10):
        # 实际工作成功后更新 done；不要重复执行已经核验完成的项。
        ...
except Exception as exc:
    r.stop("failed", str(exc))
    raise
# 完成所有必要验收后：
r.update("发布", done=1, total=1, status="complete", unit="项")
```

`update(stage, done, total, message='', status='running', unit='项')` 支持 `running/complete/paused/failed/cancelled`，立即写入；总量未知用 `None`。日常计数使用同签名的 `progress()`，默认每秒合并一次，降低频繁读写与序列化开销。`Reporter(..., flush_interval=1)` 可配置0至2秒；0表示不合并。

`stop(status, message)` 先刷新剩余计数，再保留阶段和真实完成量。`heartbeat()` 不递增完成量；`pulse()` 只包住仍在执行的业务代码，同时刷新缓冲计数，退出作用域刷新剩余量并停止线程。未使用 `pulse()` 的调用者须主动 `flush()`，避免最后一笔量留在内存中。崩溃可能丢失最多一个缓冲窗口的页面计数，实际恢复以业务检查点为准。

## 后台执行

让 worker 脱离网页生命周期。Windows 可用 `Start-Process -WindowStyle Hidden`，指定既有 Python、绝对脚本路径、D 盘工作目录和日志目录；进程创建返回不代表任务成功，必须核对新鲜进度、实际进程和工作结果。不要为查看进度另起业务服务，也不要另建随机端口。

演示 worker 仅创建一组小样例并执行复制、完整 SHA-256 校验和清单发布。初次运行目录必须不存在或为空，避免覆盖用户文件；后续用相同 ID、目录及 `--resume` 接续，重新核验本演示 SQLite 检查点后复用结果。它本身是同步脚本；由既有后台启动方式运行后，网页关闭不影响它。

## 外部 JSON 来源

已有业务自己生成 JSON 时可注册其绝对文件路径：

```powershell
python scripts/task_progress.py register --task-id existing-job --title '已有批处理' --file 'D:/现有任务/progress.json'
```

来源应显式提供 `stage`、`status`、`done`、`total`、`unit`、`updated_ts`（Unix 秒）或带时区的 `updated_at`。可提供 `stages` 字典、`speed`（单位/秒）和 `eta_seconds`。缺少更新时间使用文件修改时间；不得把每次读取时间当作 worker 心跳。没有明确速度时等待测量，不用累计历史完成量推算恢复后的速度。相同 ID 若已有本地记录，不允许再注册来源造成冲突。

## 暂停与恢复

立即调用 `stop('paused', ...)`，异常用 `failed`，取消用 `cancelled`。恢复同 ID、同阶段和真实检查点计数，保留完成的其他阶段；恢复时重置速度采样，不让停机时间或历史完成量抬高速率。普通计数倒退会被拒绝。业务明确需要再次执行某阶段时，使用 `begin_stage_attempt(stage, done, total, reason='具体原因', unit='项')`：沿用任务 ID，把该阶段旧记录保存到 `attempts`，重置此阶段采样和计数，其他阶段保留。这个操作必须有业务依据，不能用于掩盖未通过的验证。

服务超过 90 秒未收到 worker 更新时显示 `attention` 并清除速度/ETA；这只表示需要核对，不能据此判断进程一定退出。心跳仍在但 60 秒内没有完成增量时，速率为 0，ETA 停止估计。总量未知时不显示百分比或 ETA。不同计数单位的阶段不相加成虚构总进度。

## 验收清单

1. `/api/health` 指向既有唯一服务和目录。
2. `/api/tasks` 包含同一稳定 ID、实际计数、状态、新鲜时间及独立阶段。
3. 页面默认每 2 秒刷新；右上角可输入 1–300 秒并「应用」，只改变网页读取频率。历史默认折叠；当前任务可「收起详情」只看一条主进度，再「展开详情」恢复原来的阶段开合。手动展开或收起阶段后跨多个刷新、置顶、排序和精简切换仍保持选择。刷新间隔、精简模式、置顶和排序偏好在重开页面后仍保留，仅影响本浏览器内的查看方式。
4. 暂停、异常、陈旧、无实测速率时无旧 ETA；连接失败隐藏旧数字并重试。自定义长刷新间隔时，页面每秒仅在本地检查陈旧状态，记录超过 90 秒仍停止旧速度/ETA；此检查不读取 API、不调用 PowerShell/CMD。
5. 关闭页面后核对 worker 持续完成；重新打开固定入口可查看后续进度。
6. 整体完成必须有全部业务验收和交付物证据。进度上报不能替代内容校验。
