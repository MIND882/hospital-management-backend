# Database Migrations

## Purpose
Track all database schema changes over time without losing data.

## Files
- `add_missing_columns.sql` - Initial migration (2026-01-31)

## How to Run
```bash
psql -U medicare_admin -d medicare -f migrations/add_missing_columns.sql
```

## Rules
1. ✅ NEVER delete migrations folder
2. ✅ NEVER modify old migration files
3. ✅ Always create NEW migration file for changes
4. ✅ Test on staging before production
5. ✅ Always backup before running migrations

## Backup Command
```bash
pg_dump medicare > backup_$(date +%Y%m%d_%H%M%S).sql
```
```

---

## **🎯 FINAL FOLDER STRUCTURE:**
```
medicare-backend/
├── migrations/                      ✅ NEW
│   ├── README.md                    ✅ NEW
│   └── add_missing_columns.sql      ✅ NEW
├── api/
│   ├── __init__.py
│   ├── auth.py                      ✅ DONE
│   ├── appointments.py              ✅ DONE
│   ├── emergency.py                 ✅ DONE
│   ├── pharmacy.py                  ✅ DONE
│   ├── lab_tests.py                 ✅ DONE
│   └── dashboard.py                 ✅ DONE
├── database/
│   ├── __init__.py
│   ├── connection.py
│   ├── models.py
│   └── schema.sql
├── main.py
├── requirements.txt
└── .env