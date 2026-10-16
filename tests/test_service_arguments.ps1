$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '../scripts/control_service.ps1')
$backend='D:\task-progress\scripts\task_progress.py'
$stateDir='D:\task-progress\state'
$tail=@($backend,'serve','--state-dir',$stateDir,'--port','8790')
foreach($options in @(@(),@('-B'),@('-X','utf8','-B'),@('-Xutf8','-u'))) {
    if (-not (Test-ControlCommandLine (@('python.exe')+$options+$tail) $backend $stateDir 8790)) { throw 'Valid UTF-8 command rejected' }
}
foreach($argsToReject in @(@('python.exe','-X','other')+$tail,@('python.exe','-c','print(1)')+$tail,@('python.exe')+@('D:\other.py','serve','--state-dir',$stateDir,'--port','8790'))) {
    if (Test-ControlCommandLine $argsToReject $backend $stateDir 8790) { throw 'Unrelated command accepted' }
}
if (Test-ControlCommandLine (@('python.exe','-X','utf8')+$tail) $backend 'D:\other' 8790) { throw 'Different state accepted' }
if (Test-ControlCommandLine (@('python.exe','-X','utf8')+$tail) $backend $stateDir 8791) { throw 'Different port accepted' }
Write-Output 'Service argument checks passed'
