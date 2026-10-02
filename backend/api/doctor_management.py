"""
api/doctor_management.py — SECURITY-HARDENED - FINAL PRODUCTION
Install: pip install "passlib[bcrypt]"

DB Migrations to run first:
CREATE UNIQUE INDEX IF NOT EXISTS uq_doctor_slot_start ON doctor_slots (doctor_id, date, start_time);
CREATE UNIQUE INDEX IF NOT EXISTS uq_wallet_credit_per_appointment ON wallet_transactions (appointment_id, transaction_type) WHERE transaction_type = 'credit';
CREATE UNIQUE INDEX IF NOT EXISTS uq_doctor_medical_license ON doctors (medical_license_number);
ALTER TABLE wallet_transactions ADD COLUMN IF NOT EXISTS appointment_id VARCHAR(64);
"""

import logging
import uuid
from datetime import date, datetime, time, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from sqlalchemy import and_, func, desc, extract
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from database.connection import get_db
from database.models import (
    User, Doctor, Clinic, DoctorSlot, Appointment,
    DoctorWallet, WalletTransaction, AuditLog, Notification
)
from api.auth import get_current_user, create_access_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/doctor", tags=["Doctor Management"])

# ==================== SECURITY HELPERS ====================

password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
PASSWORD_MAX_LENGTH = 72

def hash_password(password: str) -> str:
    if len(password.encode("utf-8")) > PASSWORD_MAX_LENGTH:
        raise ValueError("Password is too long")
    return password_context.hash(password)

def verify_password(plain_password: str, stored_hash: str) -> bool:
    try:
        if len(plain_password.encode("utf-8")) > PASSWORD_MAX_LENGTH:
            return False
        return password_context.verify(plain_password, stored_hash)
    except Exception:
        return False

def generate_clinic_id() -> str:
    return f"CLI_{uuid.uuid4().hex[:16]}"

def mask_phone(phone: Optional[str]) -> Optional[str]:
    if not phone:
        return None
    phone = str(phone)
    if len(phone) <= 4:
        return "****"
    return f"{'*' * (len(phone) - 4)}{phone[-4:]}"

def get_verified_doctor(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Doctor:
    if current_user.role!= "doctor":
        raise HTTPException(status_code=403, detail="Doctor access required")
    if not current_user.is_active:
        raise HTTPException(status_code=403, detail="Account is inactive")
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")
    if not doctor.is_verified:
        raise HTTPException(status_code=403, detail="Doctor verification is pending")
    return doctor

def send_notification(db: Session, user_id: int, title: str, message: str, notification_type: str = "general", related_entity_type: Optional[str] = None, related_entity_id: Optional[str] = None) -> None:
    db.add(Notification(
        user_id=user_id, title=title, message=message,
        notification_type=notification_type, is_read=False,
        related_entity_type=related_entity_type, related_entity_id=related_entity_id,
        created_at=datetime.now()
    ))

# ==================== PYDANTIC MODELS ====================

VALID_WEEKDAYS = {"monday","tuesday","wednesday","thursday","friday","saturday","sunday"}

class TimeSlotInput(BaseModel):
    start: time
    end: time
    @model_validator(mode='after')
    def validate_slot_range(self):
        if self.end <= self.start:
            raise ValueError("Slot end time must be after start time")
        duration_minutes = (datetime.combine(date.today(), self.end) - datetime.combine(date.today(), self.start)).seconds // 60
        if duration_minutes < 10:
            raise ValueError("Slot duration must be at least 10 minutes")
        if duration_minutes > 180:
            raise ValueError("Slot duration cannot exceed 3 hours")
        return self

class DoctorRegistrationRequest(BaseModel):
    clinic_name: str = Field(..., min_length=2, max_length=100)
    clinic_address: str = Field(..., min_length=5, max_length=255)
    clinic_phone: Optional[str] = Field(None, max_length=20)
    location_lat: float = Field(..., ge=-90, le=90)
    location_lng: float = Field(..., ge=-180, le=180)
    full_name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=72)
    specialties: List[str] = Field(..., min_length=1, max_length=5)
    qualification: str = Field(..., min_length=2, max_length=100)
    experience_years: int = Field(..., ge=0, le=70)
    consultation_fee: int = Field(..., ge=100, le=10000)
    medical_license_number: str = Field(..., min_length=5, max_length=50)
    medical_council: str = Field(default="Medical Council of India", max_length=100)
    working_days: List[str] = Field(..., min_length=1, max_length=7)
    working_hours_start: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    working_hours_end: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    emergency_available: bool = False
    accepts_insurance: List[str] = Field(default_factory=list, max_length=20)

    @field_validator("working_days")
    @classmethod
    def validate_days(cls, days: List[str]) -> List[str]:
        cleaned = list({d.strip().lower() for d in days})
        invalid = set(cleaned) - VALID_WEEKDAYS
        if invalid:
            raise ValueError(f"Invalid working days: {', '.join(invalid)}")
        return cleaned

class DoctorLoginRequest(BaseModel):
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, min_length=10, max_length=15)
    password: str = Field(..., min_length=8)
    @model_validator(mode='after')
    def check_identifier(self):
        if not self.email and not self.phone:
            raise ValueError('Email or Phone is required')
        return self

class CreateSlotBatchRequest(BaseModel):
    start_date: date
    end_date: date
    time_slots: List[TimeSlotInput] = Field(..., min_length=1, max_length=50)
    days: List[str] = Field(..., min_length=1, max_length=7)
    skip_dates: List[date] = Field(default_factory=list, max_length=90)

    @field_validator("days")
    @classmethod
    def validate_days(cls, days: List[str]) -> List[str]:
        cleaned = list({d.strip().lower() for d in days})
        invalid = set(cleaned) - VALID_WEEKDAYS
        if invalid:
            raise ValueError(f"Invalid days: {', '.join(invalid)}")
        return cleaned

    @model_validator(mode='after')
    def validate_date_range(self):
        today = date.today()
        if self.start_date < today:
            raise ValueError("Cannot create slots in the past")
        if self.end_date < self.start_date:
            raise ValueError("end_date must be after start_date")
        if (self.end_date - self.start_date).days > 90:
            raise ValueError("Slot creation limited to 90 days per request")
        if ((self.end_date - self.start_date).days + 1) * len(self.time_slots) > 500:
            raise ValueError("Maximum 500 slots per request")
        return self

class UpdateSlotRequest(BaseModel):
    slot_id: int
    is_blocked: Optional[bool] = None
    reason: Optional[str] = Field(None, max_length=255)

class UpdateDoctorProfileRequest(BaseModel):
    consultation_fee: Optional[int] = Field(None, ge=100, le=50000)
    specialties: Optional[List[str]] = Field(None, max_length=5)
    bio: Optional[str] = Field(None, max_length=1000)
    is_available: Optional[bool] = None

class LeaveRequest(BaseModel):
    start_date: date
    end_date: date
    reason: str = Field(..., min_length=3, max_length=500)
    @model_validator(mode='after')
    def validate_leave_dates(self):
        if self.start_date < date.today():
            raise ValueError("Leave cannot start in the past")
        if self.end_date < self.start_date:
            raise ValueError("end_date must be after start_date")
        if (self.end_date - self.start_date).days > 90:
            raise ValueError("Leave range cannot exceed 90 days")
        return self

class WithdrawRequest(BaseModel):
    amount: int = Field(..., ge=500, le=500000)
    bank_account: str = Field(..., min_length=8, max_length=34)
    ifsc_code: str = Field(..., min_length=11, max_length=11)

    @field_validator("bank_account")
    @classmethod
    def validate_bank_account(cls, v: str) -> str:
        v = v.strip().replace(" ", "")
        if not v.isalnum():
            raise ValueError("Invalid bank account number")
        return v

    @field_validator("ifsc_code")
    @classmethod
    def validate_ifsc(cls, v: str) -> str:
        v = v.strip().upper()
        if len(v)!= 11 or not v[:4].isalpha() or v[4]!= "0" or not v[5:].isalnum():
            raise ValueError("Invalid IFSC code")
        return v

# ==================== CORE LOGIC ====================

def create_time_slots(doctor_id: int, start_date: date, end_date: date, time_slots: List[TimeSlotInput], days: List[str], skip_dates: List[date], db: Session) -> int:
    existing = db.query(DoctorSlot.date, DoctorSlot.start_time).filter(DoctorSlot.doctor_id == doctor_id, DoctorSlot.date >= start_date, DoctorSlot.date <= end_date).all()
    existing_keys = {(d, t) for d, t in existing}
    allowed_days = set(days)
    skipped = set(skip_dates)
    new_slots = []
    cur = start_date
    while cur <= end_date:
        if cur.strftime("%A").lower() in allowed_days and cur not in skipped:
            for slot in time_slots:
                key = (cur, slot.start)
                if key not in existing_keys:
                    new_slots.append(DoctorSlot(doctor_id=doctor_id, date=cur, start_time=slot.start, end_time=slot.end, is_booked=False, is_blocked=False))
                    existing_keys.add(key)
        cur += timedelta(days=1)
    if new_slots:
        db.bulk_save_objects(new_slots)
    return len(new_slots)

def credit_doctor_wallet_once(db: Session, doctor_id: int, appointment_id: str, amount: int, source: str) -> bool:
    """Call ONLY from webhook or admin cash confirm. Never from doctor /complete."""
    if amount <= 0:
        raise ValueError("Credit amount must be positive")
    wallet = db.query(DoctorWallet).filter(DoctorWallet.doctor_id == doctor_id).with_for_update().first()
    if not wallet:
        raise RuntimeError("Doctor wallet not found")
    existing = db.query(WalletTransaction).filter(WalletTransaction.appointment_id == appointment_id, WalletTransaction.transaction_type == "credit").first()
    if existing:
        return False
    before = int(wallet.current_balance or 0)
    db.add(WalletTransaction(wallet_id=wallet.id, appointment_id=appointment_id, amount=amount, transaction_type="credit", description=f"Verified payment credit ({source})", balance_before=before, balance_after=before+amount))
    wallet.current_balance = before + amount
    wallet.total_earned = int(wallet.total_earned or 0) + amount
    wallet.last_updated = datetime.now()
    return True

# ==================== ENDPOINTS ====================

@router.post("/register", response_model=dict)
async def register_doctor(request: DoctorRegistrationRequest, db: Session = Depends(get_db)):
    try:
        if db.query(User).filter(User.email == request.email).first():
            raise HTTPException(status_code=409, detail="An account with this email already exists")
        if db.query(Doctor).filter(Doctor.medical_license_number == request.medical_license_number.strip()).first():
            raise HTTPException(status_code=409, detail="Medical license is already registered")

        # IMPORTANT: Block clinic takeover - no clinic_id self-join allowed
        # clinic_id joining must be via invite flow, not self-service

        clinic_id = generate_clinic_id()
        new_user = User(
            full_name=request.full_name.strip(),
            email=str(request.email).lower(),
            phone=None, # Require separate phone verification flow, no fake DRxxx
            password_hash=hash_password(request.password),
            role="doctor",
            is_active=True,
            created_at=datetime.now()
        )
        db.add(new_user)
        db.flush()

        clinic = Clinic(
            id=clinic_id,
            name=request.clinic_name.strip(),
            address=request.clinic_address.strip(),
            phone=request.clinic_phone.strip() if request.clinic_phone else None,
            location_lat=request.location_lat,
            location_lng=request.location_lng,
            emergency_available=request.emergency_available,
            insurance_accepted=request.accepts_insurance or [],
            working_hours={day: f"{request.working_hours_start}-{request.working_hours_end}" for day in request.working_days}
        )
        db.add(clinic)
        db.flush()

        doctor = Doctor(
            clinic_id=clinic.id, user_id=new_user.id, name=request.full_name.strip(),
            specialties=request.specialties, specialization=request.specialties[0],
            qualification=request.qualification.strip(), experience_years=request.experience_years,
            consultation_fee=request.consultation_fee,
            medical_license_number=request.medical_license_number.strip(),
            medical_council=request.medical_council.strip(),
            is_available=False, # Not bookable until verified
            is_verified=False, rating=0.0, total_consultations=0
        )
        db.add(doctor)
        db.flush()

        db.add(DoctorWallet(doctor_id=doctor.id, current_balance=0, total_earned=0, total_withdrawn=0, pending_withdrawal=0))
        send_notification(db, new_user.id, "Registration received", "Your doctor profile is pending medical-license verification.", "verification", "doctor", str(doctor.id))
        db.add(AuditLog(user_id=new_user.id, action="DOCTOR_REGISTERED", entity_type="doctor", entity_id=str(doctor.id), details={"clinic_id": clinic.id, "verification_status": "pending"}))
        db.commit()
        return {"status": "success", "message": "Registration submitted. Verification is required.", "doctor_id": doctor.id, "clinic_id": clinic.id, "verification_status": "pending"}
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Registration conflict. Email or license may already exist.")
    except Exception as e:
        db.rollback()
        logger.error(f"Registration failed: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Registration could not be completed")

@router.post("/login", response_model=dict)
async def login_doctor(request: DoctorLoginRequest, db: Session = Depends(get_db)):
    identifier_email = str(request.email).lower() if request.email else None
    identifier_phone = request.phone.strip() if request.phone else None
    user_q = db.query(User).filter(User.role == "doctor")
    user = user_q.filter(User.email == identifier_email).first() if identifier_email else user_q.filter(User.phone == identifier_phone).first()

    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email/phone or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is inactive")

    doctor = db.query(Doctor).filter(Doctor.user_id == user.id).first()
    if not doctor:
        raise HTTPException(status_code=403, detail="Doctor profile is unavailable")
    if not doctor.is_verified:
        raise HTTPException(status_code=403, detail="Doctor verification is pending")

    token = create_access_token({"user_id": user.id, "role": "doctor", "doctor_id": doctor.id})
    user.last_login = datetime.now()
    db.add(AuditLog(user_id=user.id, action="DOCTOR_LOGGED_IN", entity_type="doctor", entity_id=str(doctor.id), details={"login_via": "email" if identifier_email else "phone"}))
    db.commit()
    return {"status": "success", "token": token, "doctor": {"doctor_id": doctor.id, "name": doctor.name, "clinic_id": doctor.clinic_id, "specialties": doctor.specialties, "is_verified": True, "is_available": doctor.is_available}}

@router.post("/slots/create-batch", response_model=dict)
async def create_slots_batch(request: CreateSlotBatchRequest, doctor: Doctor = Depends(get_verified_doctor), db: Session = Depends(get_db)):
    try:
        created = create_time_slots(doctor.id, request.start_date, request.end_date, request.time_slots, request.days, request.skip_dates, db)
        db.add(AuditLog(user_id=doctor.user_id, action="DOCTOR_SLOTS_CREATED", entity_type="doctor", entity_id=str(doctor.id), details={"start_date": request.start_date.isoformat(), "end_date": request.end_date.isoformat(), "slots_created": created}))
        db.commit()
        return {"status": "success", "slots_created": created, "date_range": f"{request.start_date.isoformat()} to {request.end_date.isoformat()}"}
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Some slots already exist. Refresh and retry.")
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Slots could not be created")

@router.get("/slots/my-schedule", response_model=dict)
async def get_my_schedule(doctor: Doctor = Depends(get_verified_doctor), start_date: Optional[date] = None, end_date: Optional[date] = None, db: Session = Depends(get_db)):
    start_date = start_date or date.today()
    end_date = end_date or (start_date + timedelta(days=7))
    slots = db.query(DoctorSlot).options(joinedload(DoctorSlot.appointment).joinedload(Appointment.user)).filter(DoctorSlot.doctor_id == doctor.id, DoctorSlot.date >= start_date, DoctorSlot.date <= end_date).order_by(DoctorSlot.date, DoctorSlot.start_time).all()
    schedule = {}
    for slot in slots:
        dstr = str(slot.date)
        if dstr not in schedule:
            schedule[dstr] = {"date": dstr, "day": slot.date.strftime('%A'), "slots": []}
        apt = getattr(slot, 'appointment', None)
        if not apt and slot.is_booked:
            apt = db.query(Appointment).filter(Appointment.slot_id == slot.id, Appointment.status.in_(["confirmed","reschedule_required"])).first()
        schedule[dstr]["slots"].append({
            "slot_id": slot.id,
            "time": f"{slot.start_time.strftime('%I:%M %p')} - {slot.end_time.strftime('%I:%M %p')}",
            "status": "blocked" if slot.is_blocked else ("booked" if slot.is_booked else "available"),
            "patient_name": apt.user.full_name if apt and apt.user else None,
            "patient_phone": mask_phone(apt.user.phone) if apt and apt.user else None,
            "appointment_id": apt.id if apt else None,
            "reason": apt.reason if apt else None
        })
    return {"date_range": f"{start_date} to {end_date}", "schedule": list(schedule.values())}

@router.put("/slots/block", response_model=dict)
async def block_slot(request: UpdateSlotRequest, doctor: Doctor = Depends(get_verified_doctor), db: Session = Depends(get_db)):
    slot = db.query(DoctorSlot).filter(DoctorSlot.id == request.slot_id, DoctorSlot.doctor_id == doctor.id).with_for_update().first()
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")
    if slot.is_booked:
        raise HTTPException(status_code=400, detail="Cannot block booked slot. Cancel appointment first.")
    slot.is_blocked = request.is_blocked if request.is_blocked is not None else True
    slot.block_reason = request.reason
    db.commit()
    return {"status": "success", "slot_id": slot.id, "is_blocked": slot.is_blocked}

@router.post("/leave/apply", response_model=dict)
async def apply_leave(request: LeaveRequest, doctor: Doctor = Depends(get_verified_doctor), db: Session = Depends(get_db)):
    try:
        locked_doctor = db.query(Doctor).filter(Doctor.id == doctor.id).with_for_update().first()
        affected = db.query(Appointment).filter(Appointment.doctor_id == doctor.id, Appointment.date >= request.start_date, Appointment.date <= request.end_date, Appointment.status == "confirmed").with_for_update().all()
        affected_ids = []
        for apt in affected:
            apt.status = "reschedule_required"
            apt.updated_at = datetime.now()
            affected_ids.append(apt.slot_id)
            send_notification(db, apt.user_id, "Appointment needs rescheduling", f"Your appointment with Dr. {locked_doctor.name} on {apt.date.isoformat()} needs rescheduling - doctor unavailable.", "appointment", "appointment", str(apt.id))

        slots = db.query(DoctorSlot).filter(DoctorSlot.doctor_id == doctor.id, DoctorSlot.date >= request.start_date, DoctorSlot.date <= request.end_date).with_for_update().all()
        for slot in slots:
            slot.is_blocked = True
            slot.block_reason = f"Doctor leave: {request.reason}"
            if slot.id in affected_ids:
                slot.is_booked = False

        db.add(AuditLog(user_id=doctor.user_id, action="DOCTOR_LEAVE_APPLIED", entity_type="doctor", entity_id=str(doctor.id), details={"start_date": request.start_date.isoformat(), "end_date": request.end_date.isoformat(), "affected": len(affected)}))
        db.commit()
        return {"status": "success", "leave_period": f"{request.start_date} to {request.end_date}", "patients_requiring_reschedule": len(affected), "message": "Leave applied and appointments marked for rescheduling."}
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Leave could not be applied")

@router.get("/appointments/today", response_model=dict)
async def get_today_appointments(doctor: Doctor = Depends(get_verified_doctor), db: Session = Depends(get_db)):
    appts = db.query(Appointment).options(joinedload(Appointment.user)).filter(Appointment.doctor_id == doctor.id, Appointment.date == date.today(), Appointment.status == 'confirmed').order_by(Appointment.time).all()
    return {"date": str(date.today()), "total": len(appts), "appointments": [{"id": a.id, "time": a.time.strftime('%I:%M %p'), "patient_name": a.user.full_name, "patient_phone": mask_phone(a.user.phone), "reason": a.reason, "consultation_type": a.consultation_type} for a in appts]}

@router.get("/appointments/upcoming", response_model=dict)
async def get_upcoming_appointments(doctor: Doctor = Depends(get_verified_doctor), days: int = Query(7, ge=1, le=30), db: Session = Depends(get_db)):
    end_date = date.today() + timedelta(days=days)
    appts = db.query(Appointment).options(joinedload(Appointment.user)).filter(Appointment.doctor_id == doctor.id, Appointment.date >= date.today(), Appointment.date <= end_date, Appointment.status == 'confirmed').order_by(Appointment.date, Appointment.time).all()
    grouped = {}
    for a in appts:
        ds = str(a.date)
        grouped.setdefault(ds, []).append({"id": a.id, "time": a.time.strftime('%I:%M %p'), "patient_name": a.user.full_name, "patient_phone": mask_phone(a.user.phone), "reason": a.reason})
    return {"period": f"Next {days} days", "total": len(appts), "appointments_by_date": grouped}

@router.post("/appointments/{appointment_id}/complete", response_model=dict)
async def complete_appointment(appointment_id: str, diagnosis: Optional[str] = Query(None, max_length=3000), follow_up_required: bool = False, doctor: Doctor = Depends(get_verified_doctor), db: Session = Depends(get_db)):
    """SECURITY: NEVER credits wallet. Money only via webhook/admin."""
    try:
        apt = db.query(Appointment).filter(Appointment.id == appointment_id, Appointment.doctor_id == doctor.id).with_for_update().first()
        if not apt:
            raise HTTPException(status_code=404, detail="Appointment not found")
        if apt.status == "completed":
            raise HTTPException(status_code=409, detail="Appointment already completed")
        if apt.status!= "confirmed":
            raise HTTPException(status_code=400, detail="Only confirmed appointments can be completed")
        if datetime.combine(apt.date, apt.time) > datetime.now() + timedelta(minutes=15):
            raise HTTPException(status_code=400, detail="Future appointments cannot be completed")

        apt.status = "completed"
        apt.updated_at = datetime.now()
        doctor.total_consultations = int(doctor.total_consultations or 0) + 1

        if diagnosis:
            from database.models import Prescription
            if not db.query(Prescription).filter(Prescription.appointment_id == apt.id).first():
                db.add(Prescription(user_id=apt.user_id, appointment_id=apt.id, doctor_id=doctor.id, diagnosis=diagnosis, medicines={}, follow_up_required=follow_up_required, valid_until=date.today() + timedelta(days=30)))

        send_notification(db, apt.user_id, "Consultation completed", "Your consultation has been marked as completed.", "appointment", "appointment", str(apt.id))
        db.add(AuditLog(user_id=doctor.user_id, action="APPOINTMENT_COMPLETED", entity_type="appointment", entity_id=apt.id, details={"follow_up_required": follow_up_required, "wallet_credit_created": False}))
        db.commit()
        return {"status": "success", "appointment_id": apt.id, "message": "Appointment marked as completed", "fee_credited": 0, "note": "Wallet credit handled only by verified payment webhook or admin cash collection."}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Appointment could not be completed")

@router.get("/wallet", response_model=dict)
async def get_wallet_details(doctor: Doctor = Depends(get_verified_doctor), db: Session = Depends(get_db)):
    wallet = db.query(DoctorWallet).filter(DoctorWallet.doctor_id == doctor.id).first()
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    txs = db.query(WalletTransaction).filter(WalletTransaction.wallet_id == wallet.id).order_by(desc(WalletTransaction.created_at)).limit(10).all()
    return {"current_balance": wallet.current_balance, "total_earned": wallet.total_earned, "total_withdrawn": wallet.total_withdrawn, "pending_withdrawal": wallet.pending_withdrawal or 0, "can_withdraw": wallet.current_balance >= 500, "recent_transactions": [{"type": t.transaction_type, "amount": t.amount, "description": t.description, "date": t.created_at.strftime('%Y-%m-%d %I:%M %p'), "balance_after": t.balance_after} for t in txs]}

@router.post("/wallet/withdraw", response_model=dict)
async def withdraw_earnings(request: WithdrawRequest, doctor: Doctor = Depends(get_verified_doctor), db: Session = Depends(get_db)):
    try:
        wallet = db.query(DoctorWallet).filter(DoctorWallet.doctor_id == doctor.id).with_for_update().first()
        if not wallet:
            raise HTTPException(status_code=404, detail="Wallet not found")
        if int(wallet.current_balance or 0) < request.amount:
            raise HTTPException(status_code=400, detail="Insufficient wallet balance")

        masked = f"****{request.bank_account[-4:]}"
        before = int(wallet.current_balance or 0)
        tx = WalletTransaction(wallet_id=wallet.id, amount=request.amount, transaction_type="withdrawal", description=f"Withdrawal request to {masked}", balance_before=before, balance_after=before-request.amount)
        db.add(tx)
        wallet.current_balance = before - request.amount
        wallet.total_withdrawn = int(wallet.total_withdrawn or 0) + request.amount
        wallet.pending_withdrawal = int(wallet.pending_withdrawal or 0) + request.amount

        send_notification(db, doctor.user_id, "Withdrawal request submitted", f"Withdrawal ₹{request.amount} to {masked} submitted.", "wallet", "withdrawal", None)
        db.add(AuditLog(user_id=doctor.user_id, action="WALLET_WITHDRAWAL_REQUESTED", entity_type="wallet", entity_id=str(wallet.id), details={"amount": request.amount, "bank_account_last4": request.bank_account[-4:]}))
        db.commit()
        db.refresh(tx)
        return {"status": "success", "withdrawal_id": tx.id, "amount": request.amount, "estimated_credit": "2-3 business days", "new_balance": wallet.current_balance}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Withdrawal could not be processed")

@router.get("/analytics/overview", response_model=dict)
async def get_analytics_overview(doctor: Doctor = Depends(get_verified_doctor), month: Optional[int] = None, year: Optional[int] = None, db: Session = Depends(get_db)):
    month = month or datetime.now().month
    year = year or datetime.now().year
    base = [Appointment.doctor_id == doctor.id, extract('month', Appointment.date) == month, extract('year', Appointment.date) == year]
    total = db.query(Appointment).filter(*base).count()
    completed = db.query(Appointment).filter(*base, Appointment.status == 'completed').count()
    cancelled = db.query(Appointment).filter(*base, Appointment.status == 'cancelled').count()
    wallet = db.query(DoctorWallet).filter(DoctorWallet.doctor_id == doctor.id).first()
    month_earn = db.query(func.sum(WalletTransaction.amount)).filter(WalletTransaction.wallet_id == wallet.id if wallet else -1, WalletTransaction.transaction_type == 'credit', extract('month', WalletTransaction.created_at) == month, extract('year', WalletTransaction.created_at) == year).scalar() or 0 if wallet else 0
    return {"period": f"{month}/{year}", "total_appointments": total, "completed": completed, "cancelled": cancelled, "no_show": total - completed - cancelled, "earnings_this_month": int(month_earn), "average_rating": float(doctor.rating or 0), "total_consultations_lifetime": doctor.total_consultations, "wallet_balance": wallet.current_balance if wallet else 0}

@router.put("/profile/update", response_model=dict)
async def update_doctor_profile(request: UpdateDoctorProfileRequest, doctor: Doctor = Depends(get_verified_doctor), db: Session = Depends(get_db)):
    changes = {}
    if request.consultation_fee is not None:
        changes["consultation_fee"] = {"old": doctor.consultation_fee, "new": request.consultation_fee}
        doctor.consultation_fee = request.consultation_fee
    if request.specialties is not None:
        changes["specialties"] = {"old": doctor.specialties, "new": request.specialties}
        doctor.specialties = request.specialties
        doctor.specialization = request.specialties[0]
    if request.bio is not None:
        changes["bio"] = {"old": getattr(doctor, 'bio', None), "new": request.bio}
        doctor.bio = request.bio
    if request.is_available is not None:
        changes["is_available"] = {"old": doctor.is_available, "new": request.is_available}
        doctor.is_available = request.is_available
    if changes:
        db.add(AuditLog(user_id=doctor.user_id, action="DOCTOR_PROFILE_UPDATED", entity_type="doctor", entity_id=str(doctor.id), details=changes))
    db.commit()
    return {"status": "success", "message": "Profile updated successfully"}
