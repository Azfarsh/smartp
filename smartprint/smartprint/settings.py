import os
from pathlib import Path
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials

# Load environment variables
load_dotenv()


def _split_env_list(value):
    """Return a cleaned list from a comma-separated env var."""
    if not value:
        return []
    return [item.strip() for item in value.split(',') if item.strip()]


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-your-secret-key')

# SECURITY WARNING: don't run with debug turned on in production!
# Default to True for local testing (override via .env DEBUG=False in prod)
DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'

# Local testing hosts + production domain + tunneling domains
ALLOWED_HOSTS = [
    'localhost',
    '127.0.0.1',
    '0.0.0.0',
    'printmax.onrender.com',
    'printmax.in',
    '.ngrok-free.app',
    '.ngrok-free.dev',
]
ALLOWED_HOSTS += _split_env_list(os.getenv('ALLOWED_HOSTS_EXTRA'))
ALLOWED_HOSTS = list(dict.fromkeys(ALLOWED_HOSTS))  # Drop duplicates while preserving order

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'channels',
    'print',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'print.middleware.SessionValidationMiddleware',  # ✅ Custom session validation
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'smartprint.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'smartprint.wsgi.application'
ASGI_APPLICATION = 'smartprint.asgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]

# WhiteNoise configuration for static files
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Google OAuth Configuration
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')

# Allow popups for Google Sign-In. This is necessary to prevent the
# "postMessage" error with the Google Sign-In popup.
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin-allow-popups'

# ─────────────────────────────────────────────────────────────
# Firebase Cloud Messaging (FCM) Configuration
# ─────────────────────────────────────────────────────────────

# Firebase Project Configuration (from Firebase Console > Project Settings > General)
FIREBASE_CONFIG = {
    'apiKey': os.getenv('FIREBASE_API_KEY', 'AIzaSyBZxTJfCiwyYdeuHLDUuACG_cPeqrz2MYw'),  # Get from Firebase Console
    'authDomain': os.getenv('FIREBASE_AUTH_DOMAIN', 'smartprint-9e291.firebaseapp.com'),
    'projectId': os.getenv('FIREBASE_PROJECT_ID', 'smartprint-9e291'),
    'storageBucket': os.getenv('FIREBASE_STORAGE_BUCKET', 'smartprint-9e291.appspot.com'),
    'messagingSenderId': os.getenv('FIREBASE_MESSAGING_SENDER_ID', '101846981910632623946'),
    'appId': os.getenv('FIREBASE_APP_ID', '1:101846981910632623946:web:1:48548800228:web:a2b523c97d5824f1836ef1'),  # Get from Firebase Console > Project Settings > General > Your apps (Web app)
}

# VAPID Keys for Web Push (from Firebase Console > Project Settings > Cloud Messaging)
FIREBASE_VAPID_PUBLIC_KEY = os.getenv('FIREBASE_VAPID_PUBLIC_KEY', 'BEgXPYZmK1CuT3BJX7nn00h4TIyY1faOk6Ei3BtYLTpRhTOIu8qcZZHrxg05aDEAkbShRP7wMbgXb4NwsADD838')
FIREBASE_VAPID_PRIVATE_KEY = os.getenv('FIREBASE_VAPID_PRIVATE_KEY', 'lN_9Q7zeIVR2zqKTfsJwDHJOsl8-zryjU2DeqbwnU5M')

# Firebase Service Account Configuration
# You can either use a JSON file path or provide credentials directly
FIREBASE_SERVICE_ACCOUNT_JSON = {
    "type": "service_account",
    "project_id": "smartprint-9e291",
    "private_key_id": "0819627ebd74ddb083f5ca002b755c4ceed08d0a",
    "private_key": os.getenv('FIREBASE_PRIVATE_KEY', "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCarD7q4T3eOm6r\nVzy0tClhLwM0TVGwInRVMIVbqA5253zOo04Ew0tE2+U17jiVMcIRMtbwC4hNwzWR\nnw/+uEzy9Ngcj+IqkVd6CgQkuwmaEsX9PbKOT9Jo4aUgTObMBCBlZNqPMJLVQtF2\nMG0Bgb69bPmodPPXGdgOurn6xUWSoh+wxPWGSjHHCn6o4sLUNMSKzwLWVqO98e8o\ngstxcDbTSsHHsLho+khd6mwuJZJC2bZA8sUYyuK2fGWyMBPVnN180qUzvd4m1ovY\ncheA9aE19Jffkh2uLCSh9gcllrXjIlXRKMBUpFS7McH0Cu1TXEpIvk/NF/2qKwc7\nW+E8Fvb1AgMBAAECggEABhMTtO6prTlZZ560wlpYcbDLsZBM9JKjjPxia9fRrQmE\nXk97Sn+9AyspZuxk5VqNWVa187qigVovvEI3sL25q1vnMXtm2u6OERcSwbqJoLcE\nUinwlEjQQWMX2T/nW2prN0uj/KPycFTbnD1ko7WCnza+3aJkgce3oUR2GtR1/pqk\nmRdMXINC7/IX3ESqyXb/LPLmGx4BH0RBIas46OSr8h/d8mvkNDI79X48fk8uKsM7\n+k+CWkG61coaxQXRt96ogvCtxmgYoveRafko0b7I5nvpIxnufg2ar+KgtRc3XeBW\njdPoI2mS+phsfjyoNXI5b55ipdn3Slxap+jQea0v1QKBgQDVdpRAa6PcV2Uqj2WW\nrP+DqTV69stcFlRAU6v5h8w7AihCpL1D3yZruAVEqgzmtOzd10taBJdicZjipCX8\nxdnsJ8Ph1FHV18D20dS5HEG8cFgyOmWF2fwwGcDxY1MUFeeLiFzRvN2BlZ/l51Wn\nw5rktfUhJUL7gGWFSWAzv3z+ZwKBgQC5fpZpY9WMJdeeWOSbaL8OyVLdbD4sYBRt\nzisevgwFtlsGvrz5Kzl0IHR+fZti6RPNpSPzBgp/4F4QZ9K3Ocg4CFbxnShokThb\nFdirIWDOsXBjL5bqU6Fz2eBtRTv8Hin3fpaCoY1wa90ASZPvqLhJU+MWOKh+C68n\nzorOrBtOQwKBgGZyY5JLVrggJYh4i7v1ySeKJQWfvleyy7qXrZiziNvlHCdn4wHY\n7hqSlcyvhEORH4EUm7BXNcRkWoijWSvoVL9XElamzKPByXVrnRk+K3phvKJWjnTf\n+n2nTodLMQsZvCemSU3Lw882XSg8j0pVwVf0z/GZbX1A0PhYD9imFToPAoGBAIEg\npChdfS0AsubiTtH4yvfKIktNrMJLaC1AVjgiaFAZr6g0Y2y5MFesuCvN2Lu0MTr4\n+NuWmvyF/jVBcShnqv+Gnq+3jYetgCO4Q4ptw+xfDTOez1n0OfJh+59VkPpjLSfD\nEZeCSum1zLUEg11UgGVbZjvz2SdVjusRFwPkP2XtAoGAGrH1z6MSTL7twZMdfaVO\nEwJZrkrEL2jXCLKpOzpcUXPXyHWA3SWSzxfYA9fTFvUcPoqw6UOI7M5vldVBujsT\n7rF9Yr7zsiUk6UhWAmvW1nofOMiHDSBhGR+LNL+HbStNN0PHDK++FRXNf0XjFD2+\nr1VTaccfMZMIrm1RSH+JH6M=\n-----END PRIVATE KEY-----\n"),
    "client_email": "firebase-adminsdk-fbsvc@smartprint-9e291.iam.gserviceaccount.com",
    "client_id": "101846981910632623946",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-fbsvc%40smartprint-9e291.iam.gserviceaccount.com",
    "universe_domain": "googleapis.com"
}

# Firebase Admin SDK Configuration
FIREBASE_SERVICE_ACCOUNT_PATH = os.getenv('FIREBASE_SERVICE_ACCOUNT_PATH', None)

try:
    if not firebase_admin._apps:
        # Try to use service account from JSON file path first
        if FIREBASE_SERVICE_ACCOUNT_PATH and os.path.exists(FIREBASE_SERVICE_ACCOUNT_PATH):
            cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT_PATH)
            firebase_admin.initialize_app(cred)
            print("✅ Firebase Admin SDK initialized from service account file")
        # Otherwise, use the JSON dictionary from settings
        elif FIREBASE_SERVICE_ACCOUNT_JSON.get('private_key'):
            # Ensure private_key has actual newlines, not literal \n
            firebase_config = FIREBASE_SERVICE_ACCOUNT_JSON.copy()
            if isinstance(firebase_config.get('private_key'), str):
                # Replace literal \n with actual newlines
                firebase_config['private_key'] = firebase_config['private_key'].replace('\\n', '\n')
            try:
                cred = credentials.Certificate(firebase_config)
                firebase_admin.initialize_app(cred)
                print("✅ Firebase Admin SDK initialized from settings")
            except Exception as cert_error:
                # If certificate initialization fails, try without credentials
                print(f"⚠️ Warning: Could not initialize Firebase with certificate: {str(cert_error)}")
                print("⚠️ Firebase Admin SDK initialized without credentials (push notifications won't work)")
                try:
                    firebase_admin.initialize_app()
                except:
                    pass  # Already initialized or other error
        else:
            firebase_admin.initialize_app()
            print("⚠️ Firebase Admin SDK initialized without credentials (push notifications won't work)")
    else:
        print("Firebase Admin SDK already initialized")
except Exception as e:
    print(f"❌ Error initializing Firebase Admin SDK: {str(e)}")
    # Try to initialize without credentials as fallback
    try:
        if not firebase_admin._apps:
            firebase_admin.initialize_app()
            print("⚠️ Firebase Admin SDK initialized without credentials (fallback mode)")
    except:
        pass  # Ignore if already initialized or other error

# Channel layers configuration
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer'
    }
}


# ✅ R2 credentials from .env
R2_ACCESS_KEY = os.getenv('R2_ACCESS_KEY')
R2_SECRET_KEY = os.getenv('R2_SECRET_KEY')
R2_ENDPOINT = os.getenv('R2_ENDPOINT', '').rstrip('/')  # Remove trailing slash
R2_BUCKET = os.getenv('R2_BUCKET')

# ✅ Cloudflare Worker API for D1 Database
# Use environment variables for production deployment
# WORKER_API_URL should be the base URL without any endpoint path
# Example: https://data.azfarshaikh7860.workers.dev
WORKER_API_URL = os.getenv('WORKER_API_URL', 'https://data.azfarshaikh7860.workers.dev')
WORKER_API_KEY = os.getenv('WORKER_API_KEY', 'your-secret-api-key-here-contact-data')

# ✅ PicWish API Configuration
# PicWish API key for image enhancement services
# Get your API key from: https://picwish.com/api
PICWISH_API = os.getenv('PICWISH_API')

# ✅ CORS setup
CORS_ALLOW_ALL_ORIGINS = True  # Use CORS_ALLOWED_ORIGINS in production

VENDOR_ID=1

# ✅ Email Configuration (Hostinger SMTP)
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.hostinger.com')

# Option A: SSL on port 465 (Hostinger recommended)
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '465'))
EMAIL_USE_SSL = os.getenv('EMAIL_USE_SSL', 'True').lower() == 'true'
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'False').lower() == 'true'

# Option B: TLS on port 587 (uncomment if SSL doesn't work)
# EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
# EMAIL_USE_SSL = os.getenv('EMAIL_USE_SSL', 'False').lower() == 'true'
# EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True').lower() == 'true'

EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', 'printmax_support@printmax.in')
# IMPORTANT: Use the EMAIL ACCOUNT password (mailbox password), NOT the hPanel password!
# Get this from: Hostinger hPanel → Email → Manage → Email Accounts → Your Email Account
# Remove any quotes from password if present
email_password = os.getenv('EMAIL_HOST_PASSWORD', 'TH%D6xeaB2z8D&F')
EMAIL_HOST_PASSWORD = email_password.strip("'\"")  # Strip quotes if any
EMAIL_TIMEOUT = int(os.getenv('EMAIL_TIMEOUT', '30'))

# Default email settings - CRITICAL: FROM must match EMAIL_HOST_USER for authentication
# Use only the email address, not formatted version, to avoid authentication issues
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', EMAIL_HOST_USER)
EMAIL_SUBJECT_PREFIX = os.getenv('EMAIL_SUBJECT_PREFIX', '[PrintMax]')

# Email templates directory
EMAIL_TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates', 'emails')

# Test email recipient (optional - for auto-sending test emails after registration)
EMAIL_TEST_TO = os.getenv('EMAIL_TEST_TO', '')

# Razorpay API Keys (set in environment variables)
RAZORPAY_KEY_ID = os.getenv('RAZORPAY_KEY_ID', 'rzp_live_RF2OLAhxugVc5B')
RAZORPAY_KEY_SECRET = os.getenv('RAZORPAY_KEY_SECRET', '5NkBgjtxzJLNAUwhQLTXzsQP')

# Google API Keys
# GOOGLE_DEVELOPER_KEY: Browser API key (with HTTP referrer restrictions) - for frontend Maps JS only
GOOGLE_DEVELOPER_KEY = os.getenv('GOOGLE_DEVELOPER_KEY', '')
# GOOGLE_MAPS_API: Server-side API key (NO referrer restrictions) - for backend Distance Matrix API only
GOOGLE_MAPS_API = os.getenv('GOOGLE_MAPS_API', '')

# ✅ Google OAuth Configuration for Production
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID', 'your-google-client-id-here')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET', 'your-google-client-secret-here')

# ✅ Session Configuration for Persistent Login
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 180  # 6 months (180 days)
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST = True
# For local HTTP testing keep cookies non-secure
SESSION_COOKIE_SECURE = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'

# ✅ Authentication Settings
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/userdashboard/'
LOGOUT_REDIRECT_URL = '/'

# ✅ Custom Authentication Backend for D1 Admin Users
# Use D1AdminUserBackend for admin authentication, fallback to ModelBackend for regular users
AUTHENTICATION_BACKENDS = [
    'print.backends.D1AdminUserBackend',  # Custom backend for D1 admin users
    'django.contrib.auth.backends.ModelBackend',  # Fallback for regular users
]

# ✅ CSRF Settings for local testing + public tunnels
CSRF_TRUSTED_ORIGINS = [
    'http://localhost:8000',
    'http://127.0.0.1:8000',
    'http://0.0.0.0:8000',
    'https://printmax.onrender.com',
    'www.printmax.in',
    'https://printmax.in',
    'https://*.ngrok-free.app',
    'https://*.ngrok-free.dev',
]
CSRF_TRUSTED_ORIGINS += _split_env_list(os.getenv('CSRF_TRUSTED_ORIGINS_EXTRA'))

# Desktop QR location flow override (needed when phones can't reach localhost)
LOCATION_QR_BASE_URL = os.getenv('LOCATION_QR_BASE_URL', '').rstrip('/')

# ✅ Security Settings for local HTTP testing
SECURE_SSL_REDIRECT = False
SECURE_PROXY_SSL_HEADER = None
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True