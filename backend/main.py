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

# Database tables managed by Alembic migrations
# Run: alembic upgrade head
# Base.metadata.create_all(bind=engine)  # DO NOT USE - use alembic

app = FastAPI(
    title="MediCare API",
    description="Complete Healthcare Platform API",
    version="1.0.0"
)

# Serve uploaded files
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:19006",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Each router already has /api/ prefix internally
# We add /v1 to get /v1/api/auth, /v1/api/appointments etc
# This allows future /v2 without breaking /v1
V1 = "/v1"

app.include_router(auth_router, prefix=V1)
app.include_router(appointments_router, prefix=V1)
app.include_router(emergency_router, prefix=V1)
app.include_router(pharmacy_router, prefix=V1)
app.include_router(lab_router, prefix=V1)
app.include_router(dashboard_router, prefix=V1)
app.include_router(payments_router, prefix=V1)
app.include_router(upload_router, prefix=V1)
app.include_router(profile_router, prefix=V1)
app.include_router(doctor_management_router, prefix=V1)
app.include_router(pharmacy_vendor_router, prefix=V1)
app.include_router(lab_vendor_router, prefix=V1)


@app.get("/")
async def root():
    return {
        "message": "MediCare API",
        "status": "running",
        "version": "1.0.0",
        "api_version": "v1",
        "endpoints": {
            "auth": "/v1/api/auth",
            "appointments": "/v1/api/appointments",
            "pharmacy": "/v1/api/pharmacy",
            "lab_tests": "/v1/api/lab-tests",
            "emergency": "/v1/api/emergency",
            "dashboard": "/v1/api/dashboard",
            "payments": "/v1/api/payments",
            "upload": "/v1/api/upload",
            "profile": "/v1/api/profile",
            "doctor_management": "/v1/api/doctor",
            "docs": "/docs"
        }
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)