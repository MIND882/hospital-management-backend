# Database Package - Centralized imports
# Allows easy importing of models, connection utilities, and ORM objects

from .connection import (
    engine,
    Base,
    SessionLocal,
    get_db,
)

from .models import (
    # User & Auth Models
    User,
    AuditLog,
    
    # Doctor Models
    Doctor,
    DoctorSlot,
    DoctorWallet,
    WalletTransaction,
    
    # Clinic Models
    Clinic,
    
    # Appointment Models
    Appointment,
    AppointmentPayment,
    PaymentStatus,
    
    # Lab Models
    LabTest,
    LabBooking,
    Laboratory,
    
    # Pharmacy Models
    Medicine,
    Pharmacy,
    Order,
    OrderItem,
    StockEntry,
    Prescription,
    
    # Notification & Profile Models
    Notification,
    NotificationPreferences,
    FamilyMember,
    Address,
    UploadedFile,
    QRCode,
)

__all__ = [
    # Connection
    "engine",
    "Base",
    "SessionLocal",
    "get_db",
    
    # User & Auth
    "User",
    "AuditLog",
    
    # Doctor
    "Doctor",
    "DoctorSlot",
    "DoctorWallet",
    "WalletTransaction",
    
    # Clinic
    "Clinic",
    
    # Appointment
    "Appointment",
    "AppointmentPayment",
    "PaymentStatus",
    
    # Lab
    "LabTest",
    "LabBooking",
    "Laboratory",
    
    # Pharmacy
    "Medicine",
    "Pharmacy",
    "Order",
    "OrderItem",
    "StockEntry",
    "Prescription",
    
    # Notifications & Profile
    "Notification",
    "NotificationPreferences",
    "FamilyMember",
    "Address",
    "UploadedFile",
    "QRCode",
]
