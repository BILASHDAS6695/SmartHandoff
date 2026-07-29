# US-063 Quick Start - Testing & Deployment Guide

**Status**: ✅ READY TO TEST  
**Time to First Test**: < 2 minutes  
**Estimated Total Time**: 10-15 minutes

---

## 🚀 Quick Start (5 Steps)

### Step 1: Navigate to Backend
```bash
cd services/api-gateway
```

### Step 2: Run All Export Tests
```bash
pytest tests/unit/export/ -v
```

**Expected Output**:
```
tests/unit/export/test_export_router.py::test_validate_date_range_accepts_valid_range PASSED
tests/unit/export/test_export_router.py::test_validate_date_range_rejects_inverted_range PASSED
tests/unit/export/test_export_router.py::test_validate_date_range_rejects_excessive_range PASSED
tests/unit/export/test_export_router.py::test_rbac_allows_manager PASSED
tests/unit/export/test_export_router.py::test_rbac_allows_admin PASSED
tests/unit/export/test_export_router.py::test_rbac_denies_nurse PASSED

tests/unit/export/test_csv_exporter.py::test_assert_no_phi_allows_safe_columns PASSED
tests/unit/export/test_csv_exporter.py::test_assert_no_phi_blocks_phi_columns PASSED
tests/unit/export/test_csv_exporter.py::test_csv_streaming_response_format PASSED
... (more tests)

tests/unit/export/test_pdf_chart_renderer.py::test_render_all_charts_count PASSED
... (more tests)

tests/unit/export/test_export_integration.py::test_csv_export_workflow_complete PASSED
tests/unit/export/test_export_integration.py::test_pdf_export_202_workflow_complete PASSED
tests/unit/export/test_export_integration.py::test_rbac_enforcement_on_export PASSED
... (more tests)

======================== 24+ passed in X.XXs =========================
```

✅ **If all tests pass, move to Step 3**

### Step 3: Start the API
```bash
python -m uvicorn app.main:app --reload
```

**Expected Output**:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete
```

### Step 4: Test CSV Export Endpoint
In a new terminal:
```bash
# Replace <jwt_token> with a valid manager/admin JWT token
curl -X GET "http://localhost:8000/api/v1/analytics/export?format=csv&from=2024-01-01&to=2024-01-31" \
  -H "Authorization: Bearer <jwt_token>" \
  -o kpi_report.csv
```

**Expected**:
- File `kpi_report.csv` created
- File contains CSV headers + KPI data
- No PHI fields present
- HTTP 200 response

### Step 5: Test PDF Export Workflow
In the same terminal:

**Step 5a: Initiate PDF Export**
```bash
curl -X GET "http://localhost:8000/api/v1/analytics/export?format=pdf&from=2024-01-01&to=2024-01-31" \
  -H "Authorization: Bearer <jwt_token>" \
  -H "Content-Type: application/json"
```

**Expected Response**:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "processing",
  "poll_url": "/api/v1/analytics/export/status/550e8400-e29b-41d4-a716-446655440000"
}
```

Copy the `job_id` for next step.

**Step 5b: Poll Status (repeat 2-3 times)**
```bash
# Replace job_id with the ID from Step 5a
curl -X GET "http://localhost:8000/api/v1/analytics/export/status/550e8400-e29b-41d4-a716-446655440000" \
  -H "Authorization: Bearer <jwt_token>"
```

**Expected Response (Processing)**:
```json
{
  "status": "processing",
  "download_url": null
}
```

**Expected Response (Complete)**:
```json
{
  "status": "complete",
  "download_url": "/api/v1/analytics/export/download/550e8400-e29b-41d4-a716-446655440000?filename=kpi_report_2024-01-01_2024-01-31.pdf"
}
```

**Step 5c: Download PDF**
```bash
curl -X GET "http://localhost:8000/api/v1/analytics/export/download/550e8400-e29b-41d4-a716-446655440000?filename=kpi_report.pdf" \
  -H "Authorization: Bearer <jwt_token>" \
  -o kpi_report.pdf
```

**Expected**:
- File `kpi_report.pdf` created
- File contains 5 charts embedded
- File has proper PDF headers
- HTTP 200 response

✅ **If all steps work, implementation is ready!**

---

## 🧪 Test Scenarios

### Test 1: CSV Export Success
```bash
# Manager/Admin can export CSV
curl "http://localhost:8000/api/v1/analytics/export?format=csv&from=2024-01-01&to=2024-01-31" \
  -H "Authorization: Bearer <manager_token>"
# Expected: 200 OK + CSV file
```

### Test 2: PDF Export Success
```bash
# Manager/Admin can export PDF (returns 202 Accepted)
curl "http://localhost:8000/api/v1/analytics/export?format=pdf&from=2024-01-01&to=2024-01-31" \
  -H "Authorization: Bearer <admin_token>"
# Expected: 202 Accepted + { job_id, poll_url }
```

### Test 3: RBAC Denial (Nurse)
```bash
# Nurse cannot export (should get 403)
curl "http://localhost:8000/api/v1/analytics/export?format=csv&from=2024-01-01&to=2024-01-31" \
  -H "Authorization: Bearer <nurse_token>"
# Expected: 403 Forbidden
```

### Test 4: Invalid Date Range (Inverted)
```bash
# from > to should fail
curl "http://localhost:8000/api/v1/analytics/export?format=csv&from=2024-01-31&to=2024-01-01" \
  -H "Authorization: Bearer <manager_token>"
# Expected: 400 Bad Request
```

### Test 5: Invalid Date Range (Too Long)
```bash
# Range > 366 days should fail
curl "http://localhost:8000/api/v1/analytics/export?format=csv&from=2023-01-01&to=2024-12-31" \
  -H "Authorization: Bearer <manager_token>"
# Expected: 400 Bad Request
```

---

## 🔍 Debugging Guide

### Issue: Tests Fail with Import Error
```
ImportError: No module named 'app.export.csv_exporter'
```
**Solution**: 
```bash
# Make sure you're in the right directory
cd services/api-gateway
# Install dependencies
pip install -r requirements.txt
```

### Issue: Tests Fail with Async Error
```
RuntimeError: no running event loop
```
**Solution**: This should be fixed now. If you see this:
1. Check that test functions are NOT decorated with `@pytest.mark.asyncio`
2. Check that test functions are NOT using `await` on sync dependencies
3. Run: `git pull` to ensure you have the latest fixes

### Issue: API Won't Start
```
ERROR: Could not import app.main
```
**Solution**:
```bash
# Check Python version
python --version  # Should be 3.9+
# Check FastAPI is installed
pip install fastapi uvicorn
# Try starting again
python -m uvicorn app.main:app --reload
```

### Issue: 404 on Export Endpoint
```
{"detail":"Not Found"}
```
**Solution**:
- Verify API is running: `python -m uvicorn app.main:app --reload`
- Verify correct path: Should be `/api/v1/analytics/export`
- Verify your JWT token is valid and includes authorization header

### Issue: 403 Forbidden
```
{"detail":"Insufficient permissions for this resource"}
```
**Solution**:
- You're using a non-manager/non-admin token
- Use a JWT token with role "manager" or "admin"
- For testing, create a test token with admin role

---

## 📋 Verification Checklist

After running Quick Start, verify:

- [ ] All pytest tests pass (24+)
- [ ] API starts without errors
- [ ] CSV export returns 200 with CSV file
- [ ] PDF export returns 202 with job_id
- [ ] Status polling returns job status
- [ ] PDF download returns 200 with PDF file
- [ ] RBAC denies nurse role (403)
- [ ] Date validation rejects invalid ranges (400)

✅ **If all checks pass, deployment is ready!**

---

## 🚀 Deployment Steps

### For Development Environment
```bash
# 1. Run tests
cd services/api-gateway
pytest tests/unit/export/ -v

# 2. Start development server
python -m uvicorn app.main:app --reload

# 3. Test endpoints manually
curl http://localhost:8000/api/v1/analytics/export?format=csv&from=2024-01-01&to=2024-01-31 \
  -H "Authorization: Bearer <token>"
```

### For Staging/Production
```bash
# 1. Run full test suite
pytest tests/unit/ -v

# 2. Run integration tests specifically
pytest tests/unit/export/test_export_integration.py -v

# 3. Build Docker image
docker build -t api-gateway:latest .

# 4. Deploy using your CI/CD pipeline
# (e.g., Cloud Build, GitHub Actions, GitLab CI)

# 5. Verify deployment
curl https://<your-api>/api/v1/analytics/export?format=csv&from=2024-01-01&to=2024-01-31 \
  -H "Authorization: Bearer <token>"
```

---

## 🎯 Success Criteria

✅ **You're done when:**
1. All 24+ tests pass
2. CSV export works (200 OK + CSV file)
3. PDF export works (202 Accepted → polling → 200 OK + PDF file)
4. RBAC works (403 for nurse, 200 for manager/admin)
5. Date validation works (400 for invalid ranges)
6. No errors in API logs
7. All endpoints respond correctly

---

## 📞 Common Commands Reference

### Run All Tests
```bash
cd services/api-gateway
pytest tests/unit/export/ -v
```

### Run Specific Test File
```bash
pytest tests/unit/export/test_export_router.py -v
```

### Run Specific Test Case
```bash
pytest tests/unit/export/test_export_router.py::TestValidateDateRange::test_validate_date_range_accepts_valid_range -v
```

### Run Tests with Coverage Report
```bash
pytest tests/unit/export/ --cov=app.routers --cov=app.export --cov-report=html
# Open htmlcov/index.html in browser
```

### Start API with Debug Logging
```bash
export LOGLEVEL=DEBUG
python -m uvicorn app.main:app --reload --log-level debug
```

### Test API Health
```bash
curl http://localhost:8000/health
# Should return 200 OK
```

---

## 🎓 Next Steps

After verification, refer to:
- **How to Deploy**: See `DEPLOYMENT-GUIDE.md`
- **Feature Details**: See `US-063-EXECUTION-READY-SUMMARY.md`
- **Troubleshooting**: See `US-063-COMPREHENSIVE-STATUS-DASHBOARD.md`
- **Production Setup**: See `.propel/rules/security-standards-owasp.md`

---

## ✅ Status

```
Implementation:    ✅ Complete
Testing:           ✅ Ready
Documentation:     ✅ Complete
Deployment:        ✅ Ready
```

**You're all set! Start with Step 1 above.** 🚀

---

**Last Updated**: 2024  
**Ready for Testing**: ✅ YES  
**Ready for Deployment**: ✅ YES
