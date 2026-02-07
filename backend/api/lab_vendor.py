import sys
from pathlib import Path

# Add backend directory to path for imports to work when running directly
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from fastapi import APIRouter, Depends,HTTPException,UploadFile,File
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_,func,desc,extract
from database.connection import get_db
from database.models import (
    User,LabTest,LabBooking,AuditLog,Notification,Laboratory
)
from api.auth import get_current_user
from pydantic import BaseModel,Field,EmailStr,model_validator
from typing import Optional,List,Dict,Literal
from datetime import date,time,datetime,timedelta
import secrets

router = APIRouter(prefix="/api/lab-vendor", tags=["Lab Vendor"])

#=========================== PYDANTIC MODELS ==============================

class LabRegistrationRequest(BaseModel):

    """ LAB VENDOR ONBOARDING"""

    lab_name : str = Field(..., min_length=2, max_length=200)
    license_number: str
    email : EmailStr = Field(..., description="official email of the lab")
    password: str = Field(..., min_length=8)
    phone : str = Field(..., min_length=10, max_length=15)
    address : str = Field(..., min_length=10, max_length=500)
    accreditation: List[str] = Field(
        default=[],
        description="NABL, CAP, ISO certifications"
    )
    city: str
    state: str
    pincode: str = Field(..., min_length=6, max_length=10)
    location_lat: Optional[float] = None
    location_lng: Optional[float] = None
    owner_name: str
    contact_person: str
    emergency_contact: str
    
    # Services
    home_collection_available: bool = True
    home_collection_charges: int = Field(default=50, ge=0)
    operating_hours: Dict[str, str] = Field(
    default={
        "mon": "09:00-21:00", 
        "tue": "09:00-21:00", 
        "wed": "09:00-21:00",
        "thu": "09:00-21:00", 
        "fri": "09:00-21:00", 
        "sat": "10:00-18:00",
        "sun": "10:00-18:00"
    },
    description="Lab opening and closing times for each day")

    
    # Equipment & facilities
    equipment_list: List[str] = [] # Optional hatakar default empty list dena better hai
    specializations: List[str] = Field(
        ...,
        min_items=1, # Kam se kam ek specialization honi chahiye
        description="Pathology, Radiology, Cardiology, etc."
    )

class LabLoginRequest(BaseModel):
    # Ya toh email dega user, ya phone
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, min_length=10, max_length=15)
    password: str = Field(..., min_length=8)

    # Validation logic: Dono mein se ek cheez toh honi hi chahiye
    @model_validator(mode='after')
    def check_identifier(self):
        if not self.email and not self.phone:
            raise ValueError('Email ya Phone mein se ek dena compulsory hai')
        return self

    class Config:
        # Isse sensitive data logs mein nahi dikhega
        str_strip_whitespace = True 

class AddTestRequest(BaseModel):
    """ADD NEW TEST TO CATALOG"""
    name:str = Field (..., min_length=2, max_length= 200, example="Complete Blood Count (CBC)")
    category: str = Field(
        ...,
        description="Blood test, Urine Test,Imaging,etc."
    )
    sub_category: Optional[str] = None
    description: Optional[str] = None 

    #Pricing
    price: int = Field(..., ge = 50)
    discount_percentage: int = Field(default=0, ge=0, le=100)

    # test details
    parameters_included: List[str] = Field(
        ...,
        description="List of parameters/components"
    )
    sample_type: str = Field(..., description="Blood, Urine, Tissue, etc.")
    fasting_required: bool = False
    fasting_duration_hours: Optional[int] = None

        
    # Processing
    result_time_hours: int = Field(..., ge=1, le=168)  # Max 7 days
    home_collection_available: bool = True
    
    # Requirements
    special_instructions: Optional[str] = None
    preparation_required: Optional[str] = None

class UpdateTestRequest(BaseModel):
    test_id:int
    price: Optional[int] = Field(None, ge=50)
    result_time_hours: Optional[int] = Field(None, ge=1, le=168)
    is_available: Optional[bool] = None
    home_collection_available: Optional[bool] = None

class UpdateBookingStatusRequest(BaseModel):
    booking_id:str
    new_status: Literal["scheduled", "sample_collected", "processing", "completed", "cancelled"]
    technician_name: Optional[str] = None
    collection_notes: Optional[str] = None
    report_url: Optional[str] = None
class SampleCollectionRequest(BaseModel):
    booking_id: str
    collected_by: str
    collection_time: datetime
    sample_quality: Literal["good", "poor", "rejected"]
    sample_notes: Optional[str] = None
    vial_ids: Optional[List[str]] = []

class UploadReportRequest(BaseModel):
    booking_id: str
    report_pdf_url: str
    verified_by: str
    remarks: Optional[str] = None

# ==================== HELPER FUNCTIONS ====================

def generate_lab_id() -> str:
    """Generate unique lab ID (e.g., LAB5421)"""
    return f"LAB{secrets.randbelow(9000) + 1000}"


def send_lab_notification(
    db: Session,
    user_id: int,
    title: str,
    message: str,
    notification_type: str = "lab_alert"
):
    """Send notification to patient"""
    notification = Notification(
        user_id=user_id,
        type=notification_type,
        title=title,
        message=message,
        created_at=datetime.now()
    )
    db.add(notification)
    try:
        db.commit()
    except Exception:
        db.rollback()
    return notification


def calculate_lab_stats(lab_id: int, db: Session) -> Dict:
    """Calculate lab performance statistics"""
    
    # Total tests
    total_tests = db.query(LabBooking).filter(
        LabBooking.laboratory_id == lab_id
    ).count()
    
    # Completed tests
    completed = db.query(LabBooking).filter(
        and_(
            LabBooking.laboratory_id == lab_id,
            LabBooking.status == 'completed'
        )
    ).count()
    
    # Average turnaround time
    avg_tat = db.query(
        func.avg(
            func.extract('epoch', LabBooking.completed_at - LabBooking.created_at) / 3600
        )
    ).filter(
        and_(
            LabBooking.laboratory_id == lab_id,
            LabBooking.status == 'completed',
            LabBooking.completed_at.isnot(None)
        )
    ).scalar() or 0
    
    # Pending reports
    pending = db.query(LabBooking).filter(
        and_(
            LabBooking.laboratory_id == lab_id,
            LabBooking.status.in_(['sample_collected', 'processing'])
        )
    ).count()
    
    return {
        "total_tests": total_tests,
        "completed": completed,
        "pending_reports": pending,
        "average_turnaround_hours": round(avg_tat, 2),
        "completion_rate": round((completed / total_tests * 100), 2) if total_tests > 0 else 0
    }


def get_test_popularity(lab_id: int, db: Session, limit: int = 10) -> List[Dict]:
    """Get most booked tests"""
    
    popular_tests = db.query(
        LabTest.name,
        LabTest.category,
        func.count(LabBooking.id).label('bookings')
    ).join(
        LabBooking, LabBooking.test_id == LabTest.id
    ).filter(
        LabBooking.laboratory_id == lab_id
    ).group_by(
        LabTest.name, LabTest.category
    ).order_by(desc('bookings')).limit(limit).all()
    
    return [
        {
            "test_name": name,
            "category": category,
            "total_bookings": int(bookings)
        }
        for name, category, bookings in popular_tests
    ]


def check_overdue_reports(lab_id: int, db: Session) -> List[Dict]:
    """Find bookings with overdue reports"""
    
    overdue = db.query(LabBooking).options(
        joinedload(LabBooking.test),
        joinedload(LabBooking.user)
    ).filter(
        and_(
            LabBooking.laboratory_id == lab_id,
            LabBooking.status.in_(['sample_collected', 'processing']),
            LabBooking.collection_date.isnot(None)
        )
    ).all()
    
    overdue_list = []
    
    for booking in overdue:
        expected_completion = datetime.combine(
            booking.collection_date,
            booking.collection_time
        ) + timedelta(hours=booking.test.result_time_hours)
        
        if datetime.now() > expected_completion:
            hours_overdue = (datetime.now() - expected_completion).total_seconds() / 3600
            
            overdue_list.append({
                "booking_id": booking.id,
                "patient_name": booking.user.name,
                "test_name": booking.test.name,
                "collection_date": str(booking.collection_date),
                "expected_completion": expected_completion.strftime('%Y-%m-%d %I:%M %p'),
                "hours_overdue": round(hours_overdue, 1),
                "status": booking.status
            })
    
    return sorted(overdue_list, key=lambda x: x['hours_overdue'], reverse=True)

# ==================== REGISTRATION ====================

@router.post("/register", response_model=dict)
async def register_lab(
    request: LabRegistrationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    🔬 LAB VENDOR REGISTRATION
    
    ✅ FIXED: Proper email/password handling
    """
    
    # Check if user already has lab
    existing = db.query(Laboratory).filter(
        Laboratory.owner_user_id == current_user.id
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Lab already registered with this account"
        )
    
    # ✅ FIX: Update user's email if provided
    if request.email and request.email != current_user.email:
        # Check if email already exists
        email_exists = db.query(User).filter(
            User.email == request.email,
            User.id != current_user.id
        ).first()
        
        if email_exists:
            raise HTTPException(
                status_code=400,
                detail="Email already registered"
            )
        
        current_user.email = request.email
    
    # Create lab profile
    lab_id = generate_lab_id()
    
    laboratory = Laboratory(
        id=lab_id,
        owner_user_id=current_user.id,
        name=request.lab_name,
        license_number=request.license_number,
        accreditation=request.accreditation,
        address=request.address,
        city=request.city,
        state=request.state,
        pincode=request.pincode,
        location_lat=request.location_lat,
        location_lng=request.location_lng,
        owner_name=request.owner_name,
        contact_person=request.contact_person,
        emergency_contact=request.emergency_contact,
        home_collection_available=request.home_collection_available,
        home_collection_charges=request.home_collection_charges,
        operating_hours=request.operating_hours,
        equipment_list=request.equipment_list,
        specializations=request.specializations,
        is_verified=False,
        is_active=True,
        rating=0.0,
        total_tests_completed=0
    )
    
    db.add(laboratory)
    db.commit()
    db.refresh(laboratory)
    
    # Log registration
    audit = AuditLog(
        user_id=current_user.id,
        action="LAB_REGISTERED",
        entity_type="laboratory",
        entity_id=lab_id,
        details={
            "lab_name": request.lab_name,
            "specializations": request.specializations
        }
    )
    db.add(audit)
    db.commit()
    
    return {
        "status": "success",
        "message": "Lab registration successful",
        "lab_id": lab_id,
        "verification_status": "pending",
        "next_steps": [
            "Upload lab license",
            "Upload accreditation certificates",
            "Upload facility photos",
            "Wait for verification (24-48 hours)",
            "Once verified, start adding tests"
        ]
    }


@router.post("/login", response_model=dict)
async def lab_vendor_login(
    request: LabLoginRequest,
    db: Session = Depends(get_db)
):
    """
    🔐 LAB VENDOR LOGIN
    """
    from database.models import Laboratory
    import bcrypt
    from .auth import create_access_token, create_refresh_token
    
    # Find user by email or phone
    user = None
    if request.email:
        user = db.query(User).filter(User.email == request.email).first()
    elif request.phone:
        user = db.query(User).filter(User.phone == request.phone).first()
    
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials"
        )
    
    # Verify password
    if not bcrypt.checkpw(request.password.encode(), user.password_hash.encode()):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials"
        )
    
    # Get lab profile
    lab = db.query(Laboratory).filter(
        Laboratory.owner_user_id == user.id
    ).first()
    
    if not lab:
        raise HTTPException(
            status_code=404,
            detail="Lab profile not found"
        )
    
    # Check if verified
    if not lab.is_verified:
        raise HTTPException(
            status_code=403,
            detail="Lab not yet verified. Please wait for admin approval."
        )
    
    # Generate tokens
    access_token = create_access_token(data={
        "user_id": user.id,
        "lab_id": lab.id,
        "role": "lab_vendor"
    })
    
    refresh_token = create_refresh_token(data={
        "user_id": user.id,
        "lab_id": lab.id
    })
    
    # Log login
    audit = AuditLog(
        user_id=user.id,
        action="LAB_VENDOR_LOGIN",
        entity_type="laboratory",
        entity_id=lab.id,
        details={"email": request.email, "phone": request.phone}
    )
    db.add(audit)
    db.commit()
    
    return {
        "status": "success",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "lab": {
            "id": lab.id,
            "name": lab.name,
            "is_verified": lab.is_verified,
            "is_active": lab.is_active
        }
    }
# ==================== PROFILE MANAGEMENT ====================

@router.get("/profile", response_model=dict)
async def get_lab_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    👤 GET LAB VENDOR PROFILE
    """
    from database.models import Laboratory
    
    lab = db.query(Laboratory).filter(
        Laboratory.owner_user_id == current_user.id
    ).first()
    
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    
    return {
        "id": lab.id,
        "name": lab.name,
        "license_number": lab.license_number,
        "accreditation": lab.accreditation,
        "address": lab.address,
        "city": lab.city,
        "state": lab.state,
        "pincode": lab.pincode,
        "location_lat": lab.location_lat,
        "location_lng": lab.location_lng,
        "owner_name": lab.owner_name,
        "contact_person": lab.contact_person,
        "emergency_contact": lab.emergency_contact,
        "home_collection_available": lab.home_collection_available,
        "home_collection_charges": lab.home_collection_charges,
        "operating_hours": lab.operating_hours,
        "equipment_list": lab.equipment_list,
        "specializations": lab.specializations,
        "is_verified": lab.is_verified,
        "is_active": lab.is_active,
        "rating": lab.rating,
        "total_tests_completed": lab.total_tests_completed,
        "created_at": lab.created_at.strftime('%Y-%m-%d'),
        "updated_at": lab.updated_at.strftime('%Y-%m-%d') if lab.updated_at else None
    }

@router.put("/profile/update", response_model=dict)
async def update_lab_profile(
    operating_hours: Optional[Dict[str, str]] = None,
    home_collection_available: Optional[bool] = None,
    home_collection_charges: Optional[int] = None,
    emergency_contact: Optional[str] = None,
    equipment_list: Optional[List[str]] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    ✏️ UPDATE LAB PROFILE
    """
    from database.models import Laboratory
    
    lab = db.query(Laboratory).filter(
        Laboratory.owner_user_id == current_user.id
    ).first()
    
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    
    # Update fields
    if operating_hours is not None:
        lab.operating_hours = operating_hours
    
    if home_collection_available is not None:
        lab.home_collection_available = home_collection_available
    
    if home_collection_charges is not None:
        lab.home_collection_charges = home_collection_charges
    
    if emergency_contact is not None:
        lab.emergency_contact = emergency_contact
    
    if equipment_list is not None:
        lab.equipment_list = equipment_list
    
    lab.updated_at = datetime.now()
    
    db.commit()
    
    return {
        "status": "success",
        "message": "Profile updated successfully"
    }

# ==================== TEST CATALOG MANAGEMENT ====================

@router.post("/tests/add", response_model=dict)
async def add_test(
    request: AddTestRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    🧪 ADD NEW TEST TO CATALOG
    """
    
    # Get lab
    from database.models import Laboratory
    lab = db.query(Laboratory).filter(
        Laboratory.owner_user_id == current_user.id
    ).first()
    
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    
    if not lab.is_verified:
        raise HTTPException(
            status_code=403,
            detail="Lab not verified. Cannot add tests yet."
        )
    
    # Check if test already exists
    existing = db.query(LabTest).filter(
        and_(
            LabTest.laboratory_id == lab.id,
            LabTest.name == request.name
        )
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Test with same name already exists"
        )
    
    # Create test
    lab_test = LabTest(
        laboratory_id=lab.id,
        name=request.name,
        category=request.category,
        sub_category=request.sub_category,
        description=request.description,
        price=request.price,
        discount_percentage=request.discount_percentage,
        parameters_included=request.parameters_included,
        sample_type=request.sample_type,
        fasting_required=request.fasting_required,
        fasting_duration_hours=request.fasting_duration_hours,
        result_time_hours=request.result_time_hours,
        home_collection_available=request.home_collection_available,
        special_instructions=request.special_instructions,
        preparation_required=request.preparation_required,
        is_available=True
    )
    
    db.add(lab_test)
    db.commit()
    db.refresh(lab_test)
    
    return {
        "status": "success",
        "message": "Test added successfully",
        "test_id": lab_test.id,
        "test_name": lab_test.name
    }


@router.put("/tests/update", response_model=dict)
async def update_test(
    request: UpdateTestRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    ✏️ UPDATE TEST DETAILS
    """
    
    # Get lab
    from database.models import Laboratory
    lab = db.query(Laboratory).filter(
        Laboratory.owner_user_id == current_user.id
    ).first()
    
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    
    # Get test
    test = db.query(LabTest).filter(
        and_(
            LabTest.id == request.test_id,
            LabTest.laboratory_id == lab.id
        )
    ).first()
    
    if not test:
        raise HTTPException(status_code=404, detail="Test not found")
    
    # Update fields
    if request.price is not None:
        test.price = request.price
    
    if request.result_time_hours is not None:
        test.result_time_hours = request.result_time_hours
    
    if request.is_available is not None:
        test.is_available = request.is_available
    
    if request.home_collection_available is not None:
        test.home_collection_available = request.home_collection_available
    
    test.updated_at = datetime.now()
    
    db.commit()
    
    return {
        "status": "success",
        "message": "Test updated successfully"
    }


@router.get("/tests/catalog", response_model=dict)
async def get_test_catalog(
    current_user: User = Depends(get_current_user),
    category: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """
    📋 VIEW TEST CATALOG
    """
    
    # Get lab
    from database.models import Laboratory
    lab = db.query(Laboratory).filter(
        Laboratory.owner_user_id == current_user.id
    ).first()
    
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    
    # Build query
    query = db.query(LabTest).filter(LabTest.laboratory_id == lab.id)
    
    if category:
        query = query.filter(LabTest.category == category)
    
    if search:
        query = query.filter(
            func.lower(LabTest.name).contains(search.lower())
        )
    
    total = query.count()
    
    tests = query.offset((page - 1) * limit).limit(limit).all()
    
    return {
        "total": total,
        "page": page,
        "tests": [
            {
                "id": test.id,
                "name": test.name,
                "category": test.category,
                "price": test.price,
                "result_time_hours": test.result_time_hours,
                "home_collection": test.home_collection_available,
                "fasting_required": test.fasting_required,
                "is_available": test.is_available
            }
            for test in tests
        ]
    }
# ==================== TEST DETAILS ====================

@router.get("/tests/{test_id}", response_model=dict)
async def get_test_details(
    test_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    🔍 GET SINGLE TEST DETAILS
    """
    from database.models import Laboratory
    
    lab = db.query(Laboratory).filter(
        Laboratory.owner_user_id == current_user.id
    ).first()
    
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    
    test = db.query(LabTest).filter(
        and_(
            LabTest.id == test_id,
            LabTest.laboratory_id == lab.id
        )
    ).first()
    
    if not test:
        raise HTTPException(status_code=404, detail="Test not found")
    
    # Get booking stats for this test
    total_bookings = db.query(LabBooking).filter(
        LabBooking.test_id == test_id
    ).count()
    
    completed_bookings = db.query(LabBooking).filter(
        and_(
            LabBooking.test_id == test_id,
            LabBooking.status == 'completed'
        )
    ).count()
    
    return {
        "id": test.id,
        "name": test.name,
        "category": test.category,
        "sub_category": test.sub_category,
        "description": test.description,
        "price": test.price,
        "discount_percentage": test.discount_percentage,
        "final_price": test.price - (test.price * test.discount_percentage / 100),
        "parameters_included": test.parameters_included,
        "sample_type": test.sample_type,
        "fasting_required": test.fasting_required,
        "fasting_duration_hours": test.fasting_duration_hours,
        "result_time_hours": test.result_time_hours,
        "home_collection_available": test.home_collection_available,
        "special_instructions": test.special_instructions,
        "preparation_required": test.preparation_required,
        "is_available": test.is_available,
        "stats": {
            "total_bookings": total_bookings,
            "completed": completed_bookings
        }
    }


@router.delete("/tests/{test_id}", response_model=dict)
async def delete_test(
    test_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    🗑️ DELETE TEST (SOFT DELETE)
    """
    from database.models import Laboratory
    
    lab = db.query(Laboratory).filter(
        Laboratory.owner_user_id == current_user.id
    ).first()
    
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    
    test = db.query(LabTest).filter(
        and_(
            LabTest.id == test_id,
            LabTest.laboratory_id == lab.id
        )
    ).first()
    
    if not test:
        raise HTTPException(status_code=404, detail="Test not found")
    
    # Check if test has active bookings
    active_bookings = db.query(LabBooking).filter(
        and_(
            LabBooking.test_id == test_id,
            LabBooking.status.in_(['scheduled', 'sample_collected', 'processing'])
        )
    ).count()
    
    if active_bookings > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete test. {active_bookings} active booking(s) exist."
        )
    
    # Soft delete
    test.is_available = False
    test.updated_at = datetime.now()
    
    db.commit()
    
    return {
        "status": "success",
        "message": "Test removed from catalog"
    }


# ==================== BOOKING MANAGEMENT (CORRECT ORDER) ====================

# ✅ 1. SPECIFIC ROUTES FIRST

@router.get("/bookings/today", response_model=dict)
async def get_today_bookings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """📋 TODAY'S SAMPLE COLLECTIONS"""
    lab = db.query(Laboratory).filter(Laboratory.owner_user_id == current_user.id).first()
    
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    
    bookings = db.query(LabBooking).options(
        joinedload(LabBooking.user),
        joinedload(LabBooking.test)
    ).filter(
        and_(
            LabBooking.laboratory_id == lab.id,
            LabBooking.collection_date == date.today(),
            LabBooking.status.in_(['scheduled', 'sample_collected'])
        )
    ).order_by(LabBooking.collection_time).all()
    
    home_collections = []
    lab_visits = []
    
    for booking in bookings:
        booking_data = {
            "booking_id": booking.id,
            "time": booking.collection_time.strftime('%I:%M %p'),
            "patient_name": booking.user.name,
            "patient_phone": booking.user.phone,
            "test_name": booking.test.name,
            "address": booking.address,
            "status": booking.status,
            "fasting_required": booking.test.fasting_required
        }
        
        if booking.collection_type == 'home':
            home_collections.append(booking_data)
        else:
            lab_visits.append(booking_data)
    
    return {
        "date": str(date.today()),
        "total": len(bookings),
        "home_collections": home_collections,
        "lab_visits": lab_visits
    }


@router.get("/bookings/pending", response_model=dict)
async def get_pending_bookings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """⏳ PENDING BOOKINGS (Sample Collected, Awaiting Results)"""
    lab = db.query(Laboratory).filter(Laboratory.owner_user_id == current_user.id).first()
    
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    
    bookings = db.query(LabBooking).options(
        joinedload(LabBooking.user),
        joinedload(LabBooking.test)
    ).filter(
        and_(
            LabBooking.laboratory_id == lab.id,
            LabBooking.status.in_(['sample_collected', 'processing'])
        )
    ).order_by(LabBooking.collection_date).all()
    
    return {
        "total": len(bookings),
        "bookings": [
            {
                "booking_id": booking.id,
                "collection_date": str(booking.collection_date),
                "patient_name": booking.user.name,
                "test_name": booking.test.name,
                "status": booking.status,
                "expected_result_time": (
                    datetime.combine(booking.collection_date, booking.collection_time) +
                    timedelta(hours=booking.test.result_time_hours)
                ).strftime('%Y-%m-%d %I:%M %p')
            }
            for booking in bookings
        ]
    }


@router.get("/bookings/history", response_model=dict)
async def get_booking_history(
    current_user: User = Depends(get_current_user),
    status: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    page: int = 1,
    limit: int = 20,
    db: Session = Depends(get_db)
):
    """📜 BOOKING HISTORY"""
    lab = db.query(Laboratory).filter(Laboratory.owner_user_id == current_user.id).first()
    
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    
    query = db.query(LabBooking).options(
        joinedload(LabBooking.user),
        joinedload(LabBooking.test)
    ).filter(LabBooking.laboratory_id == lab.id)
    
    if status:
        query = query.filter(LabBooking.status == status)
    if start_date:
        query = query.filter(LabBooking.collection_date >= start_date)
    if end_date:
        query = query.filter(LabBooking.collection_date <= end_date)
    
    total = query.count()
    bookings = query.order_by(desc(LabBooking.created_at)).offset((page - 1) * limit).limit(limit).all()
    
    return {
        "total": total,
        "page": page,
        "bookings": [
            {
                "booking_id": booking.id,
                "date": str(booking.collection_date),
                "patient_name": booking.user.name,
                "test_name": booking.test.name,
                "status": booking.status,
                "amount": booking.test.price
            }
            for booking in bookings
        ]
    }


# ✅ 2. POST/PUT ROUTES

@router.post("/bookings/collect-sample", response_model=dict)
async def collect_sample(
    request: SampleCollectionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """💉 MARK SAMPLE AS COLLECTED"""
    lab = db.query(Laboratory).filter(Laboratory.owner_user_id == current_user.id).first()
    
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    
    booking = db.query(LabBooking).filter(
        and_(LabBooking.id == request.booking_id, LabBooking.laboratory_id == lab.id)
    ).first()
    
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    if booking.status != 'scheduled':
        raise HTTPException(
            status_code=400,
            detail=f"Cannot collect sample. Current status: {booking.status}"
        )
    
    booking.status = 'sample_collected'
    booking.collected_by = request.collected_by
    booking.collection_actual_time = request.collection_time
    booking.sample_quality = request.sample_quality
    booking.sample_notes = request.sample_notes
    booking.vial_ids = request.vial_ids
    
    db.commit()
    
    send_lab_notification(
        db=db,
        user_id=booking.user_id,
        title="Sample Collected",
        message=f"Your sample for {booking.test.name} has been collected successfully. Results will be ready soon.",
        notification_type="sample_collected"
    )
    
    return {
        "status": "success",
        "booking_id": request.booking_id,
        "message": "Sample collection recorded",
        "next_step": "Process sample and upload results"
    }


@router.put("/bookings/update-status", response_model=dict)
async def update_booking_status(
    request: UpdateBookingStatusRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """📊 UPDATE BOOKING STATUS"""
    lab = db.query(Laboratory).filter(Laboratory.owner_user_id == current_user.id).first()
    
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    
    booking = db.query(LabBooking).filter(
        and_(LabBooking.id == request.booking_id, LabBooking.laboratory_id == lab.id)
    ).first()
    
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    booking.status = request.new_status
    
    if request.technician_name:
        booking.collected_by = request.technician_name
    if request.collection_notes:
        booking.sample_notes = request.collection_notes
    if request.report_url:
        booking.result_pdf_url = request.report_url
        booking.completed_at = datetime.now()
    
    db.commit()
    
    status_messages = {
        "scheduled": "Your lab test is scheduled",
        "sample_collected": "Sample collected successfully",
        "processing": "Your sample is being processed",
        "completed": "Your test report is ready!",
        "cancelled": "Your lab test booking was cancelled"
    }
    
    send_lab_notification(
        db=db,
        user_id=booking.user_id,
        title=status_messages.get(request.new_status, "Status Updated"),
        message=f"Booking #{request.booking_id[-6:]}: {status_messages.get(request.new_status)}",
        notification_type="booking_update"
    )
    
    return {
        "status": "success",
        "booking_id": request.booking_id,
        "new_status": request.new_status
    }


@router.post("/bookings/upload-report", response_model=dict)
async def upload_report(
    request: UploadReportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """📤 UPLOAD TEST REPORT"""
    lab = db.query(Laboratory).filter(Laboratory.owner_user_id == current_user.id).first()
    
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    
    booking = db.query(LabBooking).filter(
        and_(LabBooking.id == request.booking_id, LabBooking.laboratory_id == lab.id)
    ).first()
    
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    booking.status = 'completed'
    booking.result_pdf_url = request.report_pdf_url
    booking.verified_by = request.verified_by
    booking.report_remarks = request.remarks
    booking.completed_at = datetime.now()
    
    lab.total_tests_completed += 1
    
    db.commit()
    
    send_lab_notification(
        db=db,
        user_id=booking.user_id,
        title="📄 Report Ready!",
        message=f"Your {booking.test.name} report is ready. Download from the app or check your email.",
        notification_type="report_ready"
    )
    
    return {
        "status": "success",
        "booking_id": request.booking_id,
        "message": "Report uploaded successfully",
        "report_url": request.report_pdf_url
    }


@router.post("/bookings/{booking_id}/cancel", response_model=dict)
async def cancel_booking(
    booking_id: str,
    reason: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """❌ CANCEL BOOKING (Lab side)"""
    lab = db.query(Laboratory).filter(Laboratory.owner_user_id == current_user.id).first()
    
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    
    booking = db.query(LabBooking).filter(
        and_(LabBooking.id == booking_id, LabBooking.laboratory_id == lab.id)
    ).first()
    
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    if booking.status in ['completed', 'cancelled']:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel booking with status: {booking.status}"
        )
    
    booking.status = 'cancelled'
    booking.updated_at = datetime.now()
    
    db.commit()
    
    send_lab_notification(
        db=db,
        user_id=booking.user_id,
        title="Booking Cancelled",
        message=f"Your lab test booking #{booking_id[-6:]} has been cancelled by the lab. Reason: {reason}",
        notification_type="booking_cancelled"
    )
    
    return {
        "status": "success",
        "booking_id": booking_id,
        "message": "Booking cancelled successfully"
    }


# ✅ 3. DYNAMIC ROUTE LAST

@router.get("/bookings/{booking_id}", response_model=dict)
async def get_booking_details(
    booking_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """📋 GET SINGLE BOOKING DETAILS"""
    lab = db.query(Laboratory).filter(Laboratory.owner_user_id == current_user.id).first()
    
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    
    booking = db.query(LabBooking).options(
        joinedload(LabBooking.user),
        joinedload(LabBooking.test)
    ).filter(
        and_(LabBooking.id == booking_id, LabBooking.laboratory_id == lab.id)
    ).first()
    
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    return {
        "booking_id": booking.id,
        "patient": {
            "name": booking.user.name,
            "phone": booking.user.phone,
            "email": booking.user.email
        },
        "test": {
            "name": booking.test.name,
            "category": booking.test.category,
            "price": booking.test.price,
            "fasting_required": booking.test.fasting_required,
            "result_time_hours": booking.test.result_time_hours
        },
        "collection_date": str(booking.collection_date),
        "collection_time": booking.collection_time.strftime('%I:%M %p'),
        "collection_type": booking.collection_type,
        "address": booking.address,
        "location": {
            "lat": float(booking.location_lat) if booking.location_lat else None,
            "lng": float(booking.location_lng) if booking.location_lng else None
        },
        "status": booking.status,
        "collected_by": booking.collected_by,
        "sample_quality": booking.sample_quality,
        "sample_notes": booking.sample_notes,
        "vial_ids": booking.vial_ids,
        "result_pdf_url": booking.result_pdf_url,
        "verified_by": booking.verified_by,
        "report_remarks": booking.report_remarks,
        "created_at": booking.created_at.strftime('%Y-%m-%d %I:%M %p'),
        "completed_at": booking.completed_at.strftime('%Y-%m-%d %I:%M %p') if booking.completed_at else None
    }



# ==================== ANALYTICS & REPORTS ====================

@router.get("/analytics/dashboard", response_model=dict)
async def get_lab_analytics(
    current_user: User = Depends(get_current_user),
    month: Optional[int] = None,
    year: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """📊 LAB VENDOR DASHBOARD ANALYTICS"""
    lab = db.query(Laboratory).filter(Laboratory.owner_user_id == current_user.id).first()
    
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    
    if not month:
        month = datetime.now().month
    if not year:
        year = datetime.now().year
    
    total_bookings = db.query(LabBooking).filter(
        and_(
            LabBooking.laboratory_id == lab.id,
            extract('month', LabBooking.collection_date) == month,
            extract('year', LabBooking.collection_date) == year
        )
    ).count()
    
    completed = db.query(LabBooking).filter(
        and_(
            LabBooking.laboratory_id == lab.id,
            LabBooking.status == 'completed',
            extract('month', LabBooking.collection_date) == month,
            extract('year', LabBooking.collection_date) == year
        )
    ).count()
    
    revenue = db.query(func.sum(LabTest.price)).join(
        LabBooking, LabBooking.test_id == LabTest.id
    ).filter(
        and_(
            LabBooking.laboratory_id == lab.id,
            LabBooking.status == 'completed',
            extract('month', LabBooking.collection_date) == month,
            extract('year', LabBooking.collection_date) == year
        )
    ).scalar() or 0
    
    pending_reports = db.query(LabBooking).filter(
        and_(
            LabBooking.laboratory_id == lab.id,
            LabBooking.status.in_(['sample_collected', 'processing'])
        )
    ).count()
    
    today_collections = db.query(LabBooking).filter(
        and_(
            LabBooking.laboratory_id == lab.id,
            LabBooking.collection_date == date.today(),
            LabBooking.status == 'scheduled'
        )
    ).count()
    
    top_tests = db.query(
        LabTest.name,
        func.count(LabBooking.id).label('bookings')
    ).join(
        LabBooking, LabBooking.test_id == LabTest.id
    ).filter(
        and_(
            LabBooking.laboratory_id == lab.id,
            extract('month', LabBooking.collection_date) == month,
            extract('year', LabBooking.collection_date) == year
        )
    ).group_by(LabTest.name).order_by(desc('bookings')).limit(5).all()
    
    return {
        "period": f"{month}/{year}",
        "total_bookings": total_bookings,
        "completed_tests": completed,
        "pending_reports": pending_reports,
        "today_collections": today_collections,
        "total_revenue": int(revenue),
        "average_test_value": int(revenue / completed) if completed > 0 else 0,
        "total_tests_lifetime": lab.total_tests_completed,
        "rating": float(lab.rating),
        "top_tests": [
            {"name": name, "bookings": int(count)}
            for name, count in top_tests
        ]
    }


@router.get("/schedule/daily", response_model=dict)
async def get_daily_schedule(
    current_user: User = Depends(get_current_user),
    target_date: Optional[date] = None,
    db: Session = Depends(get_db)
):
    """📅 DAILY COLLECTION SCHEDULE"""
    if target_date is None:
        target_date = date.today()
    
    lab = db.query(Laboratory).filter(Laboratory.owner_user_id == current_user.id).first()
    
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    
    bookings = db.query(LabBooking).options(
        joinedload(LabBooking.user),
        joinedload(LabBooking.test)
    ).filter(
        and_(
            LabBooking.laboratory_id == lab.id,
            LabBooking.collection_date == target_date,
            LabBooking.collection_type == 'home',
            LabBooking.status == 'scheduled'
        )
    ).order_by(LabBooking.collection_time).all()
    
    route = []
    for booking in bookings:
        route.append({
            "booking_id": booking.id,
            "time": booking.collection_time.strftime('%I:%M %p'),
            "patient_name": booking.user.name,
            "patient_phone": booking.user.phone,
            "address": booking.address,
            "test_name": booking.test.name,
            "fasting_required": booking.test.fasting_required,
            "special_instructions": booking.test.special_instructions,
            "location": {
                "lat": float(booking.location_lat) if booking.location_lat else None,
                "lng": float(booking.location_lng) if booking.location_lng else None
            }
        })
    
    return {
        "date": str(target_date),
        "total_collections": len(route),
        "route": route,
        "estimated_duration_hours": len(route) * 0.5
    }


@router.get("/alerts/overdue", response_model=dict)
async def get_overdue_reports(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """🚨 OVERDUE REPORTS ALERT"""
    lab = db.query(Laboratory).filter(Laboratory.owner_user_id == current_user.id).first()
    
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    
    overdue_reports = check_overdue_reports(lab.id, db)
    
    return {
        "total_overdue": len(overdue_reports),
        "overdue_reports": overdue_reports,
        "alert_level": "critical" if len(overdue_reports) > 5 else "warning" if len(overdue_reports) > 0 else "normal"
    }


@router.get("/reports/revenue", response_model=dict)
async def get_revenue_report(
    start_date: date,
    end_date: date,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """💰 REVENUE REPORT"""
    lab = db.query(Laboratory).filter(Laboratory.owner_user_id == current_user.id).first()
    
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    
    revenue = db.query(func.sum(LabTest.price)).join(
        LabBooking, LabBooking.test_id == LabTest.id
    ).filter(
        and_(
            LabBooking.laboratory_id == lab.id,
            LabBooking.status == 'completed',
            LabBooking.collection_date >= start_date,
            LabBooking.collection_date <= end_date
        )
    ).scalar() or 0
    
    total_tests = db.query(LabBooking).filter(
        and_(
            LabBooking.laboratory_id == lab.id,
            LabBooking.collection_date >= start_date,
            LabBooking.collection_date <= end_date
        )
    ).count()
    
    completed = db.query(LabBooking).filter(
        and_(
            LabBooking.laboratory_id == lab.id,
            LabBooking.status == 'completed',
            LabBooking.collection_date >= start_date,
            LabBooking.collection_date <= end_date
        )
    ).count()
    
    daily_revenue = db.query(
        LabBooking.collection_date,
        func.sum(LabTest.price).label('revenue'),
        func.count(LabBooking.id).label('tests')
    ).join(
        LabTest, LabBooking.test_id == LabTest.id
    ).filter(
        and_(
            LabBooking.laboratory_id == lab.id,
            LabBooking.status == 'completed',
            LabBooking.collection_date >= start_date,
            LabBooking.collection_date <= end_date
        )
    ).group_by(LabBooking.collection_date).all()
    
    return {
        "period": {
            "start": str(start_date),
            "end": str(end_date)
        },
        "total_revenue": float(revenue),
        "total_tests": total_tests,
        "completed_tests": completed,
        "average_test_value": float(revenue / completed) if completed > 0 else 0,
        "daily_breakdown": [
            {
                "date": str(row.collection_date),
                "revenue": float(row.revenue),
                "tests": int(row.tests)
            }
            for row in daily_revenue
        ]
    }


@router.get("/stats/performance", response_model=dict)
async def get_performance_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """📊 LAB PERFORMANCE STATISTICS"""
    lab = db.query(Laboratory).filter(Laboratory.owner_user_id == current_user.id).first()
    
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    
    stats = calculate_lab_stats(lab.id, db)
    popular_tests = get_test_popularity(lab.id, db, limit=10)
    
    return {
        "overall_stats": stats,
        "popular_tests": popular_tests,
        "rating": float(lab.rating),
        "total_tests_lifetime": lab.total_tests_completed
    }
