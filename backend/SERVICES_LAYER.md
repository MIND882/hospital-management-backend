# Services Layer

## 1. What The Services Layer Is
The services layer contains reusable business logic that should not be tightly coupled to HTTP routes.

In a scalable FastAPI architecture:
- Routes handle HTTP concerns.
- Services handle domain workflows.
- Database models handle persistence shape.

## 2. Current Project State
Current `services/` files:

- `services/notification_service.py`
- `services/sms_service.py`
- `services/distance_calculator.py`

These files are currently placeholders, while much business logic is implemented inside route modules (`api/*.py`).

This is common in early-stage projects and gives a clear next step for refactoring toward cleaner architecture.

## 3. Why Separate Business Logic From Routes
Service extraction improves:

- Reusability: one rule can be used by patient, doctor, and vendor APIs.
- Testability: pure services are easier to unit test than route handlers.
- Maintainability: route files stay small and focused.
- Scalability: shared workflows can evolve without duplicating logic.

## 4. Intended Service Responsibilities
`notification_service.py`
- Create in-app notifications.
- Handle notification templates by event type.
- Route notifications to channels (in-app/SMS/email/push).

`sms_service.py`
- Centralize Twilio integration.
- Handle OTP and transactional message delivery.
- Add retry, throttling, and provider fallback logic.

`distance_calculator.py`
- Own geospatial helpers (Haversine, nearest facility ranking, ETA support).
- Reuse across emergency, doctor search, and lab/home-delivery modules.

## 5. Practical Extraction Targets In This Codebase
High-value logic to move from `api/` into `services/`:

- OTP sending and channel fallback from `api/auth.py`
- Notification creation helpers from multiple modules
- Distance and nearest-clinic logic from `api/emergency.py` and search modules
- Payment and wallet side-effect orchestration from `api/payments.py`
- Upload security pipeline helpers from `api/upload.py`

## 6. Recommended Service-Oriented Pattern
```text
Route Layer
  -> validates request
  -> calls service with typed input
  -> maps service result to HTTP response

Service Layer
  -> executes business rules
  -> coordinates models/repositories
  -> raises domain errors

Data Layer
  -> persists and queries entities
```

## 7. Service Design Guidelines
- Keep service methods domain-focused (`book_appointment`, `verify_payment`, `dispatch_emergency`).
- Pass DB session explicitly for transaction clarity.
- Return plain Python structures or typed models.
- Keep external API calls behind service boundaries.
- Avoid direct FastAPI imports inside services.

## 8. Suggested Refactor Roadmap
1. Create service APIs for one domain at a time.
2. Move helper functions first, then move orchestration logic.
3. Update routes to call services and keep endpoint contracts unchanged.
4. Add unit tests around service methods.
5. Reuse services across patient/vendor/admin route modules.

This approach gives cleaner separation without requiring a risky big-bang rewrite.
