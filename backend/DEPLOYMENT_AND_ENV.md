# Deployment And Environment

## 1. Environment Strategy
This backend follows environment-driven configuration through `.env` and runtime dependency files. This keeps secrets out of code and allows safe configuration changes per environment.

## 2. `.env` Purpose
`.env` stores environment-specific values such as:

- Database credentials and connection URL
- JWT signing key
- Payment gateway keys
- External provider credentials (SMS, maps, webhooks)

Why this is important:
- Security: sensitive values are not hardcoded.
- Portability: same codebase works in local, staging, production.
- Reliability: deployment behavior is controlled through explicit config.

## 3. Environment Variables
Core variables used by the backend:

| Variable | Purpose | Required In Production |
|---|---|---|
| `DB_USER` | Database username | Yes |
| `DB_PASS` | Database password | Yes |
| `DB_HOST` | Database host | Yes |
| `DB_PORT` | Database port | Yes |
| `DB_NAME` | Database name | Yes |
| `DATABASE_URL` | Full override URL for DB connection | Recommended |
| `SECRET_KEY` | JWT signing key | Yes |
| `RAZORPAY_KEY_ID` | Razorpay public key | Yes (if payments enabled) |
| `RAZORPAY_KEY_SECRET` | Razorpay secret key | Yes (if payments enabled) |
| `RAZORPAY_WEBHOOK_SECRET` | Webhook verification secret | Yes (if webhook enabled) |
| `TWILIO_ACCOUNT_SID` | Twilio account ID | Recommended for OTP |
| `TWILIO_AUTH_TOKEN` | Twilio auth token | Recommended for OTP |
| `TWILIO_PHONE_NUMBER` | SMS sender number | Recommended for OTP |
| `TWILIO_WHATSAPP_NUMBER` | WhatsApp sender | Optional |
| `GOOGLE_MAPS_API_KEY` | Geocoding support | Optional |

## 4. Dependency Files
`requirements.txt`
- Defines Python package versions for app runtime.
- Includes FastAPI, SQLAlchemy, Alembic, auth, payment, upload, and messaging libraries.

`runtime.txt`
- Pins Python runtime (`python-3.11.9`) for platform consistency.

## 5. Deployment Basics
Recommended production sequence:

1. Build environment and install dependencies.
2. Provide production `.env` values from secret manager.
3. Run Alembic migrations:
```bash
alembic upgrade head
```
4. Start app with production server process (for example, Gunicorn + Uvicorn workers).
5. Verify health endpoint:
```text
GET /health
```

## 6. Configuration And Runtime Notes
- Restrict CORS to trusted frontend origins in production.
- Keep `reload=True` only for local development.
- Prefer Alembic migrations over runtime table creation.
- Keep upload storage strategy environment-aware (local disk in dev, object storage in production).

## 7. Scalability Preparation Checklist
- Use separate configs for local, staging, and production.
- Use managed PostgreSQL with automated backups.
- Enable process scaling with multiple workers/instances.
- Add centralized logging and request tracing.
- Set up monitoring for health, error rates, and latency.
- Add queue/worker layer for heavier background jobs.

## 8. Backend Configuration Philosophy
The project is aligned with production backend principles:

- Config in environment, not in source code.
- Deterministic dependency and runtime versions.
- Schema evolution via migration history.
- Domain modularity that can scale with team growth.
