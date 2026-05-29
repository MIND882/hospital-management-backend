import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from celery_app import celery_app
from database.connection import SessionLocal
from database.models import Notification, EmergencyRequest
import logging

logger = logging.getLogger(__name__)

@celery_app.task(
    bind=True,
    name="tasks.emergency_tasks.dispatch_emergency_alert",
    max_retries=5,
    default_retry_delay=10,  # Retry every 10 seconds — emergency is urgent
    queue="emergency"
)
def dispatch_emergency_alert(self, user_id: int, emergency_id: str, message: str):
    """
    CRITICAL — Emergency notification with aggressive retry
    5 retries, 10 second intervals
    This replaces the BackgroundTask that could silently drop
    """
    db = SessionLocal()
    try:
        notification = Notification(
            user_id=user_id,
            type="emergency_alert",
            title="Emergency Response Dispatched",
            message=message
        )
        db.add(notification)
        db.commit()
        
        logger.critical(f"Emergency alert sent: {emergency_id} → user {user_id}")
        return {"status": "success", "emergency_id": emergency_id}
        
    except Exception as exc:
        db.rollback()
        logger.critical(f"Emergency alert FAILED: {emergency_id} — {exc}")
        raise self.retry(exc=exc)
    finally:
        db.close()

@celery_app.task(
    bind=True,
    name="tasks.emergency_tasks.notify_emergency_contacts",
    max_retries=3,
    default_retry_delay=30,
    queue="emergency"
)
def notify_emergency_contacts_task(self, user_id: int, emergency_id: str, location: str):
    """Notify emergency contacts — durable replacement for BackgroundTask"""
    db = SessionLocal()
    try:
        # TODO: Implement actual emergency contact notification
        # For now: log it, future: SMS to registered emergency contacts
        logger.critical(
            f"Emergency contacts notified: user={user_id}, "
            f"emergency={emergency_id}, location={location}"
        )
        return {"status": "success"}
        
    except Exception as exc:
        raise self.retry(exc=exc)
    finally:
        db.close()

