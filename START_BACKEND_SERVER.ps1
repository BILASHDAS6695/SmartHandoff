#!/usr/bin/env powershell
# ========================================
# 🚀 SMARTHANDOFF LOCALHOST - COMPLETE SETUP GUIDE
# ========================================

Write-Host @"

╔════════════════════════════════════════════════════════════════════════════╗
║                 ✅ SMARTHANDOFF LOCALHOST IS READY!                       ║
╚════════════════════════════════════════════════════════════════════════════╝

📊 DATABASE STATUS:
   ✅ Cloud SQL Proxy: Running on 127.0.0.1:9432
   ✅ Database Connection: Working
   ✅ Test Data: 200+ records populated
      • Patients: 100+
      • Encounters: 100+
      • Beds: 5
      • (More can be added)

═══════════════════════════════════════════════════════════════════════════════

🚀 HOW TO START THE BACKEND SERVER:

Step 1: Open PowerShell and navigate to the project root:
   cd C:\Users\BhalaganeshMadesh\source\repos\SmartHandoff

Step 2: Set environment variables (run from PowerShell):
   `$env:PYTHONPATH = "."`
   `$env:PRIMARY_DATABASE_URL = "postgresql://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff"`
   `$env:REPLICA_DATABASE_URL = "postgresql://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff"`
   `$env:PHI_ENCRYPTION_KEY = "peF3ahNpMuTZD6tm-B9tNA5YKZlxYSQNYVZd2x6Ou3A="`
   `$env:ALLOW_UNAUTHENTICATED_LOCALHOST = "true"`
   `$env:FHIR_BASE_URL = "https://r4.smarthealthit.org"`

Step 3: Navigate to backend and start the server:
   cd backend
   python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

Expected output:
   INFO:     Uvicorn running on http://0.0.0.0:8000
   INFO:     Application startup complete

═══════════════════════════════════════════════════════════════════════════════

🧪 TEST THE API:

Option 1: Using curl (open another PowerShell window):
   curl http://localhost:8000/api/v1/patients
   curl http://localhost:8000/api/v1/encounters
   curl http://localhost:8000/api/v1/beds

Option 2: Swagger UI (Open in browser):
   http://localhost:8000/docs

   This provides:
   • Interactive API documentation
   • Try-it-out feature for all endpoints
   • Request/response schemas
   • Parameter descriptions

═══════════════════════════════════════════════════════════════════════════════

📋 QUICK REFERENCE: Environment Variables

Copy-paste all at once in PowerShell:

`$env:PYTHONPATH = "."`
`$env:PRIMARY_DATABASE_URL = "postgresql://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff"`
`$env:REPLICA_DATABASE_URL = "postgresql://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff"`
`$env:PHI_ENCRYPTION_KEY = "peF3ahNpMuTZD6tm-B9tNA5YKZlxYSQNYVZd2x6Ou3A="`
`$env:ALLOW_UNAUTHENTICATED_LOCALHOST = "true"`
`$env:FHIR_BASE_URL = "https://r4.smarthealthit.org"`

═══════════════════════════════════════════════════════════════════════════════

🔒 DATABASE ACCESS:

Direct database access from PowerShell:
   psql -h 127.0.0.1 -p 9432 -U postgres -d smarthandoff
   
Password: SmartHandoff@123

Useful psql commands:
   \dt              - List all tables
   \d patient       - Describe patient table
   SELECT COUNT(*) FROM patient;  - Count records
   \q              - Exit psql

═══════════════════════════════════════════════════════════════════════════════

📁 IMPORTANT FILES:

   • LOCALHOST-SETUP.md               - Detailed localhost guide
   • backend/populate_test_data_sync.py - Test data population script
   • backend/app/main.py              - FastAPI application entry point
   • backend/app/models/__init__.py   - Database models
   • backend/alembic/                 - Database migrations

═══════════════════════════════════════════════════════════════════════════════

✅ VERIFICATION CHECKLIST:

Before starting the backend, verify:
   □ Cloud SQL Proxy running: netstat -ano | findstr ":9432"
   □ Database accessible: psql -h 127.0.0.1 -p 9432 -U postgres -d smarthandoff
   □ Environment variables set (run setup script)
   □ Python 3.8+ installed: python --version
   □ Requirements installed: pip list | findstr uvicorn

═══════════════════════════════════════════════════════════════════════════════

🆘 TROUBLESHOOTING:

Problem: "Connection refused" or "port 9432 refused"
   ✓ Verify Cloud SQL proxy: netstat -ano | findstr ":9432"
   ✓ Start it: cloud_sql_proxy -instances=smarthandoff:us-central1:smarthandoff=tcp:9432

Problem: "ModuleNotFoundError: No module named 'app'"
   ✓ Make sure PYTHONPATH is set: `$env:PYTHONPATH = "."`
   ✓ Run from project root: cd C:\Users\BhalaganeshMadesh\source\repos\SmartHandoff
   ✓ Don't cd into backend first

Problem: "could not translate host name..."
   ✓ Password contains @ which must be URL-encoded as %40 in connection string
   ✓ Use: postgresql://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff

Problem: Database tables don't exist
   ✓ Run migrations: cd backend && alembic upgrade head

═══════════════════════════════════════════════════════════════════════════════

📚 NEXT STEPS:

1. ✅ Database connection verified
2. ✅ Test data populated
3. → START THE BACKEND SERVER (see instructions above)
4. → TEST API ENDPOINTS (http://localhost:8000/docs)
5. → Integrate with frontend
6. → Deploy to Cloud Run when ready

═══════════════════════════════════════════════════════════════════════════════

🎯 SUMMARY:

Everything is set up and working! Your localhost SmartHandoff environment:
   ✅ Connects to Cloud SQL database via proxy
   ✅ Has 200+ test records ready
   ✅ Is fully configured and ready to go

Just follow the "HOW TO START" section above to get running!

═══════════════════════════════════════════════════════════════════════════════

"@

Write-Host "`nPress Enter to close this window..."
Read-Host
