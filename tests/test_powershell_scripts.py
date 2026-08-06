from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh")


@unittest.skipUnless(PWSH, "PowerShell is not installed")
class PowerShellScriptTests(unittest.TestCase):
    def test_rocm_foundation_uses_hashed_amd_wheels(self) -> None:
        requirements = (ROOT / "requirements" / "rocm72.txt").read_text(encoding="utf-8")
        package_lines = [
            line
            for line in requirements.splitlines()
            if line and not line.startswith("#")
        ]
        self.assertEqual(len(package_lines), 3)
        self.assertTrue(any(line.startswith("torch @ ") for line in package_lines))
        self.assertTrue(any(line.startswith("torchvision @ ") for line in package_lines))
        self.assertTrue(any(line.startswith("triton @ ") for line in package_lines))
        for line in package_lines:
            self.assertIn("https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1/", line)
            self.assertRegex(line, r"#sha256=[0-9a-f]{64}$")

    def test_scripts_parse_without_errors(self) -> None:
        command = """
$tokens = $null
$errors = $null
[void] [System.Management.Automation.Language.Parser]::ParseFile(
    $env:AGENTWORLDLAB_PS_SCRIPT,
    [ref] $tokens,
    [ref] $errors
)
if ($errors.Count -gt 0) {
    $errors | ForEach-Object { [Console]::Error.WriteLine($_.Message) }
    exit 1
}
"""
        for script in sorted((ROOT / "scripts").glob("*.ps1")):
            with self.subTest(script=script.name):
                environment = os.environ.copy()
                environment["AGENTWORLDLAB_PS_SCRIPT"] = str(script)
                result = subprocess.run(
                    [PWSH, "-NoLogo", "-NoProfile", "-Command", command],
                    check=False,
                    capture_output=True,
                    env=environment,
                    text=True,
                    timeout=20,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_rocm_setup_requires_network_acknowledgement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            environment_path = Path(temporary_directory) / "rocm-environment"
            result = subprocess.run(
                [
                    PWSH,
                    "-NoLogo",
                    "-NoProfile",
                    "-File",
                    str(ROOT / "scripts" / "setup-rocm.ps1"),
                    "-VirtualEnvironment",
                    str(environment_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, output)
            self.assertIn("-AcknowledgeNetworkInstall", output)
            self.assertFalse(environment_path.exists())


if __name__ == "__main__":
    unittest.main()
