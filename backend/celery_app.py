import os
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

# Create Celery app
celery_app = Celery(
    "medicare",
    broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
    include=[
        "tasks.notification_tasks",
        "tasks.emergency_tasks",
        "tasks.payment_tasks",
    ]
)


# Configuration
celery_app.conf.update(
    # Task routing — different queues for different priorities
    task_routes={
        "tasks.emergency_tasks.*": {"queue": "emergency"},
        "tasks.notification_tasks.*": {"queue": "notifications"},
        "tasks.payment_tasks.*": {"queue": "default"},
    },
    
    broker_connection_retry_on_startup=True,
    
    # Retry settings
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    
    # Serialization
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    
    # Timezone
    timezone="Asia/Kolkata",
    enable_utc=True,
    
    # Beat schedule (periodic tasks)
    beat_schedule={
        "cleanup-expired-otps": {
            "task": "tasks.notification_tasks.cleanup_expired_otps",
            "schedule": 300.0,  # Every 5 minutes
        },
        "check-appointment-reminders": {
            "task": "tasks.notification_tasks.send_appointment_reminders",
            "schedule": 600.0,  # Every 10 minutes
        },
    },
    
    # Result expiry
    result_expires=3600,
)

if __name__ == "__main__":
    celery_app.start()