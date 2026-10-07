---
name: global-task-progress
description: 为持续运行、批量或多阶段任务提供统一的本机实时进度看板。用于复制、校验、发布、导出、备份、索引等任务的实际完成量、阶段、速度和 ETA，也用于接续任务、隐藏历史和保留详情展开状态。默认使用本机8790端口，启动前检测占用，允许用户选择并保存端口，优先复用已有服务，日常从底层数据跟进。
---

# 统一任务进度

## 开始前

首次安装、换设备或出现依赖错误时，先读 [references/environment.md](references/environment.md)。Windows 运行 `scripts/setup.ps1` 检测；用户已要求安装/首次启用时，用 `-InstallMissing` 补齐缺失的完整 Python 并复检。其他平台用 `scripts/check_environment.py`，按实际系统和当前安装授权补齐缺失项。复用已有解释器及业务环境，只安装真实缺项；Python 标准库不能当作 pip 包安装，Node、PyYAML、Celery、Redis不是运行必需项。检查通过后沿用报告中的解释器绝对路径；失败时先解决具体缺项或冲突，不开始 worker。

1. 读取已有任务、脚本和服务配置，优先复用同身份、同数据目录的现行服务。8790 是默认端口，首次启用先用 `task_progress.py ports` 检测所选端口并列出空闲候选，让用户选择喜欢的端口；用户已明确指定时直接检测该端口，不重复询问。确认后用 `configure --port N` 或 `setup.ps1 -Port N` 保存选择。后续从配置读取实际入口，健康身份为 `agent-global-progress-v1`。冲突时返回候选并等待用户选择，不随机切换、不终止其他程序；同一目录的旧服务仍在线时，不另开第二套服务或擅自迁移端口。
2. 确定稳定 `task_id`、实际总量、计数单位和验收阶段。接续任务沿用原 ID、已核验结果和完成量。总量未知使用 `None`，不捏造分母或百分比。
3. 在业务工作开始前用 `Reporter.update()` 登记。一个任务 ID 对应一个业务写入者；多个独立任务用不同 ID。

默认 Windows 运行数据放在 `D:/Codex/维护/统一任务进度/运行数据`；已有服务以其健康响应中的目录为准。所选端口保存在该目录的 `服务配置.json`；优先级为显式 `port` / `--port`、`TASK_PROGRESS_PORT`、保存的配置、旧服务状态、默认8790。其他环境或明确指定位置时传入绝对 `state` 路径。路径不可用时说明原因，不自行迁移服务数据。端口检测只代表检测时可用，配置与启动还须复检并依赖真实绑定结果。详细接入见 [references/integration.md](references/integration.md)。

## 执行与计数

把 `scripts/task_progress.py` 的 `Reporter` 接入实际工作循环。复用已有的兼容模块时沿用原路径，避免更换正在运行的服务。示例：

```python
from task_progress import Reporter

r = Reporter("backup-photos", "照片备份")
r.update("复制", 0, len(files), "开始复制", unit="份")
with r.pulse():
    for index, item in enumerate(files, 1):
        copy_one(item)                    # 返回成功后才递增
        r.progress("复制", index, len(files), unit="份")
    r.update("完整校验", verified, len(files), unit="份")
    # 对未校验项逐项完整校验并更新；通过后进入发布阶段。
```

- 复制、完整校验、发布等阶段分别显示；阶段达到总量时，整个任务仍可为 `running`，直到全部验收通过才设 `complete`。
- `pulse()` 只在真实业务工作作用域中维持心跳。心跳只能证明写入者仍在联系，不能证明有效工作量增加。不要用独立定时器让退出的任务看起来仍在执行。
- 高频计数用 `progress()` 合并上报，默认最多等待 1 秒；配合 `pulse()`，下一项耗时很长时仍按时刷新。阶段、状态、完成及异常用 `update()` / `stop()` 立即上报。退出工作作用域会刷新剩余真实完成量，进度上报不需逐项启动 PowerShell/CMD。旧模块没有 `progress()` 时沿用 `update()`，不要中途替换正在执行的 worker。
- 后台工作由独立 worker 执行；页面只读取进度。关闭页面后 worker 继续，不依赖用户再发消息。进度脚本不会替用户启动业务任务；Windows 启动后台 helper 使用隐藏窗口。
- 暂停、恢复、异常、取消、阶段切换、完成时立即更新。异常后写入 `failed` 再保留异常证据；恢复前核对实际进程和检查点。不要仅凭陈旧文件声称仍在运行。
- 速度和 ETA 来自近期实际完成量增量，ETA 仅表示当前阶段。未测得速度、近期无进展、暂停、异常或超过 90 秒未更新时停止估计；不能沿用过期 ETA，也不能凭吞吐量宣称整个任务已提速。

需要避免重复执行、有限重试或限制并发时，读 [references/worker-reliability.md](references/worker-reliability.md)。优先复用业务已有队列和检查点；包内轻量辅助基于标准库 SQLite、OS 文件锁和线程池，不要求额外常驻服务。重试只用于已授权、可安全重复的操作；校验不一致、权限错误等应停止核对。

## 跟进与验收

日常查询、接续和跟进任务进度，默认通过底层结构化数据完成：先读取 `/api/health`、`/api/tasks`，按稳定任务 ID 提取实际完成量、总量、阶段、状态、更新时间、速度和 ETA。需要排障或核对时，再读取对应任务 JSON、业务检查点、相关日志和实际进程；来源或字段含义不清楚时才查相关代码。静态代码、进度文件或心跳都不能单独证明有效业务进展。

普通跟进不打开浏览器、不截图、不读图，不以网页显示作为判断任务状态的默认依据。进度仍须持续同步到统一服务，保留可视化入口供用户查看。用户明确要求查看或操作页面，或者本次正在修改、修复、验收页面显示与交互时，才进行对应浏览器检查；页面验收不替代底层业务验收。

开始后、阶段切换后和结束前，回读 `/api/tasks`，与对应 worker 的记录、完成量、状态和更新时间比对。数据陈旧、服务不可达或状态不一致时，查相关记录、日志和进程并报告证据，不根据旧数字声称仍在运行。复用现行服务和任务 ID，保留已核验结果；完成时提供固定入口、交付物位置及尚未验证事项。

## 页面功能验收（按需）

页面默认每 2 秒刷新，右上角可输入 1–300 秒并点击「应用」。当前未结束任务优先，终态历史默认折叠。每个任务有独立的「收起详情 / 展开详情」，只影响该任务；收起时保留名称、状态、置顶、当前阶段提示及一条主进度，不把阶段进度伪装成整个任务完成。上方「展开全部 / 收起全部」统一设置任务详情；展开全部同时打开阶段表，但不打开历史列表本身。提供每任务置顶和最近更新、需要关注、进度较少、名称排序；置顶任务在各自区域始终优先。刷新间隔、每任务展开选择、置顶和排序保存在本浏览器，旧版统一精简偏好兼容迁移，业务状态保持真实。

每个任务使用稳定 ID 保留 DOM 节点和按钮；刷新、置顶、排序和单任务详情切换不重建 `<details>`，保留用户在本次页面中的阶段展开/折叠选择。「展开全部」是用户明确要求批量打开阶段表，可以改变阶段开合。连接中断时隐藏旧数字并显示异常，恢复后继续使用原节点。长刷新间隔下，页面仍每秒在本地检查记录是否超过 90 秒并停止旧速度/ETA；此检查不发起网络请求、不调用 PowerShell/CMD。

仅在本次涉及页面功能时，验证自定义间隔生效且重开后保留；单任务详情切换不影响其他任务，收起时只显示主进度；批量展开/收起生效；展开详情跨多次刷新、置顶/排序及单任务切换不自动折叠；暂停/异常无旧 ETA；关闭并重开页面仍能看到实际任务和各任务独立查看偏好。日常进度跟进不执行这组浏览器验收。

## 配套资源

- [scripts/task_progress.py](scripts/task_progress.py)：标准库 Reporter、JSON 来源注册、固定端口服务。
- [scripts/setup.ps1](scripts/setup.ps1) / [scripts/check_environment.py](scripts/check_environment.py)：首次安装检测、缺失 Python 安装及安装后复检；不启动业务任务。
- [scripts/progress_page.html](scripts/progress_page.html)：当前任务、折叠历史、保持详情状态的看板。
- [scripts/example_worker.py](scripts/example_worker.py)：小型真实复制、SHA-256 校验、清单发布示例，支持用原 ID 和 `--resume` 重新核验检查点后继续。
- [scripts/worker_helpers.py](scripts/worker_helpers.py)：有限重试、SQLite 检查点、重复 worker 防护及有界线程提交。
- [scripts/resource_probe.py](scripts/resource_probe.py)：Windows 只读内存/CPU 采样，区分进度服务、浏览器和业务进程；需要核对资源开销时使用。
- [references/alternatives.md](references/alternatives.md)：GitHub、skills.sh、SkillHub 候选比较与核对范围。
