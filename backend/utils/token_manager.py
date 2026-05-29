import os
import redis
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

redis_client = redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    decode_responses=True
)

# Token blacklist prefix
BLACKLIST_PREFIX = "token_blacklist:"
REFRESH_TOKEN_PREFIX = "refresh_token:"


def blacklist_token(token: str, expires_in_seconds: int) -> bool:
    """
    Add token to blacklist
    Expires automatically when token would have expired anyway
    """
    try:
        key = f"{BLACKLIST_PREFIX}{token}"
        redis_client.setex(key, expires_in_seconds, "blacklisted")
        logger.info(f"Token blacklisted successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to blacklist token: {e}")
        return False


def is_token_blacklisted(token: str) -> bool:
    """Check if token is blacklisted — called on every request"""
    try:
        key = f"{BLACKLIST_PREFIX}{token}"
        return redis_client.exists(key) > 0
    except Exception as e:
        logger.error(f"Redis blacklist check failed: {e}")
        # Fail open — if Redis is down, don't block all requests
        # In production you may want to fail closed depending on risk tolerance
        return False


def store_refresh_token(user_id: int, refresh_token: str, expires_days: int = 7) -> bool:
    """
    Store refresh token in Redis
    This lets us invalidate refresh tokens server-side
    """
    try:
        key = f"{REFRESH_TOKEN_PREFIX}{user_id}"
        expires_seconds = expires_days * 24 * 3600
        redis_client.setex(key, expires_seconds, refresh_token)
        logger.info(f"Refresh token stored for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to store refresh token: {e}")
        return False


def is_refresh_token_valid(user_id: int, refresh_token: str) -> bool:
    """
    Validate refresh token against stored value
    Prevents refresh token reuse after rotation
    """
    try:
        key = f"{REFRESH_TOKEN_PREFIX}{user_id}"
        stored = redis_client.get(key)
        if not stored:
            return False
        return stored == refresh_token
    except Exception as e:
        logger.error(f"Refresh token validation failed: {e}")
        return False


def revoke_refresh_token(user_id: int) -> bool:
    """Revoke refresh token — called on logout or security event"""
    try:
        key = f"{REFRESH_TOKEN_PREFIX}{user_id}"
        redis_client.delete(key)
        logger.info(f"Refresh token revoked for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to revoke refresh token: {e}")
        return False


def revoke_all_user_tokens(user_id: int, current_access_token: str, access_token_ttl: int) -> bool:
    """
    Nuclear option — revoke everything for a user
    Use when: account compromise, suspicious activity, admin action
    """
    try:
        # Blacklist current access token
        blacklist_token(current_access_token, access_token_ttl)
        
        # Revoke refresh token
        revoke_refresh_token(user_id)
        
        logger.warning(f"ALL tokens revoked for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to revoke all tokens for user {user_id}: {e}")
        return False