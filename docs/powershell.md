# PowerShell scripts

The build, test, and run scripts under `scripts/` support PowerShell 7 on Linux,
macOS, and Windows. The ROCm setup script is Linux x86_64 only because its AMD
wheels target that platform. All scripts resolve paths from the repository
root, do not require shell activation of a virtual environment, and stop on the
first failed native command.

## ROCm runtime setup

```powershell
pwsh -NoProfile -File scripts/setup-rocm.ps1 `
  -AcknowledgeNetworkInstall
```

This creates `.venv-rocm72` with Python 3.12 and the hash-pinned AMD ROCm 7.2.1
torch, torchvision, and Triton wheels in `requirements/rocm72.txt`. It upgrades
pip before installing packages, installs `.[transformers]`, runs `pip check`,
and verifies imports and versions. Validation does not access the GPU or load
the cached model.

The script first tries `python3.12`, then an installed pyenv 3.12 version, then
a system `python3` or `python` only if it is Python 3.12. Override discovery
when necessary:

```powershell
pwsh -NoProfile -File scripts/setup-rocm.ps1 `
  -PythonPath /path/to/python3.12 `
  -VirtualEnvironment .venv-rocm72 `
  -AcknowledgeNetworkInstall
```

`-AcknowledgeNetworkInstall` confirms the large package download. It does not
authorise a model load or hardware test. `-SkipDependencyInstall` is intended
only to revalidate an already populated environment; it creates no packages and
will fail if the required packages are absent.

After setup, the test and run scripts prefer `.venv-rocm72` automatically. Pass
`-PythonPath` only to override it.

## Build

```powershell
pwsh -NoProfile -File scripts/build.ps1
```

The build script:

1. creates `.venv-build` if it does not exist;
2. upgrades pip in that isolated environment;
3. installs or updates the Python `build` frontend;
4. creates a source distribution and wheel under `dist/`.

It does not delete existing artefacts. Options:

```powershell
pwsh -NoProfile -File scripts/build.ps1 `
  -PythonPath python3 `
  -VirtualEnvironment .venv-build `
  -OutputDirectory dist
```

Use `-SkipDependencyInstall` only when the build environment already contains
the `build` package. Building may access the Python package index while setting
up dependencies; it never downloads model weights.

## Test

```powershell
pwsh -NoProfile -File scripts/test.ps1
```

The routine path compiles `src` and `tests`, runs the complete unittest suite,
and forces hardware checks off even if the parent environment has
`AGENTWORLDLAB_HARDWARE_TESTS` set.

The ROCm smoke test is separately gated:

```powershell
pwsh -NoProfile -File scripts/test.ps1 `
  -Hardware `
  -AcknowledgeHardwareRisk
```

This acknowledgement does not relax any repository safety control. Run it only
after the read-only inspection and authorisation described in
[validation.md](validation.md).

## Run

The default command uses the deterministic mock backend and the single terminal
fixture:

```powershell
pwsh -NoProfile -File scripts/run.ps1
```

Run the mock stateful trajectory:

```powershell
pwsh -NoProfile -File scripts/run.ps1 -Trajectory
```

Select another synthetic fixture or action:

```powershell
pwsh -NoProfile -File scripts/run.ps1 `
  -Fixture fixtures/swe/missing-dependency-v1.json `
  -Action "Run the synthetic test suite"
```

The script loads the selected configuration using AgentWorldLab before running.
Any backend other than `mock` requires an explicit acknowledgement:

```powershell
pwsh -NoProfile -File scripts/run.ps1 `
  -Model agentworld `
  -AcknowledgeHardwareRisk
```

Other options include `-Config`, `-MaxInputTokens`, `-MaxOutputTokens`,
`-Temperature`, `-Seed`, and `-Warm`. The configured Python safety limits remain
authoritative; script parameters cannot exceed them.

Model output is passed only to AgentWorldLab's recorder and evaluator. The
PowerShell script never invokes or interpolates generated content.
