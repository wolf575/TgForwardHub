"""
Global bot and acc instances management
Separated to avoid circular imports
"""

# Store bot and acc instances for use by handlers
_bot_instance = None
_acc_instance = None


def set_bot_instance(bot):
    """Set the bot instance for handlers"""
    global _bot_instance
    _bot_instance = bot


def set_acc_instance(acc):
    """Set the acc instance for handlers"""
    global _acc_instance
    _acc_instance = acc


def get_bot_instance():
    """Get the bot instance"""
    return _bot_instance


def get_acc_instance():
    """Get the acc instance"""
    return _acc_instance
