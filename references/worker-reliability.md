# 轻量执行保障与资源选择

从 [python-background-jobs](https://github.com/wshobson/agents/blob/main/plugins/python-development/skills/python-background-jobs/SKILL.md)借鉴可安全重复执行、分类重试和限制在途任务的思路。采用 Python 标准库的 SQLite、线程池与操作系统锁；进度看板继续作为展示层，不把它改造成分布式队列。

## 控制进度上报开销

在同一个业务 Python 进程中创建一次 `Reporter`，阶段切换立即 `update()`，循环内 `progress()`。用 `pulse()` 保持真实业务作用域内的心跳并按默认1秒刷新缓冲计数。速度保留最近60秒采样、每秒合并并限制最多62个点，已结束阶段移除内部采样数组、保留历史计数和速度。不要每完成一项或每两秒另开 PowerShell/CMD 执行上报命令。

## 避免重复 worker 和重复工作

```python
from pathlib import Path
from worker_helpers import worker_guard, CheckpointStore

with worker_guard(Path("D:/本机运行数据/锁/my-task-worker.lock")):
    with CheckpointStore(Path("D:/本机任务/work/checkpoints.sqlite3")) as store:
        evidence, reused = store.run_once(
            "复制", "稳定文件ID", perform_copy, verify_copy_evidence
        )
```

`worker_guard` 持有 OS 文件锁，重复进程拒绝启动实际工作，异常退出后系统释放锁。它不自动终止其他 worker，也不是资源监控器。相同资源的任务可使用同一锁路径来串行执行，所有调用者需遵循相同约定。

`CheckpointStore` 将每项证据存到本机 SQLite，不把全部任务清单加载到内存。`run_once()` 每次先验证已有证据，通过才跳过业务操作；新操作也须通过验证才记录成功。`verify` 根据业务要求检查目标文件、哈希或发布回读；页面计数不能替代它。SQLite 数据库不要放在 NAS/网络共享。恢复时保留原任务 ID；检查点不再可信且完成量倒退时停止核对，不静默覆盖旧尝试。

## 有限重试

```python
from worker_helpers import retry_call, RetryPolicy

result = retry_call(
    safe_operation,
    retry_if=lambda exc: isinstance(exc, (ConnectionError, TimeoutError)),
    policy=RetryPolicy(max_attempts=3, initial_delay=1, max_delay=10, max_elapsed=30),
)
```

默认最多3次，等待时间逐次增加且有上限；`max_elapsed` 限制追加重试和等待，不会强行终止正在执行的操作，网络请求本身仍须设置超时。提供 `cancel` 事件可停止等待；`on_retry(attempt, delay, error)` 可记录重试并上报暂停/等待状态，恢复实际尝试时立即上报运行状态。重试不产生新进程。

复制本演示自己创建的目标可安全重做；删除源、付费、发送消息、追加文件等操作不能仅因发生异常就自动重试。权限错误、参数错误、哈希不一致等停止核对，避免重复副作用。

## 限制在途任务

```python
from worker_helpers import bounded_map

for item_result in bounded_map(process_item, input_iterator, max_workers=2, max_pending=4):
    record_actual_result(item_result)
```

基于标准库 `ThreadPoolExecutor`，限制并发执行数和已提交未消费结果数，按完成次序返回；结果应携带稳定项目 ID。默认1个执行线程、最多2个在途项，不一次提交几万份工作。线程适合 I/O 型任务，不能据此保证 CPU 型任务变快；并发值应按实际磁盘、内存、网络约束选择。

## 内存与库的选择

进度服务、浏览器、业务 worker 分开测量，不能把服务进程的工作集当作整个方案的内存总量。

Windows 可运行 `python scripts/resource_probe.py --pid <进程PID> --seconds 10 --output D:/本机任务/outputs/资源采样.json`，读取 Windows 进程内存、CPU 时间和采样期间观察到的子进程，不调用 shell 轮询。工作集是驻留内存；私有提交量是另一个指标，不能相加或互相替代。周期采样可能漏掉短命子进程，代码检查和采样共同用于判断。

成熟队列库提供 broker、worker、重试和投递保障，适合实际需要这些能力的业务；使用库仍需编写业务验证、避免重复副作用和配置资源。[Celery 官方介绍](https://docs.celeryq.dev/en/stable/getting-started/introduction.html)说明了组件及平台支持，当前不支持 Microsoft Windows。若需要采用，应在已有适合的服务环境中单独评估。

[Celery 优化说明](https://docs.celeryq.dev/en/stable/userguide/optimizing.html)强调预取和并发配置对内存的影响、过于频繁重启 worker 的开销。小规模本机任务可先保留当前标准库方案，复用业务已有框架；未部署并测量两个方案时，不声称具体内存差值或整项任务加速。
