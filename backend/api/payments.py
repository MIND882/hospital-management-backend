import sys
from pathlib import Path

# Add backend directory to path for imports to work when running directly
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_
import razorpay
import hashlib
import hmac
import json
import os
import qrcode
import base64
from io import BytesIO
from datetime import datetime, timedelta
from typing import Optional, Literal, List
from database.connection import get_db
from database.models import (
    User, Order, Appointment, LabBooking, AuditLog,
    AppointmentPayment, DoctorWallet, WalletTransaction, 
    QRCode, PaymentStatus, Doctor, Notification
)
from .auth import get_current_user
from pydantic import BaseModel, Field
from enum import Enum

router = APIRouter(prefix="/api/payments", tags=["Payments"])

# ==================== CONFIG ====================

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "rzp_test_xxx")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "xxx")
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "whsec_xxx")

razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# Platform fees
PLATFORM_FEE_PERCENTAGE = 0.20  # 20% platform fee
DOCTOR_SHARE_PERCENTAGE = 0.80  # 80% doctor share

# ==================== ENUMS ====================

class PaymentMethod(str, Enum):
    CARD = "card"
    UPI = "upi"
    NETBANKING = "netbanking"
    WALLET = "wallet"
    EMI = "emi"

class OrderType(str, Enum):
    APPOINTMENT = "appointment"
    MEDICINE = "medicine"
    LAB_TEST = "lab_test"

# ==================== PYDANTIC MODELS ====================

class CreatePaymentOrderRequest(BaseModel):
    order_id: str = Field(..., description="APT123456 or ORD123456 or LAB123456")
    order_type: OrderType
    payment_method: Optional[PaymentMethod] = None

class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    order_id: str
    order_type: OrderType

class RefundRequest(BaseModel):
    order_id: str
    order_type: OrderType
    reason: str = Field(..., min_length=5, max_length=200)
    refund_amount: Optional[int] = None  # Partial refund (in rupees)

class PaymentResponse(BaseModel):
    status: str
    razorpay_order_id: str
    razorpay_key_id: str
    amount: int
    currency: str
    order_details: dict
    user_details: dict
    razorpay_config: dict

# ==================== HELPER FUNCTIONS ====================

def verify_razorpay_signature(order_id: str, payment_id: str, signature: str) -> bool:
    """
    ✅ Verify Razorpay payment signature
    Critical for security - prevents payment fraud
    """
    body = f"{order_id}|{payment_id}"
    secret = RAZORPAY_KEY_SECRET.encode()
    
    expected_signature = hmac.new(
        secret,
        body.encode(),
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(expected_signature, signature)


def generate_qr_code(appointment_id: str, doctor_id: int, patient_id: int) -> str:
    """
    📱 Generate QR code for appointment verification at clinic
    """
    qr_data = {
        "appointment_id": appointment_id,
        "doctor_id": doctor_id,
        "patient_id": patient_id,
        "timestamp": datetime.now().isoformat(),
        "version": "1.0"
    }
    
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,  # High error correction
        box_size=10,
        border=4,
    )
    qr.add_data(json.dumps(qr_data))
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="#3B82F6", back_color="white")
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode()


def credit_doctor_wallet(
    db: Session, 
    doctor_id: int, 
    amount: int, 
    appointment_id: str,
    transaction_type: str = "appointment_payment"
):
    """
    💰 Credit amount to doctor's wallet
    
    Transaction types:
    - appointment_payment: Payment from patient
    - bonus: Platform bonus
    - refund_reversal: When patient refund is clawed back
    """
    # Get or create wallet
    wallet = db.query(DoctorWallet).filter(
        DoctorWallet.doctor_id == doctor_id
    ).with_for_update().first()  # Lock row to prevent race condition
    
    if not wallet:
        wallet = DoctorWallet(
            doctor_id=doctor_id,
            current_balance=0,
            total_earned=0,
            total_withdrawn=0
        )
        db.add(wallet)
        db.flush()
    
    # Create transaction record
    transaction = WalletTransaction(
        wallet_id=wallet.id,
        appointment_id=appointment_id,
        amount=amount,
        transaction_type="credit",
        description=f"Payment for appointment {appointment_id}",
        balance_before=wallet.current_balance,
        balance_after=wallet.current_balance + amount,
        metadata={"transaction_type": transaction_type}
    )
    db.add(transaction)
    
    # Update wallet
    wallet.current_balance += amount
    wallet.total_earned += amount
    wallet.last_updated = datetime.now()
    
    db.commit()
    return wallet


def debit_doctor_wallet(
    db: Session,
    doctor_id: int,
    amount: int,
    appointment_id: str,
    reason: str = "refund"
):
    """
    📉 Debit amount from doctor's wallet (for refunds)
    """
    wallet = db.query(DoctorWallet).filter(
        DoctorWallet.doctor_id == doctor_id
    ).with_for_update().first()
    
    if not wallet:
        raise HTTPException(status_code=404, detail="Doctor wallet not found")
    
    if wallet.current_balance < amount:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient wallet balance. Available: ₹{wallet.current_balance}"
        )
    
    transaction = WalletTransaction(
        wallet_id=wallet.id,
        appointment_id=appointment_id,
        amount=amount,
        transaction_type="debit",
        description=f"Refund for appointment {appointment_id} - {reason}",
        balance_before=wallet.current_balance,
        balance_after=wallet.current_balance - amount
    )
    db.add(transaction)
    
    wallet.current_balance -= amount
    wallet.last_updated = datetime.now()
    
    db.commit()
    return wallet


def send_payment_notification(
    db: Session, 
    user_id: int, 
    title: str, 
    message: str,
    notification_type: str = "payment"
):
    """
    🔔 Send payment notification to user
    """
    notification = Notification(
        user_id=user_id,
        type=notification_type,
        title=title,
        message=message
    )
    db.add(notification)
    db.commit()


def get_order_details(
    db: Session, 
    order_id: str, 
    order_type: OrderType, 
    user_id: int
) -> dict:
    """
    📦 Get order details with validation
    
    Returns: {
        "order": object,
        "amount": int,
        "description": str,
        "metadata": dict
    }
    """
    if order_type == OrderType.APPOINTMENT:
        order = db.query(Appointment).options(
            joinedload(Appointment.doctor).joinedload(Doctor.clinic)
        ).filter(
            Appointment.id == order_id,
            Appointment.user_id == user_id
        ).first()
        
        if not order:
            raise HTTPException(status_code=404, detail="Appointment not found")
        
        # Check if already paid
        payment = db.query(AppointmentPayment).filter(
            AppointmentPayment.appointment_id == order_id
        ).first()
        
        if payment and payment.payment_status == PaymentStatus.PAID:
            raise HTTPException(status_code=400, detail="Payment already completed")
        
        return {
            "order": order,
            "amount": order.doctor.consultation_fee,
            "description": f"Appointment with Dr. {order.doctor.name}",
            "metadata": {
                "appointment_id": order.id,
                "doctor_id": order.doctor_id,
                "doctor_name": order.doctor.name,
                "clinic_name": order.doctor.clinic.name,
                "date": str(order.date),
                "time": order.time.strftime("%I:%M %p")
            }
        }
    
    elif order_type == OrderType.MEDICINE:
        order = db.query(Order).filter(
            Order.id == order_id,
            Order.user_id == user_id
        ).first()
        
        if not order:
            raise HTTPException(status_code=404, detail="Medicine order not found")
        
        if order.payment_status == "paid":
            raise HTTPException(status_code=400, detail="Payment already completed")
        
        return {
            "order": order,
            "amount": order.total_amount,
            "description": f"Medicine Order #{order_id[-6:]}",
            "metadata": {
                "order_id": order.id,
                "items_count": len(order.items) if order.items else 0,
                "delivery_type": order.delivery_type
            }
        }
    
    else:  # LAB_TEST
        order = db.query(LabBooking).options(
            joinedload(LabBooking.test)
        ).filter(
            LabBooking.id == order_id,
            LabBooking.user_id == user_id
        ).first()
        
        if not order:
            raise HTTPException(status_code=404, detail="Lab booking not found")
        
        return {
            "order": order,
            "amount": order.test.price,
            "description": f"Lab Test: {order.test.name}",
            "metadata": {
                "booking_id": order.id,
                "test_name": order.test.name,
                "collection_date": str(order.collection_date),
                "collection_type": order.collection_type
            }
        }


# ==================== MAIN ENDPOINTS ====================

@router.post("/create-order", response_model=dict)
async def create_payment_order(
    request: CreatePaymentOrderRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    💳 CREATE RAZORPAY PAYMENT ORDER
    
    ✅ Production-ready with:
    - Order validation
    - Amount verification
    - Payment record creation
    - Audit logging
    - Error handling
    """
    
    # Get and validate order
    order_info = get_order_details(
        db, 
        request.order_id, 
        request.order_type, 
        current_user.id
    )
    
    amount = order_info["amount"]
    
    # Create Razorpay order
    try:
        razorpay_order = razorpay_client.order.create({
            "amount": amount * 100,  # Convert to paisa
            "currency": "INR",
            "receipt": request.order_id,
            "notes": {
                "order_id": request.order_id,
                "order_type": request.order_type.value,
                "user_id": current_user.id,
                "user_name": current_user.name,
                "user_phone": current_user.phone
            },
            "partial_payment": False,
            "payment_capture": 1  # Auto-capture payment
        })
        
    except razorpay.errors.BadRequestError as e:
        raise HTTPException(
            status_code=400, 
            detail=f"Payment gateway error: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create payment order: {str(e)}"
        )
    
    # Create/update payment record for appointments
    if request.order_type == OrderType.APPOINTMENT:
        payment = db.query(AppointmentPayment).filter(
            AppointmentPayment.appointment_id == request.order_id
        ).first()
        
        if payment:
            payment.razorpay_order_id = razorpay_order["id"]
            payment.payment_status = PaymentStatus.PENDING
        else:
            payment = AppointmentPayment(
                appointment_id=request.order_id,
                total_amount=amount,
                platform_fee=int(amount * PLATFORM_FEE_PERCENTAGE),
                doctor_share=int(amount * DOCTOR_SHARE_PERCENTAGE),
                razorpay_order_id=razorpay_order["id"],
                payment_status=PaymentStatus.PENDING,
                payment_gateway="razorpay",
                payment_method=request.payment_method.value if request.payment_method else None
            )
            db.add(payment)
        
        db.commit()
    
    # Log action
    audit = AuditLog(
        user_id=current_user.id,
        action="PAYMENT_ORDER_CREATED",
        entity_type="payment",
        entity_id=razorpay_order["id"],
        details={
            "order_id": request.order_id,
            "order_type": request.order_type.value,
            "amount": amount,
            "razorpay_order_id": razorpay_order["id"]
        }
    )
    db.add(audit)
    db.commit()
    
    # Return response for frontend
    return {
        "status": "created",
        "razorpay_order_id": razorpay_order["id"],
        "razorpay_key_id": RAZORPAY_KEY_ID,
        "amount": razorpay_order["amount"],  # In paisa
        "currency": razorpay_order["currency"],
        "order_details": {
            "id": request.order_id,
            "type": request.order_type.value,
            "description": order_info["description"],
            **order_info["metadata"]
        },
        "user_details": {
            "name": current_user.name,
            "email": current_user.email,
            "phone": current_user.phone
        },
        "razorpay_config": {
            "key": RAZORPAY_KEY_ID,
            "amount": razorpay_order["amount"],
            "currency": "INR",
            "name": "MediCare Healthcare",
            "description": order_info["description"],
            "order_id": razorpay_order["id"],
            "prefill": {
                "name": current_user.name,
                "email": current_user.email or "",
                "contact": current_user.phone
            },
            "notes": {
                "order_id": request.order_id,
                "order_type": request.order_type.value
            },
            "theme": {
                "color": "#3B82F6"
            }
        }
    }


@router.post("/verify", response_model=dict)
async def verify_payment(
    request: VerifyPaymentRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    ✅ VERIFY PAYMENT & UPDATE ORDER STATUS
    
    Critical endpoint - handles:
    - Signature verification
    - Order status update
    - Doctor wallet credit
    - QR code generation
    - Notifications
    """
    
    # Step 1: Verify Razorpay signature
    is_valid = verify_razorpay_signature(
        request.razorpay_order_id,
        request.razorpay_payment_id,
        request.razorpay_signature
    )
    
    if not is_valid:
        # Log failed verification
        audit = AuditLog(
            user_id=current_user.id,
            action="PAYMENT_VERIFICATION_FAILED",
            entity_type="payment",
            entity_id=request.razorpay_payment_id,
            details={
                "reason": "Invalid signature",
                "order_id": request.order_id
            }
        )
        db.add(audit)
        db.commit()
        
        raise HTTPException(
            status_code=400,
            detail="Payment verification failed. Invalid signature."
        )
    
    # Step 2: Process based on order type
    response_data = {}
    
    try:
        if request.order_type == OrderType.APPOINTMENT:
            # Get appointment with payment
            appointment = db.query(Appointment).options(
                joinedload(Appointment.doctor)
            ).filter(
                Appointment.id == request.order_id,
                Appointment.user_id == current_user.id
            ).first()
            
            if not appointment:
                raise HTTPException(status_code=404, detail="Appointment not found")
            
            payment = db.query(AppointmentPayment).filter(
                AppointmentPayment.appointment_id == request.order_id
            ).first()
            
            if not payment:
                raise HTTPException(status_code=404, detail="Payment record not found")
            
            # Update payment status
            payment.payment_status = PaymentStatus.PAID
            payment.razorpay_payment_id = request.razorpay_payment_id
            payment.razorpay_signature = request.razorpay_signature
            payment.paid_at = datetime.now()
            
            # Update appointment
            appointment.status = "confirmed"
            
            # Generate QR code
            qr_data = generate_qr_code(
                appointment.id,
                appointment.doctor_id,
                current_user.id
            )
            
            qr_record = QRCode(
                appointment_id=appointment.id,
                qr_data=qr_data,
                verification_token=hashlib.sha256(
                    f"{appointment.id}{datetime.now().timestamp()}".encode()
                ).hexdigest()[:32],
                expires_at=datetime.combine(appointment.date, appointment.time) + timedelta(hours=2)
            )
            db.add(qr_record)
            
            db.commit()
            
            # Background tasks
            background_tasks.add_task(
                credit_doctor_wallet,
                db,
                appointment.doctor_id,
                payment.doctor_share,
                request.order_id
            )
            
            background_tasks.add_task(
                send_payment_notification,
                db,
                current_user.id,
                "Payment Successful",
                f"Payment of ₹{payment.total_amount} successful. Your appointment with Dr. {appointment.doctor.name} is confirmed.",
                "payment_success"
            )
            
            response_data = {
                "appointment_id": appointment.id,
                "doctor_name": appointment.doctor.name,
                "date": str(appointment.date),
                "time": appointment.time.strftime("%I:%M %p"),
                "qr_code": qr_data,
                "doctor_credited": payment.doctor_share,
                "next_steps": [
                    "Show QR code at clinic reception",
                    "Arrive 15 minutes before appointment",
                    "Bring any relevant medical reports"
                ]
            }
        
        elif request.order_type == OrderType.MEDICINE:
            order = db.query(Order).filter(
                Order.id == request.order_id,
                Order.user_id == current_user.id
            ).first()
            
            if not order:
                raise HTTPException(status_code=404, detail="Order not found")
            
            order.payment_status = "paid"
            order.order_status = "processing"
            order.payment_id = request.razorpay_payment_id
            
            db.commit()
            
            background_tasks.add_task(
                send_payment_notification,
                db,
                current_user.id,
                "Order Confirmed",
                f"Payment successful. Your order #{request.order_id[-6:]} is being processed.",
                "order_confirmed"
            )
            
            response_data = {
                "order_id": request.order_id,
                "status": "processing",
                "estimated_delivery": "Tomorrow by 6 PM" if order.delivery_type == "standard" else "Within 2 hours"
            }
        
        else:  # LAB_TEST
            lab_booking = db.query(LabBooking).options(
                joinedload(LabBooking.test)
            ).filter(
                LabBooking.id == request.order_id,
                LabBooking.user_id == current_user.id
            ).first()
            
            if not lab_booking:
                raise HTTPException(status_code=404, detail="Lab booking not found")
            
            lab_booking.status = "scheduled"
            lab_booking.payment_id = request.razorpay_payment_id
            
            db.commit()
            
            background_tasks.add_task(
                send_payment_notification,
                db,
                current_user.id,
                "Lab Test Scheduled",
                f"Payment successful. Your {lab_booking.test.name} is scheduled for {lab_booking.collection_date}.",
                "lab_test_scheduled"
            )
            
            response_data = {
                "booking_id": request.order_id,
                "test_name": lab_booking.test.name,
                "collection_date": str(lab_booking.collection_date),
                "collection_type": lab_booking.collection_type
            }
        
        # Log successful payment
        audit = AuditLog(
            user_id=current_user.id,
            action="PAYMENT_SUCCESS",
            entity_type="payment",
            entity_id=request.razorpay_payment_id,
            details={
                "order_id": request.order_id,
                "order_type": request.order_type.value,
                "razorpay_order_id": request.razorpay_order_id
            }
        )
        db.add(audit)
        db.commit()
        
        return {
            "status": "success",
            "message": "Payment verified successfully",
            "payment_id": request.razorpay_payment_id,
            "order_id": request.order_id,
            "order_type": request.order_type.value,
            "timestamp": datetime.now().strftime("%Y-%m-%d %I:%M %p"),
            **response_data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Payment verification failed: {str(e)}"
        )


@router.post("/webhook/razorpay", include_in_schema=False)
async def razorpay_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    🔔 RAZORPAY WEBHOOK HANDLER
    
    🚨 CRITICAL FOR PRODUCTION
    Handles async payment notifications from Razorpay
    """
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature")
    
    # Verify webhook signature
    expected_signature = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(expected_signature, signature):
        print("❌ Invalid webhook signature")
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    # Parse webhook data
    data = json.loads(body.decode())
    event = data.get("event")
    payload = data.get("payload", {}).get("payment", {}).get("entity", {})
    
    print(f"📨 Razorpay Webhook: {event} - Payment ID: {payload.get('id')}")
    
    if event == "payment.captured":
        order_id = payload.get("order_id")
        
        # Find payment by Razorpay order ID
        payment = db.query(AppointmentPayment).filter(
            AppointmentPayment.razorpay_order_id == order_id
        ).first()
        
        if payment and payment.payment_status != PaymentStatus.PAID:
            # Update payment
            payment.payment_status = PaymentStatus.PAID
            payment.razorpay_payment_id = payload.get("id")
            payment.paid_at = datetime.now()
            
            # Update appointment
            appointment = db.query(Appointment).filter(
                Appointment.id == payment.appointment_id
            ).first()
            
            if appointment:
                appointment.status = "confirmed"
                
                # Credit doctor wallet
                background_tasks.add_task(
                    credit_doctor_wallet,
                    db,
                    appointment.doctor_id,
                    payment.doctor_share,
                    appointment.id
                )
                
                # Generate QR code if not exists
                qr_exists = db.query(QRCode).filter(
                    QRCode.appointment_id == appointment.id
                ).first()
                
                if not qr_exists:
                    qr_data = generate_qr_code(
                        appointment.id,
                        appointment.doctor_id,
                        appointment.user_id
                    )
                    
                    qr_record = QRCode(
                        appointment_id=appointment.id,
                        qr_data=qr_data,
                        verification_token=hashlib.sha256(
                            f"{appointment.id}{datetime.now().timestamp()}".encode()
                        ).hexdigest()[:32]
                    )
                    db.add(qr_record)
            
            db.commit()
            print(f"✅ Payment processed successfully: {payment.razorpay_payment_id}")
    
    elif event == "payment.failed":
        order_id = payload.get("order_id")
        payment = db.query(AppointmentPayment).filter(
            AppointmentPayment.razorpay_order_id == order_id
        ).first()
        
        if payment:
            payment.payment_status = PaymentStatus.FAILED
            db.commit()
            print(f"❌ Payment failed: {order_id}")
    
    return {"status": "success"}


@router.post("/refund", response_model=dict)
async def initiate_refund(
    request: RefundRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    🔄 INITIATE REFUND
    
    Refund policies:
    - Appointments: Full refund if cancelled 24+ hours before
    - Medicines: No refund after dispatch
    - Lab Tests: Full refund if cancelled 6+ hours before collection
    """
    
    if request.order_type == OrderType.APPOINTMENT:
        appointment = db.query(Appointment).options(
            joinedload(Appointment.doctor)
        ).filter(
            Appointment.id == request.order_id,
            Appointment.user_id == current_user.id
        ).first()
        
        if not appointment:
            raise HTTPException(status_code=404, detail="Appointment not found")
        
        payment = db.query(AppointmentPayment).filter(
            AppointmentPayment.appointment_id == request.order_id
        ).first()
        
        if not payment or payment.payment_status != PaymentStatus.PAID:
            raise HTTPException(status_code=400, detail="No payment to refund")
        
        # Check cancellation policy (24 hours)
        appointment_time = datetime.combine(appointment.date, appointment.time)
        time_until = appointment_time - datetime.now()
        
        if time_until < timedelta(hours=24):
            raise HTTPException(
                status_code=400,
                detail="Cannot refund within 24 hours of appointment. Please contact support."
            )
        
        # Calculate refund amount
        refund_amount = request.refund_amount or payment.total_amount
        
        try:
            # Initiate Razorpay refund
            refund = razorpay_client.payment.refund(
                payment.razorpay_payment_id,
                {
                    "amount": refund_amount * 100,
                    "speed": "normal",  # or "optimum"
                    "notes": {
                        "reason": request.reason,
                        "appointment_id": request.order_id,
                        "user_id": current_user.id
                    }
                }
            )
            
            # Update payment
            payment.payment_status = PaymentStatus.REFUNDED
            payment.refund_id = refund["id"]
            payment.refunded_at = datetime.now()
            
            # Cancel appointment
            appointment.status = "cancelled"
            appointment.cancellation_reason = request.reason
            appointment.cancelled_at = datetime.now()
            
            db.commit()
            
            # Debit doctor wallet
            background_tasks.add_task(
                debit_doctor_wallet,
                db,
                appointment.doctor_id,
                payment.doctor_share,
                request.order_id,
                request.reason
            )
            
            # Send notification
            background_tasks.add_task(
                send_payment_notification,
                db,
                current_user.id,
                "Refund Initiated",
                f"Refund of ₹{refund_amount} initiated. Amount will be credited in 5-7 business days.",
                "refund_initiated"
            )
            
            return {
                "status": "success",
                "message": "Refund initiated successfully",
                "refund_id": refund["id"],
                "amount": refund_amount,
                "estimated_credit_days": "5-7 business days"
            }
            
        except razorpay.errors.BadRequestError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Refund failed: {str(e)}"
            )
    
    else:
        raise HTTPException(
            status_code=400,
            detail="Refunds not yet implemented for this order type"
        )


@router.get("/history", response_model=dict)
async def get_payment_history(
    current_user: User = Depends(get_current_user),
    order_type: Optional[OrderType] = None,
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """
    📜 GET PAYMENT HISTORY
    """
    
    payments = []
    
    # Get appointment payments
    if not order_type or order_type == OrderType.APPOINTMENT:
        apt_payments = db.query(AppointmentPayment).join(
            Appointment
        ).filter(
            Appointment.user_id == current_user.id
        ).order_by(
            AppointmentPayment.created_at.desc()
        ).offset(offset).limit(limit).all()
        
        for payment in apt_payments:
            appointment = db.query(Appointment).options(
                joinedload(Appointment.doctor)
            ).filter(Appointment.id == payment.appointment_id).first()
            
            payments.append({
                "payment_id": payment.razorpay_payment_id or f"pmt_{payment.id}",
                "order_id": payment.appointment_id,
                "order_type": "appointment",
                "amount": payment.total_amount,
                "status": payment.payment_status.value if isinstance(payment.payment_status, Enum) else payment.payment_status,
                "description": f"Dr. {appointment.doctor.name}" if appointment and appointment.doctor else "Appointment",
                "date": payment.created_at.strftime("%Y-%m-%d %I:%M %p"),
                "qr_available": db.query(QRCode).filter(
                    QRCode.appointment_id == payment.appointment_id
                ).first() is not None
            })
    
    return {
        "total": len(payments),
        "payments": payments
    }


@router.get("/status/{order_id}", response_model=dict)
async def get_payment_status(
    order_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    📊 GET PAYMENT STATUS
    """
    
    # Check appointment payment
    payment = db.query(AppointmentPayment).join(
        Appointment
    ).filter(
        AppointmentPayment.appointment_id == order_id,
        Appointment.user_id == current_user.id
    ).first()
    
    if payment:
        return {
            "order_id": order_id,
            "order_type": "appointment",
            "status": payment.payment_status.value if isinstance(payment.payment_status, Enum) else payment.payment_status,
            "amount": payment.total_amount,
            "payment_id": payment.razorpay_payment_id,
            "created_at": payment.created_at.strftime("%Y-%m-%d %I:%M %p") if payment.created_at else None,
            "paid_at": payment.paid_at.strftime("%Y-%m-%d %I:%M %p") if payment.paid_at else None
        }
    
    raise HTTPException(status_code=404, detail="Payment not found")


@router.get("/methods", response_model=dict)
async def get_payment_methods():
    """
    💳 GET AVAILABLE PAYMENT METHODS
    """
    return {
        "gateway": "razorpay",
        "methods": [
            {
                "id": "card",
                "name": "Credit/Debit Card",
                "icon": "💳",
                "supported_cards": ["Visa", "MasterCard", "RuPay", "American Express"]
            },
            {
                "id": "upi",
                "name": "UPI",
                "icon": "📱",
                "apps": ["Google Pay", "PhonePe", "Paytm", "BHIM"]
            },
            {
                "id": "netbanking",
                "name": "Net Banking",
                "icon": "🏦",
                "banks": ["SBI", "HDFC", "ICICI", "Axis", "Others"]
            },
            {
                "id": "wallet",
                "name": "Wallets",
                "icon": "👛",
                "wallets": ["Paytm", "PhonePe", "Amazon Pay", "Freecharge"]
            },
    
        ],
        "currency": "INR",
        "razorpay_key_id": RAZORPAY_KEY_ID
    }