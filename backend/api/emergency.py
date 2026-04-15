import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session, joinedload, relationship
from sqlalchemy import and_, func, Column, String, Integer, Float, Boolean, DateTime, Text, ForeignKey
from database.connection import get_db
from database.models import User, Clinic, EmergencyRequest, Notification, AuditLog
from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import datetime
from enum import Enum
import secrets
import math
import httpx
import os
import logging

logger = logging.getLogger(__name__)

GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

router = APIRouter(prefix="/api/emergency", tags=["Emergency"])


# ==================== ENUMS ====================

class EmergencyType(str, Enum):
    AMBULANCE = "ambulance"
    HOSPITAL = "hospital"
    BOTH = "both"


class PatientCondition(str, Enum):
    CONSCIOUS = "conscious"
    UNCONSCIOUS = "unconscious"
    BLEEDING = "bleeding"
    BREATHING_DIFFICULTY = "breathing_difficulty"
    CHEST_PAIN = "chest_pain"
    ACCIDENT = "accident"
    OTHER = "other"


class EmergencyStatus(str, Enum):
    REQUESTED = "requested"
    DISPATCHED = "dispatched"
    ARRIVED = "arrived"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


# ==================== PYDANTIC MODELS ====================

class EmergencyRequestModel(BaseModel):
    user_id: int
    latitude: float = Field(..., ge=-90, le=90, description="User's current latitude")
    longitude: float = Field(..., ge=-180, le=180, description="User's current longitude")
    address: Optional[str] = Field(None, description="Address (optional, auto-detected if not provided)")
    emergency_type: EmergencyType = Field(..., description="ambulance/hospital/both")
    description: Optional[str] = Field(None, description="Brief description of emergency")
    patient_condition: Optional[PatientCondition] = Field(None, description="Patient condition")

    @validator("user_id")
    def validate_user_id(cls, v):
        if v <= 0:
            raise ValueError("user_id must be a positive integer")
        return v


class EmergencyResponseModel(BaseModel):
    emergency_id: str
    status: str
    message: str
    ambulance: Optional[dict] = None
    nearest_hospitals: List[dict]
    emergency_contacts: dict
    eta_minutes: Optional[int] = None


class EmergencyStatusUpdate(BaseModel):
    emergency_id: str
    new_status: EmergencyStatus
    notes: Optional[str] = None


# ==================== HELPER FUNCTIONS ====================

def calculate_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate distance using Haversine formula"""
    R = 6371  # Earth's radius in km

    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)

    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance = R * c

    return round(distance, 2)


def generate_emergency_id() -> str:
    """Generate unique emergency ID like EMG-XXXXXX"""
    timestamp_part = datetime.now().strftime("%H%M%S")
    random_part = secrets.randbelow(9000) + 1000
    return f"EMG-{timestamp_part}-{random_part}"


def estimate_eta(distance_km: float) -> int:
    """
    Estimate ambulance arrival time with dynamic traffic factors.

    ✅ BUG FIX: Night hour check was broken (22 <= hour <= 6 is always False)
    FIXED: Split into two conditions using `or`
    """
    current_hour = datetime.now().hour

    # ✅ FIX: Corrected night-time condition
    if 8 <= current_hour <= 12 or 17 <= current_hour <= 20:
        traffic_factor = 1.5  # Peak hours
    elif current_hour >= 22 or current_hour <= 6:
        traffic_factor = 0.8  # Night time — LOW traffic
    else:
        traffic_factor = 1.2  # Normal traffic

    speed_kmh = 40 / traffic_factor
    time_hours = distance_km / speed_kmh
    time_minutes = int(time_hours * 60)

    # Add base response time (2-5 minutes)
    base_time = 3

    return max(time_minutes + base_time, 1)  # ✅ FIX: Minimum 1 minute


def get_nearest_clinics_with_emergency(
    db: Session,
    user_lat: float,
    user_lng: float,
    limit: int = 5,
    max_distance_km: float = 20.0
) -> List[dict]:
    """
    Find nearest clinics/hospitals with emergency services.
    Uses bounding box optimization to reduce calculations.
    """

    # ✅ FIX: Guard against division by zero at poles
    cos_lat = math.cos(math.radians(user_lat))
    if cos_lat == 0:
        cos_lat = 0.0001

    lat_range = max_distance_km / 111.0
    lng_range = max_distance_km / (111.0 * cos_lat)

    min_lat = user_lat - lat_range
    max_lat = user_lat + lat_range
    min_lng = user_lng - lng_range
    max_lng = user_lng + lng_range

    try:
        clinics = db.query(Clinic).filter(
            and_(
                Clinic.emergency_available == True,
                Clinic.location_lat >= min_lat,
                Clinic.location_lat <= max_lat,
                Clinic.location_lng >= min_lng,
                Clinic.location_lng <= max_lng
            )
        ).all()
    except Exception as e:
        logger.error(f"Database query failed in clinic search: {e}")
        return []

    if not clinics:
        return []

    clinics_with_distance = []
    for clinic in clinics:
        try:
            distance = calculate_distance(
                user_lat, user_lng,
                float(clinic.location_lat),
                float(clinic.location_lng)
            )

            if distance <= max_distance_km:
                clinics_with_distance.append({
                    "clinic": clinic,
                    "distance_km": distance
                })
        except (TypeError, ValueError) as e:
            logger.warning(f"Skipping clinic {clinic.id} — invalid coordinates: {e}")
            continue

    clinics_with_distance.sort(key=lambda x: x["distance_km"])

    return clinics_with_distance[:limit]


def send_emergency_notification(
    db: Session,
    user_id: int,
    emergency_id: str,
    message: str
):
    """Send high-priority emergency notification"""
    try:
        notification = Notification(
            user_id=user_id,
            type="emergency_alert",
            title="🚑 Emergency Response",
            message=message
        )
        db.add(notification)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to send notification for {emergency_id}: {e}")
        db.rollback()


def log_emergency_action(
    db: Session,
    user_id: int,
    action: str,
    emergency_id: str,
    details: dict
):
    """Log emergency action for audit"""
    try:
        audit = AuditLog(
            user_id=user_id,
            action=action,
            entity_type="emergency",
            entity_id=emergency_id,
            details=details
        )
        db.add(audit)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to log audit for {emergency_id}: {e}")
        db.rollback()


async def reverse_geocode(lat: float, lng: float) -> str:
    """Convert coordinates to address using Google Maps Geocoding API"""
    if not GOOGLE_API_KEY:
        logger.warning("GOOGLE_MAPS_API_KEY not set — using coordinate fallback")
        return f"Location: {lat:.4f}, {lng:.4f}"

    try:
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        params = {
            "latlng": f"{lat},{lng}",
            "key": GOOGLE_API_KEY
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=5.0)

            if response.status_code == 200:
                data = response.json()
                if data.get("results"):
                    return data["results"][0]["formatted_address"]

        return f"Location: {lat:.4f}, {lng:.4f}"

    except httpx.TimeoutException:
        logger.warning("Geocoding API timed out")
        return f"Location: {lat:.4f}, {lng:.4f}"
    except Exception as e:
        logger.error(f"Geocoding failed: {e}")
        return f"Location: {lat:.4f}, {lng:.4f}"


async def notify_emergency_contacts(user: User, emergency_id: str, location: str):
    """Notify user's emergency contacts — placeholder for SMS/WhatsApp integration"""
    logger.info(f"TODO: Notify emergency contacts for user {user.id}, emergency {emergency_id}")


async def alert_nearest_clinic(clinic: Clinic, emergency: EmergencyRequest, user: User):
    """Alert clinic about incoming emergency — placeholder for real-time push"""
    logger.info(f"TODO: Alert clinic {clinic.id} for emergency {emergency.id}")


# ==================== API ENDPOINTS ====================

@router.post("/request", response_model=EmergencyResponseModel)
async def create_emergency_request(
    request: EmergencyRequestModel,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    🚨 EMERGENCY REQUEST

    User presses emergency button → finds nearest hospitals → dispatches ambulance.
    """

    # Verify user exists
    user = db.query(User).filter(User.id == request.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Reverse geocode if address not provided
    address = request.address
    if not address:
        address = await reverse_geocode(request.latitude, request.longitude)

    # Find nearest clinics (optimized with bounding box)
    nearest_clinics = get_nearest_clinics_with_emergency(
        db=db,
        user_lat=request.latitude,
        user_lng=request.longitude,
        limit=5
    )

    if not nearest_clinics:
        raise HTTPException(
            status_code=404,
            detail="No emergency services found within 20km. Please call 108/102 (Emergency Helpline)"
        )

    nearest = nearest_clinics[0]
    nearest_clinic = nearest["clinic"]
    distance_km = nearest["distance_km"]

    # ✅ FIX: Generate collision-resistant emergency ID
    emergency_id = generate_emergency_id()

    # ✅ FIX: Check for ID collision (rare but possible)
    existing = db.query(EmergencyRequest).filter(EmergencyRequest.id == emergency_id).first()
    if existing:
        emergency_id = generate_emergency_id()  # Regenerate once

    eta_minutes = estimate_eta(distance_km)

    try:
        emergency = EmergencyRequest(
            id=emergency_id,
            user_id=request.user_id,
            location_lat=request.latitude,
            location_lng=request.longitude,
            address=address,
            emergency_type=request.emergency_type.value,
            description=request.description or f"Emergency: {request.patient_condition.value if request.patient_condition else 'Not specified'}",
            assigned_clinic_id=nearest_clinic.id,
            ambulance_eta=eta_minutes if request.emergency_type in [EmergencyType.AMBULANCE, EmergencyType.BOTH] else None,
            status=EmergencyStatus.REQUESTED.value
        )

        db.add(emergency)
        db.commit()
        db.refresh(emergency)

        # Send notification
        send_emergency_notification(
            db=db,
            user_id=request.user_id,
            emergency_id=emergency_id,
            message=f"Emergency services dispatched! Ambulance ETA: {eta_minutes} mins. Stay calm, help is on the way."
        )

        # Log action
        log_emergency_action(
            db=db,
            user_id=request.user_id,
            action="EMERGENCY_REQUESTED",
            emergency_id=emergency_id,
            details={
                "location": {"lat": request.latitude, "lng": request.longitude},
                "emergency_type": request.emergency_type.value,
                "condition": request.patient_condition.value if request.patient_condition else None,
                "nearest_clinic": nearest_clinic.name,
                "distance_km": distance_km
            }
        )

        # Background tasks
        background_tasks.add_task(notify_emergency_contacts, user, emergency_id, address)
        background_tasks.add_task(alert_nearest_clinic, nearest_clinic, emergency, user)

        # Build ambulance info
        ambulance_info = None
        has_ambulance = getattr(nearest_clinic, "ambulance_available", False)
        if request.emergency_type in [EmergencyType.AMBULANCE, EmergencyType.BOTH] and has_ambulance:
            ambulance_info = {
                "status": "dispatched",
                "eta_minutes": eta_minutes,
                "from": nearest_clinic.name,
                "distance_km": distance_km,
                "contact": getattr(nearest_clinic, "phone", "N/A"),
                "message": "Ambulance dispatched! Stay at your location."
            }

        # Build hospitals list
        hospitals_list = []
        for item in nearest_clinics:
            clinic = item["clinic"]
            hospitals_list.append({
                "name": clinic.name,
                "address": getattr(clinic, "address", "N/A"),
                "phone": getattr(clinic, "phone", "N/A"),
                "distance_km": item["distance_km"],
                "has_ambulance": getattr(clinic, "ambulance_available", False),
                "is_assigned": clinic.id == nearest_clinic.id
            })

        return EmergencyResponseModel(
            emergency_id=emergency_id,
            status="dispatched",
            message="🚨 Emergency services activated! Help is on the way.",
            ambulance=ambulance_info,
            nearest_hospitals=hospitals_list,
            emergency_contacts={
                "national_ambulance": "108",
                "police": "100",
                "fire": "101",
                "women_helpline": "1091"
            },
            eta_minutes=eta_minutes
        )

    except Exception as e:
        db.rollback()
        logger.error(f"Emergency request failed: {e}")
        raise HTTPException(status_code=500, detail=f"Emergency request failed: {str(e)}")


@router.get("/{emergency_id}")
async def get_emergency_status(
    emergency_id: str,
    db: Session = Depends(get_db)
):
    """Get real-time status of emergency request"""

    emergency = db.query(EmergencyRequest).options(
        joinedload(EmergencyRequest.user),
        joinedload(EmergencyRequest.assigned_clinic)
    ).filter(
        EmergencyRequest.id == emergency_id
    ).first()

    if not emergency:
        raise HTTPException(status_code=404, detail="Emergency request not found")

    clinic = emergency.assigned_clinic

    # ✅ FIX: Safe ETA calculation with null checks
    current_eta = None
    if emergency.status == EmergencyStatus.DISPATCHED.value and emergency.ambulance_eta:
        created = emergency.created_at
        if created:
            time_elapsed = (datetime.now() - created).total_seconds() // 60
            current_eta = max(0, int(emergency.ambulance_eta - time_elapsed))

    # ✅ FIX: Safe access to completed_at
    completed_time = "Pending"
    if hasattr(emergency, "completed_at") and emergency.completed_at:
        completed_time = emergency.completed_at.strftime("%H:%M:%S")

    created_at_str = emergency.created_at.strftime("%Y-%m-%d %H:%M:%S") if emergency.created_at else "Unknown"
    created_time_str = emergency.created_at.strftime("%H:%M:%S") if emergency.created_at else "Unknown"

    return {
        "emergency_id": emergency.id,
        "status": emergency.status,
        "created_at": created_at_str,
        "user": {
            "name": getattr(emergency.user, "name", "Unknown") if emergency.user else "Unknown",
            "phone": getattr(emergency.user, "phone", "Unknown") if emergency.user else "Unknown"
        },
        "location": {
            "latitude": float(emergency.location_lat) if emergency.location_lat else None,
            "longitude": float(emergency.location_lng) if emergency.location_lng else None,
            "address": emergency.address
        },
        "emergency_type": emergency.emergency_type,
        "description": emergency.description,
        "assigned_hospital": {
            "name": clinic.name,
            "address": getattr(clinic, "address", "N/A"),
            "phone": getattr(clinic, "phone", "N/A"),
            "has_ambulance": getattr(clinic, "ambulance_available", False)
        } if clinic else None,
        "ambulance": {
            "status": emergency.status,
            "eta_minutes": current_eta,
            "original_eta": emergency.ambulance_eta
        } if emergency.ambulance_eta else None,
        "status_timeline": [
            {"status": "requested", "time": created_time_str},
            {"status": "dispatched", "time": "In Progress" if emergency.status != EmergencyStatus.REQUESTED.value else "Pending"},
            {"status": "arrived", "time": "Pending"},
            {"status": "completed", "time": completed_time}
        ]
    }


@router.get("/user/{user_id}/history")
async def get_user_emergency_history(
    user_id: int,
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db)
):
    """Get user's emergency request history"""

    emergencies = db.query(EmergencyRequest).options(
        joinedload(EmergencyRequest.assigned_clinic)
    ).filter(
        EmergencyRequest.user_id == user_id
    ).order_by(EmergencyRequest.created_at.desc()).limit(limit).all()

    history = []
    for emergency in emergencies:
        clinic = emergency.assigned_clinic

        history.append({
            "emergency_id": emergency.id,
            "date": emergency.created_at.strftime("%Y-%m-%d") if emergency.created_at else "Unknown",
            "time": emergency.created_at.strftime("%I:%M %p") if emergency.created_at else "Unknown",
            "type": emergency.emergency_type,
            "status": emergency.status,
            "hospital": clinic.name if clinic else "Unknown",
            "location": emergency.address or "Unknown",
            "eta_minutes": emergency.ambulance_eta,
            "completed": emergency.status == EmergencyStatus.COMPLETED.value
        })

    return {
        "user_id": user_id,
        "total": len(history),
        "emergencies": history
    }


@router.post("/cancel")
async def cancel_emergency_request(
    emergency_id: str,
    user_id: int,
    reason: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Cancel emergency request — only if ambulance hasn't arrived"""

    emergency = db.query(EmergencyRequest).filter(
        EmergencyRequest.id == emergency_id
    ).first()

    if not emergency:
        raise HTTPException(status_code=404, detail="Emergency request not found")

    if emergency.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to cancel this emergency")

    if emergency.status in [EmergencyStatus.ARRIVED.value, EmergencyStatus.COMPLETED.value]:
        raise HTTPException(
            status_code=400,
            detail="Cannot cancel emergency after ambulance has arrived"
        )

    if emergency.status == EmergencyStatus.CANCELLED.value:
        raise HTTPException(status_code=400, detail="Emergency is already cancelled")

    try:
        emergency.status = EmergencyStatus.CANCELLED.value
        if hasattr(emergency, "completed_at"):
            emergency.completed_at = datetime.now()

        db.commit()

        send_emergency_notification(
            db=db,
            user_id=user_id,
            emergency_id=emergency_id,
            message="Emergency request cancelled. Hope you're safe!"
        )

        log_emergency_action(
            db=db,
            user_id=user_id,
            action="EMERGENCY_CANCELLED",
            emergency_id=emergency_id,
            details={"reason": reason or "No reason provided"}
        )

        return {
            "status": "success",
            "message": "Emergency request cancelled",
            "emergency_id": emergency_id
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Cancel failed for {emergency_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Cancellation failed: {str(e)}")


@router.get("/nearby/hospitals")
async def get_nearby_emergency_hospitals(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(default=10.0, ge=1.0, le=50.0),
    db: Session = Depends(get_db)
):
    """Get all nearby hospitals with emergency services"""

    clinics = get_nearest_clinics_with_emergency(
        db=db,
        user_lat=latitude,
        user_lng=longitude,
        limit=10,
        max_distance_km=radius_km
    )

    hospitals = []
    for item in clinics:
        clinic = item["clinic"]
        hospitals.append({
            "id": clinic.id,
            "name": clinic.name,
            "address": getattr(clinic, "address", "N/A"),
            "phone": getattr(clinic, "phone", "N/A"),
            "location": {
                "latitude": float(clinic.location_lat),
                "longitude": float(clinic.location_lng)
            },
            "distance_km": item["distance_km"],
            "has_ambulance": getattr(clinic, "ambulance_available", False),
            "has_emergency": getattr(clinic, "emergency_available", False),
            "rating": float(getattr(clinic, "rating", 0))
        })

    return {
        "user_location": {"latitude": latitude, "longitude": longitude},
        "radius_km": radius_km,
        "total": len(hospitals),
        "hospitals": hospitals
    }


@router.get("/stats/system")
async def get_emergency_system_stats(
    db: Session = Depends(get_db)
):
    """Get emergency system statistics for admin dashboard"""

    total_requests = db.query(EmergencyRequest).count()

    active_emergencies = db.query(EmergencyRequest).filter(
        EmergencyRequest.status.in_([
            EmergencyStatus.REQUESTED.value,
            EmergencyStatus.DISPATCHED.value,
            EmergencyStatus.ARRIVED.value
        ])
    ).count()

    completed = db.query(EmergencyRequest).filter(
        EmergencyRequest.status == EmergencyStatus.COMPLETED.value
    ).count()

    # Average response time
    avg_response_time = 0
    if completed > 0:
        completed_emergencies = db.query(EmergencyRequest).filter(
            EmergencyRequest.status == EmergencyStatus.COMPLETED.value
        ).all()

        response_times = []
        for e in completed_emergencies:
            if hasattr(e, "completed_at") and e.completed_at and e.created_at:
                delta = (e.completed_at - e.created_at).total_seconds() / 60
                if delta > 0:
                    response_times.append(delta)

        if response_times:
            avg_response_time = sum(response_times) / len(response_times)

    return {
        "total_emergencies": total_requests,
        "active_now": active_emergencies,
        "completed": completed,
        "cancelled": db.query(EmergencyRequest).filter(
            EmergencyRequest.status == EmergencyStatus.CANCELLED.value
        ).count(),
        "avg_response_time_minutes": round(avg_response_time, 1),
        "success_rate": round((completed / total_requests * 100), 1) if total_requests > 0 else 0
    }