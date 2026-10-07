# Test installation decisions without installing or changing this computer.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\scripts\setup.ps1')
$script:installCalls = 0
$script:mode = 'existing'
function Find-ProgressPython {
    param([string]$ExplicitPath)
    if ($script:mode -eq 'existing' -or ($script:mode -eq 'install' -and $script:installCalls -gt 0)) {
        return @{executable='verified-python'; version='3.13.0'}
    }
    return $null
}
function Install-ProgressPython { $script:installCalls++ }
function Assert-Setup($condition, $message) { if (-not $condition) { throw $message } }
$runtime = Resolve-ProgressPython -AllowInstall
Assert-Setup ($runtime.executable -eq 'verified-python' -and $script:installCalls -eq 0) 'Existing runtime must not trigger installation'
$script:mode = 'missing'
try { Resolve-ProgressPython | Out-Null; throw 'Expected failure' } catch {
    Assert-Setup ($_.Exception.Message -match 'InstallMissing') 'Detection-only mode must report a missing runtime'
}
Assert-Setup ($script:installCalls -eq 0) 'Detection-only mode must not install'
try { Resolve-ProgressPython -ExplicitPath 'selected-python' -AllowInstall | Out-Null; throw 'Expected failure' } catch {
    Assert-Setup ($_.Exception.Message -match 'selected Python') 'An invalid explicit interpreter must not silently be replaced'
}
Assert-Setup ($script:installCalls -eq 0) 'Explicit interpreter selection must be respected'
$script:mode = 'install'
$runtime = Resolve-ProgressPython -AllowInstall
Assert-Setup ($runtime.executable -eq 'verified-python' -and $script:installCalls -eq 1) 'Install missing runtime once, then verify discovery'
$script:mode = 'missing'
try { Resolve-ProgressPython -AllowInstall | Out-Null; throw 'Expected failure' } catch {
    Assert-Setup ($_.Exception.Message -match 'did not pass verification') 'Installer success must not substitute for dependency verification'
}
Assert-Setup ($script:installCalls -eq 2) 'Failed verification must stop without an unbounded install loop'
Write-Output 'Setup behavior: 5 scenarios passed (no real installation)'
