<#
.SYNOPSIS
Builds AgentWorldLab source and wheel distributions in an isolated environment.

.DESCRIPTION
Creates a build virtual environment when needed, upgrades pip, installs the
Python build frontend, and runs `python -m build`. Existing output files are not
deleted. Use -SkipDependencyInstall only when the selected environment already
contains a compatible `build` package.

.EXAMPLE
pwsh -NoProfile -File scripts/build.ps1

.EXAMPLE
pwsh -NoProfile -File scripts/build.ps1 -SkipDependencyInstall
#>

[CmdletBinding()]
param(
    [string] $PythonPath = "",
    [string] $VirtualEnvironment = ".venv-build",
    [string] $OutputDirectory = "dist",
    [switch] $SkipDependencyInstall
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

function Resolve-BootstrapPython {
    if ($PythonPath) {
        return $PythonPath
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

$RepositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$PreviousLocation = Get-Location

try {
    Set-Location $RepositoryRoot
    $EnvironmentPath = Resolve-RepositoryPath $VirtualEnvironment
    $UnixPython = Join-Path $EnvironmentPath "bin/python"
    $WindowsPython = Join-Path $EnvironmentPath "Scripts/python.exe"

    if (-not (Test-Path -LiteralPath $UnixPython -PathType Leaf) -and
        -not (Test-Path -LiteralPath $WindowsPython -PathType Leaf)) {
        Write-Host "Creating build environment at $EnvironmentPath"
        $BootstrapPython = Resolve-BootstrapPython
        Invoke-NativeCommand $BootstrapPython @("-m", "venv", $EnvironmentPath)
    }

    $BuildPython = if (Test-Path -LiteralPath $WindowsPython -PathType Leaf) {
        $WindowsPython
    }
    else {
        $UnixPython
    }

    if (-not (Test-Path -LiteralPath $BuildPython -PathType Leaf)) {
        throw "The build environment does not contain a Python interpreter: $EnvironmentPath"
    }

    if (-not $SkipDependencyInstall) {
        Write-Host "Upgrading pip in the build environment"
        Invoke-NativeCommand $BuildPython @("-m", "pip", "install", "--upgrade", "pip")
        Write-Host "Installing the build frontend"
        Invoke-NativeCommand $BuildPython @("-m", "pip", "install", "--upgrade", "build")
    }
    else {
        Invoke-NativeCommand $BuildPython @("-c", "import build")
    }

    $ResolvedOutput = Resolve-RepositoryPath $OutputDirectory
    Write-Host "Building distributions into $ResolvedOutput"
    Invoke-NativeCommand $BuildPython @("-m", "build", "--outdir", $ResolvedOutput, $RepositoryRoot)
    Write-Host "Build completed successfully."
}
finally {
    Set-Location $PreviousLocation
}
