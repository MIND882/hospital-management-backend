import sys
from pathlib import Path

# Add backend directory to path for imports to work when running directly
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_, func, desc
from database.connection import get_db
from database.models import User, Appointment, EmergencyRequest, Order, LabBooking, Notification, AuditLog
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, date, timedelta
from api.auth import get_current_user

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

# ==================== PYDANTIC MODELS ====================

class QuickAction(BaseModel):
    id: str
    title: str
    icon: str
    route: str
    color: str

class UpcomingItem(BaseModel):
    id: str
    type: str  # appointment/lab_test/order
    title: str
    subtitle: str
    date: str
    time: str
    status: str
    icon: str

class HealthStat(BaseModel):
    label: str
    value: str
    icon: str
    trend: Optional[str] = None

class DashboardResponse(BaseModel):
    user: dict
    quick_actions: List[QuickAction]
    upcoming: List[UpcomingItem]
    health_stats: List[HealthStat]
    recent_activity: List[dict]
    notifications_count: int
    critical_alerts: List[dict]

# ==================== HELPER FUNCTIONS ====================

def get_upcoming_appointments(user_id: int, db: Session, limit: int = 3) -> List[dict]:
    """
    ✅ OPTIMIZED: Get upcoming appointments with minimal queries
    """
    from database.models import Doctor, Clinic
    
    # ✅ JOINEDLOAD to prevent N+1
    from sqlalchemy.orm import joinedload
    
    upcoming = db.query(Appointment).options(
        joinedload(Appointment.doctor).joinedload(Doctor.clinic)
    ).filter(
        and_(
            Appointment.user_id == user_id,
            Appointment.date >= datetime.now().date(),
            Appointment.status == 'confirmed'
        )
    ).order_by(Appointment.date, Appointment.time).limit(limit).all()
    
    return [
        {
            "id": apt.id,
            "type": "appointment",
            "title": f"Dr. {apt.doctor.name}",
            "subtitle": apt.doctor.clinic.name,
            "date": str(apt.date),
            "time": apt.time.strftime("%I:%M %p"),
            "status": apt.status,
            "icon": "🩺"
        }
        for apt in upcoming
    ]

def get_upcoming_lab_tests(user_id: int, db: Session, limit: int = 3) -> List[dict]:
    """
    ✅ OPTIMIZED: Get upcoming lab tests
    """
    from sqlalchemy.orm import joinedload
    
    upcoming = db.query(LabBooking).options(
        joinedload(LabBooking.test)
    ).filter(
        and_(
            LabBooking.user_id == user_id,
            LabBooking.collection_date >= datetime.now().date(),
            LabBooking.status.in_(['scheduled', 'collected', 'processing'])
        )
    ).order_by(LabBooking.collection_date, LabBooking.collection_time).limit(limit).all()
    
    return [
        {
            "id": booking.id,
            "type": "lab_test",
            "title": booking.test.name,
            "subtitle": f"{booking.collection_type.capitalize()} Collection",
            "date": str(booking.collection_date),
            "time": booking.collection_time.strftime("%I:%M %p"),
            "status": booking.status,
            "icon": "🔬"
        }
        for booking in upcoming
    ]

def get_recent_orders(user_id: int, db: Session, limit: int = 2) -> List[dict]:
    """
    ✅ OPTIMIZED: Get recent medicine orders
    """
    recent = db.query(Order).filter(
        Order.user_id == user_id
    ).order_by(Order.created_at.desc()).limit(limit).all()
    
    return [
        {
            "id": order.id,
            "type": "order",
            "title": f"Medicine Order #{order.id[-6:]}",
            "subtitle": f"{order.order_status.capitalize()} - ₹{order.total_amount}",
            "date": order.created_at.strftime("%Y-%m-%d"),
            "time": order.created_at.strftime("%I:%M %p"),
            "status": order.order_status,
            "icon": "💊"
        }
        for order in recent
    ]

def get_health_statistics(user_id: int, db: Session) -> List[dict]:
    """
    ✅ OPTIMIZED: Database-level aggregation
    """
    # Total appointments
    total_appointments = db.query(Appointment).filter(
        Appointment.user_id == user_id
    ).count()
    
    # Completed lab tests
    completed_tests = db.query(LabBooking).filter(
        and_(
            LabBooking.user_id == user_id,
            LabBooking.status == 'completed'
        )
    ).count()
    
    # Total orders
    total_orders = db.query(Order).filter(
        Order.user_id == user_id
    ).count()
    
    # Emergency requests
    emergency_count = db.query(EmergencyRequest).filter(
        EmergencyRequest.user_id == user_id
    ).count()
    
    return [
        {
            "label": "Appointments",
            "value": str(total_appointments),
            "icon": "🩺",
            "trend": None
        },
        {
            "label": "Lab Tests",
            "value": str(completed_tests),
            "icon": "🔬",
            "trend": None
        },
        {
            "label": "Medicine Orders",
            "value": str(total_orders),
            "icon": "💊",
            "trend": None
        },
        {
            "label": "Emergencies",
            "value": str(emergency_count),
            "icon": "🚑",
            "trend": None
        }
    ]

def get_recent_activity(user_id: int, db: Session, limit: int = 5) -> List[dict]:
    """
    ✅ OPTIMIZED: Get recent activity from audit logs
    """
    activities = db.query(AuditLog).filter(
        AuditLog.user_id == user_id
    ).order_by(AuditLog.created_at.desc()).limit(limit).all()
    
    activity_icons = {
        "APPOINTMENT_BOOKED": "📅",
        "LAB_TEST_BOOKED": "🔬",
        "ORDER_CREATED": "💊",
        "EMERGENCY_REQUESTED": "🚑",
        "LOGIN_SUCCESS": "🔓",
        "PROFILE_COMPLETED": "✅"
    }
    
    return [
        {
            "action": activity.action.replace("_", " ").title(),
            "timestamp": activity.created_at.strftime("%b %d, %I:%M %p"),
            "icon": activity_icons.get(activity.action, "📝")
        }
        for activity in activities
    ]

def get_critical_alerts(user_id: int, db: Session) -> List[dict]:
    """
    ✅ Check for critical alerts
    """
    alerts = []
    
    # Check for appointments within 24 hours
    tomorrow = datetime.now().date() + timedelta(days=1)
    upcoming_apt = db.query(Appointment).filter(
        and_(
            Appointment.user_id == user_id,
            Appointment.date == tomorrow,
            Appointment.status == 'confirmed'
        )
    ).first()
    
    if upcoming_apt:
        alerts.append({
            "type": "appointment_reminder",
            "title": "Appointment Tomorrow",
            "message": f"Dr. {upcoming_apt.doctor.name} at {upcoming_apt.time.strftime('%I:%M %p')}",
            "priority": "high",
            "icon": "⏰"
        })
    
    # Check for pending lab reports
    pending_reports = db.query(LabBooking).filter(
        and_(
            LabBooking.user_id == user_id,
            LabBooking.status == 'completed',
            LabBooking.result_pdf_url != None
        )
    ).count()
    
    if pending_reports > 0:
        alerts.append({
            "type": "report_ready",
            "title": f"{pending_reports} Report(s) Ready",
            "message": "Download your lab reports now",
            "priority": "medium",
            "icon": "📄"
        })
    
    return alerts

# ==================== API ENDPOINTS ====================

@router.get("", response_model=DashboardResponse)
async def get_dashboard(
    current_user: User = Depends(get_current_user),  # ✅ PROTECTED ROUTE
    db: Session = Depends(get_db)
):
    """
    📊 USER DASHBOARD
    
    ✅ FEATURES:
    - Quick actions
    - Upcoming appointments/tests
    - Health statistics
    - Recent activity
    - Critical alerts
    
    ✅ PROTECTED: Requires authentication
    ✅ OPTIMIZED: Minimal database queries
    """
    
    # ✅ PARALLEL DATA FETCHING (could be made async for better performance)
    upcoming_appointments = get_upcoming_appointments(current_user.id, db, limit=2)
    upcoming_lab_tests = get_upcoming_lab_tests(current_user.id, db, limit=2)
    recent_orders = get_recent_orders(current_user.id, db, limit=1)
    
    # Combine and sort by date
    upcoming = upcoming_appointments + upcoming_lab_tests + recent_orders
    upcoming.sort(key=lambda x: x.get("date", "9999-12-31"))
    
    # Health stats
    health_stats = get_health_statistics(current_user.id, db)
    
    # Recent activity
    recent_activity = get_recent_activity(current_user.id, db, limit=5)
    
    # Unread notifications count
    unread_count = db.query(Notification).filter(
        and_(
            Notification.user_id == current_user.id,
            Notification.is_read == False
        )
    ).count()
    
    # Critical alerts
    critical_alerts = get_critical_alerts(current_user.id, db)
    
    # Quick actions
    quick_actions = [
        {
            "id": "book_appointment",
            "title": "Book Doctor",
            "icon": "🩺",
            "route": "/appointments/search",
            "color": "#4F46E5"
        },
        {
            "id": "order_medicine",
            "title": "Order Medicine",
            "icon": "💊",
            "route": "/pharmacy/search",
            "color": "#10B981"
        },
        {
            "id": "book_lab_test",
            "title": "Lab Tests",
            "icon": "🔬",
            "route": "/lab-tests/search",
            "color": "#F59E0B"
        },
        {
            "id": "emergency",
            "title": "Emergency",
            "icon": "🚑",
            "route": "/emergency",
            "color": "#EF4444"
        }
    ]
    
    return {
        "user": {
            "id": current_user.id,
            "name": current_user.name,
            "phone": current_user.phone,
            "email": current_user.email,
            "age": current_user.age,
            "gender": current_user.gender,
            "blood_group": current_user.blood_group,
            "profile_complete": bool(current_user.name and current_user.age)
        },
        "quick_actions": quick_actions,
        "upcoming": upcoming[:5],  # Top 5
        "health_stats": health_stats,
        "recent_activity": recent_activity,
        "notifications_count": unread_count,
        "critical_alerts": critical_alerts
    }


@router.get("/stats", response_model=dict)
async def get_detailed_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    📈 DETAILED HEALTH STATISTICS
    
    ✅ PROTECTED ROUTE
    """
    
    # Appointments breakdown
    apt_stats = {
        "total": db.query(Appointment).filter(Appointment.user_id == current_user.id).count(),
        "upcoming": db.query(Appointment).filter(
            and_(
                Appointment.user_id == current_user.id,
                Appointment.date >= datetime.now().date(),
                Appointment.status == 'confirmed'
            )
        ).count(),
        "completed": db.query(Appointment).filter(
            and_(
                Appointment.user_id == current_user.id,
                Appointment.status == 'completed'
            )
        ).count(),
        "cancelled": db.query(Appointment).filter(
            and_(
                Appointment.user_id == current_user.id,
                Appointment.status == 'cancelled'
            )
        ).count()
    }
    
    # Lab tests breakdown
    lab_stats = {
        "total": db.query(LabBooking).filter(LabBooking.user_id == current_user.id).count(),
        "scheduled": db.query(LabBooking).filter(
            and_(
                LabBooking.user_id == current_user.id,
                LabBooking.status == 'scheduled'
            )
        ).count(),
        "completed": db.query(LabBooking).filter(
            and_(
                LabBooking.user_id == current_user.id,
                LabBooking.status == 'completed'
            )
        ).count()
    }
    
    # Orders breakdown
    order_stats = {
        "total": db.query(Order).filter(Order.user_id == current_user.id).count(),
        "processing": db.query(Order).filter(
            and_(
                Order.user_id == current_user.id,
                Order.order_status == 'processing'
            )
        ).count(),
        "delivered": db.query(Order).filter(
            and_(
                Order.user_id == current_user.id,
                Order.order_status == 'delivered'
            )
        ).count()
    }
    
    return {
        "appointments": apt_stats,
        "lab_tests": lab_stats,
        "orders": order_stats,
        "user_since": current_user.created_at.strftime("%B %Y")
    }


@router.get("/notifications", response_model=dict)
async def get_notifications(
    current_user: User = Depends(get_current_user),
    unread_only: bool = False,
    limit: int = 20,
    db: Session = Depends(get_db)
):
    """
    🔔 GET USER NOTIFICATIONS
    
    ✅ PROTECTED ROUTE
    ✅ PAGINATION
    """
    
    query = db.query(Notification).filter(
        Notification.user_id == current_user.id
    )
    
    if unread_only:
        query = query.filter(Notification.is_read == False)
    
    notifications = query.order_by(
        Notification.created_at.desc()
    ).limit(limit).all()
    
    return {
        "total": len(notifications),
        "unread_count": db.query(Notification).filter(
            and_(
                Notification.user_id == current_user.id,
                Notification.is_read == False
            )
        ).count(),
        "notifications": [
            {
                "id": notif.id,
                "type": notif.type,
                "title": notif.title,
                "message": notif.message,
                "is_read": notif.is_read,
                "created_at": notif.created_at.strftime("%Y-%m-%d %I:%M %p")
            }
            for notif in notifications
        ]
    }


@router.post("/notifications/{notification_id}/mark-read", response_model=dict)
async def mark_notification_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    ✅ MARK NOTIFICATION AS READ
    
    ✅ PROTECTED ROUTE
    """
    
    notification = db.query(Notification).filter(
        and_(
            Notification.id == notification_id,
            Notification.user_id == current_user.id
        )
    ).first()
    
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    notification.is_read = True
    db.commit()
    
    return {
        "status": "success",
        "message": "Notification marked as read"
    }