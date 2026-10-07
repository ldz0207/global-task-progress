# 同类方案比较

核对日期：2026-10-07。检索 GitHub、skills.sh（`task progress`、`progress`、`background`）与腾讯 SkillHub 的公开技能 API（`progress`、`task-status`、`background task`、`progress tracker`）；阅读下列候选的实际 `SKILL.md`，不只依据搜索摘要。

| 候选 | 主要用途 | 与本技能的范围差异 |
| --- | --- | --- |
| [python-background-jobs](https://skills.sh/wshobson/agents/python-background-jobs) · [GitHub 源码](https://github.com/wshobson/agents/blob/main/plugins/python-development/skills/python-background-jobs/SKILL.md) | Python 队列与后台 worker 架构 | 适合组织业务执行，未提供本地统一计数看板及保留详情状态的页面 |
| [background-agent-pings](https://github.com/parcadei/Continuous-Claude-v3/blob/main/.claude/skills/background-agent-pings/SKILL.md) | Claude 后台代理进度通知及避免重复轮询 | 面向代理消息，未提供多任务各阶段计数、实测速率及 ETA 看板 |
| [Task Status](https://clawhub.ai/mightyprime1/task-status) · [GitHub 源码](https://github.com/openclaw/skills/blob/main/skills/mightyprime1/task-status/SKILL.md) | 在聊天中发送简短状态及周期提醒 | 可补充聊天反馈；周期提示本身不能验证实际完成量，未覆盖统一实时页面 |
| [background-task-runner 的原始技能](https://api.skillhub.cn/api/v1/skills/background-task-runner/file?path=SKILL.md) | 启动后台子任务，之后查询结果 | 技能写明在后续用户消息时检查、一次跟踪一个任务；未覆盖本需求的自主持续同步与可恢复看板 |
| [project-tracker 的原始技能](https://api.skillhub.cn/api/v1/skills/project-tracker/file?path=SKILL.md) | 项目 Markdown 台账、里程碑及周度审视 | 适合长期项目管理，未覆盖秒级批量操作、阶段计数及实时速度 |

[腾讯 SkillHub 官方仓库](https://github.com/Tencent/skillhub)记录公开 API 和技能检索方法。[skills.sh](https://skills.sh/)提供可安装技能索引。本次核对的候选未完整覆盖本需求的组合，因此将现有已验证方法做成独立技能；这是有限检索结论，不代表所有市场中不存在其他实现。

本仓库没有复制上述第三方技能的代码或指令。候选来源及许可证各自适用；下载量、排名和版本会变化，不作为长期可用性保证。
