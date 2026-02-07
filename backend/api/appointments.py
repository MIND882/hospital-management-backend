import sys
from pathlib import Path

# Add backend directory to path for imports to work when running directly
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, func
from database.connection import get_db
from database.models import User, Doctor, Clinic, DoctorSlot, Appointment, Notification, AuditLog, PaymentStatus, AppointmentPayment, DoctorWallet, WalletTransaction, QRCode
from pydantic import BaseModel, Field
from api.payments import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET
from typing import List, Optional
from datetime import datetime, date, time, timedelta
import secrets
import math
try:
    import qrcode
except Exception:
    qrcode = None
import base64
import json
from io import BytesIO
from sqlalchemy import Enum as SQLEnum
from enum import Enum as PyEnum
from .payments import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET

router = APIRouter(prefix="/api/appointments", tags=["Appointments"])

class PaymentMethod(PyEnum):
    ADVANCE = "advance"
    PAY_AT_CLINIC = "pay_at_clinic"

# ==================== PYDANTIC MODELS (Request/Response) ====================

class DoctorSearchRequest(BaseModel):
    location: str = Field(..., description="Area/city name or 'use_gps'")
    user_lat: Optional[float] = Field(None, description="User's latitude (if using GPS)")
    user_lng: Optional[float] = Field(None, description="User's longitude (if using GPS)")
    specialty: str = Field(..., description="Doctor specialty")
    preferred_date: date = Field(..., description="Preferred appointment date")
    preferred_time: Optional[str] = Field(None, description="morning/afternoon/evening")
    budget_min: int = Field(0, description="Minimum consultation fee")
    budget_max: int = Field(999999, description="Maximum consultation fee")
    insurance_provider: Optional[str] = Field(None, description="Insurance provider name")
    sort_by: str = Field("distance", description="distance/rating/fee")
    page: int = Field(1, ge=1)
    limit: int = Field(20, ge=1, le=50)

class DoctorResponse(BaseModel):
    id: int
    name: str
    specialty: str
    experience_years: int
    clinic_name: str
    clinic_address: str
    distance_km: float
    rating: float
    total_reviews: int
    consultation_fee: int
    insurance_accepted: List[str]
    next_slot: Optional[str]
    available_today: bool

class SlotResponse(BaseModel):
    id: int
    time: str
    display: str  # "3:00 PM"

class AppointmentBookRequest(BaseModel):
    user_id: int
    doctor_id: int
    slot_id: int
    date: date
    reason: Optional[str] = None
    symptoms: Optional[List[str]] = []
    consultation_type: str = Field("in-person", description="in-person/video/phone")
    is_emergency: bool = False
    payment_method: PaymentMethod = Field(PaymentMethod.ADVANCE, description="advance/pay_at_clinic")

class AppointmentResponse(BaseModel):
    appointment_id: str
    status: str
    details: dict

class CancellationRequest(BaseModel):
    appointment_id: str
    user_id: int
    reason: Optional[str] = None

# ==================== HELPER FUNCTIONS ====================

def calculate_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    Calculate distance between two coordinates using Haversine formula
    Returns distance in kilometers
    """
    R = 6371  # Earth's radius in kilometers
    
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    
    a = (math.sin(dlat / 2) ** 2 + 
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * 
         math.sin(dlng / 2) ** 2)
    
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance = R * c
    
    return round(distance, 1)

def generate_qr_code(appointment_id: str, doctor_id: int, patient_id: int) -> str:
    """Generate QR code for appointment verification"""
    qr_data = {
        "appointment_id": appointment_id,
        "doctor_id": doctor_id,
        "patient_id": patient_id,
        "timestamp": datetime.now().isoformat()
    }
    
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(json.dumps(qr_data))
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    
    return img_str

def calculate_payment_breakdown(consultation_fee: int) -> dict:
    """Calculate 80-20 split for payment"""
    total_amount = consultation_fee
    platform_fee = int(total_amount * 0.20)  # 20% platform fee
    doctor_share = total_amount - platform_fee  # 80% doctor share
    
    return {
        "total_amount": total_amount,
        "platform_fee": platform_fee,
        "doctor_share": doctor_share
    }

def credit_doctor_wallet(db: Session, doctor_id: int, amount: int, appointment_id: str):
    """Credit amount to doctor's wallet"""
    # Get or create doctor wallet
    wallet = db.query(DoctorWallet).filter(DoctorWallet.doctor_id == doctor_id).first()
    
    if not wallet:
        wallet = DoctorWallet(doctor_id=doctor_id, current_balance=0, total_earned=0)
        db.add(wallet)
        db.commit()
        db.refresh(wallet)
    
    # Record transaction
    transaction = WalletTransaction(
        wallet_id=wallet.id,
        appointment_id=appointment_id,
        amount=amount,
        transaction_type="credit",
        description=f"Payment for appointment {appointment_id}",
        balance_before=wallet.current_balance,
        balance_after=wallet.current_balance + amount
    )
    
    # Update wallet balance
    wallet.current_balance += amount
    wallet.total_earned += amount
    wallet.last_updated = datetime.now()
    
    db.add(transaction)
    db.commit()
    
    # Send notification to doctor
    send_notification(
        db=db,
        user_id=db.query(Doctor).filter(Doctor.id == doctor_id).first().user_id,
        type="payment_received",
        title="Payment Received",
        message=f"₹{amount} credited to wallet for appointment {appointment_id}",
        details={"amount": amount, "appointment_id": appointment_id}
    )


def generate_booking_id() -> str:
    """Generate unique appointment ID like APT123456"""
    return f"APT{secrets.randbelow(900000) + 100000}"

def update_doctor_next_available_slot(db: Session, doctor_id: int):
    """Update doctor's next_available_slot based on earliest unbooked future slot"""
    next_slot = db.query(DoctorSlot).filter(
        and_(
            DoctorSlot.doctor_id == doctor_id,
            DoctorSlot.date >= datetime.now().date(),
            DoctorSlot.is_booked == False
        )
    ).order_by(DoctorSlot.date, DoctorSlot.start_time).first()
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if doctor:
        if next_slot:
            doctor.next_available_slot = datetime.combine(next_slot.date, next_slot.start_time)
        else:
            doctor.next_available_slot = None
        db.commit()

def send_booking_notifications(db: Session, appointment_id: str, doctor_name: str, patient_name: str, payment_method: str):
    """Background task to notify patient and doctor after booking"""
    try:
        apt = db.query(Appointment).filter(Appointment.id == appointment_id).first()
        if not apt:
            return
        # Notify patient
        send_notification(
            db=db,
            user_id=apt.user_id,
            type="appointment_booked",
            title="Appointment Booked",
            message=f"Your appointment with Dr. {doctor_name} on {apt.date} at {apt.time.strftime('%I:%M %p')} is {apt.status}."
        )
        # Notify doctor (via doctor's user account)
        doc = db.query(Doctor).filter(Doctor.id == apt.doctor_id).first()
        if doc:
            send_notification(
                db=db,
                user_id=doc.user_id,
                type="new_appointment",
                title="New Appointment",
                message=f"You have a new appointment with {patient_name} on {apt.date} at {apt.time.strftime('%I:%M %p')}."
            )
    except Exception:
        # log silently — avoid raising in background task
        pass


def send_notification(db: Session, user_id: int, type: str, title: str, message: str):
    """Create notification for user"""
    notification = Notification(
        user_id=user_id,
        type=type,
        title=title,
        message=message
    )
    db.add(notification)
    db.commit()

def log_action(db: Session, user_id: int, action: str, entity_type: str, entity_id: str, details: dict):
    """Create audit log entry"""
    audit = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details
    )
    db.add(audit)
    db.commit()

def filter_slots_by_time_preference(slots: List[DoctorSlot], preference: str) -> List[DoctorSlot]:
    """Filter slots based on time preference"""
    if not preference or preference == "any":
        return slots
    
    filtered = []
    for slot in slots:
        hour = slot.start_time.hour
        
        if preference == "morning" and 6 <= hour < 12:
            filtered.append(slot)
        elif preference == "afternoon" and 12 <= hour < 17:
            filtered.append(slot)
        elif preference == "evening" and 17 <= hour < 22:
            filtered.append(slot)
    
    return filtered

# ==================== API ENDPOINTS ====================

@router.post("/search", response_model=dict)
async def search_doctors(
    request: DoctorSearchRequest,
    db: Session = Depends(get_db)
):
    """
    STEP 2 & 3: Search doctors based on filters
    
    ✅ FIXES APPLIED:
    1. Changed jsonb_exists_any → .contains() for specialty
    2. Changed jsonb_exists → .contains() for insurance
    3. Added joinedload() to prevent N+1 queries
    """
    
    # ✅ FIX 2: USE JOINEDLOAD TO FETCH CLINIC & SLOTS TOGETHER
    # WHY: Prevents N+1 problem - fetches all related data in ONE query
    # BEFORE: 1 doctor query + 50 slot queries = 51 queries
    # AFTER: Just 1 query with JOIN
    query = db.query(Doctor).options(
        joinedload(Doctor.clinic),      # Fetch clinic data with doctor
        joinedload(Doctor.slots)        # Fetch slots data with doctor
    ).filter(Doctor.is_available == True)
    
    # ✅ FIX 3: SPECIALTY FILTER - Changed from jsonb_exists_any to .contains()
    # WHY: jsonb_exists_any doesn't exist in SQLAlchemy
    # BEFORE: func.jsonb_exists_any(Doctor.specialties, [request.specialty])
    # AFTER: Doctor.specialties.contains([request.specialty])
    if request.specialty and request.specialty.lower() != "any":
        query = query.filter(
            Doctor.specialties.contains([request.specialty])  # ✅ FIXED
        )
    
    # Filter by consultation fee (budget range)
    query = query.filter(
        and_(
            Doctor.consultation_fee >= request.budget_min,
            Doctor.consultation_fee <= request.budget_max
        )
    )
    
    # Join with clinic for location and insurance (already loaded via joinedload)
    query = query.join(Clinic)
    
    # ✅ FIX 4: INSURANCE FILTER - Changed from jsonb_exists to .contains()
    # WHY: jsonb_exists checks key existence, not array containment
    # BEFORE: func.jsonb_exists(Clinic.insurance_accepted, request.insurance_provider)
    # AFTER: Clinic.insurance_accepted.contains([request.insurance_provider])
    if request.insurance_provider:
        query = query.filter(
            Clinic.insurance_accepted.contains([request.insurance_provider])  # ✅ FIXED
        )
    
    # Filter by location
    if request.location.lower() != "use_gps":
        query = query.filter(Clinic.address.ilike(f"%{request.location}%"))
    
    # Get all matching doctors
    doctors = query.all()
    
    if not doctors:
        return {
            "total": 0,
            "doctors": [],
            "message": "No doctors found matching your criteria"
        }
    
    # Calculate distance for each doctor (if GPS provided)
    doctors_with_distance = []
    for doctor in doctors:
        distance = 0.0
        
        if request.user_lat and request.user_lng:
            distance = calculate_distance(
                request.user_lat,
                request.user_lng,
                float(doctor.clinic.location_lat),
                float(doctor.clinic.location_lng)
            )
        
        # ✅ FIX 5: NO MORE N+1 QUERIES - Use already loaded slots
        # WHY: doctor.slots is already fetched via joinedload, no extra query needed
        # BEFORE: db.query(DoctorSlot).filter(...).count() <- Extra query
        # AFTER: Use doctor.slots (already in memory)
        
        # Check if doctor has slots on preferred date
        has_slots = any(
            slot.date == request.preferred_date and not slot.is_booked
            for slot in doctor.slots
        )
        
        # Get next available slot
        # Filter slots that are not booked and in future
        available_slots = [
            slot for slot in doctor.slots
            if slot.date >= datetime.now().date() and not slot.is_booked
        ]
        
        # Sort and get first slot
        next_slot = None
        if available_slots:
            available_slots.sort(key=lambda s: (s.date, s.start_time))
            next_slot = available_slots[0]
        
        doctors_with_distance.append({
            "doctor": doctor,
            "distance_km": distance,
            "has_slots": has_slots,
            "next_slot": next_slot
        })
    
    # Apply sorting
    if request.sort_by == "distance":
        doctors_with_distance.sort(key=lambda x: x["distance_km"])
    elif request.sort_by == "rating":
        doctors_with_distance.sort(key=lambda x: float(x["doctor"].rating), reverse=True)
    elif request.sort_by == "fee":
        doctors_with_distance.sort(key=lambda x: x["doctor"].consultation_fee)
    
    # Apply pagination
    start_idx = (request.page - 1) * request.limit
    end_idx = start_idx + request.limit
    paginated = doctors_with_distance[start_idx:end_idx]
    
    # Format response
    results = []
    for item in paginated:
        doctor = item["doctor"]
        next_slot = item["next_slot"]
        
        results.append({
            "id": doctor.id,
            "name": doctor.name,
            "specialty": doctor.specialties[0] if doctor.specialties else "General",
            "experience_years": doctor.experience_years or 0,
            "clinic_name": doctor.clinic.name,
            "clinic_address": doctor.clinic.address,
            "distance_km": item["distance_km"],
            "rating": float(doctor.rating),
            "total_reviews": doctor.total_consultations,
            "consultation_fee": doctor.consultation_fee,
            "insurance_accepted": doctor.clinic.insurance_accepted or [],
            "next_slot": next_slot.start_time.strftime("%I:%M %p") if next_slot else None,
            "available_today": next_slot.date == datetime.now().date() if next_slot else False,
            "has_slots_on_preferred_date": item["has_slots"]
        })
    
    return {
        "total": len(doctors_with_distance),
        "page": request.page,
        "limit": request.limit,
        "doctors": results
    }


@router.get("/doctors/{doctor_id}/slots", response_model=dict)
async def get_doctor_slots(
    doctor_id: int,
    date: date = Query(..., description="Date in YYYY-MM-DD format"),
    time_preference: Optional[str] = Query(None, description="morning/afternoon/evening"),
    db: Session = Depends(get_db)
):
    """
    STEP 4: Get available time slots for a doctor on specific date
    
    ✅ FIX APPLIED: Added current time check for today's slots
    """
    
    # Verify doctor exists
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    
    # ✅ FIX 6: CHECK CURRENT TIME FOR TODAY'S SLOTS
    # WHY: Don't show past time slots for today
    # EXAMPLE: If now is 3 PM, don't show 9 AM, 10 AM, 11 AM slots
    
    # Build base query
    base_filters = [
        DoctorSlot.doctor_id == doctor_id,
        DoctorSlot.date == date,
        DoctorSlot.is_booked == False
    ]
    
    # If date is today, add time filter
    if date == datetime.now().date():
        current_time = datetime.now().time()
        base_filters.append(DoctorSlot.start_time > current_time)  # ✅ FIXED
    
    # Get all unbooked slots for the date
    slots = db.query(DoctorSlot).filter(
        and_(*base_filters)
    ).order_by(DoctorSlot.start_time).all()
    
    # Filter by time preference if provided
    if time_preference:
        slots = filter_slots_by_time_preference(slots, time_preference)
    
    # Format response
    formatted_slots = []
    for slot in slots:
        formatted_slots.append({
            "id": slot.id,
            "time": slot.start_time.strftime("%H:%M"),
            "display": slot.start_time.strftime("%I:%M %p"),
            "end_time": slot.end_time.strftime("%I:%M %p")
        })
    
    return {
        "doctor_id": doctor_id,
        "doctor_name": doctor.name,
        "date": str(date),
        "total_slots": len(formatted_slots),
        "slots": formatted_slots
    }


@router.post("/book", response_model=AppointmentResponse)
async def book_appointment(
    request: AppointmentBookRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Book appointment with advance payment (Industry Standard)
    
    FLOW:
    - Pay at Clinic: Confirm immediately, doctor gets 80% after appointment
    - Advance Payment: Create Razorpay order, doctor gets 80% after payment
    """
    
    print(f"Booking request received: {request.dict()}")
    
    # ========== VALIDATION 1: USER EXISTS ==========
    user = db.query(User).filter(User.id == request.user_id).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found. Please login again."
        )
    
    # ========== VALIDATION 2: DOCTOR EXISTS & ACTIVE ==========
    doctor = db.query(Doctor).options(
        joinedload(Doctor.clinic)
    ).filter(
        and_(
            Doctor.id == request.doctor_id,
            Doctor.is_available == True
        )
    ).first()
    
    if not doctor:
        raise HTTPException(
            status_code=404,
            detail="Doctor not found or not available"
        )
    
    # ========== VALIDATION 3: SLOT EXISTS & AVAILABLE ==========
    slot = db.query(DoctorSlot).with_for_update().filter(
        DoctorSlot.id == request.slot_id
    ).first()
    
    if not slot:
        raise HTTPException(
            status_code=404,
            detail="Time slot not found"
        )
    
    if slot.is_booked:
        raise HTTPException(
            status_code=400,
            detail="This time slot is already booked. Please choose another slot."
        )
    
    # ========== VALIDATION 4: SLOT BELONGS TO CORRECT DOCTOR & DATE ==========
    if slot.doctor_id != request.doctor_id:
        raise HTTPException(
            status_code=400,
            detail="Selected slot does not belong to this doctor"
        )
    
    if slot.date != request.date:
        raise HTTPException(
            status_code=400,
            detail="Selected date does not match slot date"
        )
    
    # ========== VALIDATION 5: FUTURE APPOINTMENT ==========
    appointment_datetime = datetime.combine(request.date, slot.start_time)
    if appointment_datetime <= datetime.now():
        raise HTTPException(
            status_code=400,
            detail="Cannot book appointments in the past. Please select a future time."
        )
    
    # ========== VALIDATION 6: MINIMUM BOOKING TIME ==========
    min_booking_time = timedelta(hours=1)  # Can't book within 1 hour
    time_until_appointment = appointment_datetime - datetime.now()
    if time_until_appointment < min_booking_time:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot book within {min_booking_time.seconds//3600} hours of appointment time"
        )
    
    # ========== VALIDATION 7: DOCTOR MAX APPOINTMENTS PER DAY ==========
    daily_appointments = db.query(Appointment).filter(
        and_(
            Appointment.doctor_id == request.doctor_id,
            Appointment.date == request.date,
            Appointment.status.in_(["confirmed", "payment_pending"])
        )
    ).count()
    
    max_daily_appointments = 20  # Configurable
    if daily_appointments >= max_daily_appointments:
        raise HTTPException(
            status_code=400,
            detail=f"Doctor has reached maximum appointments for {request.date}. Please choose another date."
        )
    
    try:
        # Generate booking ID
        booking_id = generate_booking_id()
        print(f"Generated booking ID: {booking_id}")
        
        # Calculate payment breakdown
        breakdown = calculate_payment_breakdown(doctor.consultation_fee)
        print(f"Payment breakdown: {breakdown}")
        
        # ========== PAYMENT METHOD: ADVANCE ==========
        if request.payment_method == PaymentMethod.ADVANCE:
            # Create Razorpay order (try real client, fallback to mock)
            try:
                import razorpay
                client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
                razorpay_order = client.order.create({
                    "amount": breakdown["total_amount"] * 100,
                    "currency": "INR",
                    "receipt": booking_id,
                    "notes": {
                        "appointment_id": booking_id,
                        "patient_id": user.id,
                        "patient_name": user.name,
                        "doctor_id": doctor.id,
                        "doctor_name": doctor.name,
                        "slot_id": slot.id,
                        "date": str(request.date),
                        "time": slot.start_time.strftime("%H:%M")
                    },
                    "partial_payment": False
                })
                print(f"Razorpay order created: {razorpay_order.get('id')}")
            except Exception as e:
                # Fallback: create mock order id (dev/testing)
                print(f"Razorpay error or library not installed: {e}, using mock order")
                razorpay_order = {"id": f"order_{booking_id}_{int(datetime.now().timestamp())}"}

            # Appointment status for advance payment
            appointment_status = "payment_pending"
            payment_status = PaymentStatus.PENDING
            
        # ========== PAYMENT METHOD: PAY AT CLINIC ==========
        else:
            razorpay_order = None
            appointment_status = "confirmed"
            payment_status = PaymentStatus.PENDING  # Will be paid later
        
        # ========== CREATE APPOINTMENT ==========
        appointment = Appointment(
            id=booking_id,
            user_id=request.user_id,
            doctor_id=request.doctor_id,
            slot_id=request.slot_id,
            date=request.date,
            time=slot.start_time,
            reason=request.reason,
            symptoms=request.symptoms,
            status=appointment_status,
            is_emergency=request.is_emergency,
            consultation_type=request.consultation_type,
            total_amount=breakdown["total_amount"],
            platform_fee=breakdown["platform_fee"],
            doctor_share=breakdown["doctor_share"]
        )
        db.add(appointment)
        
        # ========== MARK SLOT AS BOOKED ==========
        slot.is_booked = True
        
        # ========== CREATE PAYMENT RECORD ==========
        payment = AppointmentPayment(
            appointment_id=booking_id,
            total_amount=breakdown["total_amount"],
            platform_fee=breakdown["platform_fee"],
            doctor_share=breakdown["doctor_share"],
            razorpay_order_id=razorpay_order["id"] if razorpay_order else None,
            payment_status=payment_status
        )
        db.add(payment)
        
        # ========== FOR PAY AT CLINIC: CREATE WALLET ENTRY (to be credited later) ==========
        if request.payment_method == PaymentMethod.PAY_AT_CLINIC:
            # Create wallet for doctor if not exists
            wallet = db.query(DoctorWallet).filter(
                DoctorWallet.doctor_id == doctor.id
            ).first()
            if not wallet:
                wallet = DoctorWallet(
                    doctor_id=doctor.id,
                    current_balance=0,
                    total_earned=0
                )
                db.add(wallet)
        
        # ========== FOR ADVANCE PAYMENT: GENERATE QR TEMPLATE ==========
        if request.payment_method == PaymentMethod.ADVANCE:
            qr_data = generate_qr_code(booking_id, doctor.id, user.id)
            qr_record = QRCode(
                appointment_id=booking_id,
                qr_data=qr_data,
                verification_token=secrets.token_urlsafe(32)
            )
            db.add(qr_record)
        
        # ========== UPDATE DOCTOR STATS ==========
        doctor.total_consultations += 1
        
        # Update next available slot
        update_doctor_next_available_slot(db, doctor.id)
        
        # ========== COMMIT ALL CHANGES ==========
        db.commit()
        db.refresh(appointment)
        print(f"Appointment created: {booking_id}")
        
        # ========== SEND NOTIFICATIONS ==========
        background_tasks.add_task(
            send_booking_notifications,
            db,
            appointment.id,
            doctor.name,
            user.name,
            request.payment_method.value
        )
        
        # ========== LOG ACTION ==========
        log_action(
            db=db,
            user_id=request.user_id,
            action="APPOINTMENT_BOOKED",
            entity_type="appointment",
            entity_id=booking_id,
            details={
                "doctor_id": request.doctor_id,
                "doctor_name": doctor.name,
                "date": str(request.date),
                "time": slot.start_time.strftime("%H:%M"),
                "fee": doctor.consultation_fee,
                "payment_method": request.payment_method.value,
                "doctor_share": breakdown["doctor_share"]
            }
        )
        
        # ========== PREPARE RESPONSE ==========
        response_data = {
            "appointment_id": booking_id,
            "status": appointment.status,
            "message": "Appointment booking successful"
        }
        
        # ========== RESPONSE FOR ADVANCE PAYMENT ==========
        if request.payment_method == PaymentMethod.ADVANCE:
            response_data.update({
                "payment_required": True,
                "next_step": "complete_payment",
                "payment_details": {
                    "order_id": razorpay_order["id"],
                    "amount": breakdown["total_amount"],
                    "currency": "INR",
                    "key_id": RAZORPAY_KEY_ID,
                    "breakdown": {
                        "total": f"₹{breakdown['total_amount']}",
                        "platform_fee": f"₹{breakdown['platform_fee']}",
                        "doctor_share": f"₹{breakdown['doctor_share']}",
                        "platform_percentage": 20.0,
                        "doctor_percentage": 80.0
                    },
                    "razorpay_data": {
                        "name": "MediBook Healthcare",
                        "description": f"Appointment with Dr. {doctor.name}",
                        "prefill": {
                            "name": user.name,
                            "email": user.email,
                            "contact": user.phone
                        },
                        "notes": {
                            "appointment_id": booking_id
                        }
                    }
                }
            })
        
        # ========== RESPONSE FOR PAY AT CLINIC ==========
        else:
            response_data.update({
                "payment_required": False,
                "appointment_details": {
                    "booking_id": booking_id,
                    "patient_name": user.name,
                    "patient_phone": user.phone,
                    "doctor_name": doctor.name,
                    "doctor_specialty": doctor.specialties[0] if doctor.specialties else "General",
                    "clinic_name": doctor.clinic.name,
                    "clinic_address": doctor.clinic.address,
                    "clinic_phone": doctor.clinic.phone,
                    "date": str(request.date),
                    "time": slot.start_time.strftime("%I:%M %p"),
                    "end_time": slot.end_time.strftime("%I:%M %p"),
                    "consultation_fee": f"₹{doctor.consultation_fee}",
                    "payment_method": "Pay at Clinic",
                    "payment_status": "pending",
                    "reason": request.reason,
                    "symptoms": request.symptoms,
                    "notes": [
                        "Please arrive 15 minutes before appointment",
                        "Carry your ID proof",
                        "Payment to be made at clinic reception",
                        "Cancellation allowed up to 2 hours before appointment"
                    ]
                }
            })
        
        return AppointmentResponse(**response_data)
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"Booking error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Booking failed. Please try again. Error: {str(e)}"
        )

@router.get("/user/{user_id}", response_model=dict)
async def get_user_appointments(
    user_id: int,
    status: Optional[str] = Query(None, description="confirmed/completed/cancelled"),
    upcoming_only: bool = Query(False, description="Show only upcoming appointments"),
    db: Session = Depends(get_db)
):
    """
    Get all appointments for a user
    
    ✅ FIX APPLIED: Added joinedload to prevent N+1 queries
    
    Used for "My Appointments" section
    """
    
    # Verify user exists
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # ✅ FIX 10: JOINEDLOAD TO PREVENT N+1 WHEN ACCESSING apt.doctor.name
    # WHY: Without this, accessing apt.doctor.name causes separate query for each appointment
    # BEFORE: 1 appointment query + 50 doctor queries = 51 queries
    # AFTER: Just 1 query with JOIN
    query = db.query(Appointment).options(
        joinedload(Appointment.doctor).joinedload(Doctor.clinic)  # ✅ FIXED
    ).filter(Appointment.user_id == user_id)
    
    # Filter by status if provided
    if status:
        query = query.filter(Appointment.status == status)
    
    # Filter upcoming only
    if upcoming_only:
        today = datetime.now().date()
        query = query.filter(Appointment.date >= today)
    
    # Get appointments
    appointments = query.order_by(Appointment.date.desc(), Appointment.time.desc()).all()
    
    # Format response
    results = []
    for apt in appointments:
        results.append({
            "id": apt.id,
            "doctor_name": apt.doctor.name,  # No extra query - already loaded
            "doctor_specialty": apt.doctor.specialties[0] if apt.doctor.specialties else "General",
            "clinic_name": apt.doctor.clinic.name,  # No extra query - already loaded
            "clinic_address": apt.doctor.clinic.address,
            "date": str(apt.date),
            "time": apt.time.strftime("%I:%M %p"),
            "status": apt.status,
            "reason": apt.reason,
            "consultation_fee": apt.doctor.consultation_fee,
            "can_cancel": (
                apt.status == "confirmed" and
                datetime.combine(apt.date, apt.time) - datetime.now() >= timedelta(hours=2)
            ),
            "created_at": apt.created_at.strftime("%Y-%m-%d %H:%M:%S")
        })
    
    return {
        "user_id": user_id,
        "total": len(results),
        "appointments": results
    }



@router.get("/{appointment_id}", response_model=dict)
async def get_appointment_details(
    appointment_id: str,
    db: Session = Depends(get_db)
):
    """
    Get detailed information about a specific appointment
    
    ✅ FIX APPLIED: Added joinedload to fetch all related data at once
    """
    
    # ✅ FIX 11: JOINEDLOAD FOR NESTED RELATIONSHIPS
    # WHY: Prevents multiple queries when accessing appointment.doctor.clinic.name
    appointment = db.query(Appointment).options(
        joinedload(Appointment.user),
        joinedload(Appointment.doctor).joinedload(Doctor.clinic)
    ).filter(Appointment.id == appointment_id).first()  # ✅ FIXED
    
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
    
    return {
        "id": appointment.id,
        "patient": {
            "name": appointment.user.name,
            "phone": appointment.user.phone,
            "age": appointment.user.age,
            "gender": appointment.user.gender
        },
        "doctor": {
            "name": appointment.doctor.name,
            "specialty": appointment.doctor.specialties[0] if appointment.doctor.specialties else "General",
            "experience_years": appointment.doctor.experience_years,
            "rating": float(appointment.doctor.rating)
        },
        "clinic": {
            "name": appointment.doctor.clinic.name,
            "address": appointment.doctor.clinic.address,
            "phone": appointment.doctor.clinic.phone
        },
        "appointment": {
            "date": str(appointment.date),
            "time": appointment.time.strftime("%I:%M %p"),
            "status": appointment.status,
            "reason": appointment.reason,
            "symptoms": appointment.symptoms,
            "consultation_type": appointment.consultation_type,
            "consultation_fee": appointment.doctor.consultation_fee
        },
        "can_cancel": (
            appointment.status == "confirmed" and
            datetime.combine(appointment.date, appointment.time) - datetime.now() >= timedelta(hours=2)
        ),
        "created_at": appointment.created_at.strftime("%Y-%m-%d %H:%M:%S")
    }



@router.post("/cancel", response_model=dict)
async def cancel_appointment(
    request: CancellationRequest,
    db: Session = Depends(get_db)
):
    """
    Cancel an appointment
    
    Rules:
    - Can only cancel if appointment is >=2 hours away
    - Frees up the slot for others
    - Sends notification to user and doctor
    """
    
    # Get appointment
    appointment = db.query(Appointment).filter(Appointment.id == request.appointment_id).first()
    
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
    
    # Verify user owns this appointment
    if appointment.user_id != request.user_id:
        raise HTTPException(status_code=403, detail="Not authorized to cancel this appointment")
    
    # Check if already cancelled
    if appointment.status == "cancelled":
        raise HTTPException(status_code=400, detail="Appointment is already cancelled")
    
    # Check if appointment is in the past
    if appointment.date < datetime.now().date():
        raise HTTPException(status_code=400, detail="Cannot cancel past appointments")
    
    # Check 2-hour cancellation policy
    appointment_datetime = datetime.combine(appointment.date, appointment.time)
    time_until_appointment = appointment_datetime - datetime.now()
    
    if time_until_appointment < timedelta(hours=2):
        raise HTTPException(
            status_code=400,
            detail="Cannot cancel within 2 hours of appointment. Please contact clinic directly."
        )
    
    try:
        # Update appointment status
        appointment.status = "cancelled"
        appointment.cancellation_reason = request.reason
        appointment.cancelled_at = datetime.now()
        
        # Free up the slot
        slot = db.query(DoctorSlot).filter(DoctorSlot.id == appointment.slot_id).first()
        if slot:
            slot.is_booked = False
        
        # Update doctor's next available slot
        next_slot = db.query(DoctorSlot).filter(
            and_(
                DoctorSlot.doctor_id == appointment.doctor_id,
                DoctorSlot.date >= datetime.now().date(),
                DoctorSlot.is_booked == False
            )
        ).order_by(DoctorSlot.date, DoctorSlot.start_time).first()
        
        if next_slot:
            appointment.doctor.next_available_slot = datetime.combine(next_slot.date, next_slot.start_time)
        
        # Commit changes
        db.commit()
        
        # Send notification
        send_notification(
            db=db,
            user_id=request.user_id,
            type="appointment_cancelled",
            title="Appointment Cancelled",
            message=f"Your appointment with Dr. {appointment.doctor.name} on {appointment.date} at {appointment.time.strftime('%I:%M %p')} has been cancelled."
        )
        
        # Log action
        log_action(
            db=db,
            user_id=request.user_id,
            action="APPOINTMENT_CANCELLED",
            entity_type="appointment",
            entity_id=request.appointment_id,
            details={
                "reason": request.reason,
                "cancelled_at": datetime.now().isoformat()
            }
        )
        
        return {
            "status": "success",
            "message": "Appointment cancelled successfully",
            "appointment_id": request.appointment_id,
            "refund_eligible": False,  # Since we're doing "pay at clinic"
            "notes": "The time slot is now available for other patients."
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Cancellation failed: {str(e)}")


@router.post("/{appointment_id}/reschedule", response_model=dict)
async def reschedule_appointment(
    appointment_id: str,
    new_slot_id: int,
    new_date: date,
    user_id: int,
    db: Session = Depends(get_db)
):
    """
    Reschedule an existing appointment to a new slot
    
    This is essentially cancel + re-book in one operation
    """
    
    # Get appointment
    appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
    
    # Verify user owns this appointment
    if appointment.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Check if new slot is available
    new_slot = db.query(DoctorSlot).filter(DoctorSlot.id == new_slot_id).first()
    
    if not new_slot:
        raise HTTPException(status_code=404, detail="New slot not found")
    
    if new_slot.is_booked:
        raise HTTPException(status_code=400, detail="New slot is already booked")
    
    # Check if new slot is for same doctor
    if new_slot.doctor_id != appointment.doctor_id:
        raise HTTPException(status_code=400, detail="Cannot reschedule to a different doctor")
    
    try:
        # Free up old slot
        old_slot = db.query(DoctorSlot).filter(DoctorSlot.id == appointment.slot_id).first()
        if old_slot:
            old_slot.is_booked = False
        
        # Book new slot
        new_slot.is_booked = True
        
        # Update appointment
        appointment.slot_id = new_slot_id
        appointment.date = new_date
        appointment.time = new_slot.start_time
        appointment.updated_at = datetime.now()
        
        # Commit changes
        db.commit()
        
        # Send notification
        send_notification(
            db=db,
            user_id=user_id,
            type="appointment_rescheduled",
            title="Appointment Rescheduled",
            message=f"Your appointment has been rescheduled to {new_date} at {new_slot.start_time.strftime('%I:%M %p')}"
        )
        
        # Log action
        log_action(
            db=db,
            user_id=user_id,
            action="APPOINTMENT_RESCHEDULED",
            entity_type="appointment",
            entity_id=appointment_id,
            details={
                "old_date": str(appointment.date),
                "new_date": str(new_date),
                "new_time": str(new_slot.start_time)
            }
        )
        
        return {
            "status": "success",
            "message": "Appointment rescheduled successfully",
            "appointment_id": appointment_id,
            "new_date": str(new_date),
            "new_time": new_slot.start_time.strftime("%I:%M %p")
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Rescheduling failed: {str(e)}")


@router.get("/stats/user/{user_id}", response_model=dict)
async def get_user_appointment_stats(
    user_id: int,
    db: Session = Depends(get_db)
):
    """
    Get statistics about user's appointments
    
    Useful for dashboard/profile page
    """
    
    total = db.query(Appointment).filter(Appointment.user_id == user_id).count()
    
    upcoming = db.query(Appointment).filter(
        and_(
            Appointment.user_id == user_id,
            Appointment.date >= datetime.now().date(),
            Appointment.status == "confirmed"
        )
    ).count()
    
    completed = db.query(Appointment).filter(
        and_(
            Appointment.user_id == user_id,
            Appointment.status == "completed"
        )
    ).count()
    
    cancelled = db.query(Appointment).filter(
        and_(
            Appointment.user_id == user_id,
            Appointment.status == "cancelled"
        )
    ).count()
    
    return {
        "user_id": user_id,
        "total_appointments": total,
        "upcoming": upcoming,
        "completed": completed,
        "cancelled": cancelled
    }