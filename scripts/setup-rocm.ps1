<#
.SYNOPSIS
Creates AgentWorldLab's project-local ROCm 7.2 environment.

.DESCRIPTION
Creates `.venv-rocm72` with CPython 3.12, upgrades pip, installs the pinned AMD
ROCm 7.2.1 wheels, and installs AgentWorldLab with its Transformers dependencies.
The script validates package imports and versions without opening a GPU device
or loading model weights. Network installation requires an explicit
-AcknowledgeNetworkInstall switch.

.EXAMPLE
pwsh -NoProfile -File scripts/setup-rocm.ps1 -AcknowledgeNetworkInstall

.EXAMPLE
pwsh -NoProfile -File scripts/setup-rocm.ps1 `
  -PythonPath /path/to/python3.12 -AcknowledgeNetworkInstall
#>

[CmdletBinding()]
param(
    [string] $PythonPath = "",
    [string] $VirtualEnvironment = ".venv-rocm72",
    [switch] $SkipDependencyInstall,
    [switch] $AcknowledgeNetworkInstall
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

function Resolve-RepositoryPath {
    param([Parameter(Mandatory)] [string] $Path)

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $script:RepositoryRoot $Path))
}

function Resolve-CommandPath {
    param([Parameter(Mandatory)] [string] $Name)

    if (Test-Path -LiteralPath $Name -PathType Leaf) {
        return [System.IO.Path]::GetFullPath($Name)
    }
    $Command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -ne $Command) {
        return $Command.Source
    }
    return $null
}

function Get-PythonMajorMinor {
    param([Parameter(Mandatory)] [string] $FilePath)

    try {
        $VersionOutput = @(
            & $FilePath "-c" "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        )
        $ExitCode = $LASTEXITCODE
    }
    catch {
        return $null
    }
    if ($ExitCode -ne 0 -or $VersionOutput.Count -eq 0) {
        return $null
    }

    $Version = [string] ($VersionOutput | Select-Object -Last 1)
    if ([string]::IsNullOrWhiteSpace($Version)) {
        return $null
    }
    return $Version.Trim()
}

function Resolve-BootstrapPython {
    if ($PythonPath) {
        $Resolved = Resolve-CommandPath $PythonPath
        if ($null -eq $Resolved) {
            throw "The requested Python interpreter was not found: $PythonPath"
        }
        return $Resolved
    }

    $Resolved = Resolve-CommandPath "python3.12"
    if ($null -ne $Resolved -and (Get-PythonMajorMinor $Resolved) -eq "3.12") {
        return $Resolved
    }

    $Pyenv = Resolve-CommandPath "pyenv"
    if ($null -ne $Pyenv) {
        try {
            $PyenvPrefixOutput = @(& $Pyenv "prefix" "3.12" 2>$null)
            $PyenvExitCode = $LASTEXITCODE
        }
        catch {
            $PyenvPrefixOutput = @()
            $PyenvExitCode = 1
        }
        if ($PyenvExitCode -eq 0 -and $PyenvPrefixOutput.Count -gt 0) {
            $PyenvPrefix = [string] ($PyenvPrefixOutput | Select-Object -Last 1)
            $PyenvPython = Join-Path $PyenvPrefix.Trim() "bin/python"
            if ((Test-Path -LiteralPath $PyenvPython -PathType Leaf) -and
                (Get-PythonMajorMinor $PyenvPython) -eq "3.12") {
                return [System.IO.Path]::GetFullPath($PyenvPython)
            }
        }
    }

    foreach ($Name in @("python3", "python")) {
        $Resolved = Resolve-CommandPath $Name
        if ($null -ne $Resolved -and (Get-PythonMajorMinor $Resolved) -eq "3.12") {
            return $Resolved
        }
    }

    throw "CPython 3.12 was not found. Install it with pyenv or pass -PythonPath explicitly."
}

if (-not $IsLinux) {
    throw "The pinned ROCm wheels support Linux only. Build and routine test scripts remain cross-platform."
}
if ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne
    [System.Runtime.InteropServices.Architecture]::X64) {
    throw "The pinned ROCm wheels require an x86_64 host."
}
if (-not $SkipDependencyInstall -and -not $AcknowledgeNetworkInstall) {
    throw "Creating the ROCm environment downloads large packages. Re-run with -AcknowledgeNetworkInstall."
}

$RepositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$PreviousLocation = Get-Location

try {
    Set-Location $RepositoryRoot
    $EnvironmentPath = Resolve-RepositoryPath $VirtualEnvironment
    $EnvironmentPython = Join-Path $EnvironmentPath "bin/python"

    if (-not (Test-Path -LiteralPath $EnvironmentPython -PathType Leaf)) {
        $BootstrapPython = Resolve-BootstrapPython
        $BootstrapVersion = Get-PythonMajorMinor $BootstrapPython
        if ($BootstrapVersion -ne "3.12") {
            $ReportedVersion = if ($null -eq $BootstrapVersion) { "unavailable" } else { $BootstrapVersion }
            throw "The ROCm environment requires CPython 3.12; '$BootstrapPython' reports $ReportedVersion."
        }
        Write-Host "Creating ROCm environment at $EnvironmentPath with $BootstrapPython"
        Invoke-NativeCommand $BootstrapPython @("-m", "venv", $EnvironmentPath)
    }

    if (-not (Test-Path -LiteralPath $EnvironmentPython -PathType Leaf)) {
        throw "The ROCm environment does not contain a Python interpreter: $EnvironmentPath"
    }

    $EnvironmentVersion = Get-PythonMajorMinor $EnvironmentPython
    if ($EnvironmentVersion -ne "3.12") {
        $ReportedVersion = if ($null -eq $EnvironmentVersion) { "unavailable" } else { $EnvironmentVersion }
        throw "The existing environment must use CPython 3.12; it reports $ReportedVersion. Choose another -VirtualEnvironment path."
    }

    if (-not $SkipDependencyInstall) {
        Write-Host "Upgrading pip in the ROCm environment"
        Invoke-NativeCommand $EnvironmentPython @("-m", "pip", "install", "--upgrade", "pip")

        $RocmRequirements = Join-Path $RepositoryRoot "requirements/rocm72.txt"
        Write-Host "Installing the pinned ROCm 7.2.1 foundation"
        Invoke-NativeCommand $EnvironmentPython @("-m", "pip", "install", "-r", $RocmRequirements)

        Write-Host "Installing AgentWorldLab and its Transformers dependencies"
        Invoke-NativeCommand $EnvironmentPython @(
            "-m", "pip", "install",
            "--constraint", $RocmRequirements,
            "--editable", ".[transformers]"
        )
    }

    $ValidationCode = @'
import sys

import torch
import transformers
from transformers import AutoModelForMultimodalLM, AutoProcessor

if sys.version_info[:2] != (3, 12):
    raise SystemExit(f"expected Python 3.12, found {sys.version.split()[0]}")
if not torch.__version__.startswith("2.9.1+rocm7.2.1"):
    raise SystemExit(f"expected torch 2.9.1+rocm7.2.1, found {torch.__version__}")
if torch.version.hip is None or not torch.version.hip.startswith("7.2"):
    raise SystemExit(f"expected a ROCm 7.2 torch build, found HIP {torch.version.hip!r}")
if int(transformers.__version__.split(".", 1)[0]) < 5:
    raise SystemExit(f"expected Transformers 5 or newer, found {transformers.__version__}")

print(f"Python {sys.version.split()[0]}")
print(f"torch {torch.__version__}; HIP {torch.version.hip}")
print(f"Transformers {transformers.__version__}")
print("Qwen-compatible Transformers entry points are importable")
'@

    Write-Host "Validating the environment without accessing the GPU or model weights"
    Invoke-NativeCommand $EnvironmentPython @("-c", $ValidationCode)
    Invoke-NativeCommand $EnvironmentPython @("-m", "pip", "check")

    Write-Host "ROCm environment is ready: $EnvironmentPython"
    Write-Host "Next: pwsh -NoProfile -File scripts/test.ps1 -Hardware -AcknowledgeHardwareRisk"
}
finally {
    Set-Location $PreviousLocation
}
