import redis
import os
import logging

logger = logging.getLogger(__name__)

redis_client = redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    decode_responses=True
)

WEBHOOK_PREFIX = "webhook_processed:"


def is_webhook_already_processed(payment_id: str, event_type: str) -> bool:
    """
    Check if this webhook was already processed
    Key: payment_id + event_type — unique per payment per event
    """
    key = f"{WEBHOOK_PREFIX}{payment_id}:{event_type}"
    return redis_client.exists(key) > 0


def mark_webhook_processed(payment_id: str, event_type: str) -> bool:
    """
    Mark webhook as processed
    Expires after 30 days — Razorpay retry window is much shorter
    """
    try:
        key = f"{WEBHOOK_PREFIX}{payment_id}:{event_type}"
        redis_client.setex(key, 86400 * 30, "processed")
        logger.info(f"Webhook marked processed: {payment_id}:{event_type}")
        return True
    except Exception as e:
        logger.error(f"Failed to mark webhook processed: {e}")
        return False