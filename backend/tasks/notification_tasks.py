import os 
import sys
from pathlib import Path

# add backend to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from celery_app import celery_app
from database.connection import SessionLocal
from database.models import Notification, User, Appointment
from datetime import datetime, timedelta
from sqlalchemy import and_
import logging

logger = logging.getLogger(__name__)

@celery_app.task(
    bind=True,
    name="tasks.notification_tasks.send_notification",
    max_retries=3,
    default_retry_delay=60,
    queue="notifications"
)
def send_notification_task(self, user_id: int, title: str, message: str, notification_type: str = "general"):
    """
    Send notification to user — replaces BackgroundTasks
    Retries 3 times if fails, 60 second delay between retries
    """
    db = SessionLocal()
    try:
        notification = Notification(
            user_id=user_id,
            type=notification_type,
            title=title,
            message=message
        )
        db.add(notification)
        db.commit()
        logger.info(f"Notification sent to user {user_id}: {title}")
        return {"status": "success", "user_id": user_id}
        
    except Exception as exc:
        db.rollback()
        logger.error(f"Notification failed for user {user_id}: {exc}")
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(
    bind=True,
    name="tasks.notification_tasks.send_otp_sms",
    max_retries=3,
    default_retry_delay=30,
    queue="notifications"
)
def send_otp_sms_task(self, phone: str, otp: str):
    """Send OTP via SMS — with retry logic"""
    try:
        from twilio.rest import Client
        from twilio.base.exceptions import TwilioRestException
        
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        twilio_number = os.getenv("TWILIO_PHONE_NUMBER")
        
        if not all([account_sid, auth_token, twilio_number]):
            logger.warning("Twilio credentials missing — OTP not sent via SMS")
            return {"status": "skipped", "reason": "no_credentials"}
        
        client = Client(account_sid, auth_token)
        message = client.messages.create(
            body=f"MediCare OTP: {otp}\nValid for 5 minutes.\nDo not share.",
            from_=twilio_number,
            to=phone
        )
        
        logger.info(f"OTP SMS sent to {phone}: {message.sid}")
        return {"status": "success", "sid": message.sid}
        
    except Exception as exc:
        logger.error(f"OTP SMS failed for {phone}: {exc}")
        raise self.retry(exc=exc)


@celery_app.task(
    name="tasks.notification_tasks.send_appointment_reminders",
    queue="notifications"
)
def send_appointment_reminders():
    """
    Periodic task — runs every 10 minutes
    Sends reminders for appointments in next 24 hours
    """
    db = SessionLocal()
    try:
        tomorrow = datetime.now() + timedelta(hours=24)
        now = datetime.now()
        
        upcoming = db.query(Appointment).filter(
            and_(
                Appointment.date >= now.date(),
                Appointment.status == "confirmed"
            )
        ).all()
        
        sent = 0
        for apt in upcoming:
            apt_datetime = datetime.combine(apt.date, apt.time)
            hours_until = (apt_datetime - now).total_seconds() / 3600
            
            # Send reminder if 24 hours away
            if 23 <= hours_until <= 25:
                send_notification_task.delay(
                    user_id=apt.user_id,
                    title="Appointment Reminder",
                    message=f"Reminder: You have an appointment tomorrow at {apt.time.strftime('%I:%M %p')}",
                    notification_type="appointment_reminder"
                )
                sent += 1
        
        logger.info(f"Appointment reminders sent: {sent}")
        return {"reminders_sent": sent}
        
    except Exception as e:
        logger.error(f"Appointment reminder task failed: {e}")
    finally:
        db.close()


@celery_app.task(
    name="tasks.notification_tasks.cleanup_expired_otps",
    queue="default"
)
def cleanup_expired_otps():
    """Periodic task — cleans up expired OTPs every 5 minutes"""
    db = SessionLocal()
    try:
        from database.models import User
        
        expired = db.query(User).filter(
            User.otp_expires_at < datetime.now(),
            User.otp != None
        ).all()
        
        count = 0
        for user in expired:
            user.otp = None
            user.otp_expires_at = None
            count += 1
        
        db.commit()
        logger.info(f"Cleaned up {count} expired OTPs")
        return {"cleaned": count}
        
    except Exception as e:
        logger.error(f"OTP cleanup failed: {e}")
        db.rollback()
    finally:
        db.close()