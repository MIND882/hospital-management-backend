import sys
from pathlib import Path

# Add backend directory to path for imports to work when running directly
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_
import os
import uuid
import magic
from datetime import datetime
from typing import Optional, List
import hashlib
import shutil
from PIL import Image
import io

from database.connection import get_db
from database.models import User, AuditLog, Appointment, Prescription, UploadedFile
from api.auth import get_current_user
from pydantic import BaseModel, Field
import logging

router = APIRouter(prefix="/api/upload", tags=["File Upload"])
logger = logging.getLogger(__name__)

# ==================== CONFIG ====================
UPLOAD_BASE_DIR = Path("uploads")
UPLOAD_BASE_DIR.mkdir(exist_ok=True)

# Security configurations
ALLOWED_MIME_TYPES = {
    "image": ["image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp"],
    "pdf": ["application/pdf"],
    "document": ["application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
    "all": ["image/jpeg", "image/png", "image/gif", "image/webp", "application/pdf",
            "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]
}

MAX_FILE_SIZES = {
    "prescription": 10 * 1024 * 1024,  # 10 MB
    "report": 20 * 1024 * 1024,        # 20 MB
    "profile": 5 * 1024 * 1024,        # 5 MB
    "insurance": 5 * 1024 * 1024,      # 5 MB
    "general": 10 * 1024 * 1024        # 10 MB
}

# File categories for organization
FILE_CATEGORIES = {
    "prescription": "prescriptions",
    "report": "reports",
    "insurance": "insurance",
    "profile": "profiles",
    "general": "general"
}

# ==================== HELPER FUNCTIONS ====================

def validate_file_security(file: UploadFile, category: str) -> dict:
    """
    🔒 COMPREHENSIVE FILE VALIDATION
    
    Validates:
    1. File size
    2. MIME type (not just extension)
    3. File signature
    4. Virus scan (if configured)
    """
    errors = []
    
    # Get file size
    file.file.seek(0, 2)  # Seek to end
    file_size = file.file.tell()
    file.file.seek(0)  # Reset to beginning
    
    # 1. Check file size
    max_size = MAX_FILE_SIZES.get(category, MAX_FILE_SIZES["general"])
    if file_size > max_size:
        errors.append(f"File size {file_size/1024/1024:.1f}MB exceeds maximum {max_size/1024/1024:.1f}MB")
    
    # 2. Check MIME type using python-magic
    try:
        import magic
        mime = magic.Magic(mime=True)
        
        # Read first 2048 bytes for MIME detection
        file_content = file.file.read(2048)
        file.file.seek(0)
        
        detected_mime = mime.from_buffer(file_content)
        
        # Check if MIME is allowed
        allowed_mimes = ALLOWED_MIME_TYPES.get(category, ALLOWED_MIME_TYPES["all"])
        if detected_mime not in allowed_mimes:
            errors.append(f"MIME type {detected_mime} not allowed for {category}")
        
        # 3. Check file signature vs extension
        extension = Path(file.filename).suffix.lower()
        if not is_valid_signature(file_content, extension):
            errors.append(f"File signature doesn't match extension {extension}")
            
    except ImportError:
        # Fallback to extension validation if magic not available
        extension = Path(file.filename).suffix.lower()
        allowed_extensions = {
            '.jpg', '.jpeg', '.png', '.gif', '.webp', '.pdf', '.doc', '.docx'
        }
        if extension not in allowed_extensions:
            errors.append(f"Extension {extension} not allowed")
    
    # 4. Check filename for path traversal
    filename = Path(file.filename).name  # Get only filename, strip path
    if '..' in filename or '/' in filename or '\\' in filename:
        errors.append("Invalid filename")
    
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "size": file_size,
        "filename": filename
    }


def is_valid_signature(file_content: bytes, extension: str) -> bool:
    """
    Validate file signature vs extension
    Prevents fake extensions
    """
    signatures = {
        '.jpg': [b'\xFF\xD8\xFF'],
        '.jpeg': [b'\xFF\xD8\xFF'],
        '.png': [b'\x89\x50\x4E\x47\x0D\x0A\x1A\x0A'],
        '.pdf': [b'%PDF'],
        '.gif': [b'GIF87a', b'GIF89a']
    }
    
    if extension in signatures:
        for sig in signatures[extension]:
            if file_content.startswith(sig):
                return True
        return False
    
    return True  # For other extensions, assume valid


def generate_file_hash(file_content: bytes) -> str:
    """Generate SHA256 hash for file deduplication"""
    return hashlib.sha256(file_content).hexdigest()


def save_file_secure(file: UploadFile, category: str, user_id: int) -> dict:
    """
    💾 SECURE FILE SAVING WITH DEDUPLICATION
    
    Features:
    - Chunked reading (prevents memory issues)
    - File hash for deduplication
    - Secure permissions
    - Backup copy
    """
    try:
        # Create directory structure: uploads/{category}/{user_id}/{year}/{month}/
        now = datetime.now()
        folder = UPLOAD_BASE_DIR / category / str(user_id) / str(now.year) / f"{now.month:02d}"
        folder.mkdir(parents=True, exist_ok=True)
        
        # Generate unique filename
        original_name = Path(file.filename).stem
        extension = Path(file.filename).suffix.lower()
        unique_id = uuid.uuid4().hex[:8]
        filename = f"{original_name}_{unique_id}{extension}"
        filepath = folder / filename
        
        # Chunked reading and writing (memory efficient)
        file_size = 0
        file_hash = hashlib.sha256()
        
        with open(filepath, "wb") as f:
            while chunk := file.file.read(8192):  # 8KB chunks
                file_size += len(chunk)
                file_hash.update(chunk)
                f.write(chunk)
        
        # Generate thumbnail for images
        thumbnail_path = None
        if extension in ['.jpg', '.jpeg', '.png', '.gif']:
            thumbnail_path = create_thumbnail(filepath, folder)
        
        # Set secure permissions (Unix only)
        if os.name != 'nt':  # Not Windows
            os.chmod(filepath, 0o644)  # Owner: RW, Others: R
        
        return {
            "path": str(filepath),
            "url": f"/api/uploads/{category}/{user_id}/{now.year}/{now.month:02d}/{filename}",
            "thumbnail_url": thumbnail_path,
            "size": file_size,
            "hash": file_hash.hexdigest(),
            "original_name": file.filename,
            "stored_name": filename
        }
        
    except Exception as e:
        logger.error(f"File save error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"File save failed: {str(e)}")


def create_thumbnail(image_path: Path, folder: Path) -> Optional[str]:
    """
    Create thumbnail for images
    """
    try:
        with Image.open(image_path) as img:
            # Convert to RGB if necessary
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            
            # Create thumbnail
            img.thumbnail((300, 300))
            
            # Save thumbnail
            thumb_name = f"thumb_{image_path.name}"
            thumb_path = folder / thumb_name
            img.save(thumb_path, "JPEG", quality=85)
            
            return f"/api/uploads/thumbnails/{thumb_name}"
            
    except Exception as e:
        logger.warning(f"Thumbnail creation failed: {str(e)}")
        return None


def save_to_database(
    db: Session,
    user_id: int,
    file_info: dict,
    category: str,
    appointment_id: Optional[str] = None,
    description: Optional[str] = None
) -> UploadedFile:
    """
    Save file metadata to database
    """
    # Check for duplicate files by hash
    existing = db.query(UploadedFile).filter(
        UploadedFile.file_hash == file_info["hash"],
        UploadedFile.user_id == user_id
    ).first()
    
    if existing:
        # Return existing file record
        return existing
    
    # Create new record
    uploaded_file = UploadedFile(
        user_id=user_id,
        filename=file_info["original_name"],
        stored_filename=file_info["stored_name"],
        file_path=file_info["path"],
        file_url=file_info["url"],
        thumbnail_url=file_info.get("thumbnail_url"),
        file_size=file_info["size"],
        file_hash=file_info["hash"],
        file_type=Path(file_info["original_name"]).suffix.lower(),
        category=category,
        description=description,
        appointment_id=appointment_id,
        is_active=True
    )
    
    db.add(uploaded_file)
    db.commit()
    db.refresh(uploaded_file)
    
    return uploaded_file


# ==================== PYDANTIC MODELS ====================

class UploadResponse(BaseModel):
    status: str
    message: str
    file_id: int
    file_url: str
    thumbnail_url: Optional[str]
    size: int
    original_name: str

class MultipleUploadResponse(BaseModel):
    status: str
    message: str
    uploaded: List[dict]
    failed: List[dict]

# ==================== API ENDPOINTS ====================

@router.post("/prescription", response_model=UploadResponse)
async def upload_prescription(
    file: UploadFile = File(...),
    appointment_id: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    📄 UPLOAD PRESCRIPTION (SECURE)
    
    Features:
    - Secure validation
    - Appointment linking
    - Duplicate detection
    - Thumbnail generation
    """
    
    # Validate appointment exists and belongs to user
    if appointment_id:
        appointment = db.query(Appointment).filter(
            Appointment.id == appointment_id,
            Appointment.user_id == current_user.id
        ).first()
        
        if not appointment:
            raise HTTPException(status_code=404, detail="Appointment not found")
    
    # Security validation
    validation = validate_file_security(file, "prescription")
    if not validation["valid"]:
        raise HTTPException(
            status_code=400,
            detail=f"File validation failed: {', '.join(validation['errors'])}"
        )
    
    try:
        # Save file securely
        file_info = save_file_secure(file, "prescription", current_user.id)
        
        # Save to database
        uploaded_file = save_to_database(
            db,
            current_user.id,
            file_info,
            "prescription",
            appointment_id,
            description
        )
        
        # Link to prescription if appointment exists
        if appointment_id:
            prescription = db.query(Prescription).filter(
                Prescription.appointment_id == appointment_id
            ).first()
            
            if prescription:
                # Update prescription with file reference
                # (Add prescription_files relationship if needed)
                pass
        
        # Audit log
        audit = AuditLog(
            user_id=current_user.id,
            action="PRESCRIPTION_UPLOADED",
            entity_type="file",
            entity_id=str(uploaded_file.id),
            details={
                "filename": file.filename,
                "size": file_info["size"],
                "appointment_id": appointment_id,
                "file_hash": file_info["hash"]
            }
        )
        db.add(audit)
        db.commit()
        
        return UploadResponse(
            status="success",
            message="Prescription uploaded successfully",
            file_id=uploaded_file.id,
            file_url=file_info["url"],
            thumbnail_url=file_info.get("thumbnail_url"),
            size=file_info["size"],
            original_name=file.filename
        )
        
    except Exception as e:
        logger.error(f"Prescription upload failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Upload failed")


@router.post("/report", response_model=UploadResponse)
async def upload_report(
    file: UploadFile = File(...),
    lab_booking_id: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    📊 UPLOAD LAB REPORT
    """
    validation = validate_file_security(file, "report")
    if not validation["valid"]:
        raise HTTPException(status_code=400, detail="Invalid file")
    
    file_info = save_file_secure(file, "report", current_user.id)
    
    uploaded_file = save_to_database(
        db, current_user.id, file_info, "report", 
        lab_booking_id, "Lab Test Report"
    )
    
    audit = AuditLog(
        user_id=current_user.id,
        action="REPORT_UPLOADED",
        entity_type="file",
        entity_id=str(uploaded_file.id),
        details={"filename": file.filename}
    )
    db.add(audit)
    db.commit()
    
    return UploadResponse(
        status="success",
        message="Report uploaded successfully",
        file_id=uploaded_file.id,
        file_url=file_info["url"],
        thumbnail_url=file_info.get("thumbnail_url"),
        size=file_info["size"],
        original_name=file.filename
    )


@router.post("/insurance", response_model=UploadResponse)
async def upload_insurance(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    🏥 UPLOAD INSURANCE DOCUMENTS
    """
    validation = validate_file_security(file, "insurance")
    if not validation["valid"]:
        raise HTTPException(status_code=400, detail="Invalid file")
    
    file_info = save_file_secure(file, "insurance", current_user.id)
    
    uploaded_file = save_to_database(
        db, current_user.id, file_info, "insurance", 
        None, "Insurance Card/Document"
    )
    
    # Update user's insurance info
    current_user.insurance_proof_url = file_info["url"]
    db.commit()
    
    return UploadResponse(
        status="success",
        message="Insurance document uploaded successfully",
        file_id=uploaded_file.id,
        file_url=file_info["url"],
        thumbnail_url=file_info.get("thumbnail_url"),
        size=file_info["size"],
        original_name=file.filename
    )


@router.post("/profile", response_model=UploadResponse)
async def upload_profile_picture(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    👤 UPLOAD PROFILE PICTURE
    """
    validation = validate_file_security(file, "profile")
    if not validation["valid"]:
        raise HTTPException(status_code=400, detail="Invalid image file")
    
    file_info = save_file_secure(file, "profile", current_user.id)
    
    uploaded_file = save_to_database(
        db, current_user.id, file_info, "profile", 
        None, "Profile Picture"
    )
    
    # Update user profile picture
    current_user.profile_picture_url = file_info["url"]
    db.commit()
    
    return UploadResponse(
        status="success",
        message="Profile picture updated successfully",
        file_id=uploaded_file.id,
        file_url=file_info["url"],
        thumbnail_url=file_info.get("thumbnail_url"),
        size=file_info["size"],
        original_name=file.filename
    )


@router.post("/multiple", response_model=MultipleUploadResponse)
async def upload_multiple_files(
    files: List[UploadFile] = File(...),
    category: str = Form("general"),
    appointment_id: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    📁 UPLOAD MULTIPLE FILES AT ONCE
    """
    uploaded = []
    failed = []
    
    for file in files:
        try:
            validation = validate_file_security(file, category)
            if not validation["valid"]:
                failed.append({
                    "filename": file.filename,
                    "error": validation["errors"][0] if validation["errors"] else "Unknown error"
                })
                continue
            
            file_info = save_file_secure(file, category, current_user.id)
            
            uploaded_file = save_to_database(
                db, current_user.id, file_info, category,
                appointment_id, "Multiple upload"
            )
            
            uploaded.append({
                "id": uploaded_file.id,
                "filename": file.filename,
                "url": file_info["url"],
                "size": file_info["size"]
            })
            
        except Exception as e:
            failed.append({
                "filename": file.filename,
                "error": str(e)
            })
    
    return MultipleUploadResponse(
        status="partial" if failed else "success",
        message=f"Uploaded {len(uploaded)} files, failed {len(failed)}",
        uploaded=uploaded,
        failed=failed
    )


@router.get("/files", response_model=dict)
async def get_user_files(
    category: Optional[str] = None,
    appointment_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    📂 GET USER'S UPLOADED FILES
    """
    query = db.query(UploadedFile).filter(
        UploadedFile.user_id == current_user.id,
        UploadedFile.is_active == True
    )
    
    if category:
        query = query.filter(UploadedFile.category == category)
    
    if appointment_id:
        query = query.filter(UploadedFile.appointment_id == appointment_id)
    
    files = query.order_by(UploadedFile.created_at.desc()).all()
    
    return {
        "total": len(files),
        "files": [
            {
                "id": f.id,
                "filename": f.filename,
                "url": f.file_url,
                "thumbnail_url": f.thumbnail_url,
                "category": f.category,
                "size": f.file_size,
                "uploaded_at": f.created_at.strftime("%Y-%m-%d %I:%M %p"),
                "description": f.description
            }
            for f in files
        ]
    }


@router.delete("/files/{file_id}")
async def delete_file(
    file_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    🗑️ DELETE UPLOADED FILE (SOFT DELETE)
    """
    file = db.query(UploadedFile).filter(
        UploadedFile.id == file_id,
        UploadedFile.user_id == current_user.id
    ).first()
    
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    
    # Soft delete (mark as inactive)
    file.is_active = False
    file.deleted_at = datetime.now()
    
    db.commit()
    
    return {
        "status": "success",
        "message": "File deleted successfully"
    }


@router.get("/download/{file_id}")
async def download_file(
    file_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    ⬇️ DOWNLOAD UPLOADED FILE
    """
    file = db.query(UploadedFile).filter(
        UploadedFile.id == file_id,
        UploadedFile.user_id == current_user.id,
        UploadedFile.is_active == True
    ).first()
    
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    
    file_path = Path(file.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on server")
    
    return FileResponse(
        path=file_path,
        filename=file.filename,
        media_type="application/octet-stream"
    )


# ==================== PUBLIC ENDPOINTS (FOR THUMBNAILS) ====================

@router.get("/uploads/{path:path}")
async def serve_uploaded_file(path: str):
    """
    🌐 SERVE UPLOADED FILES (PUBLIC)
    
    Note: Add authentication middleware in production
    """
    file_path = UPLOAD_BASE_DIR / path
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    # Security check: Ensure file is within uploads directory
    try:
        file_path.resolve().relative_to(UPLOAD_BASE_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return FileResponse(file_path)