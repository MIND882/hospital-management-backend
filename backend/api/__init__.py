# API Package - Centralized imports
# Allows easy importing of all routers and functions

from .auth import router as auth_router, get_current_user, create_access_token, create_refresh_token
from .appointments import router as appointments_router
from .emergency import router as emergency_router
from .lab_tests import router as lab_tests_router
from .pharmacy import router as pharmacy_router
from .payments import (
    router as payments_router, 
    RAZORPAY_KEY_ID, 
    RAZORPAY_KEY_SECRET
)
from .doctor_management import router as doctor_management_router
from .dashboard import router as dashboard_router
from .pharmacy_vendor import router as pharmacy_vendor_router
from .lab_vendor import router as lab_vendor_router
from .upload import router as upload_router
from .profile import router as profile_router

__all__ = [
    # Auth
    "auth_router",
    "get_current_user",
    "create_access_token",
    "create_refresh_token",
    
    # Routers
    "appointments_router",
    "emergency_router",
    "lab_tests_router",
    "pharmacy_router",
    "payments_router",
    "doctor_management_router",
    "dashboard_router",
    "pharmacy_vendor_router",
    "lab_vendor_router",
    "upload_router",
    "profile_router",
    
    # Razorpay Keys
    "RAZORPAY_KEY_ID",
    "RAZORPAY_KEY_SECRET",
]
