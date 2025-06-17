from pathlib import Path
import os
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv()

STATIC_URL = '/static/'
STATICFILES_DIRS = [
    BASE_DIR / "static",
    # Add other directories if needed
]
SECRET_KEY = 'your-secret'
DEBUG = True
ALLOWED_HOSTS = ['*']  # Allow all hosts for development

INSTALLED_APPS = [
    'print',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',  # ✅ Required for CORS
    'channels',  # Add Channels support
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',  # ✅ Add at the top
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'smartprint.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': ['templates'],
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

# Update ASGI application
ASGI_APPLICATION = 'smartprint.asgi.application'

# Channel layers configuration
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer'
    }
}

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_L10N = True
USE_TZ = True

STATIC_URL = '/static/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ✅ R2 credentials from .env
R2_ACCESS_KEY = 'e02ce6580b8c81a4899bc6f4b2250f65'
R2_SECRET_KEY = 'ad35d6fae06bd3fe15956642348a0391fbd8c8f5a3cdca052b7484869179b8e9'
R2_ENDPOINT = 'https://d3e1ce952178b1093bba642e6d0d4ab5.r2.cloudflarestorage.com'
R2_BUCKET = 'printme'

# ✅ CORS setup
CORS_ALLOW_ALL_ORIGINS = True  # Use CORS_ALLOWED_ORIGINS in production
