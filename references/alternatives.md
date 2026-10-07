# 同类方案比较

核对日期：2026-10-07。检索 GitHub、skills.sh（`task progress`、`progress`、`background`）与腾讯 SkillHub 的公开技能 API（`progress`、`task-status`、`background task`、`progress tracker`）；阅读下列候选的实际 `SKILL.md`，不只依据搜索摘要。

## Stars、安装量和下载量

查询时间：2026-10-07，北京时间。以下为本次查询的返回值；GitHub API、技能页面和 CLI 的缓存及更新时间可能不同。

| 候选 | GitHub stars（整个仓库） | SkillHub API stars（技能） | 安装量（单个技能） | 下载量 | 数据来源 |
| --- | ---: | ---: | --- | ---: | --- |
| python-background-jobs | 40,267 | 未查询此平台同名条目 | 10.6K（skills.sh 页面约数） | 未提供 | [GitHub API](https://api.github.com/repos/wshobson/agents) · [skills.sh](https://skills.sh/wshobson/agents/python-background-jobs) |
| background-agent-pings | 3,940 | 未查询此平台同名条目 | 499（skills CLI）；仓库索引页显示 500 | 未提供 | [GitHub API](https://api.github.com/repos/parcadei/Continuous-Claude-v3) · [skills.sh 索引](https://www.skills.sh/parcadei/continuous-claude-v3) |
| task-status | 未能核验，原 GitHub 来源本轮返回 404 | 14 | 1,842（SkillHub API） | 13,425 | [SkillHub 详情 API](https://api.skillhub.cn/api/v1/skills/task-status) |
| background-task-runner | 条目未提供 GitHub 仓库 | 0 | 0（SkillHub API） | 260 | [SkillHub 详情 API](https://api.skillhub.cn/api/v1/skills/background-task-runner) |
| project-tracker | 条目未提供 GitHub 仓库 | 2 | 47（SkillHub API） | 1,727 | [SkillHub 详情 API](https://api.skillhub.cn/api/v1/skills/project-tracker) |

口径说明：

- GitHub stars 是整个技能集合仓库的收藏量，不能当成某一个技能的独立 stars。
- SkillHub 表格直接使用详情 API 的 `skill.stats.stars / installs / downloads`，保持其公开计数口径；ClawHub 来源的候选可能带有上游同步数据，不把它解释为本平台独立新增安装人数。
- 安装量和下载量分开列出；缺失或无法核验写明原因，不把“未知”写成 0。10.6K 是页面约数，约为 1.06 万。
- `background-agent-pings` 的直接详情页本轮无法通过网页检索工具读取，因此用 CLI 的 499 与官方仓库索引页的 500 分别注明，不混成一个声称精确同步的数字。

## 功能与范围比较

| 候选 | 主要用途 | 与本技能的范围差异 |
| --- | --- | --- |
| [python-background-jobs](https://skills.sh/wshobson/agents/python-background-jobs) · [GitHub 源码](https://github.com/wshobson/agents/blob/main/plugins/python-development/skills/python-background-jobs/SKILL.md) | Python 队列与后台 worker 架构 | 适合组织业务执行，未提供本地统一计数看板及保留详情状态的页面 |
| [background-agent-pings](https://github.com/parcadei/Continuous-Claude-v3/blob/main/.claude/skills/background-agent-pings/SKILL.md) | Claude 后台代理进度通知及避免重复轮询 | 面向代理消息，未提供多任务各阶段计数、实测速率及 ETA 看板 |
| [Task Status](https://clawhub.ai/mightyprime1/task-status) · [SkillHub 原始技能](https://api.skillhub.cn/api/v1/skills/task-status/file?path=SKILL.md) | 在聊天中发送简短状态及周期提醒 | 可补充聊天反馈；周期提示本身不能验证实际完成量，未覆盖统一实时页面 |
| [background-task-runner 的原始技能](https://api.skillhub.cn/api/v1/skills/background-task-runner/file?path=SKILL.md) | 启动后台子任务，之后查询结果 | 技能写明在后续用户消息时检查、一次跟踪一个任务；未覆盖本需求的自主持续同步与可恢复看板 |
| [project-tracker 的原始技能](https://api.skillhub.cn/api/v1/skills/project-tracker/file?path=SKILL.md) | 项目 Markdown 台账、里程碑及周度审视 | 适合长期项目管理，未覆盖秒级批量操作、阶段计数及实时速度 |

[腾讯 SkillHub 官方仓库](https://github.com/Tencent/skillhub)记录公开 API 和技能检索方法。[skills.sh](https://skills.sh/)提供可安装技能索引。本次核对的候选未完整覆盖本需求的组合，因此将现有已验证方法做成独立技能；这是有限检索结论，不代表所有市场中不存在其他实现。

本仓库没有复制上述第三方技能的代码或指令。候选来源及许可证各自适用；下载量、排名和版本会变化，不作为长期可用性保证。

## 私有报告的访问

本仓库为私有。未登录有访问权限的 GitHub 账号时，浏览器可能将存在的报告显示为 404。[GitHub 官方说明](https://docs.github.com/en/rest/using-the-rest-api/troubleshooting-the-rest-api#404-not-found-for-an-existing-resource)解释了私有资源未正确认证时的 404 行为。

GitHub 插件的授权与浏览器网页登录分别核验：插件可以读取仓库，不代表内置浏览器已登录。同一链接在已登录的外部浏览器可读、在显示 `Sign in` 的内置浏览器返回 404，应先检查该浏览器登录状态。需要网页浏览时，在相应浏览器登录有权限的账号；日常阅读也可直接使用已下载到本地的这份 Markdown。
