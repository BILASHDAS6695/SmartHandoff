# 🔥 Firebase Authentication Setup Guide

## Why Firebase Auth?
- ✅ **FREE** - Generous free tier (50k MAU)
- ✅ **Already in your GCP project** - No new accounts needed
- ✅ **OIDC compliant** - Works with your existing OAuth code
- ✅ **Quick setup** - 5 minutes to get running

## Step 1: Enable Firebase Authentication

### Open Firebase Console
```bash
https://console.firebase.google.com/project/smarthandoff/authentication
```

### Enable Sign-in Methods
1. Click **Get Started** (if first time)
2. Go to **Sign-in method** tab
3. Enable providers:
   - **Google** (Recommended) - One-click setup
   - **Email/Password** (Optional) - For testing without Google account

## Step 2: Register Web App

### Create App
1. Go to: **Project Settings** (⚙️ gear icon)
2. Scroll to **Your apps** section
3. Click `</>` Web icon
4. Register app:
   - **App nickname:** `SmartHandoff Frontend`
   - **Check:** ☑️ Also set up Firebase Hosting (optional)
   - Click **Register app**

### Copy Configuration
You'll see:
```javascript
const firebaseConfig = {
  apiKey: "AIzaSy...",
  authDomain: "smarthandoff.firebaseapp.com",
  projectId: "smarthandoff",
  storageBucket: "smarthandoff.appspot.com",
  messagingSenderId: "123456789",
  appId: "1:123456789:web:abc123"
};
```

**Save these values! You'll need:**
- `authDomain` → This becomes your IDP URL
- `apiKey` → Your client ID for OAuth

## Step 3: Configure Authorized Domains

### Add Your Domains
1. Still in **Authentication** → **Settings** tab
2. Scroll to **Authorized domains**
3. Click **Add domain**
4. Add:
   - `smarthandoff-frontend-52528248131.us-central1.run.app` (your Cloud Run domain)
   - `localhost` (already there for dev)

## Step 4: Update Frontend Config

### Development Environment
Edit: `frontend/src/environments/environment.ts`

```typescript
export const environment = {
  production: false,
  apiBaseUrl: 'http://localhost:8000',
  // 👇 Replace these with your Firebase values
  idpBaseUrl: 'https://smarthandoff.firebaseapp.com',  // Your authDomain
  oidcClientId: 'YOUR_FIREBASE_API_KEY',              // Your apiKey
  SKIP_AUTH: false,  // Enable real auth now!
};
```

### Production Environment
Edit: `frontend/src/environments/environment.production.ts`

```typescript
export const environment = {
  production: true,
  apiBaseUrl: '',
  idpBaseUrl: 'https://smarthandoff.firebaseapp.com',
  oidcClientId: 'YOUR_FIREBASE_API_KEY',
};
```

## Step 5: Update Backend Config

### Set Environment Variables in Cloud Run

```bash
# Backend API needs to validate Firebase tokens
gcloud run services update smarthandoff-backend \
  --region=us-central1 \
  --update-env-vars="IDP_BASE_URL=https://securetoken.google.com/smarthandoff" \
  --update-env-vars="OIDC_CLIENT_ID=smarthandoff"
```

## Step 6: Test Authentication Flow

### Local Testing
1. Start dev server: `npm start`
2. Navigate to: `http://localhost:50029`
3. Click login → Should redirect to Firebase/Google login
4. After login → Redirects back to dashboard

### Production Testing
1. Deploy updated config:
   ```bash
   git add frontend/src/environments/
   git commit -m "Configure Firebase Authentication"
   git push origin build/development
   ```

2. Navigate to: `https://smarthandoff-frontend-52528248131.us-central1.run.app`
3. Test full OAuth flow

## 🎯 What You Get

| Feature | Status |
|---------|--------|
| Google Sign-In | ✅ One-click login |
| Email/Password | ✅ Optional fallback |
| MFA Support | ✅ Built-in |
| Free Tier | ✅ 50,000 MAU |
| No Separate Account | ✅ Uses your GCP project |

## 🔐 Security Notes

- **authDomain** is publicly visible (not a secret)
- **apiKey** is also public (it's for browser use)
- Backend validates tokens using Firebase Admin SDK
- Firebase handles all OAuth complexity

## 📚 Next Steps

1. Complete Firebase Console setup above
2. Copy your `authDomain` and `apiKey`
3. Run: `code frontend/src/environments/environment.ts`
4. Update the IDP values
5. Test locally with `npm start`

## 🆘 Troubleshooting

### "auth/unauthorized-domain"
- Add your domain to **Authorized domains** in Firebase Console
- Common missing: Cloud Run domain

### "Token validation failed"
- Backend needs `IDP_BASE_URL=https://securetoken.google.com/YOUR_PROJECT_ID`
- Not the authDomain - different for validation!

### Still seeing old IDP URL
- Clear browser cache
- Rebuild Angular: `npm run build`
- Check environment file is correct

---

**Ready?** Complete Steps 1-2 in Firebase Console, then copy your config values!
