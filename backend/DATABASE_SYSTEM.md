# Database System

## 1. Database Architecture Overview
This backend uses SQLAlchemy ORM with PostgreSQL-style relational modeling and Alembic for migration tracking.

Core files:
- `database/connection.py`: engine, session factory, dependency (`get_db`)
- `database/models.py`: all ORM models and relationships
- `database/schema.sql`: SQL reference schema
- `alembic/`: migration runtime and version history

## 2. Connection Layer
`database/connection.py` centralizes:

- Environment loading (`python-dotenv`)
- Database URL construction
- SQLAlchemy engine creation
- `SessionLocal` session factory
- `get_db()` dependency for FastAPI routes

Why this matters:
- One source of truth for DB connectivity.
- Consistent session lifecycle per request.
- Easier environment-specific overrides.

## 3. Relational Model Design
The schema is strongly relational with explicit keys between core healthcare entities.

```text
users
|-- doctors
|   |-- doctor_slots
|   |-- doctor_wallets
|   |-- wallet_transactions
|-- pharmacies
|   |-- medicines
|   |-- orders
|       |-- order_items
|-- laboratories
|   |-- lab_tests
|   |-- lab_bookings
|-- appointments
|   |-- appointment_payments
|   |-- qr_codes
|   |-- prescriptions
|-- emergency_requests
|-- notifications
|-- uploaded_files
|-- audit_logs
```

## 4. Why A Relational Database For Healthcare
Relational modeling is a good fit for healthcare operations because it provides:

- Referential integrity for patient-care relationships.
- Transaction safety for bookings and payments.
- Audit-friendly structure for regulated workflows.
- Query power for analytics and operational reporting.

The schema also uses JSONB in selected fields (specialties, allergies, structured metadata) where flexibility is useful.

## 5. Model Responsibilities
- Identity and auth data: `User`
- Clinical operations: `Doctor`, `Clinic`, `DoctorSlot`, `Appointment`, `Prescription`
- Emergency operations: `EmergencyRequest`
- Pharmacy operations: `Pharmacy`, `Medicine`, `Order`, `OrderItem`, `StockEntry`
- Lab operations: `Laboratory`, `LabTest`, `LabBooking`
- Payments and wallet: `Payment`, `AppointmentPayment`, `DoctorWallet`, `WalletTransaction`
- Platform support: `Notification`, `NotificationPreferences`, `UploadedFile`, `AuditLog`, `Address`, `FamilyMember`

## 6. Alembic Migration System
Key files:
- `alembic/env.py`: loads metadata and DB URL for migration execution
- `alembic/versions/*.py`: migration history
- `alembic.ini`: migration configuration

Current migration versions:
- `5077d1f0ca7d_initial_schema.py`
- `0e47d2aeb530_clean_start.py`

## 7. Migration Lifecycle
Standard workflow:

1. Update ORM models in `database/models.py`
2. Generate revision:
```bash
alembic revision --autogenerate -m "describe_change"
```
3. Review generated migration carefully
4. Apply migration:
```bash
alembic upgrade head
```
5. Verify schema and app behavior

Rollback when needed:
```bash
alembic downgrade -1
```

## 8. Important Operational Note
`main.py` currently calls:
```python
Base.metadata.create_all(bind=engine)
```

For production migration discipline, prefer Alembic as the only schema-change path. Keeping both can cause schema drift and deployment unpredictability.

## 9. Future Scalability Considerations
- Add and tune indexes based on production query patterns.
- Introduce read replicas for heavy read endpoints.
- Consider partitioning for high-volume audit/payment/event tables.
- Move long-running analytics to pre-aggregated tables or async jobs.
- Define explicit retention and archival policies for large historical data.
