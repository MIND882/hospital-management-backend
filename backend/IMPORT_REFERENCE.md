# Import Reference Guide

This backend now has centralized `__init__.py` files that make importing much easier.

## Database Imports

```python
# Import models
from database import User, Doctor, Medicine, Order, Appointment
from database import LabTest, Pharmacy, Prescription

# Import connection utilities
from database import get_db, engine, Base, SessionLocal
```

## API Imports

```python
# Import routers
from api import (
    auth_router,
    appointments_router,
    emergency_router,
    lab_tests_router,
    pharmacy_router,
    payments_router,
    doctor_management_router,
    dashboard_router,
    pharmacy_vendor_router,
    lab_vendor_router,
    upload_router,
    profile_router,
)

# Import auth functions
from api import get_current_user, create_access_token, create_refresh_token

# Import payment keys
from api import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET
```

## Services Imports

```python
# Services modules
from services import notification_service
from services import sms_service
from services import distance_calculator
```

## Utils Imports

```python
# Utils modules
from utils import helpers
```

## Running the Application

Set PYTHONPATH and run:
```powershell
$env:PYTHONPATH = "C:\Users\Admin\hospital\backend"
.\hos\Scripts\python.exe main.py
```

Or with uvicorn:
```powershell
$env:PYTHONPATH = "C:\Users\Admin\hospital\backend"
.\hos\Scripts\python.exe -m uvicorn main:app --reload
```
