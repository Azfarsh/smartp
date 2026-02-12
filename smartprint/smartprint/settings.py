import os
from pathlib import Path
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials

# Load environment variables (from project root or parent .env)
load_dotenv()
# Also try workspace root .env (e.g. smartprepit/.env)
_env_path = Path(__file__).resolve().parent.parent.parent.parent / '.env'
if _env_path.exists():
    load_dotenv(_env_path)


def _split_env_list(value):
    """Return a cleaned list from a comma-separated env var."""
    if not value:
        return []
    return [item.strip() for item in value.split(',') if item.strip()]


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-change-me-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
# Default False for production; set DEBUG=True in .env for local development
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
IS_PRODUCTION = not DEBUG

ALLOWED_HOSTS = [
    'localhost',
    '127.0.0.1',
    '0.0.0.0',
    'printmax.onrender.com',
    'printmax.in',
    'www.printmax.in',   # ✅ REQUIRED
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
    'corsheaders',
    'channels',
    'print',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',  # Must be before CommonMiddleware
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

# Use Indian Standard Time (IST) for all server-side timestamps
# Django will now treat Asia/Kolkata as the default timezone
TIME_ZONE = 'Asia/Kolkata'
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

# Allow popups for Google Sign-In. This is necessary to prevent the
# "postMessage" error with the Google Sign-In popup.
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin-allow-popups'

# ─────────────────────────────────────────────────────────────
# Firebase Cloud Messaging (FCM) Configuration
# ─────────────────────────────────────────────────────────────

# Firebase Project Configuration (from .env - no hardcoded secrets)
FIREBASE_CONFIG = {
    'apiKey': os.getenv('FIREBASE_API_KEY', ''),
    'authDomain': os.getenv('FIREBASE_AUTH_DOMAIN', ''),
    'projectId': os.getenv('FIREBASE_PROJECT_ID', ''),
    'storageBucket': os.getenv('FIREBASE_STORAGE_BUCKET', ''),
    'messagingSenderId': os.getenv('FIREBASE_MESSAGING_SENDER_ID', ''),
    'appId': os.getenv('FIREBASE_APP_ID', ''),
}

# VAPID Keys for Web Push (from .env only)
FIREBASE_VAPID_PUBLIC_KEY = os.getenv('FIREBASE_VAPID_PUBLIC_KEY', '')
FIREBASE_VAPID_PRIVATE_KEY = os.getenv('FIREBASE_VAPID_PRIVATE_KEY', '')

# Firebase Service Account (private_key from .env only; project identifiers from env)
_firebase_private_key = os.getenv('FIREBASE_PRIVATE_KEY', '')
FIREBASE_SERVICE_ACCOUNT_JSON = {
    "type": "service_account",
    "project_id": os.getenv('FIREBASE_PROJECT_ID', ''),
    "private_key_id": os.getenv('FIREBASE_PRIVATE_KEY_ID', ''),
    "private_key": _firebase_private_key,
    "client_email": os.getenv('FIREBASE_CLIENT_EMAIL', ''),
    "client_id": os.getenv('FIREBASE_CLIENT_ID', ''),
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

# Cloudflare Worker API for D1 Database (from .env only)
WORKER_API_URL = os.getenv('WORKER_API_URL', '').rstrip('/')
WORKER_API_KEY = os.getenv('WORKER_API_KEY', '')

# ✅ PicWish API Configuration
# PicWish API key for image enhancement services
# Get your API key from: https://picwish.com/api
PICWISH_API = os.getenv('PICWISH_API')

# CORS - restricted to allowed origins (from .env CORS_ALLOWED_ORIGINS)
_CORS_ORIGINS = os.getenv('CORS_ALLOWED_ORIGINS')
if not _CORS_ORIGINS:
    _CORS_ORIGINS = 'https://printmax.in,https://www.printmax.in,https://printmax.onrender.com'
    if DEBUG:
        _CORS_ORIGINS += ',http://localhost:8000,http://127.0.0.1:8000'
CORS_ALLOWED_ORIGINS = _split_env_list(_CORS_ORIGINS)

VENDOR_ID=1

# Email Configuration (from .env - no hardcoded secrets)
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.hostinger.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_USE_SSL = os.getenv('EMAIL_USE_SSL', 'False').lower() == 'true'
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True').lower() == 'true'
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
_email_password = os.getenv('EMAIL_HOST_PASSWORD', '')
EMAIL_HOST_PASSWORD = _email_password.strip("'\"") if _email_password else ''
EMAIL_TIMEOUT = int(os.getenv('EMAIL_TIMEOUT', '30'))

# Default email settings - FROM must match EMAIL_HOST_USER for authentication
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', EMAIL_HOST_USER or 'noreply@printmax.in')
EMAIL_SUBJECT_PREFIX = os.getenv('EMAIL_SUBJECT_PREFIX', '[PrintMax]')

# Email templates directory
EMAIL_TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates', 'emails')

# Test email recipient (optional - for auto-sending test emails after registration)
EMAIL_TEST_TO = os.getenv('EMAIL_TEST_TO', '')

# Razorpay API Keys (from .env only)
RAZORPAY_KEY_ID = os.getenv('RAZORPAY_KEY_ID', '')
RAZORPAY_KEY_SECRET = os.getenv('RAZORPAY_KEY_SECRET', '')

# Google API Keys
# GOOGLE_DEVELOPER_KEY: Browser API key (with HTTP referrer restrictions) - for frontend Maps JS only
GOOGLE_DEVELOPER_KEY = os.getenv('GOOGLE_DEVELOPER_KEY', '')
# GOOGLE_MAPS_API: Server-side API key (NO referrer restrictions) - for backend Distance Matrix API only
GOOGLE_MAPS_API = os.getenv('GOOGLE_MAPS_API', '')

# Google OAuth Configuration (from .env only)
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET', '')

# Session Configuration for Persistent Login
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 180  # 6 months (180 days)
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST = True
# Production: secure cookies; local: allow HTTP for testing
SESSION_COOKIE_SECURE = IS_PRODUCTION
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
    'https://www.printmax.in',
    'https://printmax.in',
    'https://*.ngrok-free.app',
    'https://*.ngrok-free.dev',
]

CSRF_TRUSTED_ORIGINS += _split_env_list(os.getenv('CSRF_TRUSTED_ORIGINS_EXTRA'))

# Desktop QR location flow override (needed when phones can't reach localhost)
LOCATION_QR_BASE_URL = os.getenv('LOCATION_QR_BASE_URL', '').rstrip('/')

# Security Settings - strict in production
SECURE_SSL_REDIRECT = IS_PRODUCTION
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https') if IS_PRODUCTION else None
SECURE_HSTS_SECONDS = 31536000 if IS_PRODUCTION else 0  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = IS_PRODUCTION
SECURE_HSTS_PRELOAD = IS_PRODUCTION
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
