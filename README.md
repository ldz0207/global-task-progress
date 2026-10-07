# 统一任务进度 · global-task-progress

可安装的 Agent Skill，把持续运行的批量任务接入一个本机看板：**http://127.0.0.1:8790/**。

当前任务优先显示，历史默认折叠；每任务可置顶，可按最近更新、需要关注、进度较少或名称排序，选择在本浏览器保存。每 2 秒自动刷新，刷新、排序和置顶时阶段详情保持用户选择的展开状态。显示实际已完成/总量、百分比、剩余、阶段、更新时间、近期实测速度及当前阶段 ETA。暂停、异常或 90 秒未更新时，停止显示旧速度与 ETA。

复制、完整校验、发布分别验收；页面关闭后 worker 继续运行。这里包含通用接入方法和 Python 标准库实现，不包含真实任务数据或业务资料。

## 安装

这是私有仓库，需要先用自己已有的 GitHub 授权将仓库下载或克隆到本地。把仓库根目录中的 `SKILL.md`、`agents/`、`scripts/`、`references/` 放到 Codex 技能目录的 `global-task-progress/` 内，例如：

```text
C:/Users/<用户名>/.codex/skills/global-task-progress/
```

重新打开会话后调用 `$global-task-progress`，或要求为批量任务接入统一实时进度。正式入口是 [SKILL.md](SKILL.md)。其他支持 `SKILL.md` 的工具可使用相同目录结构，但其自动发现行为需在对应工具中核验。

## 使用

Python 3.10+，运行脚本无需第三方包。已有健康服务时优先复用，避免覆盖正在运行的进度页面。

```powershell
python scripts/task_progress.py ensure
python scripts/example_worker.py --work-dir 'D:/Codex/维护/统一任务进度/work/新的演示目录' --task-id 'progress-example'
```

默认 Windows 数据目录：`D:/Codex/维护/统一任务进度/运行数据`。其他系统必须显式指定绝对路径；可使用 `--state-dir` 或 `TASK_PROGRESS_STATE_DIR`。入口始终固定为本机 8790；本仓库不会自动聚合其他设备上的服务。具体业务接入、接续和后台执行见 [接入说明](references/integration.md)。

## 验证与维护

```powershell
python -B -m unittest discover -s tests -v
node tests/test_page.cjs
```

测试通过独立临时数据目录验证计数、暂停恢复、短窗口速率、陈旧状态和接入冲突，不占用新的端口。页面还需在实际浏览器验证自动刷新和详情展开状态。

独立仓库用于后续版本维护。更新先修改本地源码、运行必要测试、核对正在运行的服务，再上传；升级不会自动替换既有长期服务。v0.1.0 的调研依据见 [同类方案比较](references/alternatives.md)。
