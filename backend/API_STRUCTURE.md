# API Structure

## 1. API Design Goal
The API layer is organized by healthcare domain, not by generic CRUD folders. This keeps real business workflows clear and makes large-team development easier.

## 2. Router Map
| File | Prefix | Domain Responsibility |
|---|---|---|
| `api/auth.py` | `/api/auth` | OTP login, JWT issue/refresh, user identity |
| `api/appointments.py` | `/api/appointments` | Doctor search, slot discovery, booking, cancellation, rescheduling |
| `api/doctor_management.py` | `/api/doctor` | Doctor onboarding, schedule/slots, wallet, analytics |
| `api/emergency.py` | `/api/emergency` | Emergency requests, nearest clinic assignment, status tracking |
| `api/pharmacy.py` | `/api/pharmacy` | Medicine discovery, order creation/tracking, prescription upload |
| `api/pharmacy_vendor.py` | `/api/pharmacy_vendor` | Pharmacy vendor onboarding, stock/order operations, reports |
| `api/lab_tests.py` | `/api/lab-tests` | Test search, booking flow, tracking, report management |
| `api/lab_vendor.py` | `/api/lab-vendor` | Lab vendor onboarding, catalog, booking operations, analytics |
| `api/payments.py` | `/api/payments` | Razorpay order creation, verification, webhook, refunds |
| `api/upload.py` | `/api/upload` | Secure file uploads, listing, soft delete, download |
| `api/profile.py` | `/api/profile` | Patient profile, addresses, family members, preferences |
| `api/dashboard.py` | `/api/dashboard` | Aggregated patient dashboard data and notifications |

## 3. Request And Response Lifecycle
```text
HTTP Request
  -> FastAPI router + dependency injection
  -> Pydantic request validation
  -> Authentication check (for protected routes)
  -> Domain logic execution
  -> Database read/write via SQLAlchemy session
  -> Response model/dict formatting
  -> HTTP response
```

Why this structure:
- Validation is centralized in Pydantic models.
- Auth is reused through `Depends(get_current_user)`.
- DB sessions are standardized through `Depends(get_db)`.

## 4. Authentication Flow In API
Primary auth lifecycle in `api/auth.py`:

1. `POST /api/auth/send-otp`
2. `POST /api/auth/verify-otp`
3. `POST /api/auth/complete-profile` (for new users)
4. `POST /api/auth/refresh`
5. Protected routes use `Authorization: Bearer <access_token>`

Why this is used:
- OTP reduces password friction for patient onboarding.
- JWT keeps app servers stateless and horizontally scalable.

## 5. Domain Separation Philosophy
The API is split by healthcare capability:

- Patient care journey: auth, profile, appointments, emergency, lab tests, pharmacy.
- Platform operations: payments, upload, notifications in dashboard.
- Vendor operations: doctor, pharmacy vendor, lab vendor.

This supports:
- Independent releases by domain.
- Clear ownership for backend teams.
- Safer changes with lower cross-domain impact.

## 6. Endpoint Organization Pattern
Across modules, the common pattern is:

- Search/list endpoints for discovery.
- Detail endpoints for entity retrieval.
- Action endpoints for workflow transitions.
- History/stats endpoints for analytics and operations.

Examples:
- Appointment lifecycle: search doctors, fetch slots, book, cancel/reschedule.
- Payment lifecycle: create order, verify, webhook reconciliation, refund.
- Upload lifecycle: validate, store, persist metadata, retrieve/download.

## 7. API Consistency Notes
Current codebase is modular and production-oriented, with a few consistency areas to standardize over time:

- Prefix naming style mixes hyphen and underscore.
- Some logic remains inside route files and can be moved to service modules.
- Root endpoint labels in `main.py` should stay aligned with router prefixes.

## 8. FastAPI Best Practices Already Present
- Strong use of `APIRouter` and tags.
- Dependency injection for DB and auth.
- Pydantic request/response models.
- Background task usage for non-blocking side effects.
- Domain-focused module boundaries.
