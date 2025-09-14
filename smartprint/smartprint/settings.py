import os
from pathlib import Path
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials

# Load environment variables
load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-your-secret-key')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'

ALLOWED_HOSTS = ['printmax.onrender.com', 'localhost', '127.0.0.1', '0.0.0.0', '*']  # Production domain + localhost + wildcard for Render

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

# Firebase Admin SDK Configuration
try:
    if not firebase_admin._apps:
        # For now, we'll initialize without credentials since we don't have the service account file
        # You'll need to get the service account key from Firebase Console
        firebase_admin.initialize_app()
        print("✅ Firebase Admin SDK initialized successfully (without credentials)")
    else:
        print("✅ Firebase Admin SDK already initialized")
except Exception as e:
    print(f"❌ Error initializing Firebase Admin SDK: {str(e)}")

# Channel layers configuration
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer'
    }
}

# Vendor dashboard configuration
VENDOR_DASHBOARD_URL = os.getenv('VENDOR_DASHBOARD_URL')
VENDOR_TOKEN = os.getenv('VENDOR_TOKEN')

# ✅ R2 credentials from .env
R2_ACCESS_KEY = os.getenv('R2_ACCESS_KEY')
R2_SECRET_KEY = os.getenv('R2_SECRET_KEY')
R2_ENDPOINT = os.getenv('R2_ENDPOINT', '').rstrip('/')  # Remove trailing slash
R2_BUCKET = os.getenv('R2_BUCKET')

# ✅ CORS setup for production (if using django-cors-headers)
# CORS_ALLOW_ALL_ORIGINS = True  # Use CORS_ALLOWED_ORIGINS in production
# CORS_ALLOW_CREDENTIALS = True
# CORS_ALLOWED_ORIGINS = [
#     'https://printmax.onrender.com',
#     'http://localhost:8000',  # For local development
#     'http://127.0.0.1:8000',  # For local development
# ]

VENDOR_ID=1

# ✅ Email Configuration
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', 'azfarshaikh7860@gmail.com')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', 'phwn lngl xwxy nxdb')

# Default email settings
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'PrintMax <noreply@printmax.com>')
EMAIL_SUBJECT_PREFIX = '[PrintMax] '

# Email templates directory
EMAIL_TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates', 'emails')

# Razorpay API Keys (set in environment variables)
RAZORPAY_KEY_ID = os.getenv('RAZORPAY_KEY_ID', 'rzp_live_RF2OLAhxugVc5B')
RAZORPAY_KEY_SECRET = os.getenv('RAZORPAY_KEY_SECRET', '5NkBgjtxzJLNAUwhQLTXzsQP')

GOOGLE_API_KEY = 'AIzaSyBZxTJfCiwyYdeuHLDUuACG_cPeqrz2MYw'

# ✅ Google OAuth Configuration for Production
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID', 'your-google-client-id-here')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET', 'your-google-client-secret-here')

# ✅ Google OAuth Redirect URIs for Production
GOOGLE_OAUTH_REDIRECT_URIS = [
    'https://printmax.onrender.com/auth-receiver/',
    'http://localhost:8000/auth-receiver/',  # For local development
]

# ✅ Google OAuth JavaScript Origins for Production
GOOGLE_OAUTH_JAVASCRIPT_ORIGINS = [
    'https://printmax.onrender.com',
    'http://localhost:8000',  # For local development
]

# ✅ Session Configuration for Persistent Login
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 180  # 6 months (180 days)
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_SECURE = True  # Set to True for production HTTPS
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'

# ✅ Authentication Settings
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/userdashboard/'
LOGOUT_REDIRECT_URL = '/'

# ✅ CSRF Settings for Production
CSRF_TRUSTED_ORIGINS = [
    'https://printmax.onrender.com',
    'http://localhost:8000',
    'http://127.0.0.1:8000',
]

# ✅ Security Settings for Production
SECURE_SSL_REDIRECT = True  # Force HTTPS in production
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')  # For Render.com
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
X_FRAME_OPTIONS = 'DENY'
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
CSRF_COOKIE_SECURE = True  # CSRF cookies only over HTTPS
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Lax'

# ✅ Force HTTP for localhost testing
if DEBUG:
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False