from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh")


@unittest.skipUnless(PWSH, "PowerShell is not installed")
class PowerShellScriptTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
