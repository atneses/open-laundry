"""Settings shared by every environment.

Secrets and per-environment values are read from environment variables
(`.env` file in development). See `.env.example` at the repository root.
"""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
# Outside Docker, a .env file at the repository root can be used.
environ.Env.read_env(BASE_DIR.parent / ".env", overwrite=False)

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])

INSTALLED_APPS = [
    # Unfold must come before django.contrib.admin
    "unfold",
    "unfold.contrib.filters",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "rest_framework",
    "drf_spectacular",
    # Project apps (each new app is added in the plan stage that needs it)
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {"default": env.db("DATABASE_URL")}

AUTH_USER_MODEL = "core.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Language and time zone (the UI is Spanish only)
LANGUAGE_CODE = "es-mx"
TIME_ZONE = env("DJANGO_TIME_ZONE", default="America/Mexico_City")
USE_I18N = True
# Project translations (includes Unfold strings, which ship without Spanish).
LOCALE_PATHS = [BASE_DIR / "locale"]
USE_TZ = True

# Static files (admin), served by runserver in development
STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Django REST Framework / JWT / OpenAPI ---
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_MINUTES", default=30)),
    "REFRESH_TOKEN_LIFETIME": timedelta(hours=env.int("JWT_REFRESH_HOURS", default=12)),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "API Lavandería",
    "DESCRIPTION": "API del sistema de gestión de la lavandería (caja, encargos, máquinas).",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

# --- Django Admin con Unfold ---
UNFOLD = {
    "SITE_TITLE": "Lavandería",
    "SITE_HEADER": "Lavandería",
    "SITE_SUBHEADER": "Administración",
    "SITE_SYMBOL": "local_laundry_service",
    "SHOW_HISTORY": True,
    "SHOW_LANGUAGES": False,
    # Primary color (blue). To be adjusted to the laundry branding.
    "COLORS": {
        "primary": {
            "50": "oklch(97% .014 254)",
            "100": "oklch(93% .032 255)",
            "200": "oklch(88% .059 254)",
            "300": "oklch(80% .105 251)",
            "400": "oklch(70% .165 254)",
            "500": "oklch(62% .214 259)",
            "600": "oklch(54% .245 262)",
            "700": "oklch(48% .243 264)",
            "800": "oklch(42% .199 265)",
            "900": "oklch(37% .146 265)",
            "950": "oklch(28% .091 267)",
        },
    },
}
