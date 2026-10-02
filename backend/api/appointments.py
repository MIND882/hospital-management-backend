import base64
import hashlib
import hmac
import json
import logging
import math
import os
import sys
import uuid
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum as PyEnum
from io import BytesIO
from pathlib import Path
from typing import Any, List, Optional
from zoneinfo import ZoneInfo

# Add backend directory to path for imports to work when running directly
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field, validator
from sqlalchemy import Float, and_, case, cast, func, literal, or_
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from database.connection import get_db
from database.models import (
    Appointment,
    AppointmentPayment,
    AuditLog,
    Clinic,
    Doctor,
    DoctorSlot,
    DoctorWallet,
    Notification,
    PaymentStatus,
    QRCode,
    User,
    WalletTransaction,
)
from api.auth import get_current_user
from api.payments import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET
from tasks.notification_tasks import send_notification_task

try:
    import qrcode
except Exception:
    qrcode = None


router = APIRouter(prefix="/api/appointments", tags=["Appointments"])
logger = logging.getLogger(__name__)

# Slot date/time values are treated as local naive values in this configured
# timezone. For multiple clinic timezones, add a timezone column to Clinic.
BUSINESS_TIMEZONE = ZoneInfo(os.getenv("APP_TIMEZONE", "UTC"))

MIN_BOOKING_NOTICE = timedelta(hours=1)
CANCELLATION_NOTICE = timedelta(hours=2)
MAX_DAILY_APPOINTMENTS = 20


class PaymentMethod(str, PyEnum):
    ADVANCE = "advance"
    PAY_AT_CLINIC = "pay_at_clinic"


class DoctorSearchRequest(BaseModel):
    location: str = Field(..., min_length=1, max_length=120)
    user_lat: Optional[float] = Field(None, ge=-90, le=90)
    user_lng: Optional[float] = Field(None, ge=-180, le=180)
    specialty: str = Field(..., min_length=1, max_length=80)
    preferred_date: date
    preferred_time: Optional[str] = Field(None, max_length=20)
    budget_min: int = Field(0, ge=0)
    budget_max: int = Field(999999, ge=0)
    insurance_provider: Optional[str] = Field(None, max_length=100)
    sort_by: str = Field("distance", max_length=20)
    page: int = Field(1, ge=1)
    limit: int = Field(20, ge=1, le=50)


class DoctorResponse(BaseModel):
    id: int
    name: str
    specialty: str
    experience_years: int
    clinic_name: str
    clinic_address: str
    distance_km: Optional[float]
    rating: float
    total_reviews: int
    consultation_fee: int
    insurance_accepted: List[str]
    next_slot: Optional[str]
    available_today: bool


class SlotResponse(BaseModel):
    id: int
    time: str
    display: str


class AppointmentBookRequest(BaseModel):
    doctor_id: int = Field(..., gt=0)
    slot_id: int = Field(..., gt=0)
    date: date
    reason: Optional[str] = Field(None, max_length=1000)
    symptoms: List[str] = Field(default_factory=list)
    consultation_type: str = Field("in-person", max_length=30)
    is_emergency: bool = False
    payment_method: PaymentMethod = PaymentMethod.ADVANCE

    @validator("consultation_type")
    def validate_consultation_type(cls, value: str) -> str:
        value = value.strip().lower()
        allowed = {
            "in-person",
            "online",
            "video",
            "phone",
            "telemedicine",
        }
        if value not in allowed:
            raise ValueError("Unsupported consultation type")
        return value

    @validator("reason")
    def clean_reason(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @validator("symptoms")
    def validate_symptoms(cls, values: List[str]) -> List[str]:
        if len(values) > 20:
            raise ValueError("A maximum of 20 symptoms is allowed")

        cleaned = []
        for value in values:
            value = value.strip()
            if not value or len(value) > 120:
                raise ValueError("Each symptom must be between 1 and 120 characters")
            cleaned.append(value)
        return cleaned


class AppointmentResponse(BaseModel):
    appointment_id: str
    status: str
    details: dict
    payment_required: bool = False
    next_step: Optional[str] = None
    payment_details: Optional[dict] = None
    appointment_details: Optional[dict] = None


class CancellationRequest(BaseModel):
    appointment_id: str = Field(..., min_length=1, max_length=64)
    reason: Optional[str] = Field(None, max_length=500)

    @validator("reason")
    def clean_reason(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None


class PaymentServiceError(Exception):
    """Raised when Razorpay is unavailable or returns an invalid response."""


# ==================== TIME AND SLOT HELPERS ====================

def business_now() -> datetime:
    return datetime.now(BUSINESS_TIMEZONE)


def business_now_naive() -> datetime:
    # Database date/time columns in this application are treated as local-naive.
    return business_now().replace(tzinfo=None)


def appointment_datetime(slot_date: date, slot_time: time) -> datetime:
    local_time = slot_time.replace(tzinfo=None)
    return datetime.combine(slot_date, local_time).replace(tzinfo=BUSINESS_TIMEZONE)


def slot_after_cutoff(cutoff: datetime):
    return or_(
        DoctorSlot.date > cutoff.date(),
        and_(
            DoctorSlot.date == cutoff.date(),
            DoctorSlot.start_time >= cutoff.time(),
        ),
    )


def time_preference_filters(preference: Optional[str]) -> List[Any]:
    if not preference or preference.lower() == "any":
        return []

    preference = preference.lower()
    windows = {
        "morning": (time(6, 0), time(12, 0)),
        "afternoon": (time(12, 0), time(17, 0)),
        "evening": (time(17, 0), time(22, 0)),
    }

    if preference not in windows:
        raise HTTPException(
            status_code=422,
            detail="time_preference must be morning, afternoon, evening, or any",
        )

    start, end = windows[preference]
    return [
        DoctorSlot.start_time >= start,
        DoctorSlot.start_time < end,
    ]


def can_cancel_appointment(appointment: Appointment) -> bool:
    if appointment.status not in {"confirmed", "payment_pending"}:
        return False

    scheduled = appointment_datetime(appointment.date, appointment.time)
    return scheduled - business_now() >= CANCELLATION_NOTICE


def calculate_distance(
    lat1: Optional[float],
    lng1: Optional[float],
    lat2: Optional[float],
    lng2: Optional[float],
) -> Optional[float]:
    """Haversine distance in kilometers; returns None for missing/invalid coordinates."""
    values = (lat1, lng1, lat2, lng2)
    if any(value is None for value in values):
        return None

    try:
        lat1, lng1, lat2, lng2 = (float(value) for value in values)
    except (TypeError, ValueError):
        return None

    if not all(math.isfinite(value) for value in (lat1, lng1, lat2, lng2)):
        return None
    if not (-90 <= lat1 <= 90 and -90 <= lat2 <= 90):
        return None
    if not (-180 <= lng1 <= 180 and -180 <= lng2 <= 180):
        return None

    earth_radius_km = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlng / 2) ** 2
    )
    a = max(0.0, min(1.0, a))
    return round(2 * earth_radius_km * math.asin(math.sqrt(a)), 1)


# ==================== QR CODE HELPERS ====================

def qr_hmac_secret() -> bytes:
    secret = os.getenv("APPOINTMENT_QR_HMAC_SECRET", "")
    secret_bytes = secret.encode("utf-8")

    if len(secret_bytes) < 32:
        raise RuntimeError(
            "APPOINTMENT_QR_HMAC_SECRET must contain at least 32 bytes"
        )

    return secret_bytes


def generate_qr_code(
    appointment_id: str,
    doctor_id: int,
    patient_id: int,
) -> tuple[str, str]:
    """
    Return (base64 PNG, HMAC signature).

    The QR payload is signed. The clinic-side verifier must also check that the
    appointment exists, is confirmed, and belongs to the expected doctor.
    """
    unsigned_payload = {
        "version": 1,
        "appointment_id": appointment_id,
        "doctor_id": doctor_id,
        "patient_id": patient_id,
        "issued_at": datetime.now(timezone.utc).isoformat(),
    }

    canonical_payload = json.dumps(
        unsigned_payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    signature = hmac.new(
        qr_hmac_secret(),
        canonical_payload,
        hashlib.sha256,
    ).hexdigest()

    signed_payload = {
        **unsigned_payload,
        "signature": signature,
    }
    qr_payload = json.dumps(
        signed_payload,
        sort_keys=True,
        separators=(",", ":"),
    )

    # Keep bookings available if the optional QR package is not installed.
    if qrcode is None:
        return "", signature

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=8,
        border=4,
    )
    qr.add_data(qr_payload)
    qr.make(fit=True)

    image = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    return base64.b64encode(buffer.getvalue()).decode("ascii"), signature


def verify_qr_payload(qr_payload: str, stored_token: str) -> bool:
    """Utility for the clinic QR verifier."""
    try:
        payload = json.loads(qr_payload)
        signature = payload.pop("signature")
        canonical_payload = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        expected_signature = hmac.new(
            qr_hmac_secret(),
            canonical_payload,
            hashlib.sha256,
        ).hexdigest()

        return (
            hmac.compare_digest(signature, expected_signature)
            and hmac.compare_digest(signature, stored_token)
        )
    except (ValueError, TypeError, KeyError, RuntimeError):
        return False


# ==================== PAYMENT HELPERS ====================

def calculate_payment_breakdown(consultation_fee: int) -> dict:
    total_amount = int(consultation_fee)
    platform_fee = int(total_amount * 0.20)
    doctor_share = total_amount - platform_fee

    return {
        "total_amount": total_amount,
        "platform_fee": platform_fee,
        "doctor_share": doctor_share,
    }


def razorpay_client():
    if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
        raise PaymentServiceError("Payment provider is not configured")

    try:
        import razorpay
    except ImportError:
        raise PaymentServiceError("Payment provider is unavailable") from None

    return razorpay.Client(
        auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)
    )


def create_razorpay_order(
    booking_id: str,
    doctor_id: int,
    slot_id: int,
    appointment_date: date,
    appointment_time: time,
    amount_rupees: int,
) -> dict:
    client = razorpay_client()

    try:
        order = client.order.create(
            {
                "amount": int(amount_rupees) * 100,
                "currency": "INR",
                "receipt": booking_id,
                # Do not send patient name, phone, symptoms, or other PII to notes.
                "notes": {
                    "appointment_id": booking_id,
                    "doctor_id": str(doctor_id),
                    "slot_id": str(slot_id),
                    "date": appointment_date.isoformat(),
                    "time": appointment_time.strftime("%H:%M"),
                },
                "partial_payment": False,
            }
        )
    except Exception:
        logger.warning("Razorpay order creation failed")
        raise PaymentServiceError("Payment provider is unavailable") from None

    if not isinstance(order, dict) or not order.get("id"):
        raise PaymentServiceError("Payment provider returned an invalid order")

    return order


def payment_status_member(target: str):
    """
    Support common PaymentStatus enum naming conventions:
    PAID/SUCCESS/COMPLETED and REFUNDED/FAILED.
    """
    aliases = {
        "paid": ("PAID", "SUCCESS", "SUCCESSFUL", "SUCCEEDED", "COMPLETED", "CAPTURED"),
        "failed": ("FAILED", "FAILURE"),
        "refunded": ("REFUNDED", "REFUND"),
    }

    names = aliases.get(target, ())
    members = getattr(PaymentStatus, "__members__", {})

    for name in names:
        member = members.get(name)
        if member is not None:
            return member

        member = getattr(PaymentStatus, name, None)
        if member is not None:
            return member

    for member in members.values():
        member_name = str(getattr(member, "name", "")).upper()
        member_value = str(getattr(member, "value", "")).upper()
        if member_name in names or member_value in names:
            return member

    # Older schemas often have no REFUNDED enum value. FAILED is used as a
    # terminal state in that case; add REFUNDED to the model enum in production.
    if target == "refunded":
        return payment_status_member("failed")

    raise RuntimeError(f"PaymentStatus enum is missing a {target} value")


def payment_status_is(value: Any, target: str) -> bool:
    aliases = {
        "paid": {
            "paid",
            "success",
            "successful",
            "succeeded",
            "completed",
            "captured",
        },
        "failed": {"failed", "failure"},
        "refunded": {"refunded", "refund"},
    }.get(target, {target})

    candidates = (
        getattr(value, "name", None),
        getattr(value, "value", None),
        value,
    )

    for candidate in candidates:
        if candidate is None:
            continue
        text = str(candidate).lower()
        if text in aliases or text.split(".")[-1] in aliases:
            return True

    return False


def request_razorpay_refund(
    razorpay_payment_id: str,
    amount_paise: int,
    appointment_id: str,
) -> None:
    client = razorpay_client()

    try:
        result = client.payment.refund(
            razorpay_payment_id,
            {
                "amount": int(amount_paise),
                "notes": {
                    "reason": "appointment_slot_unavailable",
                    "appointment_id": appointment_id,
                },
            },
        )
    except Exception:
        logger.warning("Razorpay refund request failed")
        raise PaymentServiceError("Refund request failed") from None

    if isinstance(result, dict) and result.get("status") == "failed":
        raise PaymentServiceError("Refund request failed")


# ==================== DATABASE HELPERS ====================

def generate_booking_id() -> str:
    # UUID avoids the small, enumerable APT123456 identifier space.
    return str(uuid.uuid4())


def update_doctor_next_available_slot(db: Session, doctor_id: int) -> None:
    """Update next_available_slot without committing the caller's transaction."""
    now = business_now_naive()

    next_slot = (
        db.query(DoctorSlot)
        .filter(
            DoctorSlot.doctor_id == doctor_id,
            DoctorSlot.is_booked.is_(False),
            or_(
                DoctorSlot.date > now.date(),
                and_(
                    DoctorSlot.date == now.date(),
                    DoctorSlot.start_time > now.time(),
                ),
            ),
        )
        .order_by(DoctorSlot.date, DoctorSlot.start_time)
        .first()
    )

    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if doctor:
        doctor.next_available_slot = (
            datetime.combine(next_slot.date, next_slot.start_time)
            if next_slot
            else None
        )


def add_notification(
    db: Session,
    user_id: int,
    notification_type: str,
    title: str,
    message: str,
) -> None:
    # No commit here. The caller owns the transaction.
    db.add(
        Notification(
            user_id=user_id,
            type=notification_type,
            title=title,
            message=message,
        )
    )


def log_action(
    db: Session,
    user_id: int,
    action: str,
    entity_type: str,
    entity_id: str,
    details: dict,
) -> None:
    # Do not put symptoms, phone numbers, or other unnecessary PII in audit logs.
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
        )
    )


def credit_doctor_wallet(
    db: Session,
    doctor_id: int,
    amount: int,
    appointment_id: str,
) -> None:
    """Credit the doctor once, in the caller's payment transaction."""
    doctor = (
        db.query(Doctor)
        .filter(Doctor.id == doctor_id)
        .with_for_update()
        .first()
    )
    if not doctor:
        raise RuntimeError("Doctor does not exist")

    wallet = (
        db.query(DoctorWallet)
        .filter(DoctorWallet.doctor_id == doctor_id)
        .with_for_update()
        .first()
    )

    if not wallet:
        wallet = DoctorWallet(
            doctor_id=doctor_id,
            current_balance=0,
            total_earned=0,
        )
        db.add(wallet)
        db.flush()

    existing_transaction = (
        db.query(WalletTransaction)
        .filter(
            WalletTransaction.appointment_id == appointment_id,
            WalletTransaction.transaction_type == "credit",
        )
        .first()
    )
    if existing_transaction:
        return

    amount = int(amount)
    before = int(wallet.current_balance or 0)

    transaction = WalletTransaction(
        wallet_id=wallet.id,
        appointment_id=appointment_id,
        amount=amount,
        transaction_type="credit",
        description=f"Payment for appointment {appointment_id}",
        balance_before=before,
        balance_after=before + amount,
    )

    wallet.current_balance = before + amount
    wallet.total_earned = int(wallet.total_earned or 0) + amount
    wallet.last_updated = business_now_naive()

    db.add(transaction)

    if doctor.user_id:
        add_notification(
            db=db,
            user_id=doctor.user_id,
            notification_type="payment_received",
            title="Payment received",
            message=f"₹{amount} credited for appointment {appointment_id}.",
        )


def send_booking_notifications(db: Session, appointment_id: str) -> None:
    """Dispatch notifications only after the appointment transaction commits."""
    try:
        appointment = (
            db.query(Appointment)
            .options(joinedload(Appointment.doctor))
            .filter(Appointment.id == appointment_id)
            .first()
        )
        if not appointment or not appointment.doctor:
            return

        doctor = appointment.doctor
        when = (
            f"{appointment.date} at "
            f"{appointment.time.strftime('%I:%M %p')}"
        )

        send_notification_task.delay(
            user_id=appointment.user_id,
            title="Appointment confirmed",
            message=f"Your appointment with Dr. {doctor.name} is confirmed for {when}.",
            notification_type="appointment_booked",
        )

        if doctor.user_id:
            # Avoid sending patient name or health details in this notification.
            send_notification_task.delay(
                user_id=doctor.user_id,
                title="New appointment",
                message=f"A new appointment is scheduled for {when}.",
                notification_type="new_appointment",
            )
    except Exception:
        logger.warning("Appointment notification dispatch failed")


# ==================== DOCTOR SEARCH AND SLOT ENDPOINTS ====================

@router.post("/search", response_model=dict)
async def search_doctors(
    request: DoctorSearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Authentication is required; apply an API gateway rate limit as well.
    del current_user

    location = request.location.strip()
    if not location:
        raise HTTPException(status_code=422, detail="Location is required")

    if request.budget_min > request.budget_max:
        raise HTTPException(
            status_code=422,
            detail="budget_min must be less than or equal to budget_max",
        )

    sort_by = request.sort_by.lower()
    if sort_by not in {"distance", "rating", "fee"}:
        raise HTTPException(
            status_code=422,
            detail="sort_by must be distance, rating, or fee",
        )

    if (request.user_lat is None) != (request.user_lng is None):
        raise HTTPException(
            status_code=422,
            detail="user_lat and user_lng must be supplied together",
        )

    use_gps = location.lower() == "use_gps"
    if use_gps and request.user_lat is None:
        raise HTTPException(
            status_code=422,
            detail="GPS coordinates are required when location is use_gps",
        )

    preference_filters = time_preference_filters(request.preferred_time)
    now = business_now_naive()
    cutoff = now + MIN_BOOKING_NOTICE

    filters = [
        Doctor.is_available.is_(True),
        Doctor.is_verified.is_(True),
        Doctor.consultation_fee >= request.budget_min,
        Doctor.consultation_fee <= request.budget_max,
    ]

    if request.specialty.strip().lower() != "any":
        filters.append(
            Doctor.specialties.contains([request.specialty.strip()])
        )

    if request.insurance_provider:
        filters.append(
            Clinic.insurance_accepted.contains(
                [request.insurance_provider.strip()]
            )
        )

    if not use_gps:
        # Escape SQL LIKE wildcards so user input cannot turn into an
        # unrestricted wildcard search.
        if len(location) < 2:
            raise HTTPException(
                status_code=422,
                detail="Location searches must contain at least 2 characters",
            )

        escaped_location = (
            location.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        filters.append(
            Clinic.address.ilike(
                f"%{escaped_location}%",
                escape="\\",
            )
        )

    base_query = (
        db.query(Doctor)
        .join(Doctor.clinic)
        .filter(*filters)
    )
    total = base_query.order_by(None).count()

    distance_expression = literal(None, type_=Float)

    if request.user_lat is not None and request.user_lng is not None:
        valid_coordinates = and_(
            Clinic.location_lat.isnot(None),
            Clinic.location_lng.isnot(None),
        )

        latitude_1 = math.radians(request.user_lat)
        longitude_1 = math.radians(request.user_lng)
        latitude_2 = func.radians(cast(Clinic.location_lat, Float))
        longitude_2 = func.radians(cast(Clinic.location_lng, Float))

        cosine_distance = (
            math.sin(latitude_1) * func.sin(latitude_2)
            + math.cos(latitude_1)
            * func.cos(latitude_2)
            * func.cos(longitude_2 - longitude_1)
        )

        clamped_cosine = case(
            (cosine_distance > 1.0, 1.0),
            (cosine_distance < -1.0, -1.0),
            else_=cosine_distance,
        )

        distance_expression = case(
            (
                valid_coordinates,
                6371.0 * func.acos(clamped_cosine),
            ),
            else_=None,
        )

    preferred_slot_query = (
        db.query(DoctorSlot.id)
        .filter(
            DoctorSlot.doctor_id == Doctor.id,
            DoctorSlot.date == request.preferred_date,
            DoctorSlot.is_booked.is_(False),
            slot_after_cutoff(cutoff),
            *preference_filters,
        )
        .correlate(Doctor)
    )
    has_preferred_slot = preferred_slot_query.exists()

    next_slot_query = (
        db.query(DoctorSlot)
        .filter(
            DoctorSlot.doctor_id == Doctor.id,
            DoctorSlot.is_booked.is_(False),
            slot_after_cutoff(cutoff),
        )
        .order_by(DoctorSlot.date, DoctorSlot.start_time)
        .correlate(Doctor)
    )

    next_slot_date = (
        next_slot_query
        .with_entities(DoctorSlot.date)
        .limit(1)
        .scalar_subquery()
    )
    next_slot_time = (
        next_slot_query
        .with_entities(DoctorSlot.start_time)
        .limit(1)
        .scalar_subquery()
    )

    page_query = (
        db.query(
            Doctor,
            has_preferred_slot.label("has_preferred_slot"),
            next_slot_date.label("next_slot_date"),
            next_slot_time.label("next_slot_time"),
            distance_expression.label("distance_km"),
        )
        .join(Doctor.clinic)
        .options(joinedload(Doctor.clinic))
        .filter(*filters)
    )

    if sort_by == "distance" and request.user_lat is not None:
        order_by = [
            case(
                (distance_expression.is_(None), 1),
                else_=0,
            ).asc(),
            distance_expression.asc(),
            Doctor.id.asc(),
        ]
    elif sort_by == "rating":
        order_by = [
            func.coalesce(cast(Doctor.rating, Float), 0.0).desc(),
            Doctor.id.asc(),
        ]
    elif sort_by == "fee":
        order_by = [
            Doctor.consultation_fee.asc(),
            Doctor.id.asc(),
        ]
    else:
        # "distance" without GPS coordinates has no meaningful distance;
        # use rating as a stable fallback.
        order_by = [
            func.coalesce(cast(Doctor.rating, Float), 0.0).desc(),
            Doctor.id.asc(),
        ]

    offset = (request.page - 1) * request.limit
    rows = (
        page_query
        .order_by(*order_by)
        .offset(offset)
        .limit(request.limit)
        .all()
    )

    results = []
    for doctor, has_slots, next_date, next_time, distance in rows:
        clinic = doctor.clinic
        specialties = doctor.specialties or []
        insurance = clinic.insurance_accepted or []

        results.append(
            {
                "id": doctor.id,
                "name": doctor.name,
                "specialty": (
                    specialties[0]
                    if isinstance(specialties, (list, tuple)) and specialties
                    else "General"
                ),
                "experience_years": doctor.experience_years or 0,
                "clinic_name": clinic.name,
                "clinic_address": clinic.address,
                "distance_km": (
                    round(float(distance), 1)
                    if distance is not None
                    else None
                ),
                "rating": float(doctor.rating or 0),
                # Do not substitute total_consultations for total_reviews.
                "total_reviews": int(
                    getattr(doctor, "total_reviews", 0) or 0
                ),
                "consultation_fee": int(doctor.consultation_fee or 0),
                "insurance_accepted": (
                    insurance if isinstance(insurance, list) else []
                ),
                "next_slot": (
                    next_time.strftime("%I:%M %p")
                    if next_time
                    else None
                ),
                "available_today": (
                    next_date == now.date()
                    if next_date
                    else False
                ),
                "has_slots_on_preferred_date": bool(has_slots),
            }
        )

    return {
        "total": total,
        "page": request.page,
        "limit": request.limit,
        "doctors": results,
    }


@router.get("/doctors/{doctor_id}/slots", response_model=dict)
async def get_doctor_slots(
    doctor_id: int,
    slot_date: date = Query(..., alias="date"),
    time_preference: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    del current_user

    doctor = (
        db.query(Doctor)
        .filter(
            Doctor.id == doctor_id,
            Doctor.is_available.is_(True),
        )
        .first()
    )
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    preference_filters = time_preference_filters(time_preference)
    cutoff = business_now_naive() + MIN_BOOKING_NOTICE

    if slot_date < cutoff.date():
        slots = []
    else:
        filters = [
            DoctorSlot.doctor_id == doctor_id,
            DoctorSlot.date == slot_date,
            DoctorSlot.is_booked.is_(False),
            DoctorSlot.is_blocked.is_(False), 
            *preference_filters,
        ]

        if slot_date == cutoff.date():
            filters.append(DoctorSlot.start_time >= cutoff.time())

        # A single doctor's daily slots should be bounded; do not return an
        # unbounded result if malformed data creates thousands of slots.
        slots = (
            db.query(DoctorSlot)
            .filter(*filters)
            .order_by(DoctorSlot.start_time)
            .limit(200)
            .all()
        )

    return {
        "doctor_id": doctor_id,
        "doctor_name": doctor.name,
        "date": slot_date.isoformat(),
        "total_slots": len(slots),
        "slots": [
            {
                "id": slot.id,
                "time": slot.start_time.strftime("%H:%M"),
                "display": slot.start_time.strftime("%I:%M %p"),
                "end_time": slot.end_time.strftime("%I:%M %p"),
            }
            for slot in slots
        ],
    }


# ==================== BOOKING ====================

@router.post("/book", response_model=AppointmentResponse)
async def book_appointment(
    request: AppointmentBookRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        # Locking the doctor row serializes daily-cap checks for that doctor.
        doctor = (
            db.query(Doctor)
            .filter(
                Doctor.id == request.doctor_id,
                Doctor.is_available.is_(True),
            )
            .with_for_update()
            .first()
        )
        if not doctor:
            raise HTTPException(
                status_code=404,
                detail="Doctor not found or not available",
            )

        # Lock the slot before checking or changing its state.
        slot = (
            db.query(DoctorSlot)
            .filter(DoctorSlot.id == request.slot_id)
            .with_for_update(nowait=True)
            .first()
        )
        if not slot:
            raise HTTPException(status_code=404, detail="Time slot not found")

        if slot.doctor_id != doctor.id:
            raise HTTPException(
                status_code=400,
                detail="Selected slot does not belong to this doctor",
            )

        if slot.date != request.date:
            raise HTTPException(
                status_code=400,
                detail="Selected date does not match the slot date",
            )

        if slot.is_booked:
            raise HTTPException(
                status_code=409,
                detail="This time slot is already booked",
            )
        
        if slot.is_blocked:
            raise HTTPException(status_code=409, detail="Slot is not available")
            
        scheduled = appointment_datetime(request.date, slot.start_time)
        if scheduled < business_now() + MIN_BOOKING_NOTICE:
            raise HTTPException(
                status_code=400,
                detail="Appointments must be booked at least one hour in advance",
            )

        consultation_fee = int(doctor.consultation_fee or 0)
        if consultation_fee <= 0:
            raise HTTPException(
                status_code=400,
                detail="Doctor consultation fee is not configured",
            )

        daily_count = (
            db.query(func.count(Appointment.id))
            .filter(
                Appointment.doctor_id == doctor.id,
                Appointment.date == request.date,
                Appointment.status == "confirmed",
            )
            .scalar()
            or 0
        )

        if daily_count >= MAX_DAILY_APPOINTMENTS:
            raise HTTPException(
                status_code=409,
                detail="Doctor has reached the daily appointment limit",
            )

        booking_id = generate_booking_id()
        breakdown = calculate_payment_breakdown(consultation_fee)

        razorpay_order = None
        if request.payment_method == PaymentMethod.ADVANCE:
            # Fail closed: never create a fake order ID.
            try:
                qr_hmac_secret()  # Validate QR signing configuration before payment.
                razorpay_order = create_razorpay_order(
                    booking_id=booking_id,
                    doctor_id=doctor.id,
                    slot_id=slot.id,
                    appointment_date=request.date,
                    appointment_time=slot.start_time,
                    amount_rupees=breakdown["total_amount"],
                )
            except (RuntimeError, PaymentServiceError):
                raise HTTPException(
                    status_code=503,
                    detail="Payment service is temporarily unavailable. No booking was made.",
                )

            appointment_status = "payment_pending"
        else:
            appointment_status = "confirmed"

        appointment = Appointment(
            id=booking_id,
            user_id=current_user.id,
            doctor_id=doctor.id,
            slot_id=slot.id,
            date=request.date,
            time=slot.start_time,
            reason=request.reason,
            symptoms=request.symptoms,
            status=appointment_status,
            is_emergency=request.is_emergency,
            consultation_type=request.consultation_type,
            consultation_fee=consultation_fee,
        )
        db.add(appointment)

        payment = AppointmentPayment(
            appointment_id=booking_id,
            total_amount=breakdown["total_amount"],
            platform_fee=breakdown["platform_fee"],
            doctor_share=breakdown["doctor_share"],
            razorpay_order_id=(
                razorpay_order["id"] if razorpay_order else None
            ),
            payment_status=PaymentStatus.PENDING,
        )
        db.add(payment)

        # Pay-at-clinic bookings are confirmed immediately.
        # Advance-payment bookings remain unbooked until payment.captured arrives.
        if request.payment_method == PaymentMethod.PAY_AT_CLINIC:
            slot.is_booked = True

        log_action(
            db=db,
            user_id=current_user.id,
            action="APPOINTMENT_BOOKED",
            entity_type="appointment",
            entity_id=booking_id,
            details={
                "doctor_id": doctor.id,
                "date": request.date.isoformat(),
                "time": slot.start_time.strftime("%H:%M"),
                "fee": consultation_fee,
                "payment_method": request.payment_method.value,
            },
        )

        update_doctor_next_available_slot(db, doctor.id)
        db.commit()
        db.refresh(appointment)

        if request.payment_method == PaymentMethod.PAY_AT_CLINIC:
            send_booking_notifications(db, booking_id)

        response_data = {
            "appointment_id": booking_id,
            "status": appointment.status,
            "details": {
                "doctor_id": doctor.id,
                "doctor_name": doctor.name,
                "slot_id": slot.id,
                "date": request.date.isoformat(),
                "time": slot.start_time.strftime("%I:%M %p"),
                "consultation_fee": consultation_fee,
            },
            "payment_required": (
                request.payment_method == PaymentMethod.ADVANCE
            ),
        }

        if request.payment_method == PaymentMethod.ADVANCE:
            response_data.update(
                {
                    "next_step": "complete_payment",
                    "payment_details": {
                        "order_id": razorpay_order["id"],
                        "amount": breakdown["total_amount"],
                        "currency": "INR",
                        "key_id": RAZORPAY_KEY_ID,
                        "breakdown": {
                            "total": breakdown["total_amount"],
                            "platform_fee": breakdown["platform_fee"],
                            "doctor_share": breakdown["doctor_share"],
                        },
                        "prefill": {
                            "name": current_user.full_name,
                            "email": current_user.email,
                            "contact": current_user.phone,
                        },
                        "notes": {"appointment_id": booking_id},
                    },
                }
            )
        else:
            clinic = doctor.clinic
            response_data["appointment_details"] = {
                "patient_name": current_user.full_name,
                "patient_phone": current_user.phone,
                "doctor_name": doctor.name,
                "doctor_specialty": (
                    doctor.specialties[0]
                    if isinstance(doctor.specialties, (list, tuple))
                    and doctor.specialties
                    else "General"
                ),
                "clinic_name": clinic.name if clinic else None,
                "clinic_address": clinic.address if clinic else None,
                "clinic_phone": clinic.phone if clinic else None,
                "date": request.date.isoformat(),
                "time": slot.start_time.strftime("%I:%M %p"),
                "end_time": slot.end_time.strftime("%I:%M %p"),
                "consultation_fee": consultation_fee,
                "payment_method": "Pay at Clinic",
                "payment_status": "pending",
            }

        return AppointmentResponse(**response_data)

    except HTTPException:
        db.rollback()
        raise
    except OperationalError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="The slot is being updated. Please try again.",
        ) from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Booking conflict. Please choose another slot.",
        ) from None
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("Booking database error (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=500,
            detail="Booking could not be completed.",
        ) from None
    except Exception as exc:
        db.rollback()
        logger.error("Booking failed (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=500,
            detail="Booking could not be completed.",
        ) from None


# ==================== USER APPOINTMENTS ====================

@router.get("/user/me", response_model=dict)
async def get_user_appointments(
    current_user: User = Depends(get_current_user),
    status: Optional[str] = Query(None, max_length=30),
    upcoming_only: bool = Query(False),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    allowed_statuses = {
        "payment_pending",
        "confirmed",
        "completed",
        "cancelled",
        "payment_failed",
    }
    if status and status not in allowed_statuses:
        raise HTTPException(status_code=422, detail="Invalid appointment status")

    query = (
        db.query(Appointment)
        .options(
            joinedload(Appointment.doctor).joinedload(Doctor.clinic)
        )
        .filter(Appointment.user_id == current_user.id)
    )

    if status:
        query = query.filter(Appointment.status == status)

    if upcoming_only:
        query = query.filter(Appointment.date >= business_now().date())

    total = query.order_by(None).count()

    appointments = (
        query.order_by(Appointment.date.asc(), Appointment.time.asc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    results = []
    for appointment in appointments:
        doctor = appointment.doctor
        clinic = doctor.clinic if doctor else None

        results.append(
            {
                "id": appointment.id,
                "doctor_name": doctor.name if doctor else None,
                "doctor_specialty": (
                    doctor.specialties[0]
                    if doctor
                    and isinstance(doctor.specialties, (list, tuple))
                    and doctor.specialties
                    else "General"
                ),
                "clinic_name": clinic.name if clinic else None,
                "clinic_address": clinic.address if clinic else None,
                "date": appointment.date.isoformat(),
                "time": appointment.time.strftime("%I:%M %p"),
                "status": appointment.status,
                "reason": appointment.reason,
                "consultation_fee": (
                    doctor.consultation_fee if doctor else None
                ),
                "can_cancel": can_cancel_appointment(appointment),
                "created_at": (
                    appointment.created_at.isoformat()
                    if appointment.created_at
                    else None
                ),
            }
        )

    return {
        "user_id": current_user.id,
        "total": total,
        "page": page,
        "limit": limit,
        "appointments": results,
    }


@router.get("/stats", response_model=dict)
async def get_user_appointment_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user.id
    today = business_now().date()

    total = (
        db.query(Appointment)
        .filter(Appointment.user_id == user_id)
        .count()
    )
    upcoming = (
        db.query(Appointment)
        .filter(
            Appointment.user_id == user_id,
            Appointment.date >= today,
            Appointment.status == "confirmed",
        )
        .count()
    )
    completed = (
        db.query(Appointment)
        .filter(
            Appointment.user_id == user_id,
            Appointment.status == "completed",
        )
        .count()
    )
    cancelled = (
        db.query(Appointment)
        .filter(
            Appointment.user_id == user_id,
            Appointment.status == "cancelled",
        )
        .count()
    )

    return {
        "user_id": user_id,
        "total_appointments": total,
        "upcoming": upcoming,
        "completed": completed,
        "cancelled": cancelled,
    }


# ==================== RAZORPAY WEBHOOK ====================

@router.post(
    "/payments/razorpay/webhook",
    response_model=dict,
    include_in_schema=False,
)
async def razorpay_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    if not webhook_secret:
        raise HTTPException(
            status_code=503,
            detail="Payment webhook is not configured",
        )

    raw_body = await request.body()
    supplied_signature = request.headers.get("X-Razorpay-Signature", "")

    expected_signature = hmac.new(
        webhook_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    if not supplied_signature or not hmac.compare_digest(
        supplied_signature,
        expected_signature,
    ):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    try:
        event_body = json.loads(raw_body)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid webhook body")

    # Only captured payments confirm appointments.
    if event_body.get("event") != "payment.captured":
        return {"status": "ignored"}

    payment_entity = (
        event_body.get("payload", {})
        .get("payment", {})
        .get("entity", {})
    )

    order_id = payment_entity.get("order_id")
    razorpay_payment_id = payment_entity.get("id")
    amount_paise = payment_entity.get("amount")
    currency = payment_entity.get("currency")

    if not order_id or not razorpay_payment_id or amount_paise is None:
        raise HTTPException(status_code=400, detail="Incomplete payment event")

    try:
        payment_ref = (
            db.query(AppointmentPayment)
            .filter(AppointmentPayment.razorpay_order_id == order_id)
            .first()
        )
        if not payment_ref:
            raise HTTPException(
                status_code=404,
                detail="Payment order not found",
            )

        appointment_ref = (
            db.query(Appointment)
            .filter(Appointment.id == payment_ref.appointment_id)
            .first()
        )
        if not appointment_ref:
            raise HTTPException(
                status_code=404,
                detail="Appointment not found",
            )

        # Use the same doctor -> appointment/payment -> slot lock order as the
        # booking and reschedule endpoints.
        doctor = (
            db.query(Doctor)
            .filter(Doctor.id == appointment_ref.doctor_id)
            .with_for_update()
            .first()
        )
        appointment = (
            db.query(Appointment)
            .filter(Appointment.id == appointment_ref.id)
            .with_for_update()
            .first()
        )
        payment = (
            db.query(AppointmentPayment)
            .filter(AppointmentPayment.razorpay_order_id == order_id)
            .with_for_update()
            .first()
        )

        if not doctor or not appointment or not payment:
            raise HTTPException(status_code=404, detail="Payment record not found")

        if payment_status_is(payment.payment_status, "paid"):
            db.rollback()
            return {"status": "already_processed"}

        if (
            payment_status_is(payment.payment_status, "failed")
            or payment_status_is(payment.payment_status, "refunded")
        ):
            db.rollback()
            return {"status": "already_processed"}

        expected_amount_paise = int(payment.total_amount) * 100
        if (
            currency != "INR"
            or int(amount_paise) != expected_amount_paise
        ):
            raise HTTPException(status_code=400, detail="Payment amount mismatch")

        slot = (
            db.query(DoctorSlot)
            .filter(DoctorSlot.id == appointment.slot_id)
            .with_for_update()
            .first()
        )

        appointment_time = appointment_datetime(
            appointment.date,
            appointment.time,
        )
        appointment_is_own_confirmed_slot = (
            appointment.status == "confirmed"
            and slot is not None
            and bool(slot.is_booked)
        )

        other_confirmed_today = (
            db.query(func.count(Appointment.id))
            .filter(
                Appointment.doctor_id == doctor.id,
                Appointment.date == appointment.date,
                Appointment.status == "confirmed",
                Appointment.id != appointment.id,
            )
            .scalar()
            or 0
        )

        slot_conflict = (
            slot is None
            or (
                bool(slot.is_booked)
                and not appointment_is_own_confirmed_slot
            )
        )
        appointment_invalid = (
            appointment.status not in {"payment_pending", "confirmed"}
            or appointment_time < business_now() + MIN_BOOKING_NOTICE
        )
        daily_limit_reached = (
            other_confirmed_today >= MAX_DAILY_APPOINTMENTS
        )

        if slot_conflict or appointment_invalid or daily_limit_reached:
            # Payment was captured but the appointment cannot be confirmed.
            # Request a full refund rather than crediting the doctor.
            request_razorpay_refund(
                razorpay_payment_id=str(razorpay_payment_id),
                amount_paise=int(amount_paise),
                appointment_id=appointment.id,
            )

            payment.payment_status = payment_status_member("refunded")
            appointment.status = "cancelled"
            appointment.cancelled_at = business_now_naive()
            appointment.cancellation_reason = (
                "Payment captured but appointment could not be confirmed"
            )

            add_notification(
                db=db,
                user_id=appointment.user_id,
                notification_type="payment_refund_requested",
                title="Appointment could not be confirmed",
                message="A refund has been requested for your payment.",
            )
            log_action(
                db=db,
                user_id=appointment.user_id,
                action="PAYMENT_REFUND_REQUESTED",
                entity_type="appointment",
                entity_id=appointment.id,
                details={"reason": "slot_or_booking_conflict"},
            )

            db.commit()
            return {"status": "refund_requested"}

        payment.payment_status = payment_status_member("paid")
        appointment.status = "confirmed"
        appointment.updated_at = business_now_naive()
        slot.is_booked = True

        # Create a signed QR only after payment has been captured.
        existing_qr = (
            db.query(QRCode)
            .filter(QRCode.appointment_id == appointment.id)
            .first()
        )
        if not existing_qr:
            qr_data, verification_token = generate_qr_code(
                appointment_id=appointment.id,
                doctor_id=doctor.id,
                patient_id=appointment.user_id,
            )
            db.add(
                QRCode(
                    appointment_id=appointment.id,
                    qr_data=qr_data,
                    verification_token=verification_token,
                )
            )

        credit_doctor_wallet(
            db=db,
            doctor_id=doctor.id,
            amount=int(payment.doctor_share),
            appointment_id=appointment.id,
        )

        update_doctor_next_available_slot(db, doctor.id)
        log_action(
            db=db,
            user_id=appointment.user_id,
            action="ADVANCE_PAYMENT_CAPTURED",
            entity_type="appointment",
            entity_id=appointment.id,
            details={
                "doctor_id": doctor.id,
                "amount": int(payment.total_amount),
            },
        )

        db.commit()
        send_booking_notifications(db, appointment.id)

        return {"status": "confirmed"}

    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error("Razorpay webhook processing failed (%s)", type(exc).__name__)
        # A non-2xx response lets Razorpay retry the webhook.
        raise HTTPException(
            status_code=500,
            detail="Payment event could not be processed",
        ) from None


# ==================== APPOINTMENT DETAILS ====================

@router.get("/{appointment_id}", response_model=dict)
async def get_appointment_details(
    appointment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    appointment = (
        db.query(Appointment)
        .options(
            joinedload(Appointment.user),
            joinedload(Appointment.doctor).joinedload(Doctor.clinic),
        )
        .filter(Appointment.id == appointment_id)
        .first()
    )

    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")

    doctor = appointment.doctor
    is_patient = appointment.user_id == current_user.id
    is_doctor_owner = bool(
        doctor and doctor.user_id == current_user.id
    )

    # Return 404 for non-participants to reduce appointment-ID enumeration.
    if not is_patient and not is_doctor_owner:
        raise HTTPException(status_code=404, detail="Appointment not found")

    patient = appointment.user
    clinic = doctor.clinic if doctor else None

    result = {
        "id": appointment.id,
        "patient": {
            "name": patient.full_name if patient else None,
            "phone": patient.phone if patient else None,
            "age": patient.age if patient else None,
            "gender": patient.gender if patient else None,
        },
        "doctor": {
            "name": doctor.name if doctor else None,
            "specialty": (
                doctor.specialties[0]
                if doctor
                and isinstance(doctor.specialties, (list, tuple))
                and doctor.specialties
                else "General"
            ),
            "experience_years": (
                doctor.experience_years if doctor else None
            ),
            "rating": float(doctor.rating or 0) if doctor else 0.0,
        },
        "clinic": {
            "name": clinic.name if clinic else None,
            "address": clinic.address if clinic else None,
            "phone": clinic.phone if clinic else None,
        },
        "appointment": {
            "date": appointment.date.isoformat(),
            "time": appointment.time.strftime("%I:%M %p"),
            "status": appointment.status,
            "reason": appointment.reason,
            "symptoms": appointment.symptoms,
            "consultation_type": appointment.consultation_type,
            "consultation_fee": (
                doctor.consultation_fee if doctor else None
            ),
        },
        "can_cancel": can_cancel_appointment(appointment),
        "created_at": (
            appointment.created_at.isoformat()
            if appointment.created_at
            else None
        ),
    }

    # Do not expose the patient's QR credential to another user.
    if is_patient:
        qr_record = (
            db.query(QRCode)
            .filter(QRCode.appointment_id == appointment.id)
            .first()
        )
        result["qr_code"] = qr_record.qr_data if qr_record else None

    return result


# ==================== CANCELLATION ====================

@router.post("/cancel", response_model=dict)
async def cancel_appointment(
    request: CancellationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        doctor_id = (
            db.query(Appointment.doctor_id)
            .filter(Appointment.id == request.appointment_id)
            .scalar()
        )
        if doctor_id is None:
            raise HTTPException(status_code=404, detail="Appointment not found")

        doctor = (
            db.query(Doctor)
            .filter(Doctor.id == doctor_id)
            .with_for_update()
            .first()
        )
        appointment = (
            db.query(Appointment)
            .filter(Appointment.id == request.appointment_id)
            .with_for_update()
            .first()
        )

        if not doctor or not appointment:
            raise HTTPException(status_code=404, detail="Appointment not found")

        if appointment.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Appointment not found")

        if appointment.status == "cancelled":
            raise HTTPException(
                status_code=400,
                detail="Appointment is already cancelled",
            )

        if appointment.status not in {"confirmed", "payment_pending"}:
            raise HTTPException(
                status_code=400,
                detail="This appointment cannot be cancelled",
            )

        scheduled = appointment_datetime(
            appointment.date,
            appointment.time,
        )
        if scheduled < business_now():
            raise HTTPException(
                status_code=400,
                detail="Cannot cancel a past appointment",
            )

        if scheduled - business_now() < CANCELLATION_NOTICE:
            raise HTTPException(
                status_code=400,
                detail="Cancellation is not allowed within two hours of the appointment",
            )

        was_confirmed = appointment.status == "confirmed"
        appointment.status = "cancelled"
        appointment.cancellation_reason = request.reason
        appointment.cancelled_at = business_now_naive()
        appointment.updated_at = business_now_naive()

        if was_confirmed:
            slot = (
                db.query(DoctorSlot)
                .filter(DoctorSlot.id == appointment.slot_id)
                .with_for_update()
                .first()
            )
            if slot:
                another_confirmed_booking = (
                    db.query(Appointment.id)
                    .filter(
                        Appointment.slot_id == slot.id,
                        Appointment.id != appointment.id,
                        Appointment.status == "confirmed",
                    )
                    .first()
                )
                if not another_confirmed_booking:
                    slot.is_booked = False

        update_doctor_next_available_slot(db, doctor.id)

        add_notification(
            db=db,
            user_id=current_user.id,
            notification_type="appointment_cancelled",
            title="Appointment cancelled",
            message="Your appointment has been cancelled.",
        )

        if doctor.user_id:
            add_notification(
                db=db,
                user_id=doctor.user_id,
                notification_type="appointment_cancelled",
                title="Appointment cancelled",
                message="An appointment has been cancelled.",
            )

        payment = (
            db.query(AppointmentPayment)
            .filter(AppointmentPayment.appointment_id == appointment.id)
            .first()
        )

        refund_status = "not_applicable"
        if payment and payment_status_is(payment.payment_status, "paid"):
            # Apply your actual refund policy here. This endpoint does not
            # silently claim that a refund was made.
            refund_status = "manual_review_required"
        elif payment and payment.payment_status == PaymentStatus.PENDING:
            # If a late captured-payment webhook arrives, it will request a refund.
            refund_status = "pending_payment"

        log_action(
            db=db,
            user_id=current_user.id,
            action="APPOINTMENT_CANCELLED",
            entity_type="appointment",
            entity_id=appointment.id,
            details={"reason_provided": bool(request.reason)},
        )

        db.commit()

        return {
            "status": "success",
            "message": "Appointment cancelled successfully",
            "appointment_id": appointment.id,
            "refund_status": refund_status,
        }

    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("Cancellation database error (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=500,
            detail="Cancellation could not be completed",
        ) from None
    except Exception as exc:
        db.rollback()
        logger.error("Cancellation failed (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=500,
            detail="Cancellation could not be completed",
        ) from None


# ==================== RESCHEDULING ====================

@router.post("/{appointment_id}/reschedule", response_model=dict)
async def reschedule_appointment(
    appointment_id: str,
    new_slot_id: int = Query(..., gt=0),
    new_date: date = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        doctor_id = (
            db.query(Appointment.doctor_id)
            .filter(Appointment.id == appointment_id)
            .scalar()
        )
        if doctor_id is None:
            raise HTTPException(status_code=404, detail="Appointment not found")

        doctor = (
            db.query(Doctor)
            .filter(Doctor.id == doctor_id)
            .with_for_update()
            .first()
        )
        appointment = (
            db.query(Appointment)
            .filter(Appointment.id == appointment_id)
            .with_for_update()
            .first()
        )

        if not doctor or not appointment:
            raise HTTPException(status_code=404, detail="Appointment not found")

        if appointment.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Appointment not found")

        if appointment.status not in {"confirmed", "reschedule_required"}:
            raise HTTPException(
                status_code=400,
                detail="Only confirmed appointments can be rescheduled",
            )

        old_datetime = appointment_datetime(
            appointment.date,
            appointment.time,
        )
        now = business_now()

        if old_datetime <= now:
            raise HTTPException(
                status_code=400,
                detail="Cannot reschedule a past appointment",
            )

        if old_datetime - now < CANCELLATION_NOTICE:
            raise HTTPException(
                status_code=400,
                detail="Rescheduling is not allowed within two hours of the appointment",
            )

        if new_slot_id == appointment.slot_id:
            raise HTTPException(
                status_code=400,
                detail="Choose a different slot to reschedule",
            )

        # Lock both slots in deterministic order to reduce deadlock risk.
        slot_ids = sorted({appointment.slot_id, new_slot_id})
        locked_slots = (
            db.query(DoctorSlot)
            .filter(DoctorSlot.id.in_(slot_ids))
            .order_by(DoctorSlot.id)
            .with_for_update()
            .all()
        )
        slots_by_id = {slot.id: slot for slot in locked_slots}

        old_slot = slots_by_id.get(appointment.slot_id)
        new_slot = slots_by_id.get(new_slot_id)

        if not old_slot or not new_slot:
            raise HTTPException(status_code=404, detail="Slot not found")

        if new_slot.doctor_id != appointment.doctor_id:
            raise HTTPException(
                status_code=400,
                detail="Cannot reschedule to a different doctor",
            )

        if new_slot.date != new_date:
            raise HTTPException(
                status_code=400,
                detail="new_date must match the selected slot date",
            )

        if new_slot.is_booked:
            raise HTTPException(
                status_code=409,
                detail="The selected slot is already booked",
            )

        new_datetime = appointment_datetime(new_date, new_slot.start_time)
        if new_datetime < now + MIN_BOOKING_NOTICE:
            raise HTTPException(
                status_code=400,
                detail="Appointments must be rescheduled at least one hour in advance",
            )

        daily_count = (
            db.query(func.count(Appointment.id))
            .filter(
                Appointment.doctor_id == doctor.id,
                Appointment.date == new_date,
                Appointment.status == "confirmed",
                Appointment.id != appointment.id,
            )
            .scalar()
            or 0
        )
        if daily_count >= MAX_DAILY_APPOINTMENTS:
            raise HTTPException(
                status_code=409,
                detail="Doctor has reached the daily appointment limit",
            )

        old_date = appointment.date
        old_time = appointment.time

        old_slot.is_booked = False
        new_slot.is_booked = True

        appointment.slot_id = new_slot.id
        appointment.date = new_date
        appointment.time = new_slot.start_time
        appointment.updated_at = business_now_naive()

        update_doctor_next_available_slot(db, doctor.id)

        add_notification(
            db=db,
            user_id=current_user.id,
            notification_type="appointment_rescheduled",
            title="Appointment rescheduled",
            message=(
                f"Your appointment is now scheduled for {new_date} "
                f"at {new_slot.start_time.strftime('%I:%M %p')}."
            ),
        )

        if doctor.user_id:
            add_notification(
                db=db,
                user_id=doctor.user_id,
                notification_type="appointment_rescheduled",
                title="Appointment rescheduled",
                message="An appointment has been rescheduled.",
            )

        log_action(
            db=db,
            user_id=current_user.id,
            action="APPOINTMENT_RESCHEDULED",
            entity_type="appointment",
            entity_id=appointment.id,
            details={
                "old_date": old_date.isoformat(),
                "old_time": old_time.strftime("%H:%M"),
                "new_date": new_date.isoformat(),
                "new_time": new_slot.start_time.strftime("%H:%M"),
            },
        )

        db.commit()

        return {
            "status": "success",
            "message": "Appointment rescheduled successfully",
            "appointment_id": appointment.id,
            "new_date": new_date.isoformat(),
            "new_time": new_slot.start_time.strftime("%I:%M %p"),
        }

    except HTTPException:
        db.rollback()
        raise
    except OperationalError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="The selected slot is being updated. Please try again.",
        ) from None
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("Rescheduling database error (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=500,
            detail="Rescheduling could not be completed",
        ) from None
    except Exception as exc:
        db.rollback()
        logger.error("Rescheduling failed (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=500,
            detail="Rescheduling could not be completed",
        ) from None
