import sys
from pathlib import Path as PathlibPath

# Add backend directory to path for imports to work when running directly
backend_dir = PathlibPath(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_
from database.connection import get_db
from database.models import (
    User, FamilyMember, Address, NotificationPreferences, 
    AuditLog, Notification, Appointment, LabBooking, Prescription
)
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime, timedelta
from api.auth import get_current_user
import os
import uuid
from pathlib import Path

router = APIRouter(prefix="/api/profile", tags=["Profile"])

# ==================== CONFIG ====================
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# ==================== PYDANTIC MODELS ====================

class UpdateProfileRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    age: Optional[int] = Field(None, ge=1, le=120)
    gender: Optional[str] = None
    blood_group: Optional[str] = None
    email: Optional[EmailStr] = None

class AddAddressRequest(BaseModel):
    label: str = Field(..., description="Home/Office/Other")
    address_line1: str = Field(..., min_length=5, max_length=200)
    address_line2: Optional[str] = None
    city: str
    state: str
    pincode: str = Field(..., pattern=r'^\d{6}$')
    location_lat: Optional[float] = None
    location_lng: Optional[float] = None
    is_default: bool = False

class UpdateAddressRequest(BaseModel):
    label: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    location_lat: Optional[float] = None
    location_lng: Optional[float] = None

class AddFamilyMemberRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    relation: str = Field(..., description="father/mother/spouse/child/sibling/other")
    age: Optional[int] = Field(None, ge=1, le=120)
    gender: Optional[str] = None
    blood_group: Optional[str] = None
    phone: Optional[str] = None
    allergies: Optional[List[str]] = []
    medical_notes: Optional[str] = None

class UpdateNotificationPreferences(BaseModel):
    sms_enabled: Optional[bool] = None
    email_enabled: Optional[bool] = None
    push_enabled: Optional[bool] = None
    appointment_reminders: Optional[bool] = None
    lab_test_reminders: Optional[bool] = None
    order_updates: Optional[bool] = None
    promotional: Optional[bool] = None

class UpdateInsuranceRequest(BaseModel):
    insurance_provider: str
    insurance_number: str

class AddAllergiesRequest(BaseModel):
    allergies: List[str]

# ==================== HELPER FUNCTIONS ====================

def calculate_profile_completion(user: User, db: Session) -> int:
    """Calculate profile completion percentage"""
    total_points = 12
    completed = 0
    
    if user.name: completed += 1
    if user.age: completed += 1
    if user.gender: completed += 1
    if user.blood_group: completed += 1
    if user.email: completed += 1
    if user.phone: completed += 1
    
    addresses = db.query(Address).filter(Address.user_id == user.id).count()
    if addresses > 0: completed += 2
    
    if user.insurance_provider: completed += 2
    if user.allergies: completed += 1
    if user.profile_photo_url: completed += 1
    
    return int((completed / total_points) * 100)

def send_notification_helper(db: Session, user_id: int, type: str, title: str, message: str):
    """Helper to send notifications"""
    notification = Notification(
        user_id=user_id,
        type=type,
        title=title,
        message=message
    )
    db.add(notification)
    db.commit()

# ==================== ENDPOINTS ====================

@router.get("/me", response_model=dict)
async def get_complete_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    👤 GET COMPLETE USER PROFILE
    
    ✅ Returns:
    - Basic info
    - All addresses
    - Family members
    - Insurance
    - Allergies
    - Notification preferences
    - Profile completion %
    """
    
    # ✅ OPTIMIZED: Fetch related data
    addresses = db.query(Address).filter(Address.user_id == current_user.id).all()
    family = db.query(FamilyMember).filter(FamilyMember.user_id == current_user.id).all()
    
    notif_prefs = db.query(NotificationPreferences).filter(
        NotificationPreferences.user_id == current_user.id
    ).first()
    
    # Create default if not exists
    if not notif_prefs:
        notif_prefs = NotificationPreferences(user_id=current_user.id)
        db.add(notif_prefs)
        db.commit()
    
    return {
        "id": current_user.id,
        "phone": current_user.phone,
        "name": current_user.name,
        "email": current_user.email,
        "age": current_user.age,
        "gender": current_user.gender,
        "blood_group": current_user.blood_group,
        "profile_photo_url": current_user.profile_photo_url,
        "addresses": [
            {
                "id": addr.id,
                "label": addr.label,
                "address_line1": addr.address_line1,
                "address_line2": addr.address_line2,
                "city": addr.city,
                "state": addr.state,
                "pincode": addr.pincode,
                "full_address": f"{addr.address_line1}, {addr.city}, {addr.state} - {addr.pincode}",
                "location": {
                    "lat": float(addr.location_lat) if addr.location_lat else None,
                    "lng": float(addr.location_lng) if addr.location_lng else None
                },
                "is_default": addr.is_default
            }
            for addr in addresses
        ],
        "insurance": {
            "provider": current_user.insurance_provider,
            "number": current_user.insurance_number
        } if current_user.insurance_provider else None,
        "allergies": current_user.allergies or [],
        "family_members": [
            {
                "id": fm.id,
                "name": fm.name,
                "relation": fm.relation,
                "age": fm.age,
                "gender": fm.gender,
                "blood_group": fm.blood_group,
                "phone": fm.phone,
                "allergies": fm.allergies or [],
                "medical_notes": fm.medical_notes
            }
            for fm in family
        ],
        "notification_preferences": {
            "sms_enabled": notif_prefs.sms_enabled,
            "email_enabled": notif_prefs.email_enabled,
            "push_enabled": notif_prefs.push_enabled,
            "appointment_reminders": notif_prefs.appointment_reminders,
            "lab_test_reminders": notif_prefs.lab_test_reminders,
            "order_updates": notif_prefs.order_updates,
            "promotional": notif_prefs.promotional
        },
        "profile_completion": calculate_profile_completion(current_user, db),
        "is_verified": current_user.is_verified,
        "created_at": current_user.created_at.strftime("%Y-%m-%d"),
        "deletion_scheduled": current_user.deletion_requested_at is not None
    }


# ==================== BASIC INFO ENDPOINTS ====================

@router.put("/update", response_model=dict)
async def update_profile(
    request: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """✏️ UPDATE BASIC PROFILE"""
    
    if request.name: current_user.name = request.name
    if request.age: current_user.age = request.age
    if request.gender: current_user.gender = request.gender
    if request.blood_group: current_user.blood_group = request.blood_group
    if request.email: current_user.email = request.email
    
    current_user.updated_at = datetime.now()
    db.commit()
    
    return {
        "status": "success",
        "message": "Profile updated",
        "profile_completion": calculate_profile_completion(current_user, db)
    }


# ==================== ADDRESS ENDPOINTS ====================

@router.post("/addresses", response_model=dict)
async def add_address(
    request: AddAddressRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """📍 ADD NEW ADDRESS"""
    
    # If set as default, unset other defaults
    if request.is_default:
        db.query(Address).filter(
            Address.user_id == current_user.id
        ).update({"is_default": False})
    
    address = Address(
        user_id=current_user.id,
        label=request.label,
        address_line1=request.address_line1,
        address_line2=request.address_line2,
        city=request.city,
        state=request.state,
        pincode=request.pincode,
        location_lat=request.location_lat,
        location_lng=request.location_lng,
        is_default=request.is_default
    )
    
    db.add(address)
    db.commit()
    db.refresh(address)
    
    return {
        "status": "success",
        "message": "Address added",
        "address_id": address.id
    }


@router.get("/addresses", response_model=dict)
async def get_addresses(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """📍 GET ALL ADDRESSES"""
    
    addresses = db.query(Address).filter(
        Address.user_id == current_user.id
    ).all()
    
    return {
        "total": len(addresses),
        "addresses": [
            {
                "id": addr.id,
                "label": addr.label,
                "full_address": f"{addr.address_line1}, {addr.city}, {addr.state} - {addr.pincode}",
                "is_default": addr.is_default
            }
            for addr in addresses
        ]
    }


@router.put("/addresses/{address_id}", response_model=dict)
async def update_address(
    address_id: int,
    request: UpdateAddressRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """✏️ UPDATE ADDRESS"""
    
    address = db.query(Address).filter(
        and_(
            Address.id == address_id,
            Address.user_id == current_user.id
        )
    ).first()
    
    if not address:
        raise HTTPException(status_code=404, detail="Address not found")
    
    if request.label: address.label = request.label
    if request.address_line1: address.address_line1 = request.address_line1
    if request.address_line2 is not None: address.address_line2 = request.address_line2
    if request.city: address.city = request.city
    if request.state: address.state = request.state
    if request.pincode: address.pincode = request.pincode
    if request.location_lat: address.location_lat = request.location_lat
    if request.location_lng: address.location_lng = request.location_lng
    
    address.updated_at = datetime.now()
    db.commit()
    
    return {"status": "success", "message": "Address updated"}


@router.delete("/addresses/{address_id}", response_model=dict)
async def delete_address(
    address_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """🗑️ DELETE ADDRESS"""
    
    address = db.query(Address).filter(
        and_(
            Address.id == address_id,
            Address.user_id == current_user.id
        )
    ).first()
    
    if not address:
        raise HTTPException(status_code=404, detail="Address not found")
    
    db.delete(address)
    db.commit()
    
    return {"status": "success", "message": "Address deleted"}


@router.put("/addresses/{address_id}/set-default", response_model=dict)
async def set_default_address(
    address_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """⭐ SET DEFAULT ADDRESS"""
    
    # Unset all defaults
    db.query(Address).filter(
        Address.user_id == current_user.id
    ).update({"is_default": False})
    
    # Set new default
    address = db.query(Address).filter(
        and_(
            Address.id == address_id,
            Address.user_id == current_user.id
        )
    ).first()
    
    if not address:
        raise HTTPException(status_code=404, detail="Address not found")
    
    address.is_default = True
    db.commit()
    
    return {"status": "success", "message": "Default address updated"}


# ==================== FAMILY MEMBERS ENDPOINTS ====================

@router.post("/family-members", response_model=dict)
async def add_family_member(
    request: AddFamilyMemberRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """👨‍👩‍👧 ADD FAMILY MEMBER"""
    
    family_member = FamilyMember(
        user_id=current_user.id,
        name=request.name,
        relation=request.relation,
        age=request.age,
        gender=request.gender,
        blood_group=request.blood_group,
        phone=request.phone,
        allergies=request.allergies,
        medical_notes=request.medical_notes
    )
    
    db.add(family_member)
    db.commit()
    db.refresh(family_member)
    
    # Log action
    audit = AuditLog(
        user_id=current_user.id,
        action="FAMILY_MEMBER_ADDED",
        entity_type="family_member",
        entity_id=str(family_member.id),
        details={"name": request.name, "relation": request.relation}
    )
    db.add(audit)
    db.commit()
    
    return {
        "status": "success",
        "message": f"Family member '{request.name}' added",
        "member_id": family_member.id
    }


@router.get("/family-members", response_model=dict)
async def get_family_members(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """👨‍👩‍👧 GET ALL FAMILY MEMBERS"""
    
    members = db.query(FamilyMember).filter(
        FamilyMember.user_id == current_user.id
    ).all()
    
    return {
        "total": len(members),
        "members": [
            {
                "id": m.id,
                "name": m.name,
                "relation": m.relation,
                "age": m.age,
                "gender": m.gender,
                "blood_group": m.blood_group,
                "phone": m.phone
            }
            for m in members
        ]
    }


@router.delete("/family-members/{member_id}", response_model=dict)
async def delete_family_member(
    member_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """🗑️ DELETE FAMILY MEMBER"""
    
    member = db.query(FamilyMember).filter(
        and_(
            FamilyMember.id == member_id,
            FamilyMember.user_id == current_user.id
        )
    ).first()
    
    if not member:
        raise HTTPException(status_code=404, detail="Family member not found")
    
    db.delete(member)
    db.commit()
    
    return {"status": "success", "message": "Family member deleted"}


# ==================== INSURANCE ENDPOINTS ====================

@router.put("/insurance", response_model=dict)
async def update_insurance(
    request: UpdateInsuranceRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """🏥 UPDATE INSURANCE"""
    
    current_user.insurance_provider = request.insurance_provider
    current_user.insurance_number = request.insurance_number
    current_user.updated_at = datetime.now()
    db.commit()
    
    return {"status": "success", "message": "Insurance updated"}


# ==================== ALLERGIES ENDPOINTS ====================

@router.post("/allergies", response_model=dict)
async def add_allergies(
    request: AddAllergiesRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """💊 ADD/UPDATE ALLERGIES"""
    
    current_user.allergies = request.allergies
    current_user.updated_at = datetime.now()
    db.commit()
    
    return {
        "status": "success",
        "message": f"{len(request.allergies)} allergies saved",
        "allergies": request.allergies
    }


# ==================== NOTIFICATION PREFERENCES ====================

@router.put("/notification-preferences", response_model=dict)
async def update_notification_preferences(
    request: UpdateNotificationPreferences,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """🔔 UPDATE NOTIFICATION PREFERENCES"""
    
    prefs = db.query(NotificationPreferences).filter(
        NotificationPreferences.user_id == current_user.id
    ).first()
    
    if not prefs:
        prefs = NotificationPreferences(user_id=current_user.id)
        db.add(prefs)
    
    if request.sms_enabled is not None: prefs.sms_enabled = request.sms_enabled
    if request.email_enabled is not None: prefs.email_enabled = request.email_enabled
    if request.push_enabled is not None: prefs.push_enabled = request.push_enabled
    if request.appointment_reminders is not None: prefs.appointment_reminders = request.appointment_reminders
    if request.lab_test_reminders is not None: prefs.lab_test_reminders = request.lab_test_reminders
    if request.order_updates is not None: prefs.order_updates = request.order_updates
    if request.promotional is not None: prefs.promotional = request.promotional
    
    prefs.updated_at = datetime.now()
    db.commit()
    
    return {"status": "success", "message": "Notification preferences updated"}


# ==================== FILE UPLOAD ====================

@router.post("/upload/profile-photo", response_model=dict)
async def upload_profile_photo(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """📸 UPLOAD PROFILE PHOTO"""
    
    # Validate file type
    allowed = ["image/jpeg", "image/png", "image/jpg"]
    if file.content_type not in allowed:
        raise HTTPException(status_code=400, detail="Only JPG/PNG allowed")
    
    # Save file
    ext = file.filename.split(".")[-1]
    filename = f"{current_user.id}_{uuid.uuid4().hex[:8]}.{ext}"
    
    upload_path = UPLOAD_DIR / "profile-photos"
    upload_path.mkdir(exist_ok=True)
    
    file_path = upload_path / filename
    
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)
    
    # Update user
    current_user.profile_photo_url = f"/uploads/profile-photos/{filename}"
    db.commit()
    
    return {
        "status": "success",
        "message": "Profile photo uploaded",
        "photo_url": current_user.profile_photo_url
    }


# ==================== MEDICAL HISTORY ====================

@router.get("/medical-history", response_model=dict)
async def get_medical_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """📋 GET MEDICAL HISTORY"""
    
    # Past appointments
    appointments = db.query(Appointment).options(
        joinedload(Appointment.doctor)
    ).filter(
        Appointment.user_id == current_user.id,
        Appointment.status == 'completed'
    ).order_by(Appointment.date.desc()).limit(10).all()
    
    # Lab tests
    lab_tests = db.query(LabBooking).options(
        joinedload(LabBooking.test)
    ).filter(
        LabBooking.user_id == current_user.id,
        LabBooking.status == 'completed'
    ).order_by(LabBooking.completed_at.desc()).limit(10).all()
    
    # Prescriptions
    prescriptions = db.query(Prescription).filter(
        Prescription.user_id == current_user.id
    ).order_by(Prescription.created_at.desc()).limit(10).all()
    
    return {
        "appointments": [
            {
                "date": apt.date.strftime("%Y-%m-%d"),
                "doctor": apt.doctor.name,
                "reason": apt.reason
            }
            for apt in appointments
        ],
        "lab_tests": [
            {
                "date": test.collection_date.strftime("%Y-%m-%d"),
                "test_name": test.test.name,
                "report_url": test.result_pdf_url
            }
            for test in lab_tests
        ],
        "prescriptions": [
            {
                "date": rx.created_at.strftime("%Y-%m-%d"),
                "medicines": rx.medicines
            }
            for rx in prescriptions
        ]
    }


# ==================== ACCOUNT DELETION ====================

@router.post("/request-account-deletion", response_model=dict)
async def request_account_deletion(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """🗑️ REQUEST ACCOUNT DELETION (30-day grace period)"""
    
    current_user.deletion_requested_at = datetime.now()
    current_user.scheduled_deletion_date = datetime.now().date() + timedelta(days=30)
    db.commit()
    
    send_notification_helper(
        db, current_user.id, "account_deletion_requested",
        "Account Deletion Scheduled",
        f"Your account will be deleted on {current_user.scheduled_deletion_date}. Cancel within 30 days."
    )
    
    return {
        "status": "scheduled",
        "message": "Account deletion scheduled",
        "deletion_date": current_user.scheduled_deletion_date.strftime("%Y-%m-%d"),
        "days_remaining": 30
    }


@router.post("/cancel-account-deletion", response_model=dict)
async def cancel_account_deletion(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """✅ CANCEL ACCOUNT DELETION"""
    
    if not current_user.deletion_requested_at:
        raise HTTPException(status_code=400, detail="No deletion request found")
    
    current_user.deletion_requested_at = None
    current_user.scheduled_deletion_date = None
    db.commit()
    
    return {"status": "success", "message": "Account deletion cancelled"}


# ==================== ACTIVITY LOG ====================

@router.get("/activity-log", response_model=dict)
async def get_activity_log(
    current_user: User = Depends(get_current_user),
    page: int = 1,
    limit: int = 20,
    db: Session = Depends(get_db)
):
    """📜 VIEW ACCOUNT ACTIVITY"""
    
    logs = db.query(AuditLog).filter(
        AuditLog.user_id == current_user.id
    ).order_by(AuditLog.created_at.desc()).offset(
        (page - 1) * limit
    ).limit(limit).all()
    
    return {
        "total": db.query(AuditLog).filter(AuditLog.user_id == current_user.id).count(),
        "page": page,
        "logs": [
            {
                "action": log.action,
                "timestamp": log.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "details": log.details
            }
            for log in logs
        ]
    }