# 🚀 SmartHandoff Localhost Setup Guide

## ✅ Connection Status

**Database Connection:** ✅ WORKING
- **Host:** 127.0.0.1
- **Port:** 9432 (Cloud SQL Proxy)
- **Database:** smarthandoff
- **Connection Method:** PostgreSQL via Cloud SQL Proxy

## 📊 Current Database State

```
✅ Tables Found: 12
   • adt_event
   • agent_task
   • alembic_version
   • app_user
   • audit_log
   • bed
   • chatbot_transcript
   • document
   • encounter
   • medication
   • notification
   • patient

✅ Current Records:
   • patient:       100+ records
   • encounter:     100+ records  
   • bed:           5 records
   • medication:    0 records
   • agent_task:    0 records
   • document:      0 records
   • notification:  0 records
   • (other tables empty)
```

## 🚀 Quick Start

### 1. Verify Cloud SQL Proxy is Running

The Cloud SQL proxy should be running on port 9432. If not, start it:

```powershell
# From C:\Program Files (x86)\Google\Cloud SDK\
cloud_sql_proxy -instances=smarthandoff:us-central1:smarthandoff=tcp:9432 -enable_iam_login
```

You should see:
```
Listening on 127.0.0.1:9432 for smarthandoff:us-central1:smarthandoff
Ready for new connections
```

### 2. Connect to Database from PowerShell

```powershell
# Set environment variables
$env:PYTHONPATH = "backend"
$env:PRIMARY_DATABASE_URL = "postgresql://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff"
$env:REPLICA_DATABASE_URL = "postgresql://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff"
$env:PHI_ENCRYPTION_KEY = "peF3ahNpMuTZD6tm-B9tNA5YKZlxYSQNYVZd2x6Ou3A="
$env:ALLOW_UNAUTHENTICATED_LOCALHOST = "true"
$env:FHIR_BASE_URL = "https://r4.smarthealthit.org"
```

### 3. Start Backend Server

```powershell
cd backend

# Set environment first (from step 2 above)
$env:PYTHONPATH = "backend"
$env:PRIMARY_DATABASE_URL = "postgresql://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff"
$env:REPLICA_DATABASE_URL = "postgresql://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff"
$env:PHI_ENCRYPTION_KEY = "peF3ahNpMuTZD6tm-B9tNA5YKZlxYSQNYVZd2x6Ou3A="
$env:ALLOW_UNAUTHENTICATED_LOCALHOST = "true"
$env:FHIR_BASE_URL = "https://r4.smarthealthit.org"

# Start server
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete
```

### 4. Test API Endpoints

In another terminal:

```powershell
# Test basic connection
curl http://localhost:8000/api/v1/patients

# Get encounters
curl http://localhost:8000/api/v1/encounters

# Get beds
curl http://localhost:8000/api/v1/beds

# Health check
curl http://localhost:8000/docs  # Opens Swagger UI in browser
```

## 🔧 Common Tasks

### Connect to Database with psql

```powershell
# Install PostgreSQL tools if needed
# Then:
psql -h 127.0.0.1 -p 9432 -U postgres -d smarthandoff
```

Password: `SmartHandoff@123`

### Run Database Migrations

```powershell
cd backend
$env:PRIMARY_DATABASE_URL = "postgresql://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff"

# Check migration status
alembic current

# Run migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1
```

### Query Database Directly

```powershell
python test_db_connection.py
```

### View Database Tables

```powershell
psql -h 127.0.0.1 -p 9432 -U postgres -d smarthandoff
# In psql:
\dt              # List all tables
\d patient       # Describe patient table
SELECT * FROM patient LIMIT 5;  # View patient data
```

## ⚠️ Important Notes

### Password Encoding
The database password `SmartHandoff@123` contains `@` which must be URL-encoded as `%40` in connection strings:

```
✅ CORRECT:   postgresql://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff
❌ WRONG:     postgresql://postgres:SmartHandoff@123@127.0.0.1:9432/smarthandoff
```

### Environment Variables
Always set these before running the backend:

```powershell
$env:PRIMARY_DATABASE_URL = "postgresql://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff"
$env:REPLICA_DATABASE_URL = "postgresql://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff"
$env:PHI_ENCRYPTION_KEY = "peF3ahNpMuTZD6tm-B9tNA5YKZlxYSQNYVZd2x6Ou3A="
$env:ALLOW_UNAUTHENTICATED_LOCALHOST = "true"
$env:FHIR_BASE_URL = "https://r4.smarthealthit.org"
```

## 📋 Troubleshooting

### Connection Refused
```
Error: connection to server at "127.0.0.1", port 9432 failed: Connection refused
```
**Solution:** Verify Cloud SQL proxy is running:
```powershell
netstat -ano | findstr ":9432"
```

### Authentication Failed
```
Error: password authentication failed for user "postgres"
```
**Solution:** Verify password is correct and properly URL-encoded

### Module Import Errors
```
ModuleNotFoundError: No module named 'app'
```
**Solution:** Make sure you're in the backend directory and PYTHONPATH is set:
```powershell
cd backend
$env:PYTHONPATH = "."
```

### Table Not Found
```
ProgrammingError: relation "patient" does not exist
```
**Solution:** Run database migrations:
```powershell
alembic upgrade head
```

## ✅ Verification Checklist

- [ ] Cloud SQL Proxy running on 127.0.0.1:9432
- [ ] Database connection working (can run `psql` command)
- [ ] Environment variables set correctly
- [ ] Backend server starts without errors
- [ ] Can access Swagger UI at http://localhost:8000/docs
- [ ] Can query API endpoints (GET /api/v1/patients, etc.)
- [ ] Database contains test data
- [ ] Migrations are up to date

## 📚 API Documentation

Once the server is running, view the API docs at:
```
http://localhost:8000/docs
```

This opens the interactive Swagger UI where you can:
- See all available endpoints
- View request/response schemas
- Test API calls directly
- Read parameter descriptions

## 🆘 Need Help?

Check these files for more information:
- [DEPLOYMENT-GUIDE.md](./DEPLOYMENT-GUIDE.md) - Production deployment
- [FIREBASE-SETUP-GUIDE.md](./FIREBASE-SETUP-GUIDE.md) - Firebase configuration
- [backend/requirements.txt](./backend/requirements.txt) - Dependencies
- [backend/app/main.py](./backend/app/main.py) - Application entry point

---

✅ **Everything is set up and working on localhost!** Start with step 3 (Start Backend Server) above.
