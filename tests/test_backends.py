from __future__ import annotations

import unittest

from agentworldlab.backends.transformers import TransformersBackend
from agentworldlab.backends.vllm import VllmBackend, create_backend
from agentworldlab.errors import BackendUnavailableError


class BackendFactoryTests(unittest.TestCase):
    def test_transformers_backend_is_constructed_without_loading_dependencies(self) -> None:
        backend = create_backend("transformers")

        self.assertIsInstance(backend, TransformersBackend)
        self.assertEqual(backend.health()["backend"], "transformers")
        self.assertFalse(backend.health()["loaded"])

    def test_vllm_backend_is_constructed_without_loading_dependencies(self) -> None:
        backend = create_backend("vllm")

        self.assertIsInstance(backend, VllmBackend)
        self.assertEqual(backend.health()["backend"], "vllm")
        self.assertFalse(backend.health()["loaded"])

    def test_unsupported_backend_is_rejected(self) -> None:
        with self.assertRaisesRegex(BackendUnavailableError, "unsupported backend"):
            create_backend("unknown")


if __name__ == "__main__":
    unittest.main()
