"""Compatibility helpers for Pyrogram's legacy peer ID range.

Pyrogram 2.0.106 still rejects Telegram channel IDs whose raw 32-bit part is
larger than 2^31 - 1.  Private ``t.me/c/<id>/<message>`` links routinely use
larger raw IDs, so :func:`apply_pyrogram_peer_id_compat` widens the accepted
channel range before any peer resolution happens.
"""

import re

from pyrogram import utils


EXPANDED_MIN_CHANNEL_ID = -1009999999999

_PRIVATE_CHANNEL_LINK_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?t\.me/c/(?P<channel_id>\d+)(?:/(?P<message_id>\d+))?/?$",
    re.IGNORECASE,
)


def apply_pyrogram_peer_id_compat():
    """Widen Pyrogram's accepted channel range without weakening chat/user IDs."""
    if utils.MIN_CHANNEL_ID > EXPANDED_MIN_CHANNEL_ID:
        utils.MIN_CHANNEL_ID = EXPANDED_MIN_CHANNEL_ID
    return utils.MIN_CHANNEL_ID


def normalize_private_channel_ref(value):
    """Convert a Telegram private-channel URL into its ``-100...`` peer ID."""
    raw = str(value or "").strip()
    match = _PRIVATE_CHANNEL_LINK_RE.match(raw)
    if match:
        return f"-100{match.group('channel_id')}"
    return raw
