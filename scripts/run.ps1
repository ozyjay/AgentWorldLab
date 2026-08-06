<#
.SYNOPSIS
Runs one safe AgentWorldLab transition or trajectory.

.DESCRIPTION
Runs the mock backend by default. The selected configuration is inspected before
execution; any non-mock backend requires -AcknowledgeHardwareRisk. Model output
remains untrusted observation data and is never executed by this script.

.EXAMPLE
pwsh -NoProfile -File scripts/run.ps1

.EXAMPLE
pwsh -NoProfile -File scripts/run.ps1 -Trajectory

.EXAMPLE
pwsh -NoProfile -File scripts/run.ps1 -Model agentworld \
  -AcknowledgeHardwareRisk
#>

[CmdletBinding()]
param(
    [string] $PythonPath = "",
    [string] $Config = "configs/default.toml",
    [string] $Model = "mock",
    [string] $Fixture = "",
    [string] $Action = "",
    [Nullable[int]] $MaxInputTokens,
    [Nullable[int]] $MaxOutputTokens,
    [double] $Temperature = 0.0,
    [int] $Seed = 0,
    [switch] $Trajectory,
    [switch] $Warm,
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
        (Join-Path $script:RepositoryRoot ".venv-rocm72/Scripts/python.exe"),
        (Join-Path $script:RepositoryRoot ".venv-rocm72/bin/python"),
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

function Resolve-RepositoryPath {
    param([Parameter(Mandatory)] [string] $Path)

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $script:RepositoryRoot $Path))
}

$RepositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$PreviousLocation = Get-Location
$PreviousPythonPath = $env:PYTHONPATH

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

    $ConfigPath = Resolve-RepositoryPath $Config
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
        throw "Configuration file does not exist: $ConfigPath"
    }

    $BackendOutput = & $Python "-c" @"
from agentworldlab.config import load_config
import sys
print(load_config(sys.argv[1]).model(sys.argv[2]).backend)
"@ $ConfigPath $Model
    if ($LASTEXITCODE -ne 0) {
        throw "Could not validate model '$Model' in configuration '$ConfigPath'."
    }
    $Backend = ($BackendOutput | Select-Object -Last 1).Trim()
    if ($Backend -ne "mock" -and -not $AcknowledgeHardwareRisk) {
        throw "Backend '$Backend' requires -AcknowledgeHardwareRisk. Read docs/safety.md and docs/validation.md first."
    }

    if ($Trajectory -and $Action) {
        throw "-Action is valid only for a single-transition run."
    }

    if (-not $Fixture) {
        $Fixture = if ($Trajectory) {
            "fixtures/terminal/stateful-trajectory-v1.json"
        }
        else {
            "fixtures/terminal/single-transition-v1.json"
        }
    }
    $FixturePath = Resolve-RepositoryPath $Fixture
    if (-not (Test-Path -LiteralPath $FixturePath -PathType Leaf)) {
        throw "Fixture file does not exist: $FixturePath"
    }

    $CommandArguments = @(
        "-m", "agentworldlab", "--config", $ConfigPath,
        $(if ($Trajectory) { "run-trajectory" } else { "run" }),
        "--model", $Model,
        "--fixture", $FixturePath,
        "--temperature", $Temperature.ToString([System.Globalization.CultureInfo]::InvariantCulture),
        "--seed", $Seed.ToString([System.Globalization.CultureInfo]::InvariantCulture)
    )
    if ($Action) {
        $CommandArguments += @("--action", $Action)
    }
    if ($null -ne $MaxInputTokens) {
        $CommandArguments += @("--max-input-tokens", $MaxInputTokens.Value.ToString())
    }
    if ($null -ne $MaxOutputTokens) {
        $CommandArguments += @("--max-output-tokens", $MaxOutputTokens.Value.ToString())
    }
    if ($Warm) {
        $CommandArguments += "--warm"
    }

    Write-Host "Running model '$Model' through backend '$Backend'"
    Invoke-NativeCommand $Python $CommandArguments
}
finally {
    if ($null -eq $PreviousPythonPath) {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    }
    else {
        $env:PYTHONPATH = $PreviousPythonPath
    }
    Set-Location $PreviousLocation
}
