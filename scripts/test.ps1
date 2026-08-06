<#
.SYNOPSIS
Runs AgentWorldLab's routine automated checks.

.DESCRIPTION
Uses an existing project virtual environment when available, otherwise
`python3`. Routine checks force hardware tests off. Passing -Hardware also runs
the opt-in ROCm smoke test and requires -AcknowledgeHardwareRisk.

.EXAMPLE
pwsh -NoProfile -File scripts/test.ps1

.EXAMPLE
pwsh -NoProfile -File scripts/test.ps1 -Hardware -AcknowledgeHardwareRisk \
  -PythonPath /path/to/rocm-env/bin/python
#>

[CmdletBinding()]
param(
    [string] $PythonPath = "",
    [switch] $Hardware,
    [switch] $AcknowledgeHardwareRisk
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory)] [string] $FilePath,
        [Parameter(Mandatory)] [string[]] $Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
    }
}

function Resolve-PythonCommand {
    if ($PythonPath) {
        return $PythonPath
    }

    $Candidates = @(
        (Join-Path $script:RepositoryRoot ".venv/Scripts/python.exe"),
        (Join-Path $script:RepositoryRoot ".venv/bin/python")
    )
    foreach ($Candidate in $Candidates) {
        if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
            return $Candidate
        }
    }

    $Command = Get-Command "python3" -ErrorAction SilentlyContinue
    if ($null -eq $Command) {
        $Command = Get-Command "python" -ErrorAction SilentlyContinue
    }
    if ($null -eq $Command) {
        throw "No Python interpreter was found. Pass -PythonPath explicitly."
    }
    return $Command.Source
}

if ($Hardware -and -not $AcknowledgeHardwareRisk) {
    throw "Hardware tests require both -Hardware and -AcknowledgeHardwareRisk. Read docs/safety.md first."
}

$RepositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$PreviousLocation = Get-Location
$PreviousPythonPath = $env:PYTHONPATH
$PreviousHardwareSetting = $env:AGENTWORLDLAB_HARDWARE_TESTS

try {
    Set-Location $RepositoryRoot
    $Python = Resolve-PythonCommand
    $SourcePath = Join-Path $RepositoryRoot "src"
    $env:PYTHONPATH = if ($PreviousPythonPath) {
        "$SourcePath$([System.IO.Path]::PathSeparator)$PreviousPythonPath"
    }
    else {
        $SourcePath
    }

    Remove-Item Env:AGENTWORLDLAB_HARDWARE_TESTS -ErrorAction SilentlyContinue

    Write-Host "Compiling Python sources"
    Invoke-NativeCommand $Python @("-m", "compileall", "-q", "src", "tests")

    Write-Host "Running routine tests"
    Invoke-NativeCommand $Python @("-m", "unittest", "discover", "-s", "tests", "-v")

    if ($Hardware) {
        Write-Host "Running explicitly acknowledged ROCm hardware smoke test"
        $env:AGENTWORLDLAB_HARDWARE_TESTS = "1"
        Invoke-NativeCommand $Python @(
            "-m", "unittest", "discover", "-s", "tests", "-p", "test_hardware.py", "-v"
        )
    }

    Write-Host "Tests completed successfully."
}
finally {
    if ($null -eq $PreviousPythonPath) {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    }
    else {
        $env:PYTHONPATH = $PreviousPythonPath
    }

    if ($null -eq $PreviousHardwareSetting) {
        Remove-Item Env:AGENTWORLDLAB_HARDWARE_TESTS -ErrorAction SilentlyContinue
    }
    else {
        $env:AGENTWORLDLAB_HARDWARE_TESTS = $PreviousHardwareSetting
    }
    Set-Location $PreviousLocation
}

