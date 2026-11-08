"""Compatibility helpers for Pyrogram's legacy peer ID range.

Pyrogram 2.0.106 still rejects Telegram channel IDs whose raw 32-bit part is
larger than 2^31 - 1.  Private ``t.me/c/<id>/<message>`` links routinely use
larger raw IDs, so :func:`apply_pyrogram_peer_id_compat` widens the accepted
channel range before any peer resolution happens.
"""

import re
import inspect
import functools

from pyrogram import raw, utils


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


def apply_pyrofork_messages_topics_compat():
    """Default the Layer 220 ``topics`` field for Pyrofork 2.3.69.

    Pyrofork 2.3.69's ``copy_media_group`` constructs ``messages.Messages``
    without ``topics`` even though its generated Layer 220 type requires it.
    The media group has already been sent when this constructor runs, so the
    resulting TypeError must not be treated as a forwarding restriction.
    """
    messages_type = getattr(getattr(raw, "types", None), "messages", None)
    messages_class = getattr(messages_type, "Messages", None)
    if messages_class is None:
        return False

    original = getattr(messages_class, "__init__", None)
    if original is None or getattr(original, "_tgfh_topics_compat", False):
        return True

    try:
        parameters = inspect.signature(original).parameters
    except (TypeError, ValueError):
        return False
    topics_parameter = parameters.get("topics")
    if topics_parameter is None or topics_parameter.default is not inspect.Parameter.empty:
        return True

    @functools.wraps(original)
    def init_with_topics(self, *, messages, chats, users, topics=None):
        return original(
            self,
            messages=messages,
            topics=topics or [],
            chats=chats,
            users=users,
        )

    init_with_topics._tgfh_topics_compat = True
    messages_class.__init__ = init_with_topics
    return True


def normalize_private_channel_ref(value):
    """Convert a Telegram private-channel URL into its ``-100...`` peer ID."""
    raw = str(value or "").strip()
    match = _PRIVATE_CHANNEL_LINK_RE.match(raw)
    if match:
        return f"-100{match.group('channel_id')}"
    return raw
