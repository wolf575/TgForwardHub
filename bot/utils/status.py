"""
User state management for multi-step interactions
"""
from typing import Dict, Any

# User state storage
user_states: Dict[str, Any] = {}


def get_user_state(user_id: str) -> Dict[str, Any]:
    """Get user state
    
    Args:
        user_id: User ID
        
    Returns:
        User state dictionary
    """
    return user_states.get(user_id, {})


def set_user_state(user_id: str, state: Dict[str, Any]):
    """Set user state
    
    Args:
        user_id: User ID
        state: State dictionary
    """
    user_states[user_id] = state


def clear_user_state(user_id: str):
    """Clear user state
    
    Args:
        user_id: User ID
    """
    if user_id in user_states:
        del user_states[user_id]


def update_user_state(user_id: str, **kwargs):
    """Update user state with new values
    
    Args:
        user_id: User ID
        **kwargs: Key-value pairs to update
    """
    if user_id not in user_states:
        user_states[user_id] = {}
    user_states[user_id].update(kwargs)
