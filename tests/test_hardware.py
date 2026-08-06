"""Opt-in smoke check; never loads model weights."""

from __future__ import annotations

import os
import unittest


@unittest.skipUnless(os.environ.get("AGENTWORLDLAB_HARDWARE_TESTS") == "1", "hardware tests are opt-in")
class RocmHardwareTests(unittest.TestCase):
    def test_torch_exposes_one_gfx1151_device(self) -> None:
        import torch

        self.assertTrue(torch.cuda.is_available())
        self.assertEqual(torch.cuda.device_count(), 1)
        properties = torch.cuda.get_device_properties(0)
        architecture = getattr(properties, "gcnArchName", "")
        self.assertIn("gfx1151", architecture)
        self.assertIsNotNone(torch.version.hip)


if __name__ == "__main__":
    unittest.main()
