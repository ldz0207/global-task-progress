# 统一任务进度 · global-task-progress

可安装的 Agent Skill，把持续运行的批量任务接入一个本机看板：**http://127.0.0.1:8790/**。

当前任务优先显示，历史默认折叠；每任务可置顶，可按最近更新、需要关注、进度较少或名称排序。右上角可自定义 **1–300 秒**刷新间隔，默认 2 秒。**每个任务**独立「展开详情 / 收起详情」，收起时只保留任务状态和一条主进度；上方还有 **展开全部 / 收起全部**，统一控制详情，历史列表仍保持折叠。刷新间隔、各任务的展开选择、置顶和排序在本浏览器保存；自动刷新和排序不会重置开合。「展开全部」会主动打开各阶段表。

完整视图显示实际已完成/总量、百分比、剩余、阶段、更新时间、近期实测速度及当前阶段 ETA。暂停、异常或 90 秒未更新时，停止显示旧速度与 ETA；刷新间隔较长时，页面也会通过本地检查及时停止旧估计，不增加网络或 shell 调用。

复制、完整校验、发布分别验收；页面关闭后 worker 继续运行。这里包含通用接入方法和 Python 标准库实现，不包含真实任务数据或业务资料。

## 安装

这是私有仓库，需要先用自己已有的 GitHub 授权将仓库下载或克隆到本地。把仓库根目录中的 `SKILL.md`、`agents/`、`scripts/`、`references/` 放到 Codex 技能目录的 `global-task-progress/` 内，例如：

```text
C:/Users/<用户名>/.codex/skills/global-task-progress/
```

重新打开会话后调用 `$global-task-progress`，或要求为批量任务接入统一实时进度。正式入口是 [SKILL.md](SKILL.md)。其他支持 `SKILL.md` 的工具可使用相同目录结构，但其自动发现行为需在对应工具中核验。

首次启用先检查环境。Windows 可以从技能根目录运行：

```powershell
.\scripts\setup.ps1 -InstallMissing
```

检测 Python 3.10+、标准库及 SQLite/SHA-256 功能、目录权限、技能文件和固定端口；已有环境复用，缺少可用 Python 时才通过 WinGet 安装完整运行时并复检。报告中的解释器绝对路径用于后续命令；不要求 PATH 已配置。不同数据目录、无 WinGet、D 盘不可用或其他系统，见 [环境与安装说明](references/environment.md)。运行无需第三方 pip 包，Node 等开发工具不作为用户安装条件。

## 使用

Python 3.10+，运行脚本无需第三方包。已有健康服务时优先复用，避免覆盖正在运行的进度页面。

```powershell
$progressPython = 'C:\检测报告中的实际位置\python.exe'
& $progressPython scripts/task_progress.py ensure
& $progressPython scripts/example_worker.py --work-dir 'D:/Codex/维护/统一任务进度/work/新的演示目录' --task-id 'progress-example'
& $progressPython scripts/example_worker.py --work-dir 'D:/Codex/维护/统一任务进度/work/新的演示目录' --task-id 'progress-example' --resume
```

默认 Windows 数据目录：`D:/Codex/维护/统一任务进度/运行数据`。其他系统必须显式指定绝对路径；可使用 `--state-dir` 或 `TASK_PROGRESS_STATE_DIR`。入口始终固定为本机 8790；本仓库不会自动聚合其他设备上的服务。具体业务接入、接续和后台执行见 [接入说明](references/integration.md)。

## 验证与维护

```powershell
python -B -m unittest discover -s tests -v
node tests/test_page.cjs
```

测试通过独立临时数据目录验证计数、暂停恢复、短窗口速率、陈旧状态和接入冲突，不占用新的端口。页面还需在实际浏览器验证自动刷新和详情展开状态。

v0.2.3 增加每任务独立详情和展开全部/收起全部，保留首次安装检测、自定义刷新和执行保障；仍只依赖 Python 标准库。[执行保障与资源选择](references/worker-reliability.md)说明适用范围和恢复方法。[同类方案比较](references/alternatives.md)保留检索与热度依据。

独立仓库用于后续版本维护。更新先修改本地源码、运行必要测试、核对正在运行的服务，再上传；升级不会自动替换既有长期服务或正在运行的业务worker。
