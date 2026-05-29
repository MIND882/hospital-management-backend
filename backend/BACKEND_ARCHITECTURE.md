# Backend Architecture

## 1. Purpose
This document explains the architecture of the FastAPI healthcare backend so new teammates and junior developers can understand how the system is organized, why design decisions were made, and how to scale safely.

## 2. Architecture At A Glance
```text
backend/
|-- main.py                  # Composition root: app creation, middleware, router registration
|-- api/                     # HTTP route layer (domain-wise modules)
|-- database/                # DB connection, ORM models, SQL reference schema
|-- alembic/                 # Migration engine and migration versions
|-- services/                # Service layer package (currently placeholder files)
|-- utils/                   # Shared helper package (currently placeholder files)
|-- uploads/                 # Uploaded file storage directory
|-- alembic.ini              # Alembic configuration
|-- requirements.txt         # Python dependencies
|-- runtime.txt              # Python runtime version
|-- .env                     # Environment configuration
```

## 3. Layered Backend Model
```text
Client (Mobile/Web/Admin)
        |
        v
FastAPI Application (main.py)
        |
        v
API Routers (api/*.py)
        |
        v
Business Logic (currently inside route modules, target: services/*.py)
        |
        v
Data Access (database/connection.py + database/models.py)
        |
        v
PostgreSQL Relational Database
```

## 4. Separation Of Concerns
`api/`
- Handles HTTP concerns: path/query/body parsing, auth dependency usage, response shaping, and status codes.
- Keeps domain modules separate (`appointments`, `pharmacy`, `lab_tests`, `emergency`, etc.) so teams can work independently.

`database/`
- Isolates persistence concerns in `connection.py` and `models.py`.
- Prevents SQL and session logic from being scattered across modules.

`services/`
- Intended home for reusable business logic (notifications, SMS, distance calculations).
- Current codebase still contains many helper/service functions inside route files, which is common in early-stage products.

`utils/`
- Intended for technical helpers that are not domain business rules.

`alembic/`
- Owns schema history and migration execution.
- Enables safe, traceable schema evolution across environments.

`uploads/`
- Keeps file storage concerns separate from database records (`uploaded_files` table stores metadata).

## 5. Modular API Strategy
The backend uses domain-based modules so each major healthcare workflow has clear ownership.

```text
Patient-facing domains:
- auth, appointments, profile, dashboard, emergency, pharmacy, lab_tests, payments, upload

Provider-facing domains:
- doctor_management, pharmacy_vendor, lab_vendor
```

Why this matters:
- Smaller files and clearer ownership per healthcare domain.
- Easier to scale teams and release features in parallel.
- Lower regression risk when changing one domain.

## 6. Scalability Strategy
Current architecture supports a clean path to production scaling:

- Stateless API design with JWT-based auth enables horizontal scaling.
- Domain router separation supports team-based scaling.
- Relational schema with explicit foreign keys supports data integrity.
- Alembic migration history supports safe multi-environment releases.
- Background task usage in selected flows reduces user-perceived latency.

Recommended next steps for scalability:
- Move business logic from routers into `services/`.
- Replace local file storage with object storage (S3/GCS/Azure Blob) in production.
- Use async database stack or tuned worker model for high concurrency.
- Add observability layers (structured logs, metrics, tracing).

## 7. Current-State Notes
Important implementation observations:

- `main.py` currently runs `Base.metadata.create_all(bind=engine)`. For production, prefer Alembic-only schema control.
- `services/*.py` and `utils/helpers.py` are currently placeholders; business logic mainly lives in API modules.
- Some route prefix naming styles are mixed (hyphen and underscore). Standardizing improves long-term API consistency.

## 8. Why This Architecture Works For Healthcare
Healthcare systems need correctness, traceability, and maintainability. This architecture supports that by:

- Keeping clinical/business domains isolated.
- Preserving auditability with relational data and migration history.
- Allowing secure auth and payment workflows to remain explicit.
- Making onboarding easier through clear backend boundaries.
