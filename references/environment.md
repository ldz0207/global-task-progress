# 首次安装与依赖检测

## 必需与可选依赖

运行需要完整的 **Python 3.10+**。SQLite、SHA-256、HTTP 服务、线程池和文件锁使用 Python 标准库；没有运行时第三方 pip 包。`sqlite3` 缺失通常是 Python 发行版不完整或损坏，不能用 `pip install sqlite3` 修复。

Node 只用于仓库的页面开发测试，PyYAML 只用于外部 `quick_validate.py` 技能格式检查；普通使用不安装它们。Celery、Redis、Docker 也不是本技能的依赖。业务 worker 自己需要的第三方库，按该项目的真实 requirements/锁文件在其原有环境检测、安装；不要为了显示进度另装一套业务框架。

## Windows 首次启用

从安装后的技能根目录运行。用户要求安装或首次启用技能时，先检测，在本次安装授权内补齐缺失项；已有运行时不升级、不重复安装：

```powershell
# 默认只检查；不安装，也不启动服务。
.\scripts\setup.ps1

# 安装缺失的完整 Python，然后重新检查。
.\scripts\setup.ps1 -InstallMissing

# 用户选择喜欢的端口后，检测并保存配置，不启动服务。
.\scripts\setup.ps1 -Port 8888

# 沿用明确选择的解释器和现有服务的数据目录。
.\scripts\setup.ps1 -PythonPath 'C:\实际位置\python.exe' -StateDir 'D:\实际数据目录'
```

脚本依次检测指定路径、现有虚拟环境、Codex 常见内置运行时、命令、用户安装目录和 CPython 注册表记录。以真实执行及 SQLite/SHA-256 功能检查确认可用，不把 Windows Store 别名当作已经安装；检查期间临时禁止 Python 安装管理器自动下载安装，结束后恢复该环境变量。

没有可用解释器且指定 `-InstallMissing` 时，使用 WinGet 的 `Python.Python.3.13` 精确包标识、`winget` 来源和当前用户范围安装，再次检测；不全局修改 PATH 或执行策略，不覆盖明确指定的 Python。WinGet 失败或复检失败时停止，不进入 worker，不循环重复安装。WinGet 缺失时，由执行本技能的 agent 从 [Python 官网](https://www.python.org/downloads/windows/) 选择适配系统架构的完整安装器，核对官方来源和微软包清单的 SHA-256，沿用当前用户安装范围，在已授权的安装任务内安装后用明确解释器路径复检；下载/日志使用用户指定工作目录。不要用第三方下载站或缺少标准库的 embeddable 包代替。

默认 Windows 数据路径为 `D:/Codex/维护/统一任务进度/运行数据`；D 盘不可用时明确报告，先确定用户允许的数据路径，再传 `-StateDir`，不自动改到 C 盘。数据目录检测只在其现有父目录建立独立临时目录，验证写入、原子替换和回读后清除，不修改原任务文件。

检查报告为 JSON。`ready=true` 表示当前解释器、技能文件、目录写入和所选端口条件通过；`service.status=reuse` 表示已核对服务身份和相同数据目录，`available` 表示所选端口暂时可用。默认8790，端口冲突返回 `available_ports` 候选，由用户选择，不自动随机切换或终止已有服务。通过 `-Port N` 明确选择时复检并保存到数据目录，后续 Reporter 沿用。已有同目录服务在线时优先复用，切换须先明确停止旧服务。此检查不启动服务或业务任务。

检查通过后，用报告中的 `checks.runtime.executable` 运行包内脚本，后续命令不要重新假设 `python` 在 PATH 中：

```powershell
& 'C:\已核验位置\python.exe' -X utf8 -B .\scripts\task_progress.py ensure --state-dir 'D:\实际数据目录'
```

同身份已有服务仍复用原服务和页面；新服务由 `ensure` 在保存的所选端口启动，未配置时默认8790。首次启用先通过 `task_progress.py ports` 检测候选，让用户选择喜欢的端口，再配置和启动；检测时空闲不保证启动时仍空闲。随后登记真实任务并核对实际入口的 `/api/tasks`、任务记录及业务结果，环境检查成功不等于业务验收成功。日常跟进使用底层数据；用户要求查看/操作页面或本次涉及页面修复、功能验收时才检查浏览器。

## macOS / Linux

使用已有 Python 或用户的项目环境，运行 `python3 -B scripts/check_environment.py --state-dir '/绝对数据目录'`。缺少完整 Python 时，由 agent 按当前系统已有包管理器和安装授权安装，再复检；此 Windows PowerShell 安装助手不承担其他平台的系统包安装。缺少标准库扩展时补齐发行版对应组件或改用完整 Python，避免把标准库名称当作 pip 包安装。

## 官方依据

- [Python Windows 安装与标准库选项](https://docs.python.org/3/using/windows.html)：完整运行时、安装管理器及自动安装配置。
- [Python 3.13 安装器选项](https://docs.python.org/3.13/using/windows.html)：本助手使用 `PrependPath=0`、`Include_lib=1` 等选项，不依赖安装器默认 PATH 行为。
- [Microsoft WinGet install](https://learn.microsoft.com/en-us/windows/package-manager/winget/install)：精确包标识、来源、用户范围和静默安装选项。
- [Microsoft CPython 包清单](https://github.com/microsoft/winget-pkgs/tree/master/manifests/p/Python/Python/3/13)：官网安装器与对应摘要，具体版本在安装时核对。

自动检查和既有运行时复用已在 Windows 实测；缺失运行时的安装决策用模拟测试验证。完整 WinGet 安装、无 WinGet 的官网安装以及其他操作系统的真实安装需在相应缺依赖环境验收。
