import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from celery_app import celery_app
from database.connection import SessionLocal
from database.models import Notification
import logging

logger = logging.getLogger(__name__)

@celery_app.task(
    bind=True,
    name="tasks.payment_tasks.send_payment_confirmation",
    max_retries=3,
    default_retry_delay=60,
    queue="default"
)
def send_payment_confirmation(self, user_id: int, order_id: str, amount: int, order_type: str):
    """Send payment confirmation notification"""
    db = SessionLocal()
    try:
        notification = Notification(
            user_id=user_id,
            type="payment_confirmed",
            title="Payment Successful",
            message=f"Payment of ₹{amount} confirmed for {order_type} #{order_id[-6:]}"
        )
        db.add(notification)
        db.commit()
        
        logger.info(f"Payment confirmation sent: user={user_id}, order={order_id}")
        return {"status": "success"}
        
    except Exception as exc:
        db.rollback()
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(
    bind=True,
    name="tasks.payment_tasks.process_refund_notification",
    max_retries=3,
    default_retry_delay=60,
    queue="default"
)
def process_refund_notification(self, user_id: int, order_id: str, amount: int):
    """Send refund initiated notification"""
    db = SessionLocal()
    try:
        notification = Notification(
            user_id=user_id,
            type="refund_initiated",
            title="Refund Initiated",
            message=f"Refund of ₹{amount} initiated for order #{order_id[-6:]}. Credit in 5-7 business days."
        )
        db.add(notification)
        db.commit()
        return {"status": "success"}
        
    except Exception as exc:
        db.rollback()
        raise self.retry(exc=exc)
    finally:
        db.close()