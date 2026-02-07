import sys
from pathlib import Path

# Add backend directory to path for imports to work when running directly
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, func
from database.connection import get_db
from database.models import User, Clinic, EmergencyRequest, Notification, AuditLog
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
import secrets
import math
import httpx
import os
GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

router = APIRouter(prefix="/api/emergency", tags=["Emergency"])

# ==================== PYDANTIC MODELS ====================

class EmergencyRequestModel(BaseModel):
    user_id: int
    latitude: float = Field(..., ge=-90, le=90, description="User's current latitude")
    longitude: float = Field(..., ge=-180, le=180, description="User's current longitude")
    address: Optional[str] = Field(None, description="Address (optional, auto-detected if not provided)")
    emergency_type: str = Field(..., description="ambulance/hospital/both")
    description: Optional[str] = Field(None, description="Brief description of emergency")
    patient_condition: Optional[str] = Field(None, description="conscious/unconscious/bleeding/breathing_difficulty/chest_pain/accident")

class EmergencyResponse(BaseModel):
    emergency_id: str
    status: str
    message: str
    ambulance: Optional[dict]
    nearest_hospitals: List[dict]
    emergency_contacts: dict
    eta_minutes: Optional[int]

class EmergencyStatusUpdate(BaseModel):
    emergency_id: str
    new_status: str  # dispatched/arrived/completed
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
    """Generate unique emergency ID like EMG123456"""
    return f"EMG{secrets.randbelow(900000) + 100000}"

def estimate_eta(distance_km: float, traffic_factor: float = 1.2) -> int:
    """
    Estimate ambulance arrival time
    Assumes average speed of 40 km/h in city with traffic
     new dynamic factors of traffic added
     why ? Because traffic can significantly affect ambulance response times.
     specifically during peak hours or in congested areas.
     and rush hour like day times and less traffic at night
    """
    curent_hour = datetime.now().hour
    if 8 <= curent_hour <= 12 or 17 <= curent_hour <= 20:
        traffic_factor = 1.5  # Higher traffic during peak hours
    elif 22 <= curent_hour <= 6:
        traffic_factor = 0.8  # Less traffic at night
    else:
        traffic_factor = 1.2  # Normal traffic
    speed_kmh = 40 / traffic_factor
    time_hours = distance_km / speed_kmh
    time_minutes = int(time_hours * 60)
    
    # Add base response time (2-5 minutes)
    base_time = 3
    
    return time_minutes + base_time

def get_nearest_clinics_with_emergency(
    db: Session,
    user_lat: float,
    user_lng: float,
    limit: int = 5,
    max_distance_km: float = 20.0
) -> List[dict]:
    """
    Find nearest clinics/hospitals with emergency services
    
    ✅ FIX 4: OPTIMIZED WITH BOUNDING BOX + REDUCED CALCULATIONS
    WHY: Prevents calculating distance for ALL clinics in database
    
    BEFORE:
    - Fetch ALL clinics (could be 1000+)
    - Calculate distance for each in Python loop
    - Sort and filter
    - Result: 1000+ distance calculations
    
    AFTER:
    - First filter by rough bounding box (SQL level)
    - Only fetch clinics within box
    - Calculate distance only for filtered results
    - Result: ~10-50 distance calculations only
    """
    
    # ✅ OPTIMIZATION: Create bounding box (rough filter at SQL level)
    # WHY: Dramatically reduces number of clinics to process
    # 1 degree latitude ≈ 111 km
    # So max_distance_km / 111 gives us the degree range
    lat_range = max_distance_km / 111.0
    lng_range = max_distance_km / (111.0 * math.cos(math.radians(user_lat)))
    
    # Bounding box coordinates
    min_lat = user_lat - lat_range
    max_lat = user_lat + lat_range
    min_lng = user_lng - lng_range
    max_lng = user_lng + lng_range
    
    # ✅ STEP 1: Fetch only clinics within bounding box (SQL-level filter)
    # BEFORE: Fetched ALL clinics
    # AFTER: Only fetch clinics within ~40km box
    clinics = db.query(Clinic).filter(
        and_(
            Clinic.emergency_available == True,
            Clinic.location_lat >= min_lat,
            Clinic.location_lat <= max_lat,
            Clinic.location_lng >= min_lng,
            Clinic.location_lng <= max_lng
        )
    ).all()
    
    if not clinics:
        return []
    
    # ✅ STEP 2: Calculate exact distance only for filtered clinics
    # WHY: Much smaller dataset now (10-50 instead of 1000+)
    clinics_with_distance = []
    for clinic in clinics:
        distance = calculate_distance(
            user_lat, user_lng,
            float(clinic.location_lat),
            float(clinic.location_lng)
        )
        
        # Only keep clinics within exact radius
        if distance <= max_distance_km:
            clinics_with_distance.append({
                "clinic": clinic,
                "distance_km": distance
            })
    
    # Sort by distance
    clinics_with_distance.sort(key=lambda x: x["distance_km"])
    
    return clinics_with_distance[:limit]


def send_emergency_notification(
    db: Session,
    user_id: int,
    emergency_id: str,
    message: str
):
    """Send high-priority emergency notification"""
    notification = Notification(
        user_id=user_id,
        type="emergency_alert",
        title="🚑 Emergency Response",
        message=message
    )
    db.add(notification)
    db.commit()

def log_emergency_action(
    db: Session,
    user_id: int,
    action: str,
    emergency_id: str,
    details: dict
):
    """Log emergency action for audit"""
    audit = AuditLog(
        user_id=user_id,
        action=action,
        entity_type="emergency",
        entity_id=emergency_id,
        details=details
    )
    db.add(audit)
    db.commit()

async def reverse_geocode(lat: float, lng: float) -> str:
    """
    Convert coordinates to address using Google Maps Geocoding API
    
    ✅ FIX 5: IMPLEMENTED REAL REVERSE GEOCODING
    WHY: Production needs actual addresses, not placeholder
    
    BEFORE: return f"Location: {lat:.4f}, {lng:.4f}"
    AFTER: Calls Google Maps API to get real address
    """
    
    # Option 1: Google Maps API (Requires API key)
    
    try:
        url = f"https://maps.googleapis.com/maps/api/geocode/json"
        params = {
            "latlng": f"{lat},{lng}",
            "key": GOOGLE_API_KEY
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=5.0)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get("results"):
                    # Get formatted address
                    address = data["results"][0]["formatted_address"]
                    return address
        
        # Fallback if API fails
        return f"Location: {lat:.4f}, {lng:.4f}"
        
    except Exception as e:
        # Fallback on error
        return f"Location: {lat:.4f}, {lng:.4f}"
    
    # Option 2: FREE Alternative - Nominatim (OpenStreetMap)
    # Uncomment this if you want free geocoding (has rate limits)
    """
    try:
        url = "https://nominatim.openstreetmap.org/reverse"
        params = {
            "lat": lat,
            "lon": lng,
            "format": "json"
        }
        headers = {
            "User-Agent": "MediCareApp/1.0"  # Required by Nominatim
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, headers=headers, timeout=5.0)
            
            if response.status_code == 200:
                data = response.json()
                return data.get("display_name", f"Location: {lat:.4f}, {lng:.4f}")
        
        return f"Location: {lat:.4f}, {lng:.4f}"
        
    except Exception as e:
        return f"Location: {lat:.4f}, {lng:.4f}"
    """


async def notify_emergency_contacts(
    user: User,
    emergency_id: str,
    location: str
):
    """
    Notify user's emergency contacts (family, etc.)
    In production, send SMS/WhatsApp
    """
    # TODO: Implement SMS/WhatsApp notifications
    # Example: Twilio SMS API
    pass


async def alert_nearest_clinic(
    clinic: Clinic,
    emergency: EmergencyRequest,
    user: User
):
    """
    Alert clinic about incoming emergency
    In production, send to clinic dashboard/app
    """
    # TODO: Implement real-time clinic alerts
    # Example: Firebase Cloud Messaging, WebSocket, etc.
    pass

# ==================== API ENDPOINTS ====================

@router.post("/request", response_model=EmergencyResponse)
async def create_emergency_request(
    request: EmergencyRequestModel,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    🚨 EMERGENCY REQUEST
    
    ✅ FIXES APPLIED:
    1. Optimized clinic search with bounding box
    2. Dynamic traffic-based ETA
    3. Real reverse geocoding (Google Maps)
    
    User presses emergency button → This endpoint is called
    
    Flow:
    1. Get user's location
    2. Find nearest hospitals/clinics with emergency services (OPTIMIZED)
    3. Dispatch ambulance (if available)
    4. Send emergency contacts notifications
    5. Return nearest hospital info and ETA
    """
    
    # Verify user exists
    user = db.query(User).filter(User.id == request.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # ✅ FIX 6: ASYNC REVERSE GEOCODING
    # WHY: Non-blocking external API call
    address = request.address
    if not address:
        address = await reverse_geocode(request.latitude, request.longitude)
    
    # ✅ FIX 7: OPTIMIZED CLINIC SEARCH (uses bounding box now)
    # WHY: Dramatically faster - filters at SQL level first
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
    
    # Get the nearest clinic
    nearest = nearest_clinics[0]
    nearest_clinic = nearest["clinic"]
    distance_km = nearest["distance_km"]
    
    # Generate emergency ID
    emergency_id = generate_emergency_id()
    
    # ✅ FIX 8: DYNAMIC ETA CALCULATION
    # WHY: Considers traffic based on time of day
    eta_minutes = estimate_eta(distance_km)
    
    try:
        # Create emergency request
        emergency = EmergencyRequest(
            id=emergency_id,
            user_id=request.user_id,
            location_lat=request.latitude,
            location_lng=request.longitude,
            address=address,
            emergency_type=request.emergency_type,
            description=request.description or f"Emergency: {request.patient_condition or 'Not specified'}",
            assigned_clinic_id=nearest_clinic.id,
            ambulance_eta=eta_minutes if request.emergency_type in ["ambulance", "both"] else None,
            status="requested"
        )
        
        db.add(emergency)
        db.commit()
        db.refresh(emergency)
        
        # Send notification to user
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
                "emergency_type": request.emergency_type,
                "condition": request.patient_condition,
                "nearest_clinic": nearest_clinic.name,
                "distance_km": distance_km
            }
        )
        
        # Background tasks (don't block response)
        background_tasks.add_task(notify_emergency_contacts, user, emergency_id, address)
        background_tasks.add_task(alert_nearest_clinic, nearest_clinic, emergency, user)
        
        # Format response
        ambulance_info = None
        if request.emergency_type in ["ambulance", "both"] and nearest_clinic.ambulance_available:
            ambulance_info = {
                "status": "dispatched",
                "eta_minutes": eta_minutes,
                "from": nearest_clinic.name,
                "distance_km": distance_km,
                "contact": nearest_clinic.phone,
                "message": "Ambulance dispatched! Stay at your location."
            }
        
        hospitals_list = []
        for item in nearest_clinics:
            clinic = item["clinic"]
            hospitals_list.append({
                "name": clinic.name,
                "address": clinic.address,
                "phone": clinic.phone,
                "distance_km": item["distance_km"],
                "has_ambulance": clinic.ambulance_available,
                "is_assigned": clinic.id == nearest_clinic.id
            })
        
        return {
            "emergency_id": emergency_id,
            "status": "dispatched",
            "message": "🚨 Emergency services activated! Help is on the way.",
            "ambulance": ambulance_info,
            "nearest_hospitals": hospitals_list,
            "emergency_contacts": {
                "national_ambulance": "108",
                "police": "100",
                "fire": "101",
                "women_helpline": "1091"
            },
            "eta_minutes": eta_minutes
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Emergency request failed: {str(e)}")



@router.get("/{emergency_id}", response_model=dict)
async def get_emergency_status(
    emergency_id: str,
    db: Session = Depends(get_db)
):
    """
    Get real-time status of emergency request
    
    ✅ FIX 9: ADDED JOINEDLOAD TO PREVENT N+1
    WHY: Fetches user and clinic data in one query
    
    User can refresh this to track ambulance
    """
    
    # ✅ FIX: USE JOINEDLOAD FOR RELATED DATA
    # BEFORE: Separate queries for user and clinic
    # AFTER: Single query with JOIN
    emergency = db.query(EmergencyRequest).options(
        joinedload(EmergencyRequest.user),
        joinedload(EmergencyRequest.assigned_clinic)
    ).filter(
        EmergencyRequest.id == emergency_id
    ).first()
    
    if not emergency:
        raise HTTPException(status_code=404, detail="Emergency request not found")
    
    # No separate clinic query needed - already loaded
    clinic = emergency.assigned_clinic
    
    # Calculate current ETA (decreases over time)
    if emergency.status == "dispatched" and emergency.ambulance_eta:
        time_elapsed = (datetime.now() - emergency.created_at).seconds // 60
        current_eta = max(0, emergency.ambulance_eta - time_elapsed)
    else:
        current_eta = None
    
    return {
        "emergency_id": emergency.id,
        "status": emergency.status,
        "created_at": emergency.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        "user": {
            "name": emergency.user.name if emergency.user else "Unknown",
            "phone": emergency.user.phone if emergency.user else "Unknown"
        },
        "location": {
            "latitude": float(emergency.location_lat),
            "longitude": float(emergency.location_lng),
            "address": emergency.address
        },
        "emergency_type": emergency.emergency_type,
        "description": emergency.description,
        "assigned_hospital": {
            "name": clinic.name,
            "address": clinic.address,
            "phone": clinic.phone,
            "has_ambulance": clinic.ambulance_available
        } if clinic else None,
        "ambulance": {
            "status": emergency.status,
            "eta_minutes": current_eta,
            "original_eta": emergency.ambulance_eta
        } if emergency.ambulance_eta else None,
        "status_timeline": [
            {"status": "requested", "time": emergency.created_at.strftime("%H:%M:%S")},
            {"status": "dispatched", "time": "Pending" if emergency.status == "requested" else "In Progress"},
            {"status": "arrived", "time": "Pending"},
            {"status": "completed", "time": emergency.completed_at.strftime("%H:%M:%S") if emergency.completed_at else "Pending"}
        ]
    }


@router.get("/user/{user_id}/history", response_model=dict)
async def get_user_emergency_history(
    user_id: int,
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """
    Get user's emergency request history
    
    ✅ FIX 10: ADDED JOINEDLOAD TO PREVENT N+1
    WHY: Prevents separate query for each emergency's clinic
    
    BEFORE: 1 emergency query + 10 clinic queries = 11 queries
    AFTER: 1 query with JOIN
    """
    
    # ✅ FIX: JOINEDLOAD CLINIC DATA
    emergencies = db.query(EmergencyRequest).options(
        joinedload(EmergencyRequest.assigned_clinic)
    ).filter(
        EmergencyRequest.user_id == user_id
    ).order_by(EmergencyRequest.created_at.desc()).limit(limit).all()
    
    history = []
    for emergency in emergencies:
        # No separate clinic query needed - already loaded
        clinic = emergency.assigned_clinic
        
        history.append({
            "emergency_id": emergency.id,
            "date": emergency.created_at.strftime("%Y-%m-%d"),
            "time": emergency.created_at.strftime("%I:%M %p"),
            "type": emergency.emergency_type,
            "status": emergency.status,
            "hospital": clinic.name if clinic else "Unknown",
            "location": emergency.address,
            "eta_minutes": emergency.ambulance_eta,
            "completed": emergency.status == "completed"
        })
    
    return {
        "user_id": user_id,
        "total": len(history),
        "emergencies": history
    }


@router.post("/cancel", response_model=dict)
async def cancel_emergency_request(
    emergency_id: str,
    user_id: int,
    reason: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Cancel emergency request
    
    Only allowed if ambulance hasn't arrived yet
    """
    
    emergency = db.query(EmergencyRequest).filter(
        EmergencyRequest.id == emergency_id
    ).first()
    
    if not emergency:
        raise HTTPException(status_code=404, detail="Emergency request not found")
    
    # Verify user owns this emergency
    if emergency.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Check if can be cancelled
    if emergency.status in ["arrived", "completed"]:
        raise HTTPException(
            status_code=400,
            detail="Cannot cancel emergency after ambulance has arrived"
        )
    
    if emergency.status == "cancelled":
        raise HTTPException(status_code=400, detail="Emergency is already cancelled")
    
    try:
        emergency.status = "cancelled"
        emergency.completed_at = datetime.now()
        
        db.commit()
        
        # Send notification
        send_emergency_notification(
            db=db,
            user_id=user_id,
            emergency_id=emergency_id,
            message="Emergency request cancelled. Hope you're safe!"
        )
        
        # Log action
        log_emergency_action(
            db=db,
            user_id=user_id,
            action="EMERGENCY_CANCELLED",
            emergency_id=emergency_id,
            details={"reason": reason}
        )
        
        return {
            "status": "success",
            "message": "Emergency request cancelled",
            "emergency_id": emergency_id
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Cancellation failed: {str(e)}")


@router.get("/nearby/hospitals", response_model=dict)
async def get_nearby_emergency_hospitals(
    latitude: float,
    longitude: float,
    radius_km: float = 10.0,
    db: Session = Depends(get_db)
):
    """
    Get all nearby hospitals with emergency services
    
    Useful for showing on map before emergency
    """
    
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
            "address": clinic.address,
            "phone": clinic.phone,
            "location": {
                "latitude": float(clinic.location_lat),
                "longitude": float(clinic.location_lng)
            },
            "distance_km": item["distance_km"],
            "has_ambulance": clinic.ambulance_available,
            "has_emergency": clinic.emergency_available,
            "rating": float(clinic.rating)
        })
    
    return {
        "user_location": {
            "latitude": latitude,
            "longitude": longitude
        },
        "radius_km": radius_km,
        "total": len(hospitals),
        "hospitals": hospitals
    }


@router.get("/stats/system", response_model=dict)
async def get_emergency_system_stats(
    db: Session = Depends(get_db)
):
    """
    Get emergency system statistics
    
    For admin dashboard
    """
    
    total_requests = db.query(EmergencyRequest).count()
    
    active_emergencies = db.query(EmergencyRequest).filter(
        EmergencyRequest.status.in_(["requested", "dispatched", "arrived"])
    ).count()
    
    completed = db.query(EmergencyRequest).filter(
        EmergencyRequest.status == "completed"
    ).count()
    
    # Average response time (for completed emergencies)
    completed_emergencies = db.query(EmergencyRequest).filter(
        EmergencyRequest.status == "completed"
    ).all()
    
    if completed_emergencies:
        response_times = [
            (e.completed_at - e.created_at).seconds // 60
            for e in completed_emergencies
            if e.completed_at
        ]
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0
    else:
        avg_response_time = 0
    
    return {
        "total_emergencies": total_requests,
        "active_now": active_emergencies,
        "completed": completed,
        "avg_response_time_minutes": round(avg_response_time, 1),
        "success_rate": round((completed / total_requests * 100), 1) if total_requests > 0 else 0
    }