import sys
from pathlib import Path

# Add backend directory to path for imports to work when running directly
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, func
from database.connection import get_db
from database.models import User, Medicine, Order, OrderItem, Prescription, Notification, AuditLog
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, date
import secrets

router = APIRouter(prefix="/api/pharmacy", tags=["Pharmacy"])

# ==================== PYDANTIC MODELS ====================

class MedicineSearchRequest(BaseModel):
    query: Optional[str] = Field(None, description="Medicine name to search")
    category: Optional[str] = Field(None, description="Category filter")
    requires_prescription: Optional[bool] = Field(None, description="Filter by prescription requirement")
    in_stock_only: bool = Field(True, description="Show only in-stock medicines")
    sort_by: str = Field("relevance", description="relevance/price/name")
    page: int = Field(1, ge=1)
    limit: int = Field(20, ge=1, le=50)

class MedicineResponse(BaseModel):
    id: int
    name: str
    generic_name: Optional[str]
    category: str
    dosage: str
    manufacturer: str
    price: int
    in_stock: bool
    stock_quantity: int
    requires_prescription: bool
    description: Optional[str]
    alternatives: Optional[List[dict]]
    rating: float

class CartItem(BaseModel):
    medicine_id: int
    quantity: int

class CreateOrderRequest(BaseModel):
    user_id: int
    items: List[CartItem]
    delivery_address: str
    delivery_type: str = Field("standard", description="standard/express")
    prescription_image_url: Optional[str] = None

class OrderResponse(BaseModel):
    order_id: str
    status: str
    total_amount: int
    delivery_type: str
    estimated_delivery: str
    items: List[dict]

# ==================== HELPER FUNCTIONS ====================

def generate_order_id() -> str:
    """Generate unique order ID like ORD123456"""
    return f"ORD{secrets.randbelow(900000) + 100000}"

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

def check_stock_and_get_alternatives(db: Session, medicine: Medicine) -> dict:
    """
    Check if medicine is in stock, if not return alternatives
    """
    if medicine.stock_quantity > 0:
        return {
            "in_stock": True,
            "alternatives": None
        }
    
    # Medicine out of stock - find alternatives
    alternatives = []
    
    if medicine.alternatives:
        # Get alternative medicines from stored IDs
        alt_ids = medicine.alternatives  # JSON array of IDs
        alt_medicines = db.query(Medicine).filter(
            and_(
                Medicine.id.in_(alt_ids),
                Medicine.stock_quantity > 0
            )
        ).all()
        
        for alt in alt_medicines:
            alternatives.append({
                "id": alt.id,
                "name": alt.name,
                "price": alt.price,
                "in_stock": True,
                "price_difference": alt.price - medicine.price
            })
    
    # If no pre-defined alternatives, find by same category/generic name
    if not alternatives:
        alt_medicines = db.query(Medicine).filter(
            and_(
                or_(
                    Medicine.generic_name == medicine.generic_name,
                    Medicine.category == medicine.category
                ),
                Medicine.id != medicine.id,
                Medicine.stock_quantity > 0
            )
        ).limit(3).all()
        
        for alt in alt_medicines:
            alternatives.append({
                "id": alt.id,
                "name": alt.name,
                "price": alt.price,
                "in_stock": True,
                "price_difference": alt.price - medicine.price
            })
    
    return {
        "in_stock": False,
        "alternatives": alternatives
    }

# ==================== API ENDPOINTS ====================

@router.get("/medicines/search", response_model=dict)
async def search_medicines(
    query: Optional[str] = Query(None, description="Medicine name"),
    category: Optional[str] = Query(None, description="Category filter"),
    requires_prescription: Optional[bool] = Query(None),
    in_stock_only: bool = Query(True),
    sort_by: str = Query("relevance", description="relevance/price/name"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db)
):
    """
    STEP 2 & 3: Search medicines with filters
    
    Features:
    - Text search by name
    - Category filter
    - Stock status filter
    - Prescription filter
    - Alternatives for out-of-stock items
    """
    
    # Base query
    base_query = db.query(Medicine)
    
    # Text search
    if query:
        search_term = f"%{query}%"
        base_query = base_query.filter(
            or_(
                Medicine.name.ilike(search_term),
                Medicine.generic_name.ilike(search_term)
            )
        )
    
    # Category filter
    if category:
        base_query = base_query.filter(Medicine.category == category)
    
    # Prescription filter
    if requires_prescription is not None:
        base_query = base_query.filter(
            Medicine.requires_prescription == requires_prescription
        )
    
    # Stock filter
    if in_stock_only:
        base_query = base_query.filter(Medicine.stock_quantity > 0)
    
    # Apply sorting
    if sort_by == "price":
        base_query = base_query.order_by(Medicine.price.asc())
    elif sort_by == "name":
        base_query = base_query.order_by(Medicine.name.asc())
    else:  # relevance (default)
        if query:
            # Prioritize exact name matches
            base_query = base_query.order_by(
                func.lower(Medicine.name).like(query.lower()).desc(),
                Medicine.name.asc()
            )
    
    # Get total count
    total = base_query.count()
    
    # Apply pagination
    start_idx = (page - 1) * limit
    medicines = base_query.offset(start_idx).limit(limit).all()
    
    # Format results with stock status and alternatives
    results = []
    for medicine in medicines:
        stock_info = check_stock_and_get_alternatives(db, medicine)
        
        results.append({
            "id": medicine.id,
            "name": medicine.name,
            "generic_name": medicine.generic_name,
            "category": medicine.category,
            "dosage": medicine.dosage,
            "manufacturer": medicine.manufacturer,
            "price": medicine.price,
            "in_stock": stock_info["in_stock"],
            "stock_quantity": medicine.stock_quantity,
            "requires_prescription": medicine.requires_prescription,
            "description": medicine.description,
            "alternatives": stock_info["alternatives"],
            "rating": 4.5  # TODO: Calculate from reviews
        })
    
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "medicines": results,
        "message": f"Found {total} medicines" if query else "Browse all medicines"
    }


@router.get("/medicines/categories", response_model=dict)
async def get_medicine_categories(db: Session = Depends(get_db)):
    """
    Get all available medicine categories
    
    Used for category browsing
    """
    
    categories = db.query(
        Medicine.category,
        func.count(Medicine.id).label('count')
    ).filter(
        Medicine.stock_quantity > 0
    ).group_by(
        Medicine.category
    ).all()
    
    category_list = [
        {
            "name": cat,
            "count": count,
            "icon": {
                "Pain Relief": "💊",
                "Fever": "🤒",
                "Cold & Cough": "🤧",
                "Antibiotics": "💉",
                "Vitamins": "🧴",
                "Diabetes": "💉",
                "Heart": "❤️",
                "Stomach": "🔴",
                "Skin Care": "🧴"
            }.get(cat, "💊")
        }
        for cat, count in categories
    ]
    
    return {
        "categories": category_list,
        "total": len(category_list)
    }


@router.get("/medicines/{medicine_id}", response_model=dict)
async def get_medicine_details(
    medicine_id: int,
    db: Session = Depends(get_db)
):
    """
    Get detailed information about a specific medicine
    """
    
    medicine = db.query(Medicine).filter(Medicine.id == medicine_id).first()
    
    if not medicine:
        raise HTTPException(status_code=404, detail="Medicine not found")
    
    stock_info = check_stock_and_get_alternatives(db, medicine)
    
    return {
        "id": medicine.id,
        "name": medicine.name,
        "generic_name": medicine.generic_name,
        "category": medicine.category,
        "dosage": medicine.dosage,
        "manufacturer": medicine.manufacturer,
        "price": medicine.price,
        "in_stock": stock_info["in_stock"],
        "stock_quantity": medicine.stock_quantity,
        "requires_prescription": medicine.requires_prescription,
        "description": medicine.description,
        "alternatives": stock_info["alternatives"],
        "usage": f"For {medicine.category.lower()} relief",
        "side_effects": "Consult doctor for side effects",
        "dosage_instructions": "As prescribed by doctor",
        "rating": 4.5
    }


# ==================== API ENDPOINTS ====================

@router.post("/orders/create", response_model=OrderResponse)
async def create_order(
    request: CreateOrderRequest,
    db: Session = Depends(get_db)
):
    """
    STEP 5: Create medicine order (Optimized with transaction lock)
    
    Validates:
    - Stock availability (with row lock)
    - Prescription requirement
    - User existence
    Creates:
    - Order record
    - Order items
    - Reduces stock securely
    - Sends notifications
    """
    
    # Verify user exists
    user = db.query(User).filter(User.id == request.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Validate items and calculate total
    total_amount = 0
    order_items_data = []
    requires_prescription = False
    
    # We lock the entire transaction context using a 'try...except...finally' block with rollback
    try:
        # Loop through items to validate and prepare data
        for item in request.items:
            # Get medicine AND LOCK THE ROW FOR UPDATE (Prevents race condition)
            medicine = db.query(Medicine).with_for_update().filter(Medicine.id == item.medicine_id).first()
            
            if not medicine:
                raise HTTPException(
                    status_code=404,
                    detail=f"Medicine with ID {item.medicine_id} not found"
                )
            
            # Check stock
            if medicine.stock_quantity < item.quantity:
                # If stock is insufficient for ANY item, the whole transaction will rollback
                raise HTTPException(
                    status_code=400,
                    detail=f"{medicine.name} is out of stock or insufficient quantity available"
                )
            
            # Check prescription requirement
            if medicine.requires_prescription:
                requires_prescription = True
                if not request.prescription_image_url:
                    raise HTTPException(
                        status_code=400,
                        detail=f"{medicine.name} requires prescription. Please upload prescription."
                    )
            
            # Calculate item total
            item_total = medicine.price * item.quantity
            total_amount += item_total
            
            order_items_data.append({
                "medicine": medicine,
                "quantity": item.quantity,
                "price": medicine.price,
                "item_total": item_total
            })
        
        # Add delivery charges
        delivery_charge = 50 if request.delivery_type == "express" else 0
        total_amount += delivery_charge
        
        # --- Database Operations within a safe transaction ---
        
        # Generate order ID
        order_id = generate_order_id()
        
        # Create order
        order = Order(
            id=order_id,
            user_id=request.user_id,
            total_amount=total_amount,
            delivery_address=request.delivery_address,
            delivery_type=request.delivery_type,
            payment_status="pending",
            order_status="processing"
        )
        
        db.add(order)
        
        # Create order items and reduce stock securely
        items_list = []
        for item_data in order_items_data:
            medicine = item_data["medicine"]
            
            # Create order item
            order_item = OrderItem(
                order_id=order_id,
                medicine_id=medicine.id,
                quantity=item_data["quantity"],
                price=item_data["price"]
            )
            db.add(order_item)
            
            # Reduce stock (we already locked the row above, so this is safe)
            medicine.stock_quantity -= item_data["quantity"]
            
            items_list.append({
                "medicine_name": medicine.name,
                "quantity": item_data["quantity"],
                "price": item_data["price"],
                "total": item_data["item_total"]
            })
        
        # Commit transaction (This releases the row locks)
        db.commit()
        db.refresh(order)
        
        # --- Notifications and Logs (After successful commit) ---
        delivery_time = "within 2 hours" if request.delivery_type == "express" else "tomorrow by 6 PM"
        send_notification(
            db=db,
            user_id=request.user_id,
            type="order_confirmed",
            title="Order Confirmed",
            message=f"Your medicine order #{order_id} is confirmed. Delivery: {delivery_time}"
        )
        
        log_action(
            db=db,
            user_id=request.user_id,
            action="ORDER_CREATED",
            entity_type="order",
            entity_id=order_id,
            details={
                "total_amount": total_amount,
                "items_count": len(items_list),
                "delivery_type": request.delivery_type
            }
        )
        
        return {
            "order_id": order_id,
            "status": "confirmed",
            "total_amount": total_amount,
            "delivery_type": request.delivery_type,
            "estimated_delivery": delivery_time,
            "items": items_list
        }

    except HTTPException as e:
        # If any HTTPException was raised during checks (e.g., stock error), rollback the transaction
        db.rollback()
        raise e
    except Exception as e:
        # For any other unexpected error, rollback and raise a generic error
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Order creation failed: {str(e)}")




@router.get("/orders/{order_id}", response_model=dict)
async def get_order_details(
    order_id: str,
    db: Session = Depends(get_db)
):
    """
    Get order details with items
    """
    
    # ✅ JOINEDLOAD TO PREVENT N+1
    order = db.query(Order).options(
        joinedload(Order.items).joinedload(OrderItem.medicine)
    ).filter(Order.id == order_id).first()
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Format items
    items = []
    for item in order.items:
        items.append({
            "medicine_name": item.medicine.name,
            "quantity": item.quantity,
            "price": item.price,
            "total": item.price * item.quantity
        })
    
    return {
        "order_id": order.id,
        "date": order.created_at.strftime("%Y-%m-%d"),
        "time": order.created_at.strftime("%I:%M %p"),
        "status": order.order_status,
        "items": items,
        "total_amount": order.total_amount,
        "delivery_address": order.delivery_address,
        "delivery_type": order.delivery_type,
        "payment_status": order.payment_status,
        "estimated_delivery": "Tomorrow 6 PM" if order.delivery_type == "standard" else "Within 2 hours"
    }


@router.get("/orders/{order_id}/track", response_model=dict)
async def track_order(
    order_id: str,
    db: Session = Depends(get_db)
):
    """
    STEP 7: Track order status in real-time
    """
    
    order = db.query(Order).filter(Order.id == order_id).first()
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Status timeline
    timeline = [
        {
            "status": "placed",
            "label": "Order Placed",
            "completed": True,
            "time": order.created_at.strftime("%I:%M %p")
        },
        {
            "status": "confirmed",
            "label": "Order Confirmed",
            "completed": order.order_status in ["processing", "packed", "shipped", "delivered"],
            "time": "Completed" if order.order_status != "placed" else "Pending"
        },
        {
            "status": "packed",
            "label": "Medicines Packed",
            "completed": order.order_status in ["packed", "shipped", "delivered"],
            "time": "Completed" if order.order_status in ["packed", "shipped", "delivered"] else "Pending"
        },
        {
            "status": "shipped",
            "label": "Out for Delivery",
            "completed": order.order_status in ["shipped", "delivered"],
            "time": "In Progress" if order.order_status == "shipped" else "Pending"
        },
        {
            "status": "delivered",
            "label": "Delivered",
            "completed": order.order_status == "delivered",
            "time": order.delivered_at.strftime("%I:%M %p") if order.delivered_at else "Expected: 6 PM"
        }
    ]
    
    return {
        "order_id": order.id,
        "current_status": order.order_status,
        "timeline": timeline,
        "delivery_partner": {
            "name": "Rajesh Kumar",
            "phone": "+91-98765-12345"
        } if order.order_status == "shipped" else None
    }


@router.get("/orders/user/{user_id}", response_model=dict)
async def get_user_orders(
    user_id: int,
    status: Optional[str] = Query(None, description="Filter by status"),
    db: Session = Depends(get_db)
):
    """
    Get all orders for a user
    """
    
    # ✅ JOINEDLOAD TO PREVENT N+1
    query = db.query(Order).options(
        joinedload(Order.items).joinedload(OrderItem.medicine)
    ).filter(Order.user_id == user_id)
    
    if status:
        query = query.filter(Order.order_status == status)
    
    orders = query.order_by(Order.created_at.desc()).all()
    
    results = []
    for order in orders:
        results.append({
            "order_id": order.id,
            "date": order.created_at.strftime("%Y-%m-%d"),
            "total_amount": order.total_amount,
            "status": order.order_status,
            "items_count": len(order.items),
            "delivery_type": order.delivery_type
        })
    
    return {
        "user_id": user_id,
        "total": len(results),
        "orders": results
    }


@router.post("/orders/{order_id}/cancel", response_model=dict)
async def cancel_order(
    order_id: str,
    user_id: int,
    reason: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Cancel order (only if not shipped yet)
    """
    
    order = db.query(Order).filter(Order.id == order_id).first()
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Verify user owns order
    if order.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Check if can be cancelled
    if order.order_status in ["shipped", "delivered"]:
        raise HTTPException(
            status_code=400,
            detail="Cannot cancel order after it has been shipped"
        )
    
    if order.order_status == "cancelled":
        raise HTTPException(status_code=400, detail="Order already cancelled")
    
    try:
        # Restore stock
        items = db.query(OrderItem).filter(OrderItem.order_id == order_id).all()
        
        for item in items:
            medicine = db.query(Medicine).filter(Medicine.id == item.medicine_id).first()
            if medicine:
                medicine.stock_quantity += item.quantity
        
        # Update order status
        order.order_status = "cancelled"
        
        db.commit()
        
        # Send notification
        send_notification(
            db=db,
            user_id=user_id,
            type="order_cancelled",
            title="Order Cancelled",
            message=f"Your order #{order_id} has been cancelled successfully."
        )
        
        return {
            "status": "success",
            "message": "Order cancelled successfully",
            "order_id": order_id
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Cancellation failed: {str(e)}")


@router.post("/prescriptions/upload", response_model=dict)
async def upload_prescription(
    user_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Upload prescription image
    
    In production, this would:
    1. Save image to cloud storage (S3/GCS)
    2. OCR to extract medicine names
    3. Auto-add medicines to cart
    
    For V1.0: Just return success with file info
    """
    
    # TODO: Implement actual file upload to S3/GCS
    # TODO: Implement OCR to extract medicine names
    
    # For now, return placeholder
    return {
        "status": "success",
        "message": "Prescription uploaded successfully",
        "file_name": file.filename,
        "file_size": file.size,
        "prescription_id": f"RX{secrets.randbelow(900000) + 100000}",
        "note": "Our pharmacist will verify and add medicines to your cart within 30 minutes"
    }