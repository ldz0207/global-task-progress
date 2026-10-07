# 接入与恢复

首次安装或依赖异常时，先执行 [环境与安装检测](environment.md)，沿用通过检查的 Python 绝对路径。缺失的标准库由完整 Python 提供；业务包使用业务项目原环境按实际缺项补齐。

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

## 进度跟进与业务验收

1. `/api/health` 指向既有唯一服务和目录。
2. `/api/tasks` 包含同一稳定 ID、实际计数、状态、新鲜时间及独立阶段。
3. 默认只读取底层数据跟进，按任务 ID 比对 worker 记录和检查点。进度陈旧、异常或不一致时，检查对应日志与实际进程；来源或字段含义不清楚时才查相关代码。不要为了普通跟进打开浏览器、截图或读图；静态代码和心跳不能单独证明有效进展。
4. 暂停、异常、陈旧、无实测速率时不沿用旧 ETA；API 或来源不可读时报告真实连接/数据问题，不把旧进度当成最新状态。
5. worker 独立于页面，通过进程、业务日志和完成量增量核对工作状态。看板继续发布给用户，整体完成须有全部业务验收和交付物证据，进度上报不能替代内容校验。

## 页面功能验收（按需）

用户明确要求查看或操作页面，或本次修改、修复、验收页面功能时，才执行对应的浏览器检查：

1. 页面默认每 2 秒刷新；右上角可输入 1–300 秒并「应用」，只改变网页读取频率。历史默认折叠；每个任务独立展开/收起，批量展开/收起有效，批量操作不打开历史列表。刷新、排序和置顶不重置阶段开合；重开保留刷新间隔及各任务的查看偏好。
2. 暂停、异常、陈旧或无实测速率时无旧 ETA；连接失败隐藏旧数字并重试。长刷新间隔下，本地陈旧检查仍及时停止旧速度/ETA，不额外读取 API 或调用 shell。
3. 验证关闭与重开页面的显示行为，结合底层数据确认 worker 不依赖网页生命周期。普通进度跟进不执行此组页面检查。
