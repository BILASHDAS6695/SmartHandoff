# Frontend Build Error Troubleshooting Guide

## Common Build Errors and Solutions

### Error 1: "npm ERR! code ELIFECYCLE" or "Angular build failed"

**Possible Cause:** Missing files or dependencies

**Solution:**
```bash
# In Cloud Shell, before deploying:
cd SmartHandoff/frontend

# Verify all source files are present
ls -la src/
ls -la src/app/

# If files are missing, ensure they're not in .gcloudignore
cat .gcloudignore
```

**Fix:** Update `.gcloudignore` to only exclude:
```
# .gcloudignore
.git
.gitignore
node_modules/
.angular/
dist/
coverage/
*.log
```

---

### Error 2: "node_modules/ not found" or "Cannot find module"

**Possible Cause:** .gcloudignore is excluding too much

**Solution:** The `.gcloudignore` should NOT exclude `src/` or `package.json`

**Verify your .gcloudignore:**
```bash
cat .gcloudignore
```

**Should look like this:**
```
node_modules/
dist/
.git/
coverage/
*.log
```

**NOT like this (WRONG):**
```
# DON'T exclude these:
src/          ❌ BAD
package.json  ❌ BAD
angular.json  ❌ BAD
```

---

### Error 3: "Out of memory" during npm install

**Solution:** Use a larger Cloud Build machine

**Update cloudbuild-frontend.yaml:**
```yaml
options:
  machineType: 'E2_HIGHCPU_8'  # Use more powerful machine
  
timeout: '1800s'  # Increase timeout to 30 minutes
```

---

### Error 4: "Error: Cannot find module '@angular/core'"

**Possible Cause:** Incorrect NODE_ENV or npm ci fails

**Solution:** Modify Dockerfile to use npm install instead:

```dockerfile
# Change this line in Dockerfile:
RUN npm ci

# To this:
RUN npm install --legacy-peer-deps
```

---

### Error 5: Build completes but files not copied correctly

**Check the build output in Cloud Build logs:**
```
Step 16: RUN ls -la /app/dist/smarthandoff-frontend/
```

**If you see "browser" folder:** ✅ Good
**If "browser" folder is missing:** ❌ Build path issue

**Fix:** Check angular.json output path:
```json
{
  "outputPath": "dist/smarthandoff-frontend"
}
```

---

## Quick Fix: Simplified Dockerfile

If all else fails, use this simplified version:

```dockerfile
# Stage 1: Build
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm install --legacy-peer-deps
COPY . .
RUN npm run build:prod

# Stage 2: Serve
FROM nginx:alpine
RUN rm -rf /etc/nginx/conf.d/default.conf /usr/share/nginx/html/*
COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=builder /app/dist/smarthandoff-frontend/browser /usr/share/nginx/html
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
```

---

## Debugging Steps in Cloud Shell

### Step 1: Test build locally in Cloud Shell
```bash
cd SmartHandoff/frontend

# Try building manually
npm install
npm run build:prod

# Check output
ls -la dist/smarthandoff-frontend/browser/
```

### Step 2: Check what files are being uploaded
```bash
# See what Cloud Build will upload
gcloud meta list-files-for-upload

# Or manually check
find . -type f | head -20
```

### Step 3: View detailed build logs
```bash
# Get recent builds
gcloud builds list --limit=5

# View logs for a specific build
gcloud builds log <BUILD_ID>
```

### Step 4: Build Docker image manually for testing
```bash
# Build locally in Cloud Shell
docker build -t test-frontend .

# If successful, tag and deploy
docker tag test-frontend gcr.io/smarthandoff/smarthandoff-frontend:test
docker push gcr.io/smarthandoff/smarthandoff-frontend:test

# Deploy the tested image
gcloud run deploy smarthandoff-frontend \
  --image gcr.io/smarthandoff/smarthandoff-frontend:test \
  --region us-central1 \
  --allow-unauthenticated
```

---

## Alternative: Deploy Without Cloud Build

Skip Cloud Build and deploy a pre-built image:

```bash
cd SmartHandoff/frontend

# Build and push directly
gcloud builds submit --tag gcr.io/smarthandoff/smarthandoff-frontend

# Deploy
gcloud run deploy smarthandoff-frontend \
  --image gcr.io/smarthandoff/smarthandoff-frontend \
  --region us-central1 \
  --allow-unauthenticated \
  --port 8080
```

---

## Get Help

**Share these with me to diagnose:**

1. **The exact error message** from Cloud Shell
2. **Build logs** - Copy the error section
3. **Files in frontend directory:**
   ```bash
   ls -la frontend/
   ```
4. **Content of .gcloudignore:**
   ```bash
   cat frontend/.gcloudignore
   ```

---

**Most Common Issue:** .gcloudignore excluding source files

**Quick test:**
```bash
cat .gcloudignore
# Should only exclude: node_modules/, dist/, .git/, coverage/, *.log
# Should NOT exclude: src/, package.json, angular.json
```
