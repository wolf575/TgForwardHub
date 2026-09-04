"""
Helper utility functions
"""
import pyrogram
from pyrogram.enums import MessageMediaType


_MESSAGE_MEDIA_TYPE_NAMES = {
    MessageMediaType.AUDIO: "Audio",
    MessageMediaType.DOCUMENT: "Document",
    MessageMediaType.PHOTO: "Photo",
    MessageMediaType.STICKER: "Sticker",
    MessageMediaType.VIDEO: "Video",
    MessageMediaType.ANIMATION: "Animation",
    MessageMediaType.VOICE: "Voice",
    MessageMediaType.VIDEO_NOTE: "VideoNote",
    MessageMediaType.CONTACT: "Contact",
    MessageMediaType.LOCATION: "Location",
    MessageMediaType.VENUE: "Venue",
    MessageMediaType.POLL: "Poll",
    MessageMediaType.WEB_PAGE: "WebPage",
    MessageMediaType.DICE: "Dice",
    MessageMediaType.GAME: "Game",
}


def get_message_type(msg: pyrogram.types.messages_and_media.message.Message):
    """Get the type of message"""
    media_type = getattr(msg, "media", None)
    if media_type is not None:
        try:
            return _MESSAGE_MEDIA_TYPE_NAMES[MessageMediaType(media_type)]
        except (TypeError, ValueError):
            pass

    try:
        msg.document.file_id
        return "Document"
    except:
        pass

    try:
        msg.video.file_id
        return "Video"
    except:
        pass

    try:
        msg.animation.file_id
        return "Animation"
    except:
        pass

    try:
        msg.video_note.file_id
        return "VideoNote"
    except:
        pass

    try:
        msg.sticker.file_id
        return "Sticker"
    except:
        pass

    try:
        msg.voice.file_id
        return "Voice"
    except:
        pass

    try:
        msg.audio.file_id
        return "Audio"
    except:
        pass

    try:
        msg.photo.file_id
        return "Photo"
    except:
        pass

    try:
        msg.text
        return "Text"
    except:
        pass
