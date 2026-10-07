<# Windows bootstrap: discover usable Python, install only if requested and missing.
   Existing services/workers, global PATH and execution policy are not changed.
#>
[CmdletBinding()]
param(
    [string]$PythonPath,
    [string]$StateDir,
    [ValidateRange(1,65535)][int]$Port,
    [switch]$InstallMissing
)

function Find-ProgressPython {
    param([string]$ExplicitPath)
    $checker = Join-Path $PSScriptRoot 'check_environment.py'
    if (-not (Test-Path -LiteralPath $checker -PathType Leaf)) {
        throw 'Skill package is incomplete: restore scripts/check_environment.py before checking dependencies.'
    }
    $candidates = @()
    if ($ExplicitPath) {
        $candidates += @{Path=$ExplicitPath; Prefix=@()}
    } else {
        if ($env:VIRTUAL_ENV) {
            $candidates += @{Path=(Join-Path $env:VIRTUAL_ENV 'Scripts\python.exe'); Prefix=@()}
        }
        $bundled = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
        $candidates += @{Path=$bundled; Prefix=@()}
        foreach ($name in @('py','python','python3')) {
            $command = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue
            if ($command) {
                # Store aliases can open the Store instead of running an interpreter.
                if ($name -ne 'py' -and $command.Source -match '\\Microsoft\\WindowsApps\\python[^\\]*\.exe$') { continue }
                $prefix = @()
                if ($name -eq 'py') { $prefix = @('-3') }
                $candidates += @{Path=$command.Source; Prefix=$prefix}
            }
        }
        if ($env:LOCALAPPDATA) {
            foreach ($file in @(Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python*\python.exe') -File -ErrorAction SilentlyContinue | Sort-Object FullName -Descending)) {
                $candidates += @{Path=$file.FullName; Prefix=@()}
            }
        }
        # Registered full Python installs may be usable without PATH or py.exe.
        foreach ($root in @('HKCU:\Software\Python\PythonCore','HKLM:\Software\Python\PythonCore','HKLM:\Software\WOW6432Node\Python\PythonCore')) {
            foreach ($tag in @(Get-ChildItem -LiteralPath $root -ErrorAction SilentlyContinue)) {
                $registration = Get-ItemProperty -LiteralPath (Join-Path $tag.PSPath 'InstallPath') -ErrorAction SilentlyContinue
                if ($registration) {
                    $executable = $registration.ExecutablePath
                    if (-not $executable -and $registration.'(default)') { $executable = Join-Path $registration.'(default)' 'python.exe' }
                    if ($executable) { $candidates += @{Path=$executable; Prefix=@()} }
                }
            }
        }
    }
    $previousAutoInstall = $env:PYTHON_MANAGER_AUTOMATIC_INSTALL
    try {
        # A check must not silently install a runtime through the new py manager.
        $env:PYTHON_MANAGER_AUTOMATIC_INSTALL = 'false'
        foreach ($candidate in $candidates) {
            if (-not (Test-Path -LiteralPath $candidate.Path -PathType Leaf)) { continue }
            try {
                $arguments = @($candidate.Prefix) + @('-X','utf8','-B',$checker,'--runtime-only')
                $output = & $candidate.Path @arguments 2>$null
                if ($LASTEXITCODE -ne 0) { continue }
                $report = ($output -join "`n") | ConvertFrom-Json
                if ($report.ready) { return $report.checks.runtime }
            } catch { continue }
        }
    } finally {
        $env:PYTHON_MANAGER_AUTOMATIC_INSTALL = $previousAutoInstall
    }
    return $null
}

function Install-ProgressPython {
    $manager = Get-Command winget -CommandType Application -ErrorAction SilentlyContinue
    if (-not $manager) {
        throw 'WinGet is unavailable. Install a full Python 3.10+ runtime from https://www.python.org/downloads/windows/ and rerun setup with -PythonPath. See references/environment.md for the agent fallback.'
    }
    Write-Host 'Installing missing full Python runtime for the current user...'
    $installerArguments = '/quiet InstallAllUsers=0 PrependPath=0 Include_lib=1 Include_pip=0 Include_test=0 Include_launcher=0'
    & $manager.Source install --id Python.Python.3.13 --exact --source winget --scope user --silent --disable-interactivity --override $installerArguments --accept-package-agreements --accept-source-agreements | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Python installation did not succeed (WinGet exit $LASTEXITCODE). Check the installer result before continuing."
    }
}

function Resolve-ProgressPython {
    param([string]$ExplicitPath, [switch]$AllowInstall)
    $runtime = Find-ProgressPython -ExplicitPath $ExplicitPath
    if ($runtime) { return $runtime }
    if ($ExplicitPath) {
        throw 'The selected Python is missing, too old, or has incomplete standard-library modules. Repair it or provide another verified full Python path.'
    }
    if (-not $AllowInstall) {
        throw 'No usable Python 3.10+ was found. Run setup.ps1 -InstallMissing to install the missing runtime.'
    }
    Install-ProgressPython
    # Re-scan known install paths: the current shell PATH need not be refreshed.
    $runtime = Find-ProgressPython
    if (-not $runtime) { throw 'Installation returned, but Python dependencies did not pass verification. Do not start a worker.' }
    return $runtime
}

function Invoke-ProgressSetup {
    param([string]$SelectedPython, [string]$SelectedState, [int]$SelectedPort, [switch]$AllowInstall)
    $runtime = Resolve-ProgressPython -ExplicitPath $SelectedPython -AllowInstall:$AllowInstall
    $arguments = @('-X','utf8','-B',(Join-Path $PSScriptRoot 'check_environment.py'))
    if ($SelectedState) { $arguments += @('--state-dir',$SelectedState) }
    if ($SelectedPort) { $arguments += @('--port',[string]$SelectedPort,'--select-port') }
    $reportText = & $runtime.executable @arguments
    $code = $LASTEXITCODE
    $reportText | Write-Output
    if ($code -ne 0) { return $code }
    Write-Host ('Environment ready. Use this verified interpreter: ' + $runtime.executable)
    return 0
}

if ($MyInvocation.InvocationName -ne '.') {
    # Keep JSON output separate from the process return code.
    $ErrorActionPreference = 'Stop'
    try {
        $result = @(Invoke-ProgressSetup -SelectedPython $PythonPath -SelectedState $StateDir -SelectedPort $Port -AllowInstall:$InstallMissing)
        $result | Select-Object -SkipLast 1 | Write-Output
        exit [int]$result[-1]
    } catch {
        Write-Error $_ -ErrorAction Continue
        exit 1
    }
}
