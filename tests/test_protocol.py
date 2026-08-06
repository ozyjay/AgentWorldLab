from __future__ import annotations

import unittest

from agentworldlab.errors import ProtocolError
from agentworldlab.protocol import MAX_MESSAGE_BYTES, decode, encode, request, validate_request


class ProtocolTests(unittest.TestCase):
    def test_round_trip_request(self) -> None:
        original = request("health")
        decoded = decode(encode(original))
        self.assertEqual(validate_request(decoded)[1], "health")

    def test_malformed_json_is_visible(self) -> None:
        with self.assertRaisesRegex(ProtocolError, "malformed JSON"):
            decode("{not json}\n")

    def test_unknown_operation_is_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            request("execute-shell")

    def test_large_message_is_rejected(self) -> None:
        with self.assertRaisesRegex(ProtocolError, "size limit"):
            encode({"version": 1, "id": "x", "value": "x" * MAX_MESSAGE_BYTES})


if __name__ == "__main__":
    unittest.main()

