<# Builds the native Windows panel and creates one desktop shortcut. Does not start/stop the server. #>
[CmdletBinding()]
param(
    [string]$StateDir = 'D:\Codex\维护\统一任务进度\运行数据',
    [string]$BackendScript = (Join-Path $PSScriptRoot 'task_progress.py'),
    [string]$PythonPath,
    [string]$OutputDir,
    [string]$DesktopDir = [Environment]::GetFolderPath('Desktop')
)
$ErrorActionPreference = 'Stop'
if (-not [IO.Path]::IsPathRooted($StateDir)) { throw '数据目录必须是绝对路径。' }
if (-not $OutputDir) { $OutputDir = Join-Path (Split-Path -Parent $StateDir) 'work\桌面服务控制' }
if (-not [IO.Path]::IsPathRooted($OutputDir) -or -not [IO.Path]::IsPathRooted($DesktopDir)) { throw '输出和桌面目录必须是绝对路径。' }
if (-not (Test-Path -LiteralPath $BackendScript -PathType Leaf)) { throw '选定的服务脚本不存在。' }
. (Join-Path $PSScriptRoot 'setup.ps1') -StateDir $StateDir -PythonPath $PythonPath
$runtime = Resolve-ProgressPython -ExplicitPath $PythonPath
$controller = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'control_service.ps1'))
$source = Join-Path $PSScriptRoot 'ServiceControl.cs'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { $compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe' }
if (-not (Test-Path -LiteralPath $compiler)) { throw '本机缺少.NET Framework编译器，不能创建控制面板；可直接使用control_service.ps1。' }
$null = New-Item -ItemType Directory -Path $OutputDir -Force
$sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
$executable = Join-Path $OutputDir ('TaskProgressControl-' + $sourceHash.Substring(0,12) + '.exe')
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    $compileArgs = @('/nologo','/target:winexe','/optimize+',('/out:'+$executable),'/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll','/reference:System.Web.Extensions.dll',$source)
    $compileOutput = & $compiler @compileArgs 2>&1
    if ($LASTEXITCODE -ne 0) { throw ('编译控制面板失败：' + ($compileOutput -join ' ')) }
}
function Quote-DesktopArgument([string]$Value) { return '"' + [regex]::Replace([regex]::Replace($Value,'(\\*)"','$1$1\"'),'(\\+)$','$1$1') + '"' }
$values = @('--controller',$controller,'--state-dir',[IO.Path]::GetFullPath($StateDir),'--backend-script',[IO.Path]::GetFullPath($BackendScript),'--python',$runtime.executable)
$arguments = ($values | ForEach-Object { Quote-DesktopArgument $_ }) -join ' '
$shortcutPath = Join-Path $DesktopDir '任务进度服务.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
if ((Test-Path -LiteralPath $shortcutPath) -and $shortcut.Description -ne '统一任务进度服务：启动、停止和打开看板') { throw '桌面上已有同名快捷方式，未覆盖。' }
$shortcut.TargetPath = $executable
$shortcut.Arguments = $arguments
$shortcut.WorkingDirectory = $OutputDir
$shortcut.Description = '统一任务进度服务：启动、停止和打开看板'
$shortcut.IconLocation = $executable + ',0'
$shortcut.Save()
if ($shell.CreateShortcut($shortcutPath).TargetPath -ne $executable) { throw '快捷方式保存后核验失败。' }
@{shortcut=$shortcutPath; executable=$executable; controller=$controller; backend=[IO.Path]::GetFullPath($BackendScript); state_dir=[IO.Path]::GetFullPath($StateDir); python=$runtime.executable; source_sha256=$sourceHash; service_unchanged=$true} | ConvertTo-Json -Compress
