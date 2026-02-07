import sys
from pathlib import Path

# Add backend directory to path for imports to work when running directly
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from fastapi import APIRouter, Depends, HTTPException,UploadFile, File
from sqlalchemy.orm import Session, joinedload
from database.connection import get_db
from sqlalchemy import and_,func,desc,extract
from database.models import (
    User, Medicine,Order,OrderItem,Prescription,
    AuditLog,Notification
)
from api.auth import get_current_user
from pydantic import BaseModel, Field, EmailStr, model_validator
from typing import List, Optional, Literal
from datetime import datetime ,time, date,timedelta, timezone
import secrets
import os
router = APIRouter(
    prefix="/api/pharmacy_vendor",
    tags = ["Pharmacy Vendor"]
)
#============================== Pharmacy Vendor Models ========================#
class PharmacyRegisterationRequest(BaseModel):
    pharmacy : str = Field(..., min_length=5, max_length=100)
    license_number : str = Field(..., min_length=5, max_length=50)
    address : str = Field(..., min_length=10, max_length=500)
    phone : str = Field(..., min_length=10, max_length=15)
    email : EmailStr = Field(..., description="official email of the pharmacy")
    city : str 
    state : str
    pincode : str = Field(..., min_length=6, max_length=6)
    password : str = Field(..., min_length=8, max_length=24)
    location_lat : Optional[float] = None
    location_lng : Optional[float] = None
    owner_name : str 
    gstin : Optional[str] = Field(None, min_length=15, max_length=15)
    drug_license : str
    operating_hours : dict = Field(
        default={
            "mon": "9:00-21:00", "tue": "9:00-21:00", "wed": "9:00-21:00",
            "thu": "9:00-21:00", "fri": "9:00-21:00", "sat": "10:00-18:00",
            "sun": "10:00-18:00"},
    )
    home_delivery : bool =  Field(default=True)
    minimum_order_amount : float = Field(default=0.0, ge=0.0)
class PharmacyLoginRequest(BaseModel):
    """Pharmacy vendor login credentials"""
    email: EmailStr = Field(..., description="Registered with email what u given us providing during registeration")
    password: str = Field(..., min_length=8, description="Account password")
class PharmacyVendorProfileResponse(BaseModel):
    id : int
    pharmacy : str
    license_number : str
    address : str
    phone : str
    email : EmailStr
    city : str 
    state : str
    pincode : str
    location_lat : Optional[float] = None
    location_lng : Optional[float] = None
    owner_name : str 
    gstin : Optional[str] = None
    drug_license : str
    operating_hours : dict 
    home_delivery : bool 
    minimum_order_amount : float 
    is_active : bool 
    is_approved : bool 
    created_at : datetime
    updated_at : datetime
class addMedicineRequest(BaseModel):
    """Model for adding a new medicine"""
    name : str = Field(..., min_length=2, max_length=200)
    generic_name : Optional[str] = Field(None, max_length=200)
    category : str = Field(..., description=" Pain relief, Antibiotics, Antiseptics, Vitamins, Supplements, etc.", max_length=100)
    description : Optional[str] = Field(None, max_length=500)
    manufacturer : str = Field(..., max_length=100)
    composition : Optional[str] = Field(None, max_length=300)
    """Pricing"""
    mrp : float = Field(..., gt=0.0)
    selling_price : float = Field(..., gt=0.0)
    discount_percentage: Optional[float] = Field(default=0.0, ge=0.0, le=100.0)


    #inventory
    stock_quantity : int = Field(..., ge=0)
    reorder_level : int = Field(default=10, ge=0)
    #classification
    prescription_required : bool 
    is_controlled_substance : bool = False
    schedule_type : Optional[str] = Field(None, description="e.g., Schedule H, Schedule X, etc.", max_length=50)

    #storage
    storage_conditions : Optional[str] = Field(None, max_length=200)
    expiry_date: date = Field(...)
    batch_number : Optional[str] = Field(None, max_length=100)
    medicine_image : Optional[str] = None  # URL or path to the image

    #Alteenative medicine
    alternative_medicines_ids: List[int] = Field(default_factory=list)

 # List of medicine IDs
   
    @model_validator(mode='after')
    def check_pricing(self):
        # Logic: Selling price hamesha MRP se kam ya barabar honi chahiye
        if self.selling_price > self.mrp:
            raise ValueError(f"Selling price ({self.selling_price}) cannot be greater than MRP ({self.mrp})")
        
        # Bonus Logic: Agar discount 0 hai par selling_price MRP se kam hai, toh % calculate kar lo
        if self.discount_percentage == 0 and self.selling_price < self.mrp:
            self.discount_percentage = round(((self.mrp - self.selling_price) / self.mrp) * 100, 2)
            
        return self
class UpdateMedicineRequest(BaseModel):
    """Model for updating an existing medicine"""
    name: Optional[str] = Field(None, min_length=2, max_length=200)
    generic_name : Optional[str] = Field(None, max_length=200)
    category : Optional[str] = Field(None, description=" Pain relief, Antibiotics, Antiseptics, Vitamins, Supplements, etc.", max_length=100)
    description : Optional[str] = Field(None, max_length=500)
    manufacturer : Optional[str] = Field(None, max_length=100)
    composition : Optional[str] = Field(None, max_length=300)
    medicine_id: int = Field(..., description="ID of the medicine to update")
    """Pricing"""
    mrp : Optional[float] = Field(None, gt=0.0)
    selling_price : Optional[float] = Field(None, gt=0.0)
    discount_percentage: Optional[float] = Field(None, ge=0.0, le=100.0)


    #inventory
    stock_quantity : Optional[int] = Field(None, ge=0)
    reorder_level : Optional[int] = Field(None, ge=0)
    #classification
    prescription_required : Optional[bool] = None
    is_controlled_substance : Optional[bool] = None
    schedule_type : Optional[str] = Field(None, description="e.g., Schedule H, Schedule X, etc.", max_length=50)

    #storage
    storage_conditions : Optional[str] = Field(None, max_length=200)
    expiry_date: Optional[date] = Field(None)
    batch_number : Optional[str] = Field(None, max_length=100)
    medicine_image : Optional[str] = None  # URL or path to the image

    #Alteenative medicine
    alternative_medicines_ids: Optional[List[int]] = None  # List of medicine IDs
   
    @model_validator(mode='after')
    def check_pricing(self):
        # Logic: Selling price hamesha MRP se kam ya barabar honi chahiye
        if self.mrp is not None and self.selling_price is not None:
            if self.selling_price > self.mrp:
                raise ValueError(f"Selling price ({self.selling_price}) cannot be greater than MRP ({self.mrp})")
        
        # Bonus Logic: Agar discount 0 hai par selling_price MRP se kam hai, toh % calculate kar lo
        if self.mrp is not None and self.selling_price is not None and self.discount_percentage is None:
            if self.selling_price < self.mrp:
                self.discount_percentage = round(((self.mrp - self.selling_price) / self.mrp) * 100, 2)
        return self
class UpdateOrderStatusRequest(BaseModel):
    order_id : int
    new_status: Literal["Pending", "Processing", "Shipped", "Delivered", "Cancelled"]
    tracking_number : Optional[str] = Field(None, description="Tracking number if applicable")
    estimated_delivery_date : Optional[datetime] = Field(None, description="Estimated delivery date if applicable")
    notes: Optional[str] = Field(None, description="Additional notes regarding the status update")
class PharmacyOrderResponse(BaseModel):
    id : int
    user_id : int
    pharmacy_vendor_id : int
    total_amount : float
    order_status : str
    placed_at : datetime
    updated_at : datetime
    delivery_address : str
    contact_number : str
    prescription_id : Optional[int] = None
    tracking_number : Optional[str] = None
    estimated_delivery_date : Optional[datetime] = None
    notes : Optional[str] = None
    items : List[dict]  # List of order items with details
    @model_validator(mode='after')
    def compute_total_amount(self):
        total = 0.0
        if self.items:
            for item in self.items:
                # .get() use karein taki agar key na ho to 0 le le, crash na ho
                price = item.get('selling_price', 0.0)
                qty = item.get('quantity', 0)
                total += price * qty
        self.total_amount = total
        return self
class ADDStockRequest(BaseModel):
    medicine_id : int
    quantity : int = Field(..., gt=0)
    batch_number : str = Field(..., max_length=100)
    expiry_date : date = Field(...)
    supplier_name : Optional[str] = Field(None, max_length=100)
    purchase_price_per_unit : float = Field(..., gt=0.0)
    purchase_date : datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    invoice_number : Optional[str] = Field(None, max_length=100)

    # ==================== HELPER FUNCTIONS ====================

def generate_pharmacy_id() -> str:
    """Unique ID for internal tracking (e.g., PHR5421)"""
    return f"PHR{secrets.randbelow(9000) + 1000}"

def calculate_profit_margin(purchase_price: float, selling_price: float) -> float:
    """Profit margin calculate karne ke liye (Ab float support karega)"""
    if purchase_price <= 0: return 0.0 # Division by zero se bachne ke liye
    return round(((selling_price - purchase_price) / purchase_price) * 100, 2)

def check_stock_alerts(pharmacy_id: int, db: Session) -> List[dict]:
    """Medicines jo khatam hone wali hain unki list"""
    low_stock = db.query(Medicine).filter(
        and_(
            Medicine.pharmacy_vendor_id == pharmacy_id, # DB model column name check karein
            Medicine.stock_quantity <= Medicine.reorder_level
        )
    ).all()
    
    return [
        {
            "medicine_id": med.id,
            "name": med.name,
            "current_stock": med.stock_quantity,
            "reorder_level": med.reorder_level,
            "deficit": max(0, med.reorder_level - med.stock_quantity)
        }
        for med in low_stock
    ]

def send_vendor_notification(
    db: Session,
    vendor_user_id: int,
    title: str,
    message: str,
    notification_type: str = "vendor_alert"
):
    """Vendor ko dashboard par alert bhejne ke liye"""
    notification = Notification(
        user_id=vendor_user_id,
        type=notification_type,
        title=title,
        message=message,
        created_at=datetime.now(timezone.utc) # Time hamesha add karein
    )
    db.add(notification)
    try:
        db.commit()
    except Exception:
        db.rollback() # Error aaye toh database safe rahe
    return notification 
# ==================== END OF HELPERS ====================
# ==================== ROUTES WILL BE ADDED BELOW ====================
@router.post("/register", response_model=dict)
async def register_pharmacy(
    request: PharmacyRegisterationRequest, 
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    from database.models import Pharmacy
    
    # 1. Pehle check karo user ki pharmacy hai ya nahi
    existing = db.query(Pharmacy).filter(Pharmacy.owner_user_id == current_user.id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Pharmacy already registered")

    pharmacy_id = generate_pharmacy_id()
    
    # 2. Map correctly as per your Pydantic Class fields
    new_pharmacy = Pharmacy(
        id=pharmacy_id,
        owner_user_id=current_user.id,
        name=request.pharmacy,             # 'pharmacy' field in your class
        license_number=request.license_number,
        drug_license_number=request.drug_license, # 'drug_license' in your class
        address=request.address,
        city=request.city,
        state=request.state,
        pincode=request.pincode,
        location_lat=request.location_lat,
        location_lng=request.location_lng,
        owner_name=request.owner_name,
        gstin=request.gstin,
        operating_hours=request.operating_hours,
        home_delivery_available=request.home_delivery, # 'home_delivery' in your class
        minimum_order_amount=request.minimum_order_amount,
        is_verified=False,
        is_active=True
    )
    
    db.add(new_pharmacy)

    # 3. Log it (Single Transaction)
    audit = AuditLog(
        user_id=current_user.id,
        action="PHARMACY_REGISTERED",
        entity_type="pharmacy",
        entity_id=pharmacy_id,
        details={"email": request.email}
    )
    db.add(audit)

    try:
        db.commit()
        db.refresh(new_pharmacy)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Database registration failed")

    return {"status": "success", "pharmacy_id": pharmacy_id}
# 1. ✅ LOGIN ENDPOINT (Missing tha!)
@router.post("/login", response_model=dict)
async def pharmacy_vendor_login(
    request: PharmacyLoginRequest,
    db: Session = Depends(get_db)
):
    """
    🔐 PHARMACY VENDOR LOGIN
    
    Returns JWT token for vendor authentication
    """
    from database.models import Pharmacy
    import bcrypt
    from .auth import create_access_token, create_refresh_token
    
    # Find pharmacy by email
    pharmacy = db.query(Pharmacy).filter(
        Pharmacy.email == request.email
    ).first()
    
    if not pharmacy:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )
    
    # Verify password (assuming password stored in pharmacy table)
    # Note: Add password field to Pharmacy model if not exists
    if not hasattr(pharmacy, 'password_hash'):
        raise HTTPException(
            status_code=500,
            detail="Password authentication not configured"
        )
    
    # Verify password
    if not bcrypt.checkpw(request.password.encode(), pharmacy.password_hash.encode()):
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )
    
    # Check if approved
    if not pharmacy.is_approved:
        raise HTTPException(
            status_code=403,
            detail="Pharmacy not yet approved by admin. Please wait for verification."
        )
    
    # Get user
    user = db.query(User).filter(User.id == pharmacy.owner_user_id).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Generate tokens
    access_token = create_access_token(data={
        "user_id": user.id,
        "pharmacy_id": pharmacy.id,
        "role": "pharmacy_vendor"
    })
    
    refresh_token = create_refresh_token(data={
        "user_id": user.id,
        "pharmacy_id": pharmacy.id
    })
    
    # Log action
    audit = AuditLog(
        user_id=user.id,
        action="PHARMACY_VENDOR_LOGIN",
        entity_type="pharmacy",
        entity_id=pharmacy.id,
        details={"email": request.email}
    )
    db.add(audit)
    db.commit()
    
    return {
        "status": "success",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "pharmacy": {
            "id": pharmacy.id,
            "name": pharmacy.name,
            "is_approved": pharmacy.is_approved,
            "is_active": pharmacy.is_active
        }
    }
# 2. ✅ GET VENDOR PROFILE
@router.get("/profile", response_model=PharmacyVendorProfileResponse)
async def get_vendor_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    👤 GET PHARMACY VENDOR PROFILE
    """
    from database.models import Pharmacy
    
    pharmacy = db.query(Pharmacy).filter(
        Pharmacy.owner_user_id == current_user.id
    ).first()
    
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")
    
    return PharmacyVendorProfileResponse(
        id=pharmacy.id,
        pharmacy=pharmacy.name,
        license_number=pharmacy.license_number,
        address=pharmacy.address,
        phone=pharmacy.phone,
        email=pharmacy.email,
        city=pharmacy.city,
        state=pharmacy.state,
        pincode=pharmacy.pincode,
        location_lat=pharmacy.location_lat,
        location_lng=pharmacy.location_lng,
        owner_name=pharmacy.owner_name,
        gstin=pharmacy.gstin,
        drug_license=pharmacy.drug_license_number,
        operating_hours=pharmacy.operating_hours,
        home_delivery=pharmacy.home_delivery_available,
        minimum_order_amount=pharmacy.minimum_order_amount,
        is_active=pharmacy.is_active,
        is_approved=pharmacy.is_verified,
        created_at=pharmacy.created_at,
        updated_at=pharmacy.updated_at
    )
# 3. ✅ UPDATE VENDOR PROFILE
@router.put("/profile/update", response_model=dict)
async def update_vendor_profile(
    operating_hours: Optional[dict] = None,
    home_delivery: Optional[bool] = None,
    minimum_order_amount: Optional[float] = None,
    phone: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    ✏️ UPDATE PHARMACY PROFILE
    """
    from database.models import Pharmacy
    
    pharmacy = db.query(Pharmacy).filter(
        Pharmacy.owner_user_id == current_user.id
    ).first()
    
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")
    
    # Update fields
    if operating_hours is not None:
        pharmacy.operating_hours = operating_hours
    
    if home_delivery is not None:
        pharmacy.home_delivery_available = home_delivery
    
    if minimum_order_amount is not None:
        pharmacy.minimum_order_amount = minimum_order_amount
    
    if phone is not None:
        pharmacy.phone = phone
    
    pharmacy.updated_at = datetime.now(timezone.utc)
    
    db.commit()
    
    return {
        "status": "success",
        "message": "Profile updated successfully"
    }
# 4. ✅ DELETE MEDICINE
@router.delete("/medicines/{medicine_id}", response_model=dict)
async def delete_medicine(
    medicine_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    🗑️ DELETE MEDICINE (SOFT DELETE)
    """
    from database.models import Pharmacy
    
    pharmacy = db.query(Pharmacy).filter(
        Pharmacy.owner_user_id == current_user.id
    ).first()
    
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")
    
    medicine = db.query(Medicine).filter(
        and_(
            Medicine.id == medicine_id,
            Medicine.pharmacy_id == pharmacy.id
        )
    ).first()
    
    if not medicine:
        raise HTTPException(status_code=404, detail="Medicine not found")
    
    # Soft delete (mark as unavailable)
    medicine.is_available = False
    medicine.updated_at = datetime.now(timezone.utc)
    
    db.commit()
    
    return {
        "status": "success",
        "message": "Medicine removed from inventory"
    }
# 5. ✅ GET MEDICINE DETAILS
@router.get("/medicines/{medicine_id}", response_model=dict)
async def get_medicine_details(
    medicine_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    🔍 GET SINGLE MEDICINE DETAILS
    """
    from database.models import Pharmacy
    
    pharmacy = db.query(Pharmacy).filter(
        Pharmacy.owner_user_id == current_user.id
    ).first()
    
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")
    
    medicine = db.query(Medicine).filter(
        and_(
            Medicine.id == medicine_id,
            Medicine.pharmacy_id == pharmacy.id
        )
    ).first()
    
    if not medicine:
        raise HTTPException(status_code=404, detail="Medicine not found")
    
    return {
        "id": medicine.id,
        "name": medicine.name,
        "generic_name": medicine.generic_name,
        "category": medicine.category,
        "dosage": medicine.dosage,
        "manufacturer": medicine.manufacturer,
        "composition": medicine.composition,
        "description": medicine.description,
        "mrp": medicine.mrp,
        "selling_price": medicine.price,
        "discount_percentage": medicine.discount_percentage,
        "stock_quantity": medicine.stock_quantity,
        "reorder_level": medicine.reorder_level,
        "requires_prescription": medicine.requires_prescription,
        "is_controlled_substance": medicine.is_controlled_substance,
        "schedule_type": medicine.schedule_type,
        "storage_conditions": medicine.storage_conditions,
        "expiry_date": str(medicine.expiry_date) if medicine.expiry_date else None,
        "batch_number": medicine.batch_number,
        "alternatives": medicine.alternatives,
        "is_available": medicine.is_available,
        "created_at": medicine.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": medicine.updated_at.strftime("%Y-%m-%d %H:%M:%S")
    }
# 6. ✅ REDUCE STOCK (When order placed)
@router.post("/medicines/stock/reduce", response_model=dict)
async def reduce_stock(
    medicine_id: int,
    quantity: int,
    order_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    📉 REDUCE STOCK (Automatic on order placement)
    """
    from database.models import Pharmacy, StockEntry
    
    pharmacy = db.query(Pharmacy).filter(
        Pharmacy.owner_user_id == current_user.id
    ).first()
    
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")
    
    medicine = db.query(Medicine).filter(
        and_(
            Medicine.id == medicine_id,
            Medicine.pharmacy_id == pharmacy.id
        )
    ).first()
    
    if not medicine:
        raise HTTPException(status_code=404, detail="Medicine not found")
    
    # Check stock availability
    if medicine.stock_quantity < quantity:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient stock. Available: {medicine.stock_quantity}, Required: {quantity}"
        )
    
    # Create stock entry (outgoing)
    stock_entry = StockEntry(
        medicine_id=medicine_id,
        pharmacy_id=pharmacy.id,
        entry_type="sale",
        quantity=-quantity,  # Negative for outgoing
        reference_id=str(order_id),
        created_at=datetime.now(timezone.utc)
    )
    db.add(stock_entry)
    
    # Reduce stock
    medicine.stock_quantity -= quantity
    medicine.updated_at = datetime.now(timezone.utc)
    
    db.commit()
    
    # Check if reorder needed
    if medicine.stock_quantity <= medicine.reorder_level:
        send_vendor_notification(
            db=db,
            vendor_user_id=current_user.id,
            title="Low Stock Alert",
            message=f"{medicine.name} stock is low. Current: {medicine.stock_quantity}, Reorder level: {medicine.reorder_level}",
            notification_type="stock_alert"
        )
    
    return {
        "status": "success",
        "medicine_name": medicine.name,
        "quantity_reduced": quantity,
        "remaining_stock": medicine.stock_quantity,
        "reorder_needed": medicine.stock_quantity <= medicine.reorder_level
    }
# 7. ✅ GET ORDER DETAILS
@router.get("/orders/{order_id}", response_model=PharmacyOrderResponse)
async def get_order_details(
    order_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    📦 GET SINGLE ORDER DETAILS
    """
    from database.models import Pharmacy
    
    pharmacy = db.query(Pharmacy).filter(
        Pharmacy.owner_user_id == current_user.id
    ).first()
    
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")
    
    order = db.query(Order).options(
        joinedload(Order.items).joinedload(OrderItem.medicine),
        joinedload(Order.user),
        joinedload(Order.prescription)
    ).filter(
        and_(
            Order.id == order_id,
            Order.pharmacy_id == pharmacy.id
        )
    ).first()
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    items = [
        {
            "medicine_id": item.medicine_id,
            "medicine_name": item.medicine.name,
            "quantity": item.quantity,
            "selling_price": item.price,
            "total": item.price * item.quantity
        }
        for item in order.items
    ]
    
    return PharmacyOrderResponse(
        id=order.id,
        user_id=order.user_id,
        pharmacy_vendor_id=pharmacy.id,
        total_amount=order.total_amount,
        order_status=order.order_status,
        placed_at=order.created_at,
        updated_at=order.updated_at,
        delivery_address=order.delivery_address,
        contact_number=order.user.phone if order.user else "N/A",
        prescription_id=order.prescription_id,
        tracking_number=order.tracking_number if hasattr(order, 'tracking_number') else None,
        estimated_delivery_date=order.estimated_delivery if hasattr(order, 'estimated_delivery') else None,
        notes=order.notes if hasattr(order, 'notes') else None,
        items=items
    )
# 8. ✅ CANCEL ORDER
@router.post("/orders/{order_id}/cancel", response_model=dict)
async def cancel_order(
    order_id: int,
    reason: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    ❌ CANCEL ORDER (Vendor side)
    
    Restores stock if already reduced
    """
    from database.models import Pharmacy
    
    pharmacy = db.query(Pharmacy).filter(
        Pharmacy.owner_user_id == current_user.id
    ).first()
    
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")
    
    order = db.query(Order).options(
        joinedload(Order.items).joinedload(OrderItem.medicine)
    ).filter(
        and_(
            Order.id == order_id,
            Order.pharmacy_id == pharmacy.id
        )
    ).first()
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Check if can cancel
    if order.order_status in ['delivered', 'cancelled']:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel order with status: {order.order_status}"
        )
    
    # Restore stock
    for item in order.items:
        medicine = item.medicine
        medicine.stock_quantity += item.quantity
    
    # Update order
    order.order_status = 'cancelled'
    order.updated_at = datetime.now(timezone.utc)
    
    db.commit()
    
    # Notify customer
    send_vendor_notification(
        db=db,
        vendor_user_id=order.user_id,
        title="Order Cancelled",
        message=f"Your order #{order_id} has been cancelled by pharmacy. Reason: {reason}",
        notification_type="order_cancelled"
    )
    
    return {
        "status": "success",
        "order_id": order_id,
        "message": "Order cancelled successfully",
        "refund_initiated": order.payment_status == "paid"
    }


# 9. ✅ GET REVENUE REPORT
@router.get("/reports/revenue", response_model=dict)
async def get_revenue_report(
    start_date: date,
    end_date: date,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    💰 REVENUE REPORT (Date Range)
    """
    from database.models import Pharmacy
    
    pharmacy = db.query(Pharmacy).filter(
        Pharmacy.owner_user_id == current_user.id
    ).first()
    
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")
    
    # Total revenue
    revenue = db.query(func.sum(Order.total_amount)).filter(
        and_(
            Order.pharmacy_id == pharmacy.id,
            Order.payment_status == 'paid',
            Order.created_at >= start_date,
            Order.created_at <= end_date
        )
    ).scalar() or 0
    
    # Total orders
    total_orders = db.query(Order).filter(
        and_(
            Order.pharmacy_id == pharmacy.id,
            Order.created_at >= start_date,
            Order.created_at <= end_date
        )
    ).count()
    
    # Completed orders
    completed = db.query(Order).filter(
        and_(
            Order.pharmacy_id == pharmacy.id,
            Order.order_status == 'delivered',
            Order.created_at >= start_date,
            Order.created_at <= end_date
        )
    ).count()
    
    # Day-wise breakdown
    daily_revenue = db.query(
        func.date(Order.created_at).label('date'),
        func.sum(Order.total_amount).label('revenue'),
        func.count(Order.id).label('orders')
    ).filter(
        and_(
            Order.pharmacy_id == pharmacy.id,
            Order.payment_status == 'paid',
            Order.created_at >= start_date,
            Order.created_at <= end_date
        )
    ).group_by(func.date(Order.created_at)).all()
    
    return {
        "period": {
            "start": str(start_date),
            "end": str(end_date)
        },
        "total_revenue": float(revenue),
        "total_orders": total_orders,
        "completed_orders": completed,
        "average_order_value": float(revenue / total_orders) if total_orders > 0 else 0,
        "daily_breakdown": [
            {
                "date": str(row.date),
                "revenue": float(row.revenue),
                "orders": int(row.orders)
            }
            for row in daily_revenue
        ]
    }


# 10. ✅ GET EXPIRING MEDICINES
@router.get("/medicines/expiring", response_model=dict)
async def get_expiring_medicines(
    days: int = 90,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    ⏰ GET MEDICINES EXPIRING SOON
    """
    from database.models import Pharmacy
    
    pharmacy = db.query(Pharmacy).filter(
        Pharmacy.owner_user_id == current_user.id
    ).first()
    
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")
    
    expiry_threshold = date.today() + timedelta(days=days)
    
    medicines = db.query(Medicine).filter(
        and_(
            Medicine.pharmacy_id == pharmacy.id,
            Medicine.expiry_date.isnot(None),
            Medicine.expiry_date <= expiry_threshold,
            Medicine.expiry_date >= date.today()
        )
    ).order_by(Medicine.expiry_date).all()
    
    return {
        "threshold_days": days,
        "total": len(medicines),
        "medicines": [
            {
                "id": med.id,
                "name": med.name,
                "batch_number": med.batch_number,
                "expiry_date": str(med.expiry_date),
                "days_remaining": (med.expiry_date - date.today()).days,
                "stock": med.stock_quantity,
                "estimated_loss": med.stock_quantity * med.price
            }
            for med in medicines
        ]
    }


# 11. ✅ COMPLETE STOCK ALERTS (Missing code completion)
@router.get("/alerts/stock", response_model=dict)
async def get_stock_alerts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    🚨 STOCK ALERTS (Low Stock & Expiring Soon)
    """
    from database.models import Pharmacy
    
    pharmacy = db.query(Pharmacy).filter(
        Pharmacy.owner_user_id == current_user.id
    ).first()
    
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")
    
    # Low stock
    low_stock = check_stock_alerts(pharmacy.id, db)
    
    # Expiring soon (within 3 months)
    expiring_soon = db.query(Medicine).filter(
        and_(
            Medicine.pharmacy_id == pharmacy.id,
            Medicine.expiry_date.isnot(None),
            Medicine.expiry_date <= date.today() + timedelta(days=90),
            Medicine.expiry_date >= date.today()
        )
    ).all()
    
    # Already expired
    expired = db.query(Medicine).filter(
        and_(
            Medicine.pharmacy_id == pharmacy.id,
            Medicine.expiry_date.isnot(None),
            Medicine.expiry_date < date.today()
        )
    ).all()
    
    return {
        "low_stock": low_stock,
        "low_stock_count": len(low_stock),
        "expiring_soon": [
            {
                "medicine_id": med.id,
                "name": med.name,
                "batch_number": med.batch_number,
                "expiry_date": str(med.expiry_date),
                "days_remaining": (med.expiry_date - date.today()).days,
                "stock": med.stock_quantity,
                "action": "Plan discount sale or return to supplier"
            }
            for med in expiring_soon
        ],
        "expiring_count": len(expiring_soon),
        "expired": [
            {
                "medicine_id": med.id,
                "name": med.name,
                "batch_number": med.batch_number,
                "expiry_date": str(med.expiry_date),
                "stock": med.stock_quantity,
                "days_expired": (date.today() - med.expiry_date).days,
                "action_required": "Remove from inventory immediately"
            }
            for med in expired
        ],
        "expired_count": len(expired),
        "total_alerts": len(low_stock) + len(expiring_soon) + len(expired)
    }
