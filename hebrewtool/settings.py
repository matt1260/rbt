"""
Django settings for realbible project.

For more information on this file, see
https://docs.djangoproject.com/en/4.1/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/4.1/ref/settings/
"""

from pathlib import Path
import os
import logging
from logging.handlers import TimedRotatingFileHandler
import dj_database_url
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file explicitly from BASE_DIR and OVERRIDE existing environment variables
env_path = BASE_DIR / '.env'
# Optional debug prints for environment loading — only output when explicitly enabled
if os.getenv('SETTINGS_PRINT', 'False') == 'True':
    print(f"[SETTINGS DEBUG] Loading .env from: {env_path}")
    print(f"[SETTINGS DEBUG] .env exists: {env_path.exists()}")

load_dotenv(dotenv_path=env_path, override=True)  # Force override shell env vars

# Verify GEMINI_API_KEYS loaded
gemini_keys = os.getenv('GEMINI_API_KEYS', '')
if os.getenv('SETTINGS_PRINT', 'False') == 'True':
    print(f"[SETTINGS DEBUG] GEMINI_API_KEYS length: {len(gemini_keys)}")
    print(f"[SETTINGS DEBUG] Number of keys: {len([k for k in gemini_keys.split(',') if k.strip()])}")

DEFAULT_CHARSET = 'utf-8'

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DEBUG', 'False') == 'True'
ENABLE_VERBOSE_DEBUG = os.environ.get('ENABLE_VERBOSE_DEBUG', 'False') == 'True'

ALLOWED_HOSTS = ["*"]

CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True

CSRF_TRUSTED_ORIGINS = ['https://mzg2o4p8.up.railway.app', 'https://rbtproject.up.railway.app', 'https://www.realbible.tech', 'https://read.realbible.tech', 'https://realbible.tech', 'http://rbt.realbible.tech', 'http://localhost', 'http://127.0.0.1']

# CORS Settings - Allow WordPress frontend to make API requests
CORS_ALLOWED_ORIGINS = [
    'https://www.realbible.tech',
    'https://realbible.tech',
    'https://read.realbible.tech',
    'http://127.0.0.1:8000',
    'http://localhost:8000',
]
CORS_ALLOW_CREDENTIALS = True

CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
]

CORS_ALLOW_METHODS = [
    'DELETE',
    'GET',
    'OPTIONS',
    'PATCH',
    'POST',
    'PUT',
]

LOGIN_URL = 'accounts/login/'

# Increase field limits for bulk editing forms (e.g., find_and_replace)
DATA_UPLOAD_MAX_NUMBER_FIELDS = 10000  # Default is 1000
DATA_UPLOAD_MAX_MEMORY_SIZE = 10485760  # 10MB (default is 2.5MB)

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'search',
    'translate',
    'rest_framework',
]

REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',
    ],
}

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'hebrewtool.middleware.AjaxExceptionMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'hebrewtool.middleware.BotFilterMiddleware',  # Block bad bots early
    'hebrewtool.middleware.RateLimitMiddleware',  # Rate limit after bot filtering
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'hebrewtool.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
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

WSGI_APPLICATION = 'hebrewtool.wsgi.application'


# Database
            'file_info': {
                'level': 'INFO',
                'class': 'logging.handlers.TimedRotatingFileHandler',
                'filename': 'RBT_info.log',
                'when': 'D',
                'interval': 1,
                'backupCount': 7,
                'formatter': 'standard',
            },
# https://docs.djangoproject.com/en/4.1/ref/settings/#databases


DATABASES = {
    'default': dj_database_url.config(
        default=os.environ.get('DATABASE_URL'),
        conn_max_age=600,  # Keep connections alive for 10 minutes
            'translate': {
                'handlers': ['file_info', 'file'],
                'level': 'INFO',
                'propagate': False,
            },
        conn_health_checks=True  # Django 4.1+ health checks
    )
}

# Cache configuration - use database cache for rate limiting persistence
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
        'LOCATION': 'django_cache_table',
        'OPTIONS': {
            'MAX_ENTRIES': 10000,
            'CULL_FREQUENCY': 4,  # When full, delete 1/4 of entries
        }
    }
}

# Rate limiting configuration (override with env vars if needed)
# Defaults chosen to be more permissive than previous hardcoded values
RATE_LIMIT_VERSE_LIMIT = int(os.getenv('RATE_LIMIT_VERSE_LIMIT', '30'))
RATE_LIMIT_VERSE_WINDOW = int(os.getenv('RATE_LIMIT_VERSE_WINDOW', '60'))
RATE_LIMIT_VERSE_MAX_STRIKES = int(os.getenv('RATE_LIMIT_VERSE_MAX_STRIKES', '3'))
RATE_LIMIT_VERSE_BAN_DURATION = int(os.getenv('RATE_LIMIT_VERSE_BAN_DURATION', '1800'))  # seconds (30m)

RATE_LIMIT_CHAPTER_LIMIT = int(os.getenv('RATE_LIMIT_CHAPTER_LIMIT', '60'))
RATE_LIMIT_CHAPTER_WINDOW = int(os.getenv('RATE_LIMIT_CHAPTER_WINDOW', '60'))
RATE_LIMIT_CHAPTER_MAX_STRIKES = int(os.getenv('RATE_LIMIT_CHAPTER_MAX_STRIKES', '4'))
RATE_LIMIT_CHAPTER_BAN_DURATION = int(os.getenv('RATE_LIMIT_CHAPTER_BAN_DURATION', '1800'))  # seconds (30m)

RATE_LIMIT_API_LIMIT = int(os.getenv('RATE_LIMIT_API_LIMIT', '20'))
RATE_LIMIT_API_WINDOW = int(os.getenv('RATE_LIMIT_API_WINDOW', '60'))
RATE_LIMIT_API_MAX_STRIKES = int(os.getenv('RATE_LIMIT_API_MAX_STRIKES', '3'))
RATE_LIMIT_API_BAN_DURATION = int(os.getenv('RATE_LIMIT_API_BAN_DURATION', '3600'))  # seconds (1h)

RATE_LIMIT_GENERAL_LIMIT = int(os.getenv('RATE_LIMIT_GENERAL_LIMIT', '120'))
RATE_LIMIT_GENERAL_WINDOW = int(os.getenv('RATE_LIMIT_GENERAL_WINDOW', '60'))
RATE_LIMIT_GENERAL_MAX_STRIKES = int(os.getenv('RATE_LIMIT_GENERAL_MAX_STRIKES', '6'))
RATE_LIMIT_GENERAL_BAN_DURATION = int(os.getenv('RATE_LIMIT_GENERAL_BAN_DURATION', '300'))  # seconds (5m)



# Password validation
# https://docs.djangoproject.com/en/4.1/ref/settings/#auth-password-validators

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

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',  # This is the default backend
    # ... any additional authentication backends you might want to use ...
]


# Internationalization
# https://docs.djangoproject.com/en/4.1/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = False


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.1/howto/static-files/
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")
STATICFILES_DIRS = [os.path.join(BASE_DIR, "static")]

STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'
WHITENOISE_USE_FINDERS = True

# Default primary key field type
# https://docs.djangoproject.com/en/4.1/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
    },
    'handlers': {
        'mail_admins': {
            'level': 'ERROR',
            'class': 'django.utils.log.AdminEmailHandler',
        },
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
        },
        'file': {
            'level': 'ERROR',
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'filename': 'RBT_error.log',
            'when': 'D',  # Rotate daily
            'interval': 1,  # Keep one backup
            'backupCount': 7,  # Keep up to 7 days of logs
            'formatter': 'standard',  # Use the 'standard' formatter
        },
        'file_info': {
            'level': 'INFO',
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'filename': 'RBT_info.log',
            'when': 'D',
            'interval': 1,
            'backupCount': 7,
            'formatter': 'standard',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['file'],
            'level': 'ERROR',
            'propagate': True,
        },
        'translate': {
            'handlers': ['file_info', 'file', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}