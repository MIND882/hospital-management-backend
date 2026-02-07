from fastapi import FastAPI
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from api.appointments import router as appointments_router
from api.auth import router as auth_router
from api.pharmacy import router as pharmacy_router
from api.lab_tests import router as lab_router
from api.emergency import router as emergency_router
from api.dashboard import router as dashboard_router
from api.payments import router as payments_router
from api.upload import router as upload_router
from api.profile import router as profile_router
from api.doctor_management import router as doctor_management_router
from api.pharmacy_vendor import router as pharmacy_vendor_router
from api.lab_vendor import router as lab_vendor_router
from database.connection import engine, Base
import uvicorn

# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="MediCare API",
    description="Complete Healthcare Platform API",
    version="1.0.0"
)
# ✅ IMPORTANT: Serve uploaded files
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ "http://localhost:19006",  
                    "http://localhost:5173", ],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(appointments_router)
app.include_router(emergency_router)
app.include_router(auth_router)
app.include_router(pharmacy_router)
app.include_router(lab_router)
app.include_router(dashboard_router)
app.include_router(payments_router)
app.include_router(upload_router)
app.include_router(profile_router)
app.include_router(doctor_management_router)
app.include_router(pharmacy_vendor_router)
app.include_router(lab_vendor_router)

@app.get("/")
async def root():
    return {
        "message": "MediCare API",
        "status": "running",
        "version": "1.0.0",
        "endpoints": {
            "appointments": "/api/appointments",
            "auth": "/api/auth",
            "pharmacy": "/api/pharmacy",
            "lab_tests": "/api/lab_tests",
            "emergency": "/api/emergency",
            "dashboard": "/api/dashboard",
            "payments": "/api/payments",
            "upload": "/api/upload",
            "profile": "/api/profile",
            "doctor_management": "/api/doctor_management",
            "pharmacy_vendor": "/api/pharmacy_vendor",
            "docs": "/docs"
        }
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)