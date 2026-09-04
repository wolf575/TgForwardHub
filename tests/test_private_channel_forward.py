import unittest

from pyrogram import utils

import batch_forward
from pyrogram_compat import (
    apply_pyrogram_peer_id_compat,
    normalize_private_channel_ref,
)


class _UsernameClient:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.resolved_ref = None

    def get_chat(self, ref):
        self.resolved_ref = ref
        return type("Chat", (), {"id": self.chat_id})()


class PrivateChannelForwardTests(unittest.TestCase):
    def test_private_link_normalization(self):
        self.assertEqual(
            normalize_private_channel_ref("https://t.me/c/3906869022/9961"),
            "-1003906869022",
        )
        self.assertEqual(
            normalize_private_channel_ref("t.me/c/3906869022"),
            "-1003906869022",
        )
        self.assertEqual(
            normalize_private_channel_ref("@public_channel"),
            "@public_channel",
        )

    def test_pyrogram_accepts_modern_private_channel_ids(self):
        apply_pyrogram_peer_id_compat()

        self.assertEqual(utils.get_peer_type(-1003906869022), "channel")
        self.assertEqual(utils.get_channel_id(-1003906869022), 3906869022)

    def test_resolve_chat_from_private_link(self):
        self.assertEqual(
            batch_forward._resolve_chat(
                None,
                "https://t.me/c/3906869022/9961",
            ),
            -1003906869022,
        )

    def test_resolve_chat_preserves_numeric_and_username_behavior(self):
        self.assertEqual(batch_forward._resolve_chat(None, "-1001234567890"), -1001234567890)

        client = _UsernameClient(-1009876543210)
        self.assertEqual(batch_forward._resolve_chat(client, "@private"), -1009876543210)
        self.assertEqual(client.resolved_ref, "@private")


if __name__ == "__main__":
    unittest.main()
