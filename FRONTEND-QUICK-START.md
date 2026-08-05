# 🚀 SmartHandoff Frontend - Quick Start Guide

## ✅ Frontend Configuration

**Framework:** Angular 17.3+  
**Port:** 4200 (default)  
**Backend API:** http://localhost:8000 (already configured)  
**Authentication:** Google OAuth 2.0

---

## 🚀 HOW TO RUN FRONTEND

### Option 1: NPM Start (Recommended)
```powershell
cd frontend
npm install              # Install dependencies (first time only)
npm start                # Start development server
```

The frontend will open automatically at:
```
http://localhost:4200
```

### Option 2: With All Services (Terminal 1 - Backend, Terminal 2 - Frontend)

**Terminal 1 - Backend:**
```powershell
cd c:\Users\BhalaganeshMadesh\source\repos\SmartHandoff

$env:PYTHONPATH = "."
$env:PRIMARY_DATABASE_URL = "postgresql://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff"
$env:REPLICA_DATABASE_URL = "postgresql://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff"
$env:PHI_ENCRYPTION_KEY = "peF3ahNpMuTZD6tm-B9tNA5YKZlxYSQNYVZd2x6Ou3A="
$env:ALLOW_UNAUTHENTICATED_LOCALHOST = "true"
$env:FHIR_BASE_URL = "https://r4.smarthealthit.org"

cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 - Frontend:**
```powershell
cd c:\Users\BhalaganeshMadesh\source\repos\SmartHandoff\frontend
npm install
npm start
```

---

## 📋 Frontend Features

✅ **Care Team Dashboard**
- Real-time patient updates via SignalR
- Task management for care coordination
- Patient encounter tracking
- Medication reconciliation

✅ **Authentication**
- Google OAuth 2.0 integration
- Secure JWT-based authentication
- Role-based access control

✅ **Real-time Features**
- SignalR for live notifications
- Real-time bed availability
- Live task updates

---

## 🧪 Testing the Full System

### 1. Start Everything (3 Terminals)

**Terminal 1 - Cloud SQL Proxy:**
```
C:\Program Files (x86)\Google\Cloud SDK\
cloud_sql_proxy -instances=smarthandoff:us-central1:smarthandoff=tcp:9432
```

**Terminal 2 - Backend Server:**
```powershell
cd c:\Users\BhalaganeshMadesh\source\repos\SmartHandoff
$env:PYTHONPATH = "."; $env:PRIMARY_DATABASE_URL = "postgresql://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff"; $env:REPLICA_DATABASE_URL = "postgresql://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff"; $env:PHI_ENCRYPTION_KEY = "peF3ahNpMuTZD6tm-B9tNA5YKZlxYSQNYVZd2x6Ou3A="; $env:ALLOW_UNAUTHENTICATED_LOCALHOST = "true"; $env:FHIR_BASE_URL = "https://r4.smarthealthit.org"
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 3 - Frontend Server:**
```powershell
cd c:\Users\BhalaganeshMadesh\source\repos\SmartHandoff\frontend
npm start
```

### 2. Access the Application

- **Frontend:** http://localhost:4200
- **Backend API Docs:** http://localhost:8000/docs
- **Admin Panel:** http://localhost:4200/admin

### 3. Test Features

**View Dashboard:**
```
http://localhost:4200
```

**API Health Check:**
```powershell
curl http://localhost:8000/api/v1/patients
curl http://localhost:8000/api/v1/encounters
```

---

## 🔧 Build Commands

| Command | Purpose |
|---------|---------|
| `npm start` | Start development server (port 4200) |
| `npm run build` | Build for development |
| `npm run build:prod` | Build for production |
| `npm test` | Run unit tests with Jest |
| `npm test:coverage` | Generate test coverage report |
| `npm run lint` | Run Angular linter |

---

## 🚨 Troubleshooting

### "Cannot find module '@angular/cli'"
```powershell
npm install -g @angular/cli
npm install
```

### Port 4200 already in use
```powershell
# Use different port
ng serve --port 4300
```

### Backend connection refused
```
Error: Cannot connect to http://localhost:8000
```
✓ Make sure backend is running on port 8000
✓ Check: http://localhost:8000/docs (should show API docs)

### Google OAuth fails
```
Error: redirect_uri_mismatch
```
✓ Backend OAuth URL must match configured redirect URI
✓ Check environment configuration

---

## 📊 Project Structure

```
frontend/
├── src/
│   ├── app/
│   │   ├── core/              # Services, models, auth
│   │   ├── features/          # Feature modules (auth, dashboard)
│   │   ├── shared/            # Shared components
│   │   ├── app.config.ts      # Main configuration
│   │   └── app.routes.ts      # Routes configuration
│   ├── environments/          # Environment configs
│   ├── assets/                # Static assets
│   └── index.html
├── angular.json               # Angular CLI config
├── package.json               # Dependencies
└── tsconfig.json              # TypeScript config
```

---

## ✅ FULL SYSTEM CHECKLIST

- [ ] Cloud SQL Proxy running on :9432
- [ ] Backend server running on :8000
- [ ] Frontend server running on :4200
- [ ] Can access http://localhost:4200
- [ ] Can see API docs at http://localhost:8000/docs
- [ ] Database has test data
- [ ] Google OAuth configured

---

## 🎉 YOU'RE ALL SET!

Just run `npm start` in the frontend directory and you'll have the full SmartHandoff system running locally!

```
Frontend:     http://localhost:4200
Backend API:  http://localhost:8000/docs
Database:     localhost:9432 (via proxy)
```
