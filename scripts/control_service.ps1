<# Controls only the verified progress server; preserves workers and state files. #>
[CmdletBinding()]
param(
    [ValidateSet('status','start','stop')][string]$Action = 'status',
    [string]$StateDir = 'D:\Codex\维护\统一任务进度\运行数据',
    [string]$BackendScript = (Join-Path $PSScriptRoot 'task_progress.py'),
    [string]$PythonPath,
    [int]$Port = 0
)
function Test-ControlPath {
    param([string]$Left, [string]$Right)
    try { return [IO.Path]::GetFullPath($Left).TrimEnd('\','/') -ieq [IO.Path]::GetFullPath($Right).TrimEnd('\','/') } catch { return $false }
}
function Read-ControlJson {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path -PathType Leaf) { return [IO.File]::ReadAllText($Path,[Text.Encoding]::UTF8) | ConvertFrom-Json }
    return $null
}
function Convert-ControlPort {
    param($Value)
    if ($Value -is [bool] -or [string]$Value -notmatch '^\d+$') { throw '端口必须是1至65535的整数。' }
    $number = [int]$Value
    if ($number -lt 1 -or $number -gt 65535) { throw '端口必须是1至65535的整数。' }
    return $number
}
function Get-ControlPort {
    param([string]$Directory,[int]$SelectedPort=0)
    if ($SelectedPort) { return Convert-ControlPort $SelectedPort }
    if ($env:TASK_PROGRESS_PORT) { return Convert-ControlPort $env:TASK_PROGRESS_PORT }
    foreach ($name in @('服务配置.json','服务状态.json')) {
        $record = Read-ControlJson (Join-Path $Directory $name)
        if ($record) {
            if ($record.identity -ne 'agent-global-progress-v1') { throw "服务配置身份不匹配：$name" }
            return Convert-ControlPort $record.port
        }
    }
    return 8790
}
function Read-ControlHealth {
    param([int]$SelectedPort)
    $request = [Net.HttpWebRequest]::Create("http://127.0.0.1:$SelectedPort/api/health")
    $request.Proxy=$null; $request.Timeout=1000; $request.ReadWriteTimeout=1000
    $response=$null; $reader=$null
    try {
        $response=$request.GetResponse()
        $reader=New-Object IO.StreamReader($response.GetResponseStream(),[Text.Encoding]::UTF8)
        return $reader.ReadToEnd() | ConvertFrom-Json
    } catch { return $null } finally {
        if ($reader) { $reader.Dispose() }; if ($response) { $response.Dispose() }
    }
}
function Test-ControlListener {
    param([int]$SelectedPort)
    $client=New-Object Net.Sockets.TcpClient
    try {
        $pending=$client.BeginConnect('127.0.0.1',$SelectedPort,$null,$null)
        if (-not $pending.AsyncWaitHandle.WaitOne(250)) { return $false }
        $client.EndConnect($pending); return $true
    } catch { return $false } finally { $client.Close() }
}
function Test-ControlHealth {
    param($Health,[string]$Directory,[int]$SelectedPort)
    return $Health -and $Health.identity -eq 'agent-global-progress-v1' -and $Health.port -eq $SelectedPort -and
        (Test-ControlPath $Health.state_dir $Directory) -and $Health.pid -isnot [bool] -and [string]$Health.pid -match '^\d+$' -and $Health.pid -gt 0
}
function Get-ProgressServiceStatus {
    param([string]$Directory,[string]$ScriptPath,[int]$SelectedPort=0)
    $actualPort=Get-ControlPort $Directory $SelectedPort
    $metadata=Read-ControlJson (Join-Path $Directory '服务状态.json')
    if ($metadata -and $metadata.identity -eq 'agent-global-progress-v1' -and $metadata.port -ne $actualPort) {
        $oldPort=Convert-ControlPort $metadata.port; $oldHealth=Read-ControlHealth $oldPort
        if (Test-ControlHealth $oldHealth $Directory $oldPort) {
            return @{status='port_mismatch';port=$actualPort;active_port=$oldPort;url="http://127.0.0.1:$oldPort/";pid=$oldHealth.pid;message='原服务仍在另一端口运行，请先沿用原端口或明确停止后再切换。'}
        }
    }
    $health=Read-ControlHealth $actualPort
    $result=@{status='stopped';port=$actualPort;url="http://127.0.0.1:$actualPort/";pid=$null;message='服务已停止'}
    if (Test-ControlHealth $health $Directory $actualPort) {
        $result.pid=$health.pid
        if ($metadata -and $metadata.identity -eq $health.identity -and $metadata.pid -eq $health.pid -and $metadata.port -eq $actualPort -and (Test-ControlPath $metadata.script $ScriptPath)) {
            $result.status='running';$result.message='服务运行中'
        } else { $result.status='unverified';$result.message='看板在线，但启动记录或服务脚本不匹配，不能通过此入口停止。' }
    } elseif ($health -or (Test-ControlListener $actualPort)) {
        $result.status='conflict';$result.message='端口被其他程序占用，或服务尚未通过身份核对。'
    }
    return $result
}
function Test-ControlCommandLine {
    param([string[]]$Arguments,[string]$ScriptPath,[string]$Directory,[int]$SelectedPort)
    $index=1
    while ($index -lt $Arguments.Count -and $Arguments[$index] -in @('-B','-u')) { $index++ }
    if ($index+1 -ge $Arguments.Count -or -not (Test-ControlPath $Arguments[$index] $ScriptPath) -or $Arguments[$index+1] -ne 'serve') { return $false }
    $stateIndex=[Array]::IndexOf($Arguments,'--state-dir');$portIndex=[Array]::IndexOf($Arguments,'--port')
    return $stateIndex -gt $index -and $stateIndex+1 -lt $Arguments.Count -and $portIndex -gt $index -and $portIndex+1 -lt $Arguments.Count -and
        (Test-ControlPath $Arguments[$stateIndex+1] $Directory) -and $Arguments[$portIndex+1] -eq [string]$SelectedPort
}
function Split-ControlCommandLine {
    param([string]$CommandLine)
    if (-not ('ProgressControlArguments' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ProgressControlArguments {
    [DllImport("shell32.dll", SetLastError=true)] static extern IntPtr CommandLineToArgvW([MarshalAs(UnmanagedType.LPWStr)] string command, out int count);
    [DllImport("kernel32.dll")] static extern IntPtr LocalFree(IntPtr memory);
    public static string[] Split(string command) {
        int count;IntPtr memory=CommandLineToArgvW(command,out count);
        if(memory==IntPtr.Zero)throw new System.ComponentModel.Win32Exception();
        try{string[] args=new string[count];for(int i=0;i<count;i++)args[i]=Marshal.PtrToStringUni(Marshal.ReadIntPtr(memory,i*IntPtr.Size));return args;}
        finally{LocalFree(memory);}
    }
}
'@
    }
    return [ProgressControlArguments]::Split($CommandLine)
}
function Start-ProgressService {
    param([string]$Directory,[string]$ScriptPath,[string]$SelectedPython,[int]$SelectedPort=0)
    $status=Get-ProgressServiceStatus $Directory $ScriptPath $SelectedPort
    if ($status.status -eq 'running') { return $status }
    if ($status.status -ne 'stopped') { throw $status.message }
    if (-not (Test-Path -LiteralPath $ScriptPath -PathType Leaf)) { throw '原服务脚本不存在，请修复桌面入口。' }
    . (Join-Path $PSScriptRoot 'setup.ps1')
    $runtime=Resolve-ProgressPython -ExplicitPath $SelectedPython
    $arguments=@('-X','utf8','-B',$ScriptPath,'ensure','--state-dir',$Directory,'--port',[string]$status.port)
    $output=& $runtime.executable @arguments 2>&1
    if ($LASTEXITCODE -ne 0) { throw ('启动失败：'+($output -join ' ')) }
    $verified=Get-ProgressServiceStatus $Directory $ScriptPath $status.port
    if ($verified.status -ne 'running') { throw ('启动后核验失败：'+$verified.message) }
    return $verified
}
function Stop-ProgressService {
    param([string]$Directory,[string]$ScriptPath,[int]$SelectedPort=0)
    $status=Get-ProgressServiceStatus $Directory $ScriptPath $SelectedPort
    if ($status.status -eq 'stopped') { return $status }
    if ($status.status -ne 'running') { throw $status.message }
    $process=[Diagnostics.Process]::GetProcessById([int]$status.pid)
    try {
        $null=$process.Handle;$started=$process.StartTime.ToUniversalTime()
        $actual=Get-CimInstance Win32_Process -Filter "ProcessId=$($status.pid)"
        $arguments=@(Split-ControlCommandLine $actual.CommandLine)
        if (-not $actual -or [Math]::Abs(($actual.CreationDate.ToUniversalTime()-$started).TotalSeconds) -gt 0.05 -or
            -not (Test-ControlCommandLine $arguments $ScriptPath $Directory $status.port)) { throw '进程与服务启动记录不一致，停止操作已取消。' }
        $again=Get-ProgressServiceStatus $Directory $ScriptPath $status.port
        if ($again.status -ne 'running' -or $again.pid -ne $status.pid) { throw '停止前服务身份或进程已变化，请刷新状态。' }
        $process.Kill()
        if (-not $process.WaitForExit(3000)) { throw '服务未按时退出，请核对进程。' }
    } finally { $process.Dispose() }
    $after=Get-ProgressServiceStatus $Directory $ScriptPath $status.port
    if ($after.status -ne 'stopped') { throw ('停止后端口仍在使用，可能有新任务重新启动服务：'+$after.message) }
    return $after
}
if ($MyInvocation.InvocationName -ne '.') {
    $ErrorActionPreference='Stop'
    try {
        if (-not [IO.Path]::IsPathRooted($StateDir)) { throw '数据目录必须是绝对路径。' }
        $result=switch ($Action) {
            'start' { Start-ProgressService $StateDir $BackendScript $PythonPath $Port }
            'stop' { Stop-ProgressService $StateDir $BackendScript $Port }
            default { Get-ProgressServiceStatus $StateDir $BackendScript $Port }
        }
        [Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
        $result | ConvertTo-Json -Compress | Write-Output
    } catch {
        [Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
        @{status='error';message=$_.Exception.Message} | ConvertTo-Json -Compress | Write-Output
        exit 1
    }
}
