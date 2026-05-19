"""
Django settings for GoldFlux project.
"""

import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-dev-key-change-in-production",
)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get("DJANGO_DEBUG", "True").lower() in ("true", "1", "yes")

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party apps
    "corsheaders",
    "rest_framework",
    # Local apps
    "prices",
    "predictions",
    "news",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "config.middleware.RateLimitMiddleware",
    "config.middleware.CorrelationIdMiddleware",
    "config.middleware.ErrorHandlingMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ──────────────────────────────────────────────────────────────────────────────
# Database Configuration
# ──────────────────────────────────────────────────────────────────────────────
# When POSTGRES_DB or DATABASE_URL is configured, use PostgreSQL with a
# 5-second connection timeout (Requirement 13.1). Otherwise, fall back to
# SQLite for local development.
POSTGRES_DB = os.environ.get("POSTGRES_DB", "").strip()
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# PostgreSQL connection timeout in seconds (Requirement 13.1).
DB_CONNECT_TIMEOUT = int(os.environ.get("DB_CONNECT_TIMEOUT", "5"))

if POSTGRES_DB or DATABASE_URL:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": POSTGRES_DB or os.environ.get("DB_NAME", "goldflux"),
            "USER": os.environ.get("POSTGRES_USER", os.environ.get("DB_USER", "postgres")),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", os.environ.get("DB_PASSWORD", "")),
            "HOST": os.environ.get("POSTGRES_HOST", os.environ.get("DB_HOST", "localhost")),
            "PORT": os.environ.get("POSTGRES_PORT", os.environ.get("DB_PORT", "5432")),
            "CONN_MAX_AGE": int(os.environ.get("DB_CONN_MAX_AGE", "60")),
            "OPTIONS": {
                "connect_timeout": DB_CONNECT_TIMEOUT,
            },
        }
    }
else:
    # SQLite fallback for local development.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
            "OPTIONS": {
                "timeout": DB_CONNECT_TIMEOUT,
            },
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = "static/"

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ──────────────────────────────────────────────────────────────────────────────
# CORS Configuration
# ──────────────────────────────────────────────────────────────────────────────
# Read allowed origins from environment variable (comma-separated).
# Default: http://localhost:3000 (Next.js dev server)
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "CORS_ALLOWED_ORIGINS", "http://localhost:3000"
    ).split(",")
    if origin.strip()
]

# ──────────────────────────────────────────────────────────────────────────────
# Security Headers
# ──────────────────────────────────────────────────────────────────────────────
# X-Content-Type-Options: nosniff
SECURE_CONTENT_TYPE_NOSNIFF = True

# X-Frame-Options: DENY
X_FRAME_OPTIONS = "DENY"

# Strict-Transport-Security: max-age=31536000
SECURE_HSTS_SECONDS = 31536000

# ──────────────────────────────────────────────────────────────────────────────
# ML Models Configuration
# ──────────────────────────────────────────────────────────────────────────────
ML_MODELS_DIR = Path(
    os.environ.get("ML_MODELS_DIR", str(BASE_DIR / "models"))
)

# ──────────────────────────────────────────────────────────────────────────────
# Redis Configuration
# ──────────────────────────────────────────────────────────────────────────────
# Single Redis instance serves dual duty as Celery broker and cache layer.
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# Redis connection timeout in seconds (Requirement 13.2).
REDIS_SOCKET_TIMEOUT = int(os.environ.get("REDIS_SOCKET_TIMEOUT", "2"))

# Django cache backend (uses Redis when available; falls back to local memory).
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "TIMEOUT": int(os.environ.get("CACHE_DEFAULT_TIMEOUT", "900")),  # 15 min default
        "OPTIONS": {
            "socket_timeout": REDIS_SOCKET_TIMEOUT,
            "socket_connect_timeout": REDIS_SOCKET_TIMEOUT,
        },
    }
}

# ──────────────────────────────────────────────────────────────────────────────
# Celery Configuration
# ──────────────────────────────────────────────────────────────────────────────
# Redis serves as both Celery broker and result backend.
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"
CELERY_BROKER_CONNECTION_TIMEOUT = int(
    os.environ.get("CELERY_BROKER_CONNECTION_TIMEOUT", "5")
)

# ──────────────────────────────────────────────────────────────────────────────
# Data Ingestion Schedule (Requirement 2.1)
# ──────────────────────────────────────────────────────────────────────────────
# Daily ingestion time in HH:MM UTC format. Default: 00:30 UTC.
INGESTION_TIME = os.environ.get("INGESTION_TIME", "00:30")

# ──────────────────────────────────────────────────────────────────────────────
# News API Configuration (Requirement 19)
# ──────────────────────────────────────────────────────────────────────────────
# Marketaux API base URL (Requirement 19.1). Default: https://api.marketaux.com
NEWS_API_BASE_URL = os.environ.get(
    "NEWS_API_BASE_URL", "https://api.marketaux.com"
).rstrip("/")

# Marketaux API authentication token (Requirement 19.2). Required for news fetching.
NEWS_API_KEY = os.environ.get("NEWS_API_KEY", "").strip()

# Comma-separated search keywords (Requirement 19.4). Default: gold,XAU,commodities.
NEWS_API_KEYWORDS = os.environ.get("NEWS_API_KEYWORDS", "gold,XAU,commodities")

# News fetch interval in hours, valid range 1-12 (Requirement 17.1).
try:
    _news_interval = int(os.environ.get("NEWS_FETCH_INTERVAL_HOURS", "4"))
except (ValueError, TypeError):
    _news_interval = 4
NEWS_FETCH_INTERVAL_HOURS = max(1, min(12, _news_interval))

# ──────────────────────────────────────────────────────────────────────────────
# Django REST Framework
# ──────────────────────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}

# Silence admin middleware checks (admin middleware not needed for API-only project)
SILENCED_SYSTEM_CHECKS = ["admin.E408", "admin.E409", "admin.E410"]

