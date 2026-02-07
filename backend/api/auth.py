
import sys
from pathlib import Path

# Add backend directory to path for imports to work when running directly
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from fastapi import APIRouter, Depends, HTTPException, Header, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import func
from database.connection import get_db
from database.models import User, AuditLog
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
import asyncio
import jwt
import secrets
import bcrypt
import re
load_dotenv()
router = APIRouter(prefix="/api/auth", tags=["Authentication"])
security = HTTPBearer()

# ==================== CONFIG ====================

SECRET_KEY = "your-super-secret-key-change-in-production"  # Store in .env
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440  # 1 day
REFRESH_TOKEN_EXPIRE_DAYS = 7

OTP_EXPIRY_MINUTES = 5
MAX_OTP_ATTEMPTS = 3
OTP_RATE_LIMIT_PER_HOUR = 3

# ==================== PYDANTIC MODELS ====================

class SendOTPRequest(BaseModel):
    phone: str = Field(..., description="Phone with country code: +919876543210")

class VerifyOTPRequest(BaseModel):
    phone: str
    otp: str = Field(..., min_length=6, max_length=6)

class CompleteProfileRequest(BaseModel):
    phone: str
    name: str = Field(..., min_length=2, max_length=100)
    age: Optional[int] = Field(None, ge=1, le=120)
    gender: Optional[str] = Field(None, description="male/female/other")
    blood_group: Optional[str] = Field(None, description="A+, B+, O+, etc.")
    email: Optional[str] = None

class RefreshTokenRequest(BaseModel):
    refresh_token: str

class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict

# ==================== HELPER FUNCTIONS ====================

def validate_phone(phone: str) -> bool:
    """Validate phone number format"""
    pattern = r'^\+\d{1,3}\d{10}$'  # +countrycode + 10 digits
    return bool(re.match(pattern, phone))

def generate_otp() -> str:
    """Generate 6-digit OTP"""
    return str(secrets.randbelow(900000) + 100000)

def hash_otp(otp: str) -> str:
    """Hash OTP before storing"""
    return bcrypt.hashpw(otp.encode(), bcrypt.gensalt()).decode()

def verify_otp(plain_otp: str, hashed_otp: str) -> bool:
    """Verify OTP against hash"""
    try:
        return bcrypt.checkpw(plain_otp.encode(), hashed_otp.encode())
    except:
        return False

def create_access_token(data: dict) -> str:
    """Create JWT access token"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "access"
    })
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def create_refresh_token(data: dict) -> str:
    """Create JWT refresh token"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "refresh"
    })
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> dict:
    """Decode and validate JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )

async def send_otp_sms(phone: str, otp: str) -> bool:
    """✅ SMS via Twilio (Primary - Production Ready)"""
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    twilio_number = os.getenv("TWILIO_PHONE_NUMBER")
    
    if not all([account_sid, auth_token, twilio_number]):
        print("❌ TWILIO SMS: Missing credentials in .env")
        return False
    
    try:
        client = Client(account_sid, auth_token)
        message = client.messages.create(
            body=f"🩺 MediCare OTP: {otp}\nValid for 5 minutes\nDo not share.",
            from_=twilio_number,
            to=phone
        )
        print(f"✅ SMS Success: {message.sid} → {phone}")
        return True
        
    except TwilioRestException as e:
        print(f"❌ SMS Error: {e}")
        return False
    except Exception as e:
        print(f"❌ SMS Exception: {str(e)}")
        return False

async def send_otp_whatsapp(phone: str, otp: str) -> bool:
    """✅ WhatsApp via Twilio (Secondary - High Open Rate)"""
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    whatsapp_number = os.getenv("TWILIO_WHATSAPP_NUMBER")
    
    if not all([account_sid, auth_token, whatsapp_number]):
        print("⚠️ WhatsApp: Missing config")
        return False
    
    try:
        client = Client(account_sid, auth_token)
        message = client.messages.create(
            body=f"🩺 *MediCare OTP*\n\n{otp}\n\n*Valid for 5 minutes*\n_Do not share with anyone._",
            from_=whatsapp_number,
            to=f"whatsapp:{phone}"
        )
        print(f"✅ WhatsApp Success: {message.sid} → {phone}")
        return True
        
    except TwilioRestException as e:
        print(f"❌ WhatsApp Error: {e}")
        return False
    except Exception as e:
        print(f"❌ WhatsApp Exception: {str(e)}")
        return False
def check_rate_limit(phone: str, db: Session) -> bool:
    """
    Check if user exceeded OTP rate limit
    Returns True if within limit, False if exceeded
    """
    one_hour_ago = datetime.now() - timedelta(hours=1)
    
    # ✅ YE 3 LINES CHANGE KARO (TOP PE IMPORT func add karna):
    count = db.query(func.count(User.id)).filter(
        User.phone == phone,
        User.otp_expires_at >= one_hour_ago
    ).scalar()
    
    return count < OTP_RATE_LIMIT_PER_HOUR

# ==================== DEPENDENCY: Get Current User ====================

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """
    Dependency to get current authenticated user
    Use this in protected routes: current_user: User = Depends(get_current_user)
    """
    token = credentials.credentials
    payload = decode_token(token)
    
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type"
        )
    
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    
    return user

# ==================== API ENDPOINTS ====================

@router.post("/send-otp", response_model=dict)
async def send_otp(
    request: SendOTPRequest,
    db: Session = Depends(get_db)
):
    """📱 PRODUCTION OTP: SMS + WhatsApp via TWILIO"""
    
    # Phone validation
    if not validate_phone(request.phone):
        raise HTTPException(
            status_code=400,
            detail="Invalid phone. Use: +919876543210"
        )
    
    # Rate limiting
    if not check_rate_limit(request.phone, db):
        raise HTTPException(
            status_code=429,
            detail="Too many OTP requests. Try again in 1 hour."
        )
    
    # Generate OTP
    otp = generate_otp()
    hashed_otp = hash_otp(otp)
    otp_expiry = datetime.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)
    
    # User handling
    user = db.query(User).filter(User.phone == request.phone).first()
    if user:
        user.otp = hashed_otp
        user.otp_expires_at = otp_expiry
    else:
       user = User(
    email=f"user_{request.phone.replace('+', '').replace('-', '')}@temp.hospital.in",
    phone=request.phone,
    full_name=f"Patient {request.phone[-4:]}",
    role="patient",
    password_hash="",  # Empty for now
    otp=hashed_otp,
    otp_expires_at=otp_expiry,
    is_verified=False
)
    db.add(user)
    
    db.commit()
    
    # 🔥 PRODUCTION: Send SMS + WhatsApp (Parallel)
    sms_task = asyncio.create_task(send_otp_sms(request.phone, otp))
    whatsapp_task = asyncio.create_task(send_otp_whatsapp(request.phone, otp))
    
    sms_success, whatsapp_success = await asyncio.gather(sms_task, whatsapp_task)
    
    # Audit log
    audit = AuditLog(
        user_id=user.id,
        action="OTP_SENT",
        entity_type="auth",
        entity_id=request.phone,
        details={
            "phone": request.phone,
            "sms_success": sms_success,
            "whatsapp_success": whatsapp_success,
            "otp_length": 6
        }
    )
    db.add(audit)
    db.commit()
    
    return {
        "status": "success",
        "message": "OTP sent successfully via SMS & WhatsApp",
        "phone": request.phone,
        "expires_in_seconds": OTP_EXPIRY_MINUTES * 60,
        "channels": {
            "sms": sms_success,
            "whatsapp": whatsapp_success
        },
        "is_new_user": user.name is None
    }

@router.post("/verify-otp", response_model=AuthResponse)
async def verify_otp_endpoint(
    request: VerifyOTPRequest,
    db: Session = Depends(get_db)
):
    """
    ✅ STEP 2: Verify OTP
    
    - Validates OTP
    - Checks expiry
    - Returns JWT tokens if valid
    """
    
    # Get user
    user = db.query(User).filter(User.phone == request.phone).first()
    
    if not user or not user.otp:
        raise HTTPException(
            status_code=404,
            detail="No OTP request found for this phone number"
        )
    
    # Check if OTP expired
    if user.otp_expires_at < datetime.now():
        raise HTTPException(
            status_code=400,
            detail="OTP has expired. Please request a new one."
        )
    
    # Verify OTP
    if not verify_otp(request.otp, user.otp):
        raise HTTPException(
            status_code=400,
            detail="Invalid OTP. Please try again."
        )
    
    # Mark user as verified
    user.is_verified = True
    user.otp = None  # Clear OTP after successful verification
    user.otp_expires_at = None
    db.commit()
    db.refresh(user)
    
    # Generate tokens
    access_token = create_access_token(data={
        "user_id": user.id,
        "phone": user.phone,
        "role": "patient"
    })
    
    refresh_token = create_refresh_token(data={
        "user_id": user.id
    })
    
    # Log action
    audit = AuditLog(
        user_id=user.id,
        action="LOGIN_SUCCESS",
        entity_type="auth",
        entity_id=str(user.id),
        details={"phone": user.phone}
    )
    db.add(audit)
    db.commit()
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "phone": user.phone,
            "name": user.name,
            "email": user.email,
            "age": user.age,
            "gender": user.gender,
            "is_profile_complete": bool(user.name and user.age)
        }
    }
@router.post("/complete-profile", response_model=AuthResponse)
async def complete_profile(
    request: CompleteProfileRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    📝 STEP 3: Complete Profile (for new users)
    
    - Updates user information
    - Returns updated tokens
    """
    
    # Update user profile
    current_user.name = request.name
    current_user.age = request.age
    current_user.gender = request.gender
    current_user.blood_group = request.blood_group
    current_user.email = request.email
    current_user.updated_at = datetime.now()
    
    db.commit()
    db.refresh(current_user)
    
    # Generate new tokens with updated info
    access_token = create_access_token(data={
        "user_id": current_user.id,
        "phone": current_user.phone,
        "role": "patient"
    })
    
    refresh_token = create_refresh_token(data={
        "user_id": current_user.id
    })
    
    # Log action
    audit = AuditLog(
        user_id=current_user.id,
        action="PROFILE_COMPLETED",
        entity_type="user",
        entity_id=str(current_user.id),
        details={"name": request.name}
    )
    db.add(audit)
    db.commit()
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": current_user.id,
            "phone": current_user.phone,
            "name": current_user.name,
            "email": current_user.email,
            "age": current_user.age,
            "gender": current_user.gender,
            "blood_group": current_user.blood_group,
            "is_profile_complete": True
        }
    }


@router.post("/refresh", response_model=dict)
async def refresh_access_token(
    request: RefreshTokenRequest,
    db: Session = Depends(get_db)
):
    """
    🔄 Refresh Access Token
    
    - Validates refresh token
    - Returns new access token
    """
    
    payload = decode_token(request.refresh_token)
    
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=400,
            detail="Invalid token type. Must be refresh token."
        )
    
    user_id = payload.get("user_id")
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )
    
    # Generate new access token
    new_access_token = create_access_token(data={
        "user_id": user.id,
        "phone": user.phone,
        "role": "patient"
    })
    
    return {
        "access_token": new_access_token,
        "token_type": "bearer"
    }


@router.post("/logout", response_model=dict)
async def logout(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    🚪 Logout
    
    - Logs the action
    - Client should delete tokens
    """
    
    # Log action
    audit = AuditLog(
        user_id=current_user.id,
        action="LOGOUT",
        entity_type="auth",
        entity_id=str(current_user.id),
        details={"phone": current_user.phone}
    )
    db.add(audit)
    db.commit()
    
    return {
        "status": "success",
        "message": "Logged out successfully"
    }


@router.get("/me", response_model=dict)
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """
    👤 Get Current User Info
    
    Protected route example - requires authentication
    """
    
    return {
        "id": current_user.id,
        "phone": current_user.phone,
        "name": current_user.name,
        "email": current_user.email,
        "age": current_user.age,
        "gender": current_user.gender,
        "blood_group": current_user.blood_group,
        "insurance_provider": current_user.insurance_provider,
        "created_at": current_user.created_at.strftime("%Y-%m-%d"),
        "is_verified": current_user.is_verified
    }


@router.post("/resend-otp", response_model=dict)
async def resend_otp(
    request: SendOTPRequest,
    db: Session = Depends(get_db)
):
    """
    🔁 Resend OTP
    
    Same as send-otp but with different messaging
    """
    
    # Reuse send_otp logic
    result = await send_otp(request, db)
    result["message"] = "OTP resent successfully"
    
    return result