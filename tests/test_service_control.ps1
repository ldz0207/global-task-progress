param([Parameter(Mandatory=$true)][string]$PythonPath)
$ErrorActionPreference = 'Stop'
$selectedPython = $PythonPath
$scripts = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\scripts'))
. (Join-Path $scripts 'control_service.ps1')
$checks = 0
function Assert-Control($Condition, [string]$Message) { if (-not $Condition) { throw $Message }; $script:checks++ }
$backend = Join-Path $scripts 'task_progress.py'
$testDirectory = Join-Path 'D:\Codex\维护\统一任务进度\work' ('desktop-control-test-' + [guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $testDirectory
$utf8 = New-Object Text.UTF8Encoding($false)
$stateRecord = Join-Path $testDirectory '服务状态.json'
$configRecord = Join-Path $testDirectory '服务配置.json'
$selectedPort = 0
foreach ($candidate in 19300..19340) {
    $probe = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback,$candidate)
    try { $probe.Server.ExclusiveAddressUse=$true; $probe.Start(); $selectedPort=$candidate; break } catch {} finally { $probe.Stop() }
}
if (-not $selectedPort) { throw 'No isolated test port is available' }
try {
    [IO.File]::WriteAllText($configRecord,(@{identity='agent-global-progress-v1';port=$selectedPort}|ConvertTo-Json),$utf8)
    $initial = Get-ProgressServiceStatus $testDirectory $backend
    Assert-Control ($initial.status -eq 'stopped' -and $initial.port -eq $selectedPort) 'Saved port must be respected without starting the service'
    $correct = @('python.exe',$backend,'serve','--state-dir',$testDirectory,'--port',[string]$selectedPort)
    Assert-Control (Test-ControlCommandLine $correct $backend $testDirectory $selectedPort) 'Exact server command must pass'
    Assert-Control (-not (Test-ControlCommandLine @('python.exe',$backend,'ensure','--state-dir',$testDirectory,'--port',[string]$selectedPort) $backend $testDirectory $selectedPort)) 'Ensure helper is not the server process'
    Assert-Control (-not (Test-ControlCommandLine @('python.exe','-c',('print("'+$backend+'")'),'serve','--state-dir',$testDirectory,'--port',[string]$selectedPort) $backend $testDirectory $selectedPort)) 'Quoted text mentioning the script is not proof'
    Assert-Control (-not (Test-ControlCommandLine $correct $backend ($testDirectory+'-other') $selectedPort)) 'Other data directories must not be stopped'
    Assert-Control (-not (Test-ControlCommandLine $correct $backend $testDirectory ($selectedPort+1))) 'Other ports must not be stopped'
    $quoted = '"C:\Python Tools\python.exe" "C:\Progress Tools\task_progress.py" serve --state-dir "D:\Progress Data" --port 8888'
    $split = @(Split-ControlCommandLine $quoted)
    Assert-Control ($split.Count -eq 7 -and $split[1] -eq 'C:\Progress Tools\task_progress.py' -and $split[4] -eq 'D:\Progress Data') 'Windows argument quoting must round-trip'
    $started = Start-ProgressService $testDirectory $backend $selectedPython
    Assert-Control ($started.status -eq 'running' -and $started.pid -gt 0) 'Start must verify a live isolated server'
    $reused = Start-ProgressService $testDirectory $backend $selectedPython
    Assert-Control ($reused.pid -eq $started.pid) 'Starting again must reuse the same PID'
    $metadata = Read-ControlJson $stateRecord
    $metadata.script = Join-Path $testDirectory 'unrelated-worker.py'
    [IO.File]::WriteAllText($stateRecord,($metadata|ConvertTo-Json),$utf8)
    $refused = $false
    try { Stop-ProgressService $testDirectory $backend | Out-Null } catch { $refused = $true }
    Assert-Control ($refused -and (Test-ControlListener $selectedPort)) 'Mismatched metadata must refuse termination and preserve the listener'
    $metadata.script = $backend
    [IO.File]::WriteAllText($stateRecord,($metadata|ConvertTo-Json),$utf8)
    $alternate = Get-ProgressServiceStatus $testDirectory $backend ($selectedPort+1)
    Assert-Control ($alternate.status -eq 'port_mismatch' -and $alternate.active_port -eq $selectedPort) 'An active old port must prevent duplicate service startup'
    $marker = Join-Path $testDirectory 'worker-result.txt'
    [IO.File]::WriteAllText($marker,'preserve-business-output',$utf8)
    $stopped = Stop-ProgressService $testDirectory $backend
    Assert-Control ($stopped.status -eq 'stopped' -and -not (Test-ControlListener $selectedPort)) 'Stop must remove the verified listener'
    Assert-Control ((Test-Path -LiteralPath $stateRecord) -and (Test-Path -LiteralPath $configRecord) -and [IO.File]::ReadAllText($marker) -eq 'preserve-business-output') 'Stopping must preserve configuration, records and business files'
    Assert-Control ((Stop-ProgressService $testDirectory $backend).status -eq 'stopped') 'Repeated stop must be harmless'
    $restart = Start-ProgressService $testDirectory $backend $selectedPython
    Assert-Control ($restart.status -eq 'running' -and $restart.pid -ne $started.pid) 'Restart after a stop must create and verify a fresh server'
    Stop-ProgressService $testDirectory $backend | Out-Null
    $listener = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback,$selectedPort)
    $listener.Start()
    try {
        $conflict = Get-ProgressServiceStatus $testDirectory $backend
        $refused = $false
        try { Start-ProgressService $testDirectory $backend $selectedPython | Out-Null } catch { $refused = $true }
        Assert-Control ($conflict.status -eq 'conflict' -and $refused) 'A foreign occupied port must be reported, never replaced'
    } finally { $listener.Stop() }
    $desktop = Join-Path $testDirectory 'Desktop'
    $null = New-Item -ItemType Directory -Path $desktop
    $installer = Join-Path $scripts 'install_desktop_control.ps1'
    $output = & $installer -PythonPath $selectedPython -StateDir $testDirectory -BackendScript $backend -DesktopDir $desktop -OutputDir (Join-Path $testDirectory 'panel')
    $installed = $output | ConvertFrom-Json
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($installed.shortcut)
    $arguments = @(Split-ControlCommandLine ('"'+$installed.executable+'" '+$shortcut.Arguments))
    Assert-Control ((Test-Path -LiteralPath $installed.executable) -and $shortcut.TargetPath -eq $installed.executable -and $arguments[4] -eq $testDirectory) 'Built panel and shortcut must preserve the selected data directory'
    Assert-Control (-not (Test-ControlListener $selectedPort)) 'Installing the desktop entry must not start the service'
    # Exercise the native panel's health reader and action bridge without opening a window.
    $assembly = [Reflection.Assembly]::LoadFile($installed.executable)
    $type = $assembly.GetType('ProgressControl')
    $panel = [Activator]::CreateInstance($type,[object[]]@(,[string[]]$arguments[1..($arguments.Count-1)]))
    try {
        $flags = [Reflection.BindingFlags]::Instance -bor [Reflection.BindingFlags]::NonPublic
        $fetch = $type.GetMethod('FetchStatus',$flags)
        $nativeActionMethod = $type.GetMethod('InvokeControl',$flags)
        $observed = $fetch.Invoke($panel,@())
        Assert-Control ($observed['status'] -eq 'stopped' -and $observed['url'] -eq "http://127.0.0.1:$selectedPort/") 'Native panel must read the actual saved port without shell polling'
        $nativeStarted = $nativeActionMethod.Invoke($panel,[object[]]@('start'))
        Assert-Control ($nativeStarted['status'] -eq 'running' -and (Test-ControlListener $selectedPort)) 'Native start bridge must pass paths and parse UTF-8 JSON'
        $observed = $fetch.Invoke($panel,@())
        Assert-Control ($observed['status'] -eq 'running') 'Native health reader must recognize the verified server'
        $nativeStopped = $nativeActionMethod.Invoke($panel,[object[]]@('stop'))
        Assert-Control ($nativeStopped['status'] -eq 'stopped' -and -not (Test-ControlListener $selectedPort)) 'Native stop bridge must stop only the isolated server'
    } finally { $panel.Dispose() }
    Write-Output "Desktop service control: $checks scenarios passed; isolated directory $testDirectory"
} finally {
    $metadata = Read-ControlJson $stateRecord
    if ($metadata -and (Test-ControlPath $metadata.script $backend)) {
        $status = Get-ProgressServiceStatus $testDirectory $backend
        if ($status.status -eq 'running') { Stop-ProgressService $testDirectory $backend | Out-Null }
    }
}
