"""
Medicare Platform - Database Models
Complete schema for all features with all missing columns added
"""
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text, Boolean, DECIMAL, Time, Date, Float
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
from .connection import Base
from sqlalchemy import Enum as SQLEnum
from sqlalchemy import func
import enum



# ============================================
# ENUMS
# ============================================

class UserRole(str, enum.Enum):
    PATIENT = "patient"
    DOCTOR = "doctor"
    PHARMACY = "pharmacy"
    LAB = "lab"
    ADMIN = "admin"


class AppointmentStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"


class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


# ============================================
# USER MANAGEMENT
# ============================================

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(100), unique=True, index=True, nullable=False)
    phone = Column(String(15), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    
    # Both naming conventions for compatibility
    name = Column(String(100))
    full_name = Column(String(100), nullable=False)
    
    role = Column(String(50), default="patient")  # customer | doctor | pharmacy | lab | admin
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    
    # Both naming conventions for profile picture
    profile_image = Column(String(255))
    profile_picture_url = Column(String(255), nullable=True)
    profile_photo_url = Column(String(255))
    
    date_of_birth = Column(Date)
    gender = Column(String(10))
    address = Column(Text)
    city = Column(String(50))
    state = Column(String(50))
    pincode = Column(String(10))
    
    # ✅ NEW: Additional user fields
    age = Column(Integer)
    blood_group = Column(String(5))
    deletion_requested_at = Column(DateTime)
    scheduled_deletion_date = Column(Date)
    location_lat = Column(DECIMAL(10, 8))
    location_lng = Column(DECIMAL(11, 8))
    insurance_provider = Column(String(50))
    insurance_number = Column(String(50))
    insurance_proof_url = Column(String(500))
    allergies = Column(JSONB)
    otp = Column(String(100))
    otp_expires_at = Column(DateTime)
    auth_token = Column(String(500), nullable=True)
    last_login = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    appointments_as_patient = relationship("Appointment", back_populates="user", foreign_keys="Appointment.user_id")
    doctor_profile = relationship("Doctor", back_populates="user", uselist=False)
    pharmacy_profile = relationship(
        "Pharmacy", 
        foreign_keys="Pharmacy.user_id",
        back_populates="user", 
        uselist=False
    )
    lab_profile = relationship(
        "Laboratory", 
        foreign_keys="Laboratory.user_id", 
        back_populates="user", 
        uselist=False
    )
    payments = relationship("Payment", back_populates="user")
    emergency_requests = relationship("EmergencyRequest", back_populates="user")
    orders = relationship("Order", back_populates="user")
    prescriptions = relationship("Prescription", back_populates="user")
    notifications = relationship("Notification", back_populates="user")
    lab_bookings = relationship("LabBooking", back_populates="user")
    audit_logs = relationship("AuditLog", back_populates="user")
    family_members = relationship("FamilyMember", back_populates="user", cascade="all, delete-orphan")
    addresses = relationship("Address", back_populates="user", cascade="all, delete-orphan")
    notification_preferences = relationship("NotificationPreferences", back_populates="user", uselist=False, cascade="all, delete-orphan")
    uploaded_files = relationship("UploadedFile", back_populates="user")


# ============================================
# CLINIC MANAGEMENT
# ============================================

class Clinic(Base):
    __tablename__ = "clinics"
    
    id = Column(String(50), primary_key=True)
    name = Column(String(200), nullable=False)
    address = Column(Text, nullable=False)
    location_lat = Column(DECIMAL(10, 8), nullable=False)
    location_lng = Column(DECIMAL(11, 8), nullable=False)
    phone = Column(String(15))
    email = Column(String(100))
    working_hours = Column(JSONB)
    emergency_available = Column(Boolean, default=False)
    ambulance_available = Column(Boolean, default=False)
    insurance_accepted = Column(JSONB)
    rating = Column(DECIMAL(3, 2), default=0.0)
    total_reviews = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)
    
    # Relationships
    doctors = relationship("Doctor", back_populates="clinic")
    emergency_requests = relationship("EmergencyRequest", back_populates="assigned_clinic")


# ============================================
# DOCTOR MANAGEMENT
# ============================================

class Doctor(Base):
    __tablename__ = "doctors"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    
    # ✅ NEW: Clinic relationship
    clinic_id = Column(String(50), ForeignKey("clinics.id"))
    
    name = Column(String(100), nullable=False)
    specialties = Column(JSONB, nullable=False)  # ["Cardiology", "General"]
    specialization = Column(String(100), nullable=False)  # Primary specialization
    qualification = Column(String(200), nullable=False)
    experience_years = Column(Integer, default=0)
    registration_number = Column(String(50), unique=True)
    consultation_fee = Column(Integer, nullable=False)
    
    # ✅ NEW: Additional doctor fields
    bio = Column(Text, nullable=True)
    medical_license_number = Column(String(100), nullable=False)
    medical_council = Column(String(100), default="Medical Council of India")
    
    clinic_name = Column(String(100))
    clinic_address = Column(Text)
    available_days = Column(JSONB)  # ["monday", "tuesday", ...]
    available_time_start = Column(Time)
    available_time_end = Column(Time)
    rating = Column(DECIMAL(3, 2), default=0.0)
    total_patients = Column(Integer, default=0)
    
    # ✅ NEW: Total consultations and next available slot
    total_consultations = Column(Integer, default=0)
    next_available_slot = Column(DateTime)
    is_available = Column(Boolean, default=True)
    
    is_verified = Column(Boolean, default=False)
    wallet_balance = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    user = relationship("User", back_populates="doctor_profile")
    clinic = relationship("Clinic", back_populates="doctors")
    appointments = relationship("Appointment", back_populates="doctor")
    slots = relationship("DoctorSlot", back_populates="doctor")
    wallet_transactions = relationship("WalletTransaction", back_populates="doctor")
    prescriptions = relationship("Prescription", back_populates="doctor")
    wallet = relationship("DoctorWallet", back_populates="doctor", uselist=False, cascade="all, delete-orphan")


class DoctorSlot(Base):
    __tablename__ = "doctor_slots"
    
    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    is_booked = Column(Boolean, default=False)
    
    # ✅ NEW: Slot blocking fields
    is_blocked = Column(Boolean, default=False)
    block_reason = Column(Text, nullable=True)
    
    appointment_id = Column(String(20), ForeignKey("appointments.id"), unique=True)
    created_at = Column(DateTime, default=datetime.now)
    
    # Relationships
    doctor = relationship("Doctor", back_populates="slots")

# ============================================
# APPOINTMENTS
# ============================================

class Appointment(Base):
    __tablename__ = "appointments"
    
    id = Column(String(20), primary_key=True)  # APT123 format
    user_id = Column(Integer, ForeignKey("users.id", ondelete='CASCADE'), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    slot_id = Column(Integer, ForeignKey("doctor_slots.id"), unique=False)
    date = Column(Date, nullable=False)
    time = Column(Time, nullable=False)
    reason = Column(Text)
    
    # ✅ NEW: Symptoms and emergency fields
    symptoms = Column(JSONB)
    is_emergency = Column(Boolean, default=False)
    consultation_type = Column(String(20), default='in-person')
    
    status = Column(String(20), default='confirmed')  # confirmed | completed | cancelled
    consultation_fee = Column(Integer, nullable=False)
    payment_id = Column(Integer, ForeignKey("payments.id"))
    prescription = Column(Text)
    notes = Column(Text)
    qr_code = Column(String(255))  # QR code for verification
    
    # ✅ NEW: Cancellation fields
    cancellation_reason = Column(String(100))
    cancelled_at = Column(DateTime)
    
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    user = relationship("User", back_populates="appointments_as_patient", foreign_keys=[user_id])
    doctor = relationship("Doctor", back_populates="appointments")
    payment = relationship("Payment", back_populates="appointment", uselist=False)
    prescription_obj = relationship("Prescription", back_populates="appointment", uselist=False)
    appointment_payment = relationship("AppointmentPayment", back_populates="appointment", uselist=False, cascade="all, delete-orphan")
    qr_code_obj = relationship("QRCode", back_populates="appointment", uselist=False, cascade="all, delete-orphan")
    uploaded_files = relationship("UploadedFile", back_populates="appointment")


# ============================================
# PAYMENT MANAGEMENT
# ============================================

class AppointmentPayment(Base):
    """Payment specifically for appointments with platform fee split"""
    __tablename__ = "appointment_payments"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    appointment_id = Column(String(20), ForeignKey('appointments.id'), unique=True)
    total_amount = Column(Integer, nullable=False)
    platform_fee = Column(Integer, nullable=False)
    doctor_share = Column(Integer, nullable=False)
    razorpay_order_id = Column(String(100))
    razorpay_payment_id = Column(String(100))
    razorpay_signature = Column(String(255))
    payment_status = Column(String(20), default="pending")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    appointment = relationship("Appointment", back_populates="appointment_payment", uselist=False)


class Payment(Base):
    __tablename__ = "payments"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Float, nullable=False)
    payment_type = Column(String(50))  # appointment, pharmacy, lab
    razorpay_order_id = Column(String(100), unique=True)
    razorpay_payment_id = Column(String(100), unique=True)
    razorpay_signature = Column(String(255))
    status = Column(String(20), default="pending")  # pending | success | failed | refunded
    payment_method = Column(String(50))  # card, upi, netbanking
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    user = relationship("User", back_populates="payments")
    appointment = relationship("Appointment", back_populates="payment", uselist=False)
    pharmacy_order = relationship("Order", back_populates="payment", uselist=False)
    lab_booking = relationship("LabBooking", back_populates="payment", uselist=False)


# ============================================
# DOCTOR WALLET
# ============================================

class DoctorWallet(Base):
    __tablename__ = "doctor_wallets"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    doctor_id = Column(Integer, ForeignKey('doctors.id'), unique=True)
    current_balance = Column(Integer, default=0)
    total_earned = Column(Integer, default=0)
    total_withdrawn = Column(Integer, default=0)
    pending_withdrawal = Column(Integer, default=0)
    last_updated = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    doctor = relationship("Doctor", back_populates="wallet", uselist=False)
    transactions = relationship("WalletTransaction", back_populates="wallet")


class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    wallet_id = Column(Integer, ForeignKey("doctor_wallets.id"))
    amount = Column(Integer, nullable=False)
    transaction_type = Column(String(20))  # credit, debit, withdrawal
    description = Column(Text)
    appointment_id = Column(String(20), ForeignKey("appointments.id"), unique=True)  # Changed to String for consistency
    balance_before = Column(Integer)
    balance_after = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    
    # Relationships
    doctor = relationship("Doctor", back_populates="wallet_transactions")
    wallet = relationship("DoctorWallet", back_populates="transactions")


# ============================================
# QR CODE MANAGEMENT
# ============================================

class QRCode(Base):
    __tablename__ = "qr_codes"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    appointment_id = Column(String(20), ForeignKey('appointments.id'), unique=True)
    qr_data = Column(Text, nullable=False)
    verification_token = Column(String(100), unique=True)
    is_used = Column(Boolean, default=False)
    used_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)
    
    # Relationships
    appointment = relationship("Appointment", back_populates="qr_code_obj", uselist=False)


# ============================================
# FAMILY & ADDRESS MANAGEMENT
# ============================================

class FamilyMember(Base):
    __tablename__ = "family_members"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    name = Column(String(100), nullable=False)
    relation = Column(String(20), nullable=False)
    age = Column(Integer)
    gender = Column(String(10))
    blood_group = Column(String(5))
    phone = Column(String(15))
    allergies = Column(JSONB)
    medical_notes = Column(Text)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationship
    user = relationship("User", back_populates="family_members")


class Address(Base):
    __tablename__ = "addresses"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    label = Column(String(50), nullable=False)
    address_line1 = Column(String(200), nullable=False)
    address_line2 = Column(String(200))
    city = Column(String(100), nullable=False)
    state = Column(String(100), nullable=False)
    pincode = Column(String(10), nullable=False)
    location_lat = Column(DECIMAL(10, 8))
    location_lng = Column(DECIMAL(11, 8))
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationship
    user = relationship("User", back_populates="addresses")


# ============================================
# NOTIFICATION MANAGEMENT
# ============================================

class NotificationPreferences(Base):
    __tablename__ = "notification_preferences"
    
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    sms_enabled = Column(Boolean, default=True)
    email_enabled = Column(Boolean, default=True)
    push_enabled = Column(Boolean, default=True)
    appointment_reminders = Column(Boolean, default=True)
    lab_test_reminders = Column(Boolean, default=True)
    order_updates = Column(Boolean, default=True)
    promotional = Column(Boolean, default=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationship
    user = relationship("User", back_populates="notification_preferences")


class Notification(Base):
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    title = Column(String(200))
    message = Column(Text)
    is_read = Column(Boolean, default=False)
    
    # Both naming conventions for compatibility
    type = Column(String(50))  # Old format
    notification_type = Column(String(50))  # New format
    
    # ✅ NEW: Related entity tracking
    related_entity_type = Column(String(50), nullable=True)
    related_entity_id = Column(String(50), nullable=True)
    
    created_at = Column(DateTime, default=datetime.now)
    
    # Relationships
    user = relationship("User", back_populates="notifications")


# ============================================
# FILE UPLOAD MANAGEMENT
# ============================================

class UploadedFile(Base):
    __tablename__ = "uploaded_files"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    appointment_id = Column(String(20), ForeignKey('appointments.id'), nullable=True)
    filename = Column(String(255), nullable=False)
    stored_filename = Column(String(255), nullable=False)
    file_path = Column(Text, nullable=False)
    file_url = Column(Text, nullable=False)
    thumbnail_url = Column(Text, nullable=True)
    file_size = Column(Integer, nullable=False)
    file_hash = Column(String(64), nullable=False)
    file_type = Column(String(10), nullable=False)
    category = Column(String(50), nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    deleted_at = Column(DateTime, nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="uploaded_files")
    appointment = relationship("Appointment", back_populates="uploaded_files")


# ============================================
# PRESCRIPTIONS
# ============================================

class Prescription(Base):
    __tablename__ = "prescriptions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    appointment_id = Column(String(20), ForeignKey('appointments.id'), unique=True)
    doctor_id = Column(Integer, ForeignKey('doctors.id'))
    
    # ✅ NEW: Prescription details
    medicines = Column(JSONB)
    instructions = Column(Text)
    valid_until = Column(Date)
    doctor_name = Column(String(100))
    issue_date = Column(Date)
    image_url = Column(String(500), nullable=True)
    diagnosis = Column(Text, nullable=True)
    follow_up_required = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.now)
    
    # Relationships
    user = relationship("User", back_populates="prescriptions")
    appointment = relationship("Appointment", back_populates="prescription_obj")
    doctor = relationship("Doctor", back_populates="prescriptions")


# ============================================
# PHARMACY
# ============================================

class Pharmacy(Base):
    __tablename__ = "pharmacies"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Both naming conventions for compatibility
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    
    # ✅ NEW: Display ID
    display_id = Column(String(50), unique=True, nullable=False)
    
    # Both naming conventions
    name = Column(String(100), nullable=False)
    pharmacy_name = Column(String(100), nullable=False)
    
    license_number = Column(String(50), unique=True)
    
    # ✅ NEW: Drug license number
    drug_license_number = Column(String(50), nullable=False)
    
    address = Column(String(200), nullable=False)
    city = Column(String(100))
    state = Column(String(100))
    pincode = Column(String(6))
    
    # ✅ NEW: Location coordinates
    location_lat = Column(DECIMAL(10, 8))
    location_lng = Column(DECIMAL(11, 8))
    
    phone = Column(String(15))
    email = Column(String(255))
    
    # ✅ NEW: Owner details
    owner_name = Column(String(100), nullable=False)
    gstin = Column(String(15), unique=True)
    operating_hours = Column(JSONB, nullable=False)
    
    is_verified = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    rating = Column(Float, default=0.0)
    
    # Both naming conventions
    delivery_available = Column(Boolean, default=True)
    home_delivery_available = Column(Boolean, default=True)
    
    # ✅ NEW: Minimum order and total orders
    minimum_order_amount = Column(Float, default=0.0)
    total_orders = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    user = relationship(
        "User", 
        foreign_keys=[user_id], 
        back_populates="pharmacy_profile"
    )
    medicines = relationship("Medicine", back_populates="pharmacy")
    orders = relationship("Order", back_populates="pharmacy")
    stock_entries = relationship("StockEntry", back_populates="pharmacy")


class Medicine(Base):
    __tablename__ = "medicines"
    
    id = Column(Integer, primary_key=True, index=True)
    pharmacy_id = Column(Integer, ForeignKey("pharmacies.id"), nullable=False)
    name = Column(String(200), nullable=False)
    
    # ✅ NEW: Generic name and dosage
    generic_name = Column(String(200))
    dosage = Column(String(50))
    
    manufacturer = Column(String(100))
    
    # ✅ NEW: Composition
    composition = Column(String(300))
    
    description = Column(Text)
    
    # ✅ NEW: MRP and selling price
    mrp = Column(Integer, nullable=False)
    selling_price = Column(Integer, nullable=False)
    discount_percentage = Column(Float, default=0.0)
    
    price = Column(Integer, nullable=False)
    stock_quantity = Column(Integer, default=0)
    
    # ✅ NEW: Reorder level
    reorder_level = Column(Integer, default=10, nullable=False)
    
    category = Column(String(50))  # tablet, syrup, injection, etc.
    requires_prescription = Column(Boolean, default=False)
    
    # ✅ NEW: Controlled substance fields
    is_controlled_substance = Column(Boolean, default=False)
    schedule_type = Column(String(50))
    storage_conditions = Column(String(200))
    
    # ✅ NEW: Expiry and batch
    expiry_date = Column(Date, nullable=False)
    batch_number = Column(String(100), nullable=False)
    
    image_url = Column(String(255))
    
    # ✅ NEW: Medicine image URL
    medicine_image_url = Column(String(500))
    
    is_available = Column(Boolean, default=True)
    
    # ✅ Alternative medicines (both formats supported)
    alternatives = Column(JSONB)  # Old format - keeping for backward compatibility
    alternative_medicines_ids = Column(JSONB)  # New format
    
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    pharmacy = relationship("Pharmacy", back_populates="medicines")
    order_items = relationship("OrderItem", back_populates="medicine")
    stock_entries = relationship("StockEntry", back_populates="medicine", cascade="all, delete-orphan")


class Order(Base):
    """Pharmacy orders (renamed from PharmacyOrder)"""
    __tablename__ = "orders"
    
    id = Column(String(20), primary_key=True)  # ORD123 format
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    pharmacy_id = Column(Integer, ForeignKey("pharmacies.id"), nullable=False)
    order_items = Column(JSONB, nullable=False)  # [{"medicine_id": 1, "quantity": 2, "price": 100}]
    total_amount = Column(Integer, nullable=False)
    delivery_address = Column(Text, nullable=False)
    
    # ✅ NEW: Contact number
    contact_number = Column(String(15), nullable=False)
    
    order_status = Column(String(20), default='pending')  # pending | confirmed | processing | shipped | delivered | cancelled
    payment_status = Column(String(20), default="pending")
    delivery_type = Column(String(20))  # home | pickup
    payment_id = Column(Integer, ForeignKey("payments.id"))
    prescription_id = Column(Integer, ForeignKey("prescriptions.id"))
    prescription_file = Column(String(255))  # If required
    
    # ✅ NEW: Tracking and delivery fields
    tracking_number = Column(String(100))
    estimated_delivery = Column(DateTime)
    delivery_date = Column(DateTime)
    delivered_at = Column(DateTime)
    notes = Column(Text)
    
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    user = relationship("User", back_populates="orders")
    pharmacy = relationship("Pharmacy", back_populates="orders")
    payment = relationship("Payment", back_populates="pharmacy_order", uselist=False)
    prescription = relationship("Prescription")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    """Individual items within an order"""
    __tablename__ = "order_items"
    
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(String(20), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    medicine_id = Column(Integer, ForeignKey("medicines.id", ondelete="RESTRICT"), nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Integer, nullable=False)  # Price at time of order
    
    # Relationships
    order = relationship("Order", back_populates="items")
    medicine = relationship("Medicine", back_populates="order_items")


class StockEntry(Base):
    """Stock movement tracking for pharmacy"""
    __tablename__ = "stock_entries"
    
    id = Column(Integer, primary_key=True, index=True)
    medicine_id = Column(Integer, ForeignKey("medicines.id", ondelete="CASCADE"), nullable=False, index=True)
    pharmacy_id = Column(Integer, ForeignKey("pharmacies.id", ondelete="CASCADE"), nullable=False, index=True)
    entry_type = Column(String(20), nullable=False)  # 'purchase' or 'sale'
    quantity = Column(Integer, nullable=False)
    reference_id = Column(String(50))
    batch_number = Column(String(100))
    expiry_date = Column(Date)
    supplier_name = Column(String(100))
    purchase_price_per_unit = Column(Float)
    invoice_number = Column(String(100))
    created_at = Column(DateTime, default=datetime.now)
    
    # Relationships
    medicine = relationship("Medicine", back_populates="stock_entries")
    pharmacy = relationship("Pharmacy", back_populates="stock_entries")


# ============================================
# LAB TESTS
# ============================================

class Laboratory(Base):
    """Lab vendor (renamed from LabVendor)"""
    __tablename__ = "laboratories"
    
    # ✅ NEW: String ID instead of Integer
    id = Column(String(50), primary_key=True)
    
    # Both naming conventions for compatibility
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    
    # Both naming conventions
    name = Column(String(200), nullable=False)
    lab_name = Column(String(100), nullable=False)
    
    license_number = Column(String(100), unique=True)
    
    # ✅ NEW: Accreditation
    accreditation = Column(JSONB)
    
    address = Column(String(500), nullable=False)
    city = Column(String(100))
    state = Column(String(100))
    pincode = Column(String(10))
    
    # ✅ NEW: Location coordinates
    location_lat = Column(DECIMAL(10, 8))
    location_lng = Column(DECIMAL(11, 8))
    
    phone = Column(String(15))
    
    # ✅ NEW: Owner and contact details
    owner_name = Column(String(100), nullable=False)
    contact_person = Column(String(100), nullable=False)
    emergency_contact = Column(String(15), nullable=False)
    
    is_verified = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    rating = Column(Float, default=0.0)
    home_collection_available = Column(Boolean, default=True)
    
    # ✅ NEW: Home collection charges
    home_collection_charges = Column(Integer, default=50)
    operating_hours = Column(JSONB, nullable=False)
    
    # ✅ NEW: Equipment and specializations
    equipment_list = Column(JSONB)
    specializations = Column(JSONB, nullable=False)
    
    # ✅ NEW: Total tests completed
    total_tests_completed = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    user = relationship(
        "User", 
        foreign_keys=[user_id], 
        back_populates="lab_profile"
    )
    tests = relationship("LabTest", back_populates="laboratory", cascade="all, delete-orphan")
    bookings = relationship("LabBooking", back_populates="laboratory")


class LabTest(Base):
    __tablename__ = "lab_tests"
    
    id = Column(Integer, primary_key=True, index=True)
    laboratory_id = Column(String(50), ForeignKey("laboratories.id"), nullable=False)
    
    test_name = Column(String(200), nullable=False)
    name = Column(String(200), nullable=False)
    category = Column(String(50))  # blood_test, urine_test, etc.
    description = Column(Text)
    price = Column(Integer, nullable=False)
    
    # ✅ NEW: Result time in hours
    result_time_hours = Column(Integer, nullable=False)
    
    sample_type = Column(String(50))  # blood, urine, etc.
    preparation_required = Column(Text)  # fasting, etc.
    report_time = Column(String(50))  # "24 hours", "48 hours"
    
    # ✅ NEW: Home collection and fasting
    home_collection_available = Column(Boolean, default=True)
    fasting_required = Column(Boolean, default=False)
    
    is_available = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    laboratory = relationship("Laboratory", back_populates="tests")
    bookings = relationship("LabBooking", back_populates="test")


class LabBooking(Base):
    __tablename__ = "lab_bookings"
    
    id = Column(String(20), primary_key=True)  # LAB123 format
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    laboratory_id = Column(String(50), ForeignKey("laboratories.id"), nullable=False)
    test_id = Column(Integer, ForeignKey("lab_tests.id"), nullable=False)
    
    test_items = Column(JSONB, nullable=False)  # [{"test_id": 1, "price": 500}]
    total_amount = Column(Float, nullable=False)
    booking_date = Column(Date, nullable=False)
    
    # ✅ NEW: Collection time and type
    collection_date = Column(Date, nullable=False)
    collection_time = Column(Time, nullable=False)
    collection_type = Column(String(20), default='home')
    
    booking_time = Column(Time, nullable=False)
    sample_collection_address = Column(Text)
    
    # ✅ NEW: Address field
    address = Column(Text)
    
    is_home_collection = Column(Boolean, default=False)
    status = Column(String(20), default='scheduled')  # scheduled | completed | cancelled
    payment_id = Column(Integer, ForeignKey("payments.id"))
    report_file = Column(String(255))
    
    # ✅ NEW: Result PDF URL
    result_pdf_url = Column(Text)
    
    # ✅ NEW: Completed at
    completed_at = Column(DateTime)
    
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    user = relationship("User", back_populates="lab_bookings")
    laboratory = relationship("Laboratory", back_populates="bookings")
    test = relationship("LabTest", back_populates="bookings")
    payment = relationship("Payment", back_populates="lab_booking", uselist=False)


# ============================================
# EMERGENCY SERVICES
# ============================================

class EmergencyRequest(Base):
    __tablename__ = "emergency_requests"
    
    id = Column(String(20), primary_key=True)  # EMG123 format
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    emergency_type = Column(String(20), nullable=False)  # ambulance, doctor, nurse
    description = Column(Text)
    location = Column(String(500), nullable=False)
    address = Column(Text)
    
    # Both naming conventions for compatibility
    latitude = Column(Float)
    longitude = Column(Float)
    location_lat = Column(DECIMAL(10, 8), nullable=False)
    location_lng = Column(DECIMAL(11, 8), nullable=False)
    
    contact_number = Column(String(15), nullable=False)
    status = Column(String(20), default="requested")  # requested | assigned | completed | cancelled
    assigned_to = Column(String(100))  # Service provider name/ID
    
    # ✅ NEW: Assigned clinic
    assigned_clinic_id = Column(String(50), ForeignKey('clinics.id'))
    ambulance_eta = Column(Integer)
    
    created_at = Column(DateTime, default=datetime.now)
    resolved_at = Column(DateTime)
    completed_at = Column(DateTime)
    
    # Relationships
    user = relationship("User", back_populates="emergency_requests")
    assigned_clinic = relationship("Clinic", back_populates="emergency_requests")


# ============================================
# AUDIT LOGS
# ============================================

class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    action = Column(String(100))
    entity_type = Column(String(50))
    entity_id = Column(String(50))
    details = Column(JSONB)
    created_at = Column(DateTime, default=datetime.now)
    
    # Relationships
    user = relationship("User", back_populates="audit_logs")