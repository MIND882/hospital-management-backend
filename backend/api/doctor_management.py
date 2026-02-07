import sys
from pathlib import Path

# Add backend directory to path for imports to work when running directly
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, func, desc, extract
from database.connection import get_db
from database.models import (
    User, Doctor, Clinic, DoctorSlot, Appointment, 
    DoctorWallet, WalletTransaction, AuditLog, Notification
)
from api.auth import get_current_user
from pydantic import BaseModel, Field, EmailStr,model_validator
from typing import List, Optional
from datetime import datetime, date, time, timedelta
import secrets
import hashlib
import hmac
router = APIRouter(prefix="/api/doctor", tags=["Doctor Management"])

# ==================== PYDANTIC MODELS ====================

class DoctorRegistrationRequest(BaseModel):
    """Doctor onboarding form"""
    clinic_id: Optional[str] = None  # If joining existing clinic
    clinic_name: Optional[str] = None  # If creating new clinic
    clinic_address: Optional[str] = None
    clinic_phone: Optional[str] = None
    location_lat: Optional[float] = None
    location_lng: Optional[float] = None
    
    # Doctor details
    full_name:str =Field(..., min_length=2, max_length=100)
    email: EmailStr = Field(..., description="Doctor's official email for login")
    password_hash:str = Field(..., min_length=8, description="Set a strong password for login")
    specialties: List[str] = Field(..., min_length=1, description="List of specialties")
    qualification: str = Field(..., min_length=2)
    experience_years: int = Field(..., ge=0, le=70)
    consultation_fee: int = Field(..., ge=100, le=10000)
    
    # Registration documents
    medical_license_number: str
    medical_council: str = Field(default="Medical Council of India")
    
    # Working hours
    working_days: List[str] 
    working_hours_start: str 
    working_hours_end: str 

    
    # Services
    emergency_available: bool = False
    accepts_insurance: List[str] = []
class DoctorLoginRequest(BaseModel):
    """Doctor Login Form - Use email OR phone"""
    email: Optional[EmailStr] = Field(None, example="dr.smith@clinic.com")
    phone: Optional[str] = Field(None, min_length=10, max_length=15, example="9876543210")
    password: str = Field(..., min_length=8)

    # Validation logic: Dono mein se ek cheez toh honi hi chahiye
    @model_validator(mode='after')
    def check_identifier(self):
        if not self.email and not self.phone:
            raise ValueError('Email ya Phone number, mein se ek dena compulsory hai')
        return self

    class Config:
        str_strip_whitespace = True

class CreateSlotBatchRequest(BaseModel):
    """Bulk slot creation"""
    start_date: date
    end_date: date
    time_slots: List[dict] = Field(
        ..., 
        description="[{'start': '09:00', 'end': '09:30'}, ...]"
    )
    days: List[str] = Field(..., description="['monday', 'tuesday', ...]")
    skip_dates: Optional[List[date]] = []  # Holidays/leave

class UpdateSlotRequest(BaseModel):
    slot_id: int
    is_blocked: Optional[bool] = None
    reason: Optional[str] = None

class UpdateDoctorProfileRequest(BaseModel):
    consultation_fee: Optional[int] = None
    specialties: Optional[List[str]] = None
    bio: Optional[str] = None
    is_available: Optional[bool] = None

class LeaveRequest(BaseModel):
    start_date: date
    end_date: date
    reason: str

class WithdrawRequest(BaseModel):
    amount: int = Field(..., ge=100)
    bank_account: str
    ifsc_code: str

# ==================== HELPER FUNCTIONS ====================

def hash_password(password: str) -> str:
    """
    Plain password ko salted SHA-256 hash mein convert karta hai.
    Format: salt$hash  (salt alag rakhte hain taaki verify mein use kar sakein)
    """
    salt = secrets.token_hex(16)                          # 16 bytes = 32 char random salt
    hashed = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}${hashed}"                             # "salt$hash" format mein store karo


def verify_password(plain_password: str, stored_hash: str) -> bool:
    """
    Login pe plain password ko stored hash se compare karta hai.
    Stored hash ka format: salt$hash
    """
    try:
        salt, hashed = stored_hash.split("$")            # salt aur hash alag karo
        computed = hashlib.sha256((salt + plain_password).encode()).hexdigest()
        return hmac.compare_digest(computed, hashed)     # timing-safe comparison
    except ValueError:
        return False                                     # format wrong ho toh False


def generate_clinic_id() -> str:
    """Generate unique clinic ID"""
    return f"CLI{secrets.randbelow(900) + 100:03d}"


def generate_token() -> str:
    """
    Login ke baad ek unique session/auth token generate karta hai.
    secrets.token_urlsafe gives a cryptographically strong random token.
    """
    return secrets.token_urlsafe(32)                     # 32 bytes = ~43 char URL-safe token


def send_notification(
    db: Session,
    user_id: int,
    title: str,
    message: str,
    notification_type: str = "general",
    related_entity_type: Optional[str] = None,
    related_entity_id: Optional[str] = None
) -> None:
    """
    📣 Notification create karta hai kisi bhi user ke liye.
    Har jagah pe reuse karo — registration, leave, appointment complete, withdrawal, etc.

    Args:
        db: Database session
        user_id: Notification kis user ko milegi uska ID
        title: Notification ka title
        message: Notification ka body/message
        notification_type: "general" | "appointment" | "wallet" | "leave" | "verification"
        related_entity_type: Optional — jaise "appointment", "withdrawal", "doctor"
        related_entity_id: Optional — related entity ka ID (str mein)
    """
    notification = Notification(
        user_id=user_id,
        title=title,
        message=message,
        notification_type=notification_type,
        is_read=False,
        related_entity_type=related_entity_type,
        related_entity_id=related_entity_id,
        created_at=datetime.now()
    )
    db.add(notification)
    # Note: db.commit() caller pe hai — yahan sirf add karte hain


def create_time_slots(
    doctor_id: int,
    start_date: date,
    end_date: date,
    time_slots: List[dict],
    days: List[str],
    skip_dates: List[date],
    db: Session
) -> int:
    """
    Bulk create time slots for doctor
    Returns: Number of slots created
    """
    slots_created = 0
    current_date = start_date
    
    day_map = {
        'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
        'friday': 4, 'saturday': 5, 'sunday': 6
    }

    while current_date <= end_date:
        # Check if this day should have slots
        day_name = current_date.strftime('%A').lower()
        
        if day_name in days and current_date not in skip_dates:
            # Create slots for this day
            for slot in time_slots:
                start_time = datetime.strptime(slot['start'], '%H:%M').time()
                end_time = datetime.strptime(slot['end'], '%H:%M').time()
                
                # Check if slot already exists
                existing = db.query(DoctorSlot).filter(
                    and_(
                        DoctorSlot.doctor_id == doctor_id,
                        DoctorSlot.date == current_date,
                        DoctorSlot.start_time == start_time
                    )
                ).first()
                
                if not existing:
                    new_slot = DoctorSlot(
                        doctor_id=doctor_id,
                        date=current_date,
                        start_time=start_time,
                        end_time=end_time,
                        is_booked=False,
                        is_blocked=False
                    )
                    db.add(new_slot)
                    slots_created += 1
        
        current_date += timedelta(days=1)
    
    return slots_created


# ==================== REGISTRATION & ONBOARDING ====================

@router.post("/register", response_model=dict)
async def register_doctor(
    request: DoctorRegistrationRequest,
    db: Session = Depends(get_db)
):
    """
    📝 DOCTOR REGISTRATION/ONBOARDING
    
    Creates:
    - User account (email + hashed password)
    - Clinic (if new) or joins existing
    - Doctor profile
    - Initial slots (1 month)
    - Wallet
    - Welcome notification
    """

    # --- Step 1: Check if email already registered ---
    existing_user = db.query(User).filter(User.email == request.email).first()
    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="Email already registered. Please use a different email or login."
        )

    # --- Step 2: Create User account with hashed password ---
    hashed_pwd = hash_password(request.password)
    new_user = User(
        name=request.name,
        email=request.email,
        password=hashed_pwd,
        role="doctor",                                   # Doctor role set karo
        is_active=True,
        created_at=datetime.now()
    )
    db.add(new_user)
    db.flush()                                           # new_user.id milega

    # --- Step 3: Check if doctor profile already exists (edge case) ---
    existing_doctor = db.query(Doctor).filter(Doctor.user_id == new_user.id).first()
    if existing_doctor:
        raise HTTPException(
            status_code=400, 
            detail="Doctor profile already exists"
        )
    
    # --- Step 4: Handle clinic ---
    clinic_id = request.clinic_id
    
    if not clinic_id:
        # Create new clinic
        if not all([request.clinic_name, request.clinic_address]):
            raise HTTPException(
                status_code=400,
                detail="Clinic name and address required for new clinic"
            )
        
        clinic_id = generate_clinic_id()
        
        clinic = Clinic(
            id=clinic_id,
            name=request.clinic_name,
            address=request.clinic_address,
            phone=request.clinic_phone or None,
            location_lat=request.location_lat,
            location_lng=request.location_lng,
            emergency_available=request.emergency_available,
            insurance_accepted=request.accepts_insurance,
            working_hours={
                day: f"{request.working_hours_start}-{request.working_hours_end}"
                for day in request.working_days
            }
        )
        db.add(clinic)
    else:
        # Verify clinic exists
        clinic = db.query(Clinic).filter(Clinic.id == clinic_id).first()
        if not clinic:
            raise HTTPException(status_code=404, detail="Clinic not found")
    
    # --- Step 5: Create doctor profile ---
    doctor = Doctor(
        clinic_id=clinic_id,
        user_id=new_user.id,
        name=request.name,
        specialties=request.specialties,
        qualification=request.qualification,
        experience_years=request.experience_years,
        consultation_fee=request.consultation_fee,
        medical_license_number=request.medical_license_number,
        medical_council=request.medical_council,
        is_available=True,
        is_verified=False,                               # Pending admin verification
        rating=0.0,
        total_consultations=0
    )
    
    db.add(doctor)
    db.flush()                                           # Get doctor.id
    
    # --- Step 6: Create wallet ---
    wallet = DoctorWallet(
        doctor_id=doctor.id,
        current_balance=0,
        total_earned=0,
        total_withdrawn=0
    )
    db.add(wallet)
    
    # --- Step 7: Create initial slots (next 30 days) ---
    default_slots = [
        {'start': '09:00', 'end': '09:30'},
        {'start': '09:30', 'end': '10:00'},
        {'start': '10:00', 'end': '10:30'},
        {'start': '10:30', 'end': '11:00'},
        {'start': '11:00', 'end': '11:30'},
        {'start': '11:30', 'end': '12:00'},
        {'start': '14:00', 'end': '14:30'},
        {'start': '14:30', 'end': '15:00'},
        {'start': '15:00', 'end': '15:30'},
        {'start': '15:30', 'end': '16:00'},
        {'start': '16:00', 'end': '16:30'},
        {'start': '16:30', 'end': '17:00'},
    ]
    
    slots_created = create_time_slots(
        doctor_id=doctor.id,
        start_date=date.today(),
        end_date=date.today() + timedelta(days=30),
        time_slots=default_slots,
        days=request.working_days,
        skip_dates=[],
        db=db
    )

    # --- Step 8: Welcome notification ---
    send_notification(
        db=db,
        user_id=new_user.id,
        title="Welcome! 🎉",
        message=(
            f"Dr. {request.name}, aapka registration successful hai. "
            f"Aapka profile abhi verification pending hai. "
            f"24-48 ghante mein admin verify karega."
        ),
        notification_type="verification",
        related_entity_type="doctor",
        related_entity_id=str(doctor.id)
    )
    
    # --- Step 9: Audit log ---
    audit = AuditLog(
        user_id=new_user.id,
        action="DOCTOR_REGISTERED",
        entity_type="doctor",
        entity_id=str(doctor.id),
        details={
            "clinic_id": clinic_id,
            "specialties": request.specialties,
            "slots_created": slots_created
        }
    )
    db.add(audit)
    db.commit()
    
    return {
        "status": "success",
        "message": "Doctor registration successful. Pending verification.",
        "doctor_id": doctor.id,
        "clinic_id": clinic_id,
        "slots_created": slots_created,
        "verification_status": "pending",
        "next_steps": [
            "Upload medical license document",
            "Upload clinic registration certificate",
            "Wait for admin verification (24-48 hours)",
            "Once verified, you can start accepting appointments"
        ]
    }



# ==================== LOGIN ====================

@router.post("/login", response_model=dict)
async def login_doctor(
    request: DoctorLoginRequest,
    db: Session = Depends(get_db)
):
    """
    🔐 DOCTOR LOGIN
    
    Email ya phone se login karo + password verify karo.
    Successful login pe token return hota hai + doctor profile info.
    """

    # --- Step 1: User dhundho email ya phone se ---
    if request.email:
        user = db.query(User).filter(User.email == request.email).first()
    else:
        user = db.query(User).filter(User.phone == request.phone).first()

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Email/Phone number not found. Please register first."
        )

    # --- Step 2: Password verify karo ---
    if not verify_password(request.password, user.password):
        raise HTTPException(
            status_code=401,
            detail="Incorrect password. Please try again."
        )

    # --- Step 3: Doctor profile check karo ---
    doctor = db.query(Doctor).filter(Doctor.user_id == user.id).first()
    if not doctor:
        raise HTTPException(
            status_code=404,
            detail="Doctor profile not found. Please complete registration."
        )

    # --- Step 4: Token generate karo aur user pe store karo ---
    token = generate_token()
    user.auth_token = token
    user.last_login = datetime.now()
    db.commit()

    # --- Step 5: Audit log ---
    audit = AuditLog(
        user_id=user.id,
        action="DOCTOR_LOGGED_IN",
        entity_type="doctor",
        entity_id=str(doctor.id),
        details={
            "login_via": "email" if request.email else "phone",
            "timestamp": str(datetime.now())
        }
    )
    db.add(audit)
    db.commit()

    return {
        "status": "success",
        "message": "Login successful",
        "token": token,
        "doctor": {
            "doctor_id": doctor.id,
            "user_id": user.id,
            "name": doctor.name,
            "clinic_id": doctor.clinic_id,
            "specialties": doctor.specialties,
            "is_verified": doctor.is_verified,
            "is_available": doctor.is_available,
            "verification_status": "verified" if doctor.is_verified else "pending"
        }
    }


# ==================== SLOT MANAGEMENT ====================

@router.post("/slots/create-batch", response_model=dict)
async def create_slots_batch(
    request: CreateSlotBatchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    📅 BULK CREATE SLOTS
    
    Example: Create next 3 months slots in one go
    """
    
    # Get doctor profile
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")
    
    # Create slots
    slots_created = create_time_slots(
        doctor_id=doctor.id,
        start_date=request.start_date,
        end_date=request.end_date,
        time_slots=request.time_slots,
        days=request.days,
        skip_dates=request.skip_dates or [],
        db=db
    )
    
    db.commit()
    
    return {
        "status": "success",
        "slots_created": slots_created,
        "date_range": f"{request.start_date} to {request.end_date}"
    }


@router.get("/slots/my-schedule", response_model=dict)
async def get_my_schedule(
    current_user: User = Depends(get_current_user),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db)
):
    """
    📆 VIEW MY SCHEDULE
    
    Shows all slots with booking status
    """
    
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")
    
    # Default to next 7 days
    if not start_date:
        start_date = date.today()
    if not end_date:
        end_date = start_date + timedelta(days=7)

    # Get slots
    slots = db.query(DoctorSlot).filter(
        and_(
            DoctorSlot.doctor_id == doctor.id,
            DoctorSlot.date >= start_date,
            DoctorSlot.date <= end_date
        )
    ).order_by(DoctorSlot.date, DoctorSlot.start_time).all()
    
    # Group by date
    schedule = {}
    for slot in slots:
        date_str = str(slot.date)
        if date_str not in schedule:
            schedule[date_str] = {
                "date": date_str,
                "day": slot.date.strftime('%A'),
                "slots": []
            }
        
        # Get appointment if booked
        appointment = None
        if slot.is_booked:
            appointment = db.query(Appointment).filter(
                Appointment.slot_id == slot.id
            ).first()

        schedule[date_str]["slots"].append({
            "slot_id": slot.id,
            "time": f"{slot.start_time.strftime('%I:%M %p')} - {slot.end_time.strftime('%I:%M %p')}",
            "status": "blocked" if slot.is_blocked else ("booked" if slot.is_booked else "available"),
            "patient_name": appointment.user.name if appointment else None,
            "patient_phone": appointment.user.phone if appointment else None,
            "appointment_id": appointment.id if appointment else None,
            "reason": appointment.reason if appointment else None
        })
    
    return {
        "date_range": f"{start_date} to {end_date}",
        "schedule": list(schedule.values())
    }


@router.put("/slots/block", response_model=dict)
async def block_slot(
    request: UpdateSlotRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    🚫 BLOCK/UNBLOCK SLOT
    
    Use cases:
    - Emergency break
    - Personal time
    - Lunch break
    """
    
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")
    
    slot = db.query(DoctorSlot).filter(
        and_(
            DoctorSlot.id == request.slot_id,
            DoctorSlot.doctor_id == doctor.id
        )
    ).first()
    
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")
    
    if slot.is_booked:
        raise HTTPException(
            status_code=400,
            detail="Cannot block already booked slot. Cancel appointment first."
        )
    
    slot.is_blocked = request.is_blocked if request.is_blocked is not None else True
    slot.block_reason = request.reason
    
    db.commit()

    return {
        "status": "success",
        "slot_id": slot.id,
        "is_blocked": slot.is_blocked,
        "message": "Slot blocked" if slot.is_blocked else "Slot unblocked"
    }


@router.post("/leave/apply", response_model=dict)
async def apply_leave(
    request: LeaveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    🏖 APPLY FOR LEAVE
    
    Blocks all slots in date range.
    Agar kisi patient ka appointment already booked hai ussi range mein,
    toh usse notification milegi ki doctor ne leave apply kiya hai.
    """
    
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    # --- Pehle: booked appointments dhundho is date range mein ---
    #     Taaki unke patients ko notification de sakein
    booked_appointments = db.query(Appointment).filter(
        and_(
            Appointment.doctor_id == doctor.id,
            Appointment.date >= request.start_date,
            Appointment.date <= request.end_date,
            Appointment.status == "confirmed"
        )
    ).all()

    # Har booked patient ko notification bhejo
    for apt in booked_appointments:
        send_notification(
            db=db,
            user_id=apt.user_id,
            title="⚠️ Doctor Leave Notice",
            message=(
                f"Dr. {doctor.name} ne {request.start_date} se {request.end_date} "
                f"tak leave apply kiya hai. Aapka {apt.date} ka appointment affected ho sakta hai. "
                f"Please apna appointment reschedule karein."
            ),
            notification_type="appointment",
            related_entity_type="appointment",
            related_entity_id=str(apt.id)
        )

    # --- Get all unbooked slots in date range ---
    slots = db.query(DoctorSlot).filter(
        and_(
            DoctorSlot.doctor_id == doctor.id,
            DoctorSlot.date >= request.start_date,
            DoctorSlot.date <= request.end_date,
            DoctorSlot.is_booked == False
        )
    ).all()
    
    # Block all available slots
    blocked_count = 0
    for slot in slots:
        slot.is_blocked = True
        slot.block_reason = f"Leave: {request.reason}"
        blocked_count += 1
    
    # Set doctor as unavailable
    doctor.is_available = False
    
    db.commit()
    
    return {
        "status": "success",
        "slots_blocked": blocked_count,
        "leave_period": f"{request.start_date} to {request.end_date}",
        "patients_notified": len(booked_appointments),
        "message": "Leave applied successfully"
    }


# ==================== APPOINTMENTS MANAGEMENT ====================

@router.get("/appointments/today", response_model=dict)
async def get_today_appointments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    📋 TODAY'S APPOINTMENTS
    """
    
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")
    
    appointments = db.query(Appointment).options(
        joinedload(Appointment.user)
    ).filter(
        and_(
            Appointment.doctor_id == doctor.id,
            Appointment.date == date.today(),
            Appointment.status == 'confirmed'
        )
    ).order_by(Appointment.time).all()
    
    return {
        "date": str(date.today()),
        "total": len(appointments),
        "appointments": [
            {
                "id": apt.id,
                "time": apt.time.strftime('%I:%M %p'),
                "patient_name": apt.user.name,
                "patient_phone": apt.user.phone,
                "patient_age": apt.user.age,
                "reason": apt.reason,
                "symptoms": apt.symptoms,
                "consultation_type": apt.consultation_type,
                "is_emergency": apt.is_emergency
            }
            for apt in appointments
        ]
    }


@router.get("/appointments/upcoming", response_model=dict)
async def get_upcoming_appointments(
    current_user: User = Depends(get_current_user),
    days: int = 7,
    db: Session = Depends(get_db)
):
    """
    📅 UPCOMING APPOINTMENTS (Next 7 days)
    """
    
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    end_date = date.today() + timedelta(days=days)
    
    appointments = db.query(Appointment).options(
        joinedload(Appointment.user)
    ).filter(
        and_(
            Appointment.doctor_id == doctor.id,
            Appointment.date >= date.today(),
            Appointment.date <= end_date,
            Appointment.status == 'confirmed'
        )
    ).order_by(Appointment.date, Appointment.time).all()
    
    # Group by date
    grouped = {}
    for apt in appointments:
        date_str = str(apt.date)
        if date_str not in grouped:
            grouped[date_str] = []
        
        grouped[date_str].append({
            "id": apt.id,
            "time": apt.time.strftime('%I:%M %p'),
            "patient_name": apt.user.name,
            "patient_phone": apt.user.phone,
            "reason": apt.reason
        })
    
    return {
        "period": f"Next {days} days",
        "total": len(appointments),
        "appointments_by_date": grouped
    }


@router.post("/appointments/{appointment_id}/complete", response_model=dict)
async def complete_appointment(
    appointment_id: str,
    diagnosis: Optional[str] = None,
    prescription: Optional[dict] = None,
    follow_up_required: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    ✅ MARK APPOINTMENT AS COMPLETED
    
    After consultation:
    - Status "completed" set karta hai
    - Prescription save karta hai (if provided)
    - Doctor wallet mein consultation fee credit karta hai
    - Patient ko completion notification bhejta hai
    """
    
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    appointment = db.query(Appointment).filter(
        and_(
            Appointment.id == appointment_id,
            Appointment.doctor_id == doctor.id
        )
    ).first()
    
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
    
    appointment.status = "completed"
    
    # Increment consultation count
    doctor.total_consultations += 1
    
    # Save diagnosis/prescription if provided
    if diagnosis or prescription:
        from database.models import Prescription
        
        prescription_record = Prescription(
            user_id=appointment.user_id,
            appointment_id=appointment.id,
            doctor_id=doctor.id,
            diagnosis=diagnosis,
            medicines=prescription,
            follow_up_required=follow_up_required,
            valid_until=date.today() + timedelta(days=30)
        )
        db.add(prescription_record)

    # --- Wallet mein consultation fee credit karo ---
    wallet = db.query(DoctorWallet).filter(
        DoctorWallet.doctor_id == doctor.id
    ).first()

    if wallet:
        credit_amount = doctor.consultation_fee

        # Credit transaction create karo
        credit_tx = WalletTransaction(
            wallet_id=wallet.id,
            amount=credit_amount,
            transaction_type="credit",
            description=f"Consultation fee — Appointment #{appointment.id}",
            balance_before=wallet.current_balance,
            balance_after=wallet.current_balance + credit_amount,
            metadata={
                "appointment_id": str(appointment.id),
                "patient_user_id": appointment.user_id
            }
        )
        db.add(credit_tx)

        # Wallet balance update karo
        wallet.current_balance += credit_amount
        wallet.total_earned += credit_amount

    # --- Patient ko notification bhejo ---
    send_notification(
        db=db,
        user_id=appointment.user_id,
        title="✅ Consultation Completed",
        message=(
            f"Dr. {doctor.name} ke saath aapki consultation complete ho gayi hai. "
            + (f"Diagnosis: {diagnosis}. " if diagnosis else "")
            + ("Follow-up required hai. " if follow_up_required else "")
            + "Prescription dekh sakte hain app mein."
        ),
        notification_type="appointment",
        related_entity_type="appointment",
        related_entity_id=str(appointment.id)
    )
    
    db.commit()
    
    return {
        "status": "success",
        "appointment_id": appointment_id,
        "message": "Appointment marked as completed",
        "fee_credited": doctor.consultation_fee if wallet else 0
    }


# ==================== WALLET & EARNINGS ====================

@router.get("/wallet", response_model=dict)
async def get_wallet_details(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    💰 VIEW WALLET BALANCE & EARNINGS
    """
    
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    wallet = db.query(DoctorWallet).filter(
        DoctorWallet.doctor_id == doctor.id
    ).first()
    
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    
    # Get recent transactions
    transactions = db.query(WalletTransaction).filter(
        WalletTransaction.wallet_id == wallet.id
    ).order_by(desc(WalletTransaction.created_at)).limit(10).all()
    
    return {
        "current_balance": wallet.current_balance,
        "total_earned": wallet.total_earned,
        "total_withdrawn": wallet.total_withdrawn,
        "pending_withdrawal": wallet.pending_withdrawal or 0,
        "can_withdraw": wallet.current_balance >= 500,  # Min ₹500
        "recent_transactions": [
            {
                "type": tx.transaction_type,
                "amount": tx.amount,
                "description": tx.description,
                "date": tx.created_at.strftime('%Y-%m-%d %I:%M %p'),
                "balance_after": tx.balance_after
            }
            for tx in transactions
        ]
    }


@router.post("/wallet/withdraw", response_model=dict)
async def withdraw_earnings(
    request: WithdrawRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    💸 WITHDRAW EARNINGS TO BANK
    
    Min: ₹500
    Processing: 2-3 business days
    """
    
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")
    
    wallet = db.query(DoctorWallet).filter(
        DoctorWallet.doctor_id == doctor.id
    ).with_for_update().first()
    
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    # Validation
    if request.amount < 500:
        raise HTTPException(
            status_code=400,
            detail="Minimum withdrawal amount is ₹500"
        )
    
    if wallet.current_balance < request.amount:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient balance. Available: ₹{wallet.current_balance}"
        )
    
    # Create withdrawal transaction
    transaction = WalletTransaction(
        wallet_id=wallet.id,
        amount=request.amount,
        transaction_type="withdrawal",
        description=f"Withdrawal to {request.bank_account}",
        balance_before=wallet.current_balance,
        balance_after=wallet.current_balance - request.amount,
        metadata={
            "bank_account": request.bank_account,
            "ifsc_code": request.ifsc_code,
            "status": "pending"
        }
    )
    db.add(transaction)
    
    # Update wallet
    wallet.current_balance -= request.amount
    wallet.total_withdrawn += request.amount
    wallet.pending_withdrawal = (wallet.pending_withdrawal or 0) + request.amount

    # --- Withdrawal notification doctor ko ---
    send_notification(
        db=db,
        user_id=current_user.id,
        title="💸 Withdrawal Request Submitted",
        message=(
            f"₹{request.amount} ka withdrawal request submit ho gaya hai. "
            f"Bank account: ****{request.bank_account[-4:]}. "
            f"2-3 business days mein credit ho jayega."
        ),
        notification_type="wallet",
        related_entity_type="withdrawal",
        related_entity_id=str(transaction.id)
    )
    
    db.commit()
    
    return {
        "status": "success",
        "withdrawal_id": transaction.id,
        "amount": request.amount,
        "estimated_credit": "2-3 business days",
        "new_balance": wallet.current_balance
    }


# ==================== ANALYTICS & STATS ====================

@router.get("/analytics/overview", response_model=dict)
async def get_analytics_overview(
    current_user: User = Depends(get_current_user),
    month: Optional[int] = None,
    year: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """
    📊 DOCTOR ANALYTICS DASHBOARD
    """
    
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")
    
    # Default to current month
    if not month:
        month = datetime.now().month
    if not year:
        year = datetime.now().year
    
    # Total appointments this month
    total_appointments = db.query(Appointment).filter(
        and_(
            Appointment.doctor_id == doctor.id,
            extract('month', Appointment.date) == month,
            extract('year', Appointment.date) == year
        )
    ).count()
    
    # Completed appointments
    completed = db.query(Appointment).filter(
        and_(
            Appointment.doctor_id == doctor.id,
            extract('month', Appointment.date) == month,
            extract('year', Appointment.date) == year,
            Appointment.status == 'completed'
        )
    ).count()
    
    # Cancelled appointments
    cancelled = db.query(Appointment).filter(
        and_(
            Appointment.doctor_id == doctor.id,
            extract('month', Appointment.date) == month,
            extract('year', Appointment.date) == year,
            Appointment.status == 'cancelled'
        )
    ).count()
    
    # Earnings this month
    wallet = db.query(DoctorWallet).filter(
        DoctorWallet.doctor_id == doctor.id
    ).first()
    
    month_earnings = db.query(func.sum(WalletTransaction.amount)).filter(
        and_(
            WalletTransaction.wallet_id == wallet.id,
            WalletTransaction.transaction_type == 'credit',
            extract('month', WalletTransaction.created_at) == month,
            extract('year', WalletTransaction.created_at) == year
        )
    ).scalar() or 0
    
    return {
        "period": f"{month}/{year}",
        "total_appointments": total_appointments,
        "completed": completed,
        "cancelled": cancelled,
        "no_show": total_appointments - completed - cancelled,
        "earnings_this_month": int(month_earnings),
        "average_rating": float(doctor.rating),
        "total_consultations_lifetime": doctor.total_consultations,
        "wallet_balance": wallet.current_balance if wallet else 0
    }


# ==================== PROFILE ====================

@router.put("/profile/update", response_model=dict)
async def update_doctor_profile(
    request: UpdateDoctorProfileRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    ✏️ UPDATE DOCTOR PROFILE
    """
    
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    # Track kya changes hue — audit log ke liye
    changes = {}

    if request.consultation_fee is not None:
        changes["consultation_fee"] = {"old": doctor.consultation_fee, "new": request.consultation_fee}
        doctor.consultation_fee = request.consultation_fee
    
    if request.specialties is not None:
        changes["specialties"] = {"old": doctor.specialties, "new": request.specialties}
        doctor.specialties = request.specialties
    
    if request.bio is not None:
        changes["bio"] = {"old": doctor.bio, "new": request.bio}
        doctor.bio = request.bio
    
    if request.is_available is not None:
        changes["is_available"] = {"old": doctor.is_available, "new": request.is_available}
        doctor.is_available = request.is_available

    # --- Audit log: kya kya change hua ---
    if changes:
        audit = AuditLog(
            user_id=current_user.id,
            action="DOCTOR_PROFILE_UPDATED",
            entity_type="doctor",
            entity_id=str(doctor.id),
            details=changes
        )
        db.add(audit)
    
    db.commit()
    
    return {
        "status": "success",
        "message": "Profile updated successfully"
    }