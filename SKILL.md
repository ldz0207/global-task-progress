---
name: global-task-progress
description: 为持续运行、批量或多阶段任务提供统一的本机实时进度看板。用于文件复制、校验、发布、导出、备份、索引等需要显示实际已完成/总量、剩余量、阶段、更新时间、实测速度和 ETA 的任务，也用于接续已有任务、隐藏历史记录、修复自动刷新导致详情折叠的问题。固定使用 http://127.0.0.1:8790/，优先接入已存在的统一进度服务。
---

# 统一任务进度

## 开始前

1. 读取已有任务、脚本和 `/api/health`。固定入口为 `http://127.0.0.1:8790/`；健康身份应为 `agent-global-progress-v1`。复用现行服务和运行数据目录。端口被其他程序占用或目录不一致时，说明冲突，不改随机端口、不终止其他任务。
2. 确定稳定 `task_id`、实际总量、计数单位和验收阶段。接续任务沿用原 ID、已核验结果和完成量。总量未知使用 `None`，不捏造分母或百分比。
3. 在业务工作开始前用 `Reporter.update()` 登记。一个任务 ID 对应一个业务写入者；多个独立任务用不同 ID。

默认 Windows 运行数据放在 `D:/Codex/维护/统一任务进度/运行数据`；已有服务以其健康响应中的目录为准。其他环境或明确指定位置时传入绝对 `state` 路径。路径不可用时说明原因，不自行迁移服务数据。详细接入见 [references/integration.md](references/integration.md)。

## 执行与计数

把 `scripts/task_progress.py` 的 `Reporter` 接入实际工作循环。复用已有的兼容模块时沿用原路径，避免更换正在运行的服务。示例：

```python
from task_progress import Reporter

r = Reporter("backup-photos", "照片备份")
r.update("复制", 0, len(files), "开始复制", unit="份")
with r.pulse():
    for index, item in enumerate(files, 1):
        copy_one(item)                    # 返回成功后才递增
        r.update("复制", index, len(files), unit="份")
    r.update("完整校验", verified, len(files), unit="份")
    # 对未校验项逐项完整校验并更新；通过后进入发布阶段。
```

- 复制、完整校验、发布等阶段分别显示；阶段达到总量时，整个任务仍可为 `running`，直到全部验收通过才设 `complete`。
- `pulse()` 只在真实业务工作作用域中维持心跳。心跳只能证明写入者仍在联系，不能证明有效工作量增加。不要用独立定时器让退出的任务看起来仍在执行。
- 后台工作由独立 worker 执行；页面只读取进度。关闭页面后 worker 继续，不依赖用户再发消息。进度脚本不会替用户启动业务任务；Windows 启动后台 helper 使用隐藏窗口。
- 暂停、恢复、异常、取消、阶段切换、完成时立即更新。异常后写入 `failed` 再保留异常证据；恢复前核对实际进程和检查点。不要仅凭陈旧文件声称仍在运行。
- 速度和 ETA 来自近期实际完成量增量，ETA 仅表示当前阶段。未测得速度、近期无进展、暂停、异常或超过 90 秒未更新时停止估计；不能沿用过期 ETA，也不能凭吞吐量宣称整个任务已提速。

## 页面与验收

页面每 2 秒刷新，当前未结束任务优先，终态历史默认折叠。提供每任务置顶和最近更新、需要关注、进度较少、名称排序；置顶任务在各自区域始终优先，选择保存在本浏览器，业务状态保持真实。每个任务使用稳定 ID 保留 DOM 节点；刷新、置顶和排序只移动原节点并更新内容，不重建 `<details>`，保留用户的展开/折叠选择。连接中断时隐藏旧数字并显示异常，恢复后继续使用原节点。

开始后、阶段切换后和结束前，回读 `/api/tasks` 并检查实际页面，与 worker 的完成量、状态和更新时间比对。验证展开详情跨多次刷新及置顶/排序不自动折叠；暂停/异常无旧 ETA；关闭并重开页面仍能看到实际任务和查看偏好。完成时提供固定入口和交付物位置，并明确尚未验证的功能。

## 配套资源

- [scripts/task_progress.py](scripts/task_progress.py)：标准库 Reporter、JSON 来源注册、固定端口服务。
- [scripts/progress_page.html](scripts/progress_page.html)：当前任务、折叠历史、保持详情状态的看板。
- [scripts/example_worker.py](scripts/example_worker.py)：小型真实复制、SHA-256 校验、清单发布示例，仅写入新建演示目录。
- [references/alternatives.md](references/alternatives.md)：GitHub、skills.sh、SkillHub 候选比较与核对范围。
