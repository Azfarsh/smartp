# Google OAuth Configuration Fix

## Issues Fixed

1. ✅ **Django Backend Error**: Fixed the `ValueError` by specifying the authentication backend in the `login()` call
2. ✅ **Error Handling**: Improved error handling to always return JSON responses
3. ⚠️ **Google OAuth Origin Error**: Requires configuration in Google Cloud Console

## How to Fix Google OAuth "Origin Not Allowed" Error

The error **"The given origin is not allowed for the given client ID"** means you need to add your local development origins to your Google OAuth client configuration.

### Steps to Fix:

1. **Go to Google Cloud Console**
   - Visit: https://console.cloud.google.com/
   - Select your project (or create one if needed)

2. **Navigate to OAuth 2.0 Client IDs**
   - Go to: **APIs & Services** → **Credentials**
   - Find your OAuth 2.0 Client ID (the one matching your `GOOGLE_CLIENT_ID`)

3. **Add Authorized JavaScript Origins**
   - Click on your OAuth 2.0 Client ID to edit it
   - Under **"Authorized JavaScript origins"**, click **"+ ADD URI"**
   - Add these origins (one at a time):
     - `http://localhost:8000`
     - `http://127.0.0.1:8000`
     - `http://localhost:8000/` (with trailing slash)
     - `http://127.0.0.1:8000/` (with trailing slash)

4. **Add Authorized Redirect URIs** (if needed)
   - Under **"Authorized redirect URIs"**, add:
     - `http://localhost:8000/auth-receiver/`
     - `http://127.0.0.1:8000/auth-receiver/`

5. **Save Changes**
   - Click **"SAVE"** at the bottom
   - Wait a few minutes for changes to propagate

6. **Test Again**
   - Restart your Django server
   - Clear browser cache/cookies
   - Try logging in again

### For Production

When deploying to production, make sure to add your production domain:
- `https://yourdomain.com`
- `https://www.yourdomain.com`

## Current Configuration

Your Django settings already have:
- ✅ `SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin-allow-popups'` (correctly set)
- ✅ `CSRF_TRUSTED_ORIGINS` includes localhost origins
- ✅ Error handling improved to return JSON responses

## Testing

After fixing the Google OAuth configuration:
1. Restart your Django server
2. Clear browser cache
3. Try logging in with Google
4. Check the browser console for any remaining errors

## Common Issues

- **"Origin not allowed"**: Add the origin to Google Cloud Console (see steps above)
- **"Invalid client ID"**: Verify your `GOOGLE_CLIENT_ID` environment variable matches the one in Google Cloud Console
- **CORS errors**: Already handled by Django settings, but verify `CSRF_TRUSTED_ORIGINS` includes your domain

