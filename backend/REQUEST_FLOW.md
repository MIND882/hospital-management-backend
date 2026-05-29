# Request Flow

## 1. End-To-End Flow
Core request lifecycle in this backend:

```text
Client Request
    |
    v
FastAPI Route (api/*.py)
    |
    v
Validation (Pydantic + dependency checks)
    |
    v
Service Logic (currently in route helpers, target: services/*.py)
    |
    v
Database Layer (SQLAlchemy session + ORM models)
    |
    v
Response (JSON payload + status code)
```

## 2. Step-By-Step Explanation
1. Client sends HTTP request with JSON/body/query/path data.
2. FastAPI routes map request to the correct module.
3. Pydantic models validate payload shape and types.
4. `Depends(get_current_user)` enforces auth on protected routes.
5. `Depends(get_db)` provides a request-scoped DB session.
6. Domain logic runs and performs DB operations.
7. Response is returned in a normalized API format.

## 3. Async Request Handling
The API endpoints are mostly defined as `async def`, which supports non-blocking web handling at the framework layer.

Current behavior note:
- The project uses synchronous SQLAlchemy sessions (`create_engine`, standard `Session`).
- This is valid and common, but true high-concurrency async DB behavior would require SQLAlchemy async engine/session migration.

## 4. Authentication Flow
```text
POST /api/auth/send-otp
  -> validate phone + rate limit
  -> generate and store hashed OTP
  -> send via Twilio channels

POST /api/auth/verify-otp
  -> verify OTP + expiry
  -> mark user verified
  -> issue access + refresh JWT

Protected endpoint call
  -> Bearer token decode
  -> user lookup
  -> authorized business action
```

## 5. Upload Flow
```text
POST /api/upload/{category}
  -> validate file size, MIME, signature, filename safety
  -> save file to uploads directory
  -> compute hash for dedup
  -> store metadata in uploaded_files table
  -> return file URL and metadata
```

Security and maintainability choices:
- File validation is defensive (MIME + signature checks).
- Soft delete strategy preserves auditability.
- Metadata and binary storage responsibilities are separated.

## 6. Payment Flow
```text
POST /api/payments/create-order
  -> validate domain order (appointment/order/lab booking)
  -> create Razorpay order
  -> persist payment linkage

POST /api/payments/verify
  -> verify Razorpay signature
  -> update payment + domain entity status
  -> trigger wallet/notification side effects
  -> log audit trail

POST /api/payments/webhook/razorpay
  -> gateway-driven async reconciliation
```

Why this is scalable:
- Verification path is explicit and auditable.
- Webhook support enables eventual consistency with payment gateway events.

## 7. Emergency Flow
```text
POST /api/emergency/request
  -> validate user and coordinates
  -> find nearest emergency-capable clinic
  -> create emergency request + ETA
  -> queue background tasks for notifications/alerts
```

Why this is modular:
- Geospatial logic is contained in one domain module.
- Notification and alert side effects are decoupled from initial response path.

## 8. Appointment Flow
```text
Search doctors
  -> Fetch slots
  -> Book appointment
  -> Create payment context
  -> Confirm and notify
```

Important integrity checks in flow:
- Slot lock/check to reduce double booking risk.
- Future-time validation.
- Per-doctor/day load control.

## 9. Modular Backend Execution Model
Each domain module executes independently but follows shared backend conventions:

- Shared auth dependency
- Shared DB session dependency
- Shared audit/notification behavior patterns
- Shared entity model graph

This gives consistency without forcing all healthcare domains into one large route file.
