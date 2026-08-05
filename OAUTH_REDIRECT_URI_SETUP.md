# OAuth Redirect URI Setup Guide

## Problem
`Error 400: redirect_uri_mismatch` when accessing the production URL.

## Solution
Add the production redirect URI to your Google OAuth client.

---

## Step-by-Step Instructions

### 1. Open Google Cloud Console
Go to: https://console.cloud.google.com/apis/credentials?project=smarthandoff

### 2. Find Your OAuth Client
- Look for Client ID: `52528248131-kdk6um989bnrr80v61890b3kpeqqm5nt`
- Click the **pencil icon (✏️)** to edit

### 3. Add Redirect URIs
Scroll down to **"Authorized redirect URIs"** section.

Click **"+ ADD URI"** and add these three URIs:

#### Production URI (REQUIRED - fixes the error)
```
https://smarthandoff-frontend-52528248131.us-central1.run.app/auth/callback
```

#### Local Development URIs
```
http://localhost:50029/auth/callback
```

```
http://localhost:4200/auth/callback
```

### 4. Save Changes
- Click **"SAVE"** at the bottom of the page
- Wait 30-60 seconds for Google to propagate the changes

### 5. Test
- Clear your browser cache or use incognito mode
- Try accessing: https://smarthandoff-frontend-52528248131.us-central1.run.app
- The Google sign-in should now work!

---

## Current Configuration

**Project**: smarthandoff  
**OAuth Client ID**: 52528248131-kdk6um989bnrr80v61890b3kpeqqm5nt.apps.googleusercontent.com  
**Frontend Environment**: Google OAuth (SKIP_AUTH: false)  

---

## After Adding Redirect URIs

Once saved, your OAuth client will accept authentication requests from:
- ✅ Production Cloud Run: https://smarthandoff-frontend-52528248131.us-central1.run.app
- ✅ Local development: http://localhost:4200 and http://localhost:50029

---

## Troubleshooting

If the error persists after adding the URI:
1. Wait a full minute for Google to propagate changes
2. Clear browser cache / use incognito mode
3. Verify the URI was saved correctly in the console
4. Check that the URI matches exactly (including /auth/callback path)
5. Ensure no extra spaces or typos in the URI
