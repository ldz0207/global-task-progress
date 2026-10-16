# 接入与恢复

首次安装或依赖异常时，先执行 [环境与安装检测](environment.md)，沿用通过检查的 Python 绝对路径。缺失的标准库由完整 Python 提供；业务包使用业务项目原环境按实际缺项补齐。

## 接入已有服务

先从所选或保存端口的 `/api/health` 读取身份和目录，确认 `identity=agent-global-progress-v1` 和 `state_dir`。默认入口为 `http://127.0.0.1:8790/`，但不把默认端口当作所有用户的实际配置。新 Reporter 的 `state` 必须与服务目录一致。已有同身份、同目录服务会被复用；端口被其他程序或不同目录的服务占用时返回空闲候选，由用户重新选择。服务只绑定 `127.0.0.1`，没有远程写入或执行业务的接口。

`Reporter` 写入 `<state>/任务/<task_id>.json`，使用临时文件加原子替换。任务 ID 只用英数字、`-`、`_`。不要让两个业务 worker 同时写同一任务。数据结构兼容 v1；整个任务状态与阶段完成状态分开记录。

```python
import sys
sys.path.insert(0, "/技能所在绝对路径/task-progress/scripts")
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

让 worker 脱离网页生命周期。Windows 可用 `Start-Process -WindowStyle Hidden`，指定既有 Python、绝对脚本路径、D 盘工作目录和日志目录；进程创建返回不代表任务成功，必须核对新鲜进度、实际进程和工作结果。不要为查看进度另起业务服务，不自动换随机端口；已选择的进度端口统一复用。

## 任务所属 Codex 对话

`Reporter` 默认将 `CODEX_THREAD_ID` 保存为任务 JSON 的 `codex_thread_id`。后台 worker 没有该变量时，构造 Reporter 时显式传入完整 UUID：`Reporter(..., codex_thread_id="完整对话UUID")`。外部来源注册同样支持 `register_source(..., codex_thread_id=...)` 和 CLI `register --codex-thread-id ...`，注册信息优先于外部 JSON 的关联字段。传入空字符串可让跨对话的全局服务或其他应用任务不自动绑定当前聊天。原任务已有绑定时 Reporter 保留它。

`/api/tasks` 的每项增加 `codex_conversation={id,name,source,status}`，卡片在任务名称下显示「Codex 对话：名称」。关联依赖稳定 UUID，用户改名后仍对应原聊天。名称来自本机 Codex 元数据，默认 `CODEX_HOME` 或用户目录的 `.codex`；已配置续接的 `codex_home` 优先。独立开启名称显示不需要启用续接。

在Windows点击对话名称，网页向现有服务的 `/api/codex/open` 提交所显示的对话UUID，服务复用Host/Origin及临时token检查，并确认该UUID已关联到看板任务，再调用Codex已注册的 `codex://threads/<UUID>` 系统入口。只打开原对话，不发送消息或启动模型工作，也不要求开启续接记录器。使用系统原生链接处理器，不增加监控/跳转进程；网页保留进度和偏好。缺少关联的记录显示普通文字；打开失败时显示错误。接口接受成功代表系统已接收打开请求，实际显示需在Codex核验。

缓存每10秒最多只读一次与任务相关的 ID/名称/默认标题，不读取消息历史，不调用模型，不增加后台进程/监控线程。由已有看板请求触发，页面关闭不为名称轮询；实际可见更新受页面刷新间隔影响，默认2秒刷新通常在10–12秒内跟随已落盘改名。缓存只保留有关联的名称，读取连接随查询关闭；数据库暂不可用时保留上次名称并提示尚未更新，进度照常返回。

旧任务 ID 中包含完整 UUID 或唯一的8位 UUID 前缀时可只读补关联；不唯一、缺失或无匹配则显示「未记录所属对话」。其他旧记录仅在核实创建来源后补入完整 ID，并保持实际计数、状态及更新时间，不根据任务标题或 PID 猜测。

## 端口检测与用户选择

```powershell
python scripts/task_progress.py ports --state-dir 'D:/实际数据目录'
# 读取 selected、active_port 和 available_ports；首次使用让用户选择。
python scripts/task_progress.py configure --state-dir 'D:/实际数据目录' --port 8888
python scripts/task_progress.py ensure --state-dir 'D:/实际数据目录'
```

候选检测只短暂尝试绑定本机 IPv4 端口，不启动监听或扫描整个端口空间；默认列出8790起有限范围内的5个空闲候选，`--scan-start` 可指定起点。用户可以选候选之外的任意有效端口，范围1–65535；仍需通过本机权限、保留端口和占用检查。空闲只代表检测时可用，配置与真实启动会再次检测，最终以操作系统绑定结果为准，不承诺端口以后不会被其他程序占用。

`configure` 只验证并保存选择到数据目录的 `服务配置.json`，不启动服务。端口优先级：显式 `port` / `--port`、`TASK_PROGRESS_PORT`、已保存配置、旧服务状态、8790默认值。`Reporter(..., port=N)`、注册来源、环境检查和服务启动使用同一选择逻辑；`Reporter.url` 和 `/api/health` 返回实际入口。页面链接使用访问时的地址，浏览器查看偏好按入口分别保存。

已运行的同目录服务不得因端口选项另开第二套；切换须先按用户明确要求停止旧服务，保留数据和稳定任务 ID，再保存新端口并启动。服务停止只影响查看和聚合，不等于停止业务 worker。关闭网页或业务任务完成不会自动关闭服务；安装检查不启动服务，`ensure` 或首个 Reporter 会按需启动。技能不自动配置开机启动。

演示 worker 仅创建一组小样例并执行复制、完整 SHA-256 校验和清单发布。初次运行目录必须不存在或为空，避免覆盖用户文件；后续用相同 ID、目录及 `--resume` 接续，重新核验本演示 SQLite 检查点后复用结果。它本身是同步脚本；由既有后台启动方式运行后，网页关闭不影响它。

## 外部 JSON 来源

已有业务自己生成 JSON 时可注册其绝对文件路径：

```powershell
python scripts/task_progress.py register --task-id existing-job --title '已有批处理' --file 'D:/现有任务/progress.json'
```

来源应显式提供 `stage`、`status`、`done`、`total`、`unit`、`updated_ts`（Unix 秒）或带时区的 `updated_at`。可提供 `stages` 字典、`speed`（单位/秒）和 `eta_seconds`。缺少更新时间使用文件修改时间；不得把每次读取时间当作 worker 心跳。没有明确速度时等待测量，不用累计历史完成量推算恢复后的速度。相同 ID 若已有本地记录，不允许再注册来源造成冲突。

## 桌面服务控制

Windows首次安装桌面入口：

```powershell
# 使用已检测通过的Python；已有服务明确指定原脚本及数据目录。
scripts/install_desktop_control.ps1 -PythonPath 'C:/实际解释器/python.exe' -BackendScript 'D:/原服务/task_progress.py' -StateDir 'D:/实际运行数据'
# 不打开窗口也可使用同一控制逻辑。
scripts/control_service.ps1 -Action status -BackendScript 'D:/原服务/task_progress.py' -StateDir 'D:/实际运行数据'
scripts/control_service.ps1 -Action start -PythonPath 'C:/实际解释器/python.exe' -BackendScript 'D:/原服务/task_progress.py' -StateDir 'D:/实际运行数据'
scripts/control_service.ps1 -Action stop -BackendScript 'D:/原服务/task_progress.py' -StateDir 'D:/实际运行数据'
```

安装器检测现有Python和Windows内置.NET Framework编译器，把控制面板生成在数据目录同主题的 `work/桌面服务控制/`，用系统返回的实际桌面目录创建「任务进度服务」快捷方式；可显式传入 `-OutputDir` 或 `-DesktopDir`。不覆盖同名非本技能快捷方式，不添加启动项，不因安装而改变服务启停。快捷方式保留解释器、服务脚本和数据目录的绝对路径，端口从配置读取；路径迁移后重新运行安装器更新入口。

面板提供「启动服务」「停止服务」「打开看板」「刷新状态」。每5秒由面板自身读取健康API，无周期性shell进程；启停按钮才调用一次控制脚本，实际动作期间禁用按钮以免重复提交。打开看板使用用户默认浏览器。停止前核对身份、端口、数据目录、启动记录、脚本、实际命令行和进程创建时间，并保持目标进程句柄，防止旧PID被复用后误停其他程序。记录不一致、其他端口仍有同目录服务、端口冲突或目标变化时停止操作并显示原因。

停止只关闭看板服务，保留所有任务文件和业务worker；业务继续更新记录，恢复服务后重新显示。关闭面板不停止服务，关闭网页也不停止任务。新Reporter接入可能按需再次启动看板；此按钮不提供「永久禁止自动启动」或业务取消。启停验收用独立目录/测试端口完成，不为验证按钮而中断正在使用的真实看板。

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

1. 顶部四块实时统计保持可见：主任务总数、进行中、暂停/待核对/异常、已完成，后台记录不累计到主任务统计。默认展开正在执行的主任务和置顶的未结束主任务，暂停/待核对、后台、历史默认折叠，展开后才生成对应卡片。阶段表和长说明只在任务详情展开时读取；大任务内部明确complete的旧阶段超过8条默认收起，当前和未完成阶段保留在展开的详情中。不凭阶段100%判断全任务完成，来源和计数不变。
2. 右上角折叠的「设置」包含1–300秒刷新间隔、排序和取消全部置顶，默认仍每2秒刷新。历史默认折叠，批量展开不打开历史列表，也不强制展开大型已完成子任务分组。每条任务的置顶、详情、上下移保持可用，移动自动保存为手动排序，在各自当前/历史、置顶/普通组内生效，边界禁用；新任务追加到所属组末，可切回自动排序。刷新和重开保留查看偏好及手动顺序。
3. 暂停、异常、陈旧或无实测速率时无旧 ETA；连接失败隐藏旧数字及四块统计并重试。长刷新间隔下，本地陈旧检查仍及时停止旧速度/ETA，不额外读取 API 或调用 shell。
4. 验证关闭与重开页面的显示行为，结合底层数据确认 worker 不依赖网页生命周期。普通进度跟进不执行此组页面检查。

5. 首次进入读取一次概要，前台按所选间隔刷新，隐藏标签暂停自动请求，返回前台立即刷新。快速连续展开分组或详情时，先前请求结束后必须补读最终查看状态。验证分组关闭后释放其页面节点、全局统计仍包含未加载历史，局部过期时运行/待核对计数同步变化。

## 后台记录与轻量页面读取

后台常驻服务可在原数据目录的 `服务配置.json` 中通过 `dashboard.background_task_ids` 指定。保留文件内原有 `identity`、`port`、`codex_resume` 等字段，仅增加此配置，例如：

```json
{
  "dashboard": {
    "background_task_ids": ["my-background-service"]
  }
}
```

这里是需要加入的字段片段，不是完整服务配置。使用实际已核实的任务ID，不按名称猜测；配置只控制分组，不停止服务、删除记录或改写业务状态。未配置的任务继续作为主任务显示。

页面使用 `/api/tasks?view=summary` 读取未结束主任务概要和全局计数。展开历史、后台分组分别增加 `history=1`、`background=1`；仅可见且展开详情的任务通过 `details=任务ID` 获取阶段，多项用逗号分隔。阶段和长说明未展开时不传输完整详情，关闭分组后不渲染整批卡片。Codex手动续接入口位于原设置中，点击名称跳转对话仍保留。

默认 `/api/tasks` 保持完整业务API。服务按文件修改时间和大小复用未变JSON，写入后下次请求重读；读取失败继续显示原有错误。复用同一进程，无额外轮询程序。已有服务更新需要按[更新说明](updating.md)重启看板服务，业务worker与数据目录保持。
