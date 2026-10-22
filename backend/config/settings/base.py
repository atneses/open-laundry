"""Settings shared by every environment.

Secrets and per-environment values are read from environment variables
(`.env` file in development). See `.env.example` at the repository root.
"""

from datetime import timedelta
from pathlib import Path

import environ
from django.templatetags.static import static
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

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
    "customers",
    "sales",
    "inventory",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.CurrentUserMiddleware",
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
# Unfold's login form has no hidden "next" field, so logging in from
# /admin/login/ directly would fall back to /accounts/profile/ (which does not exist).
LOGIN_REDIRECT_URL = reverse_lazy("admin:index")

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
# Project translations (kept with makemessages), then the hand-made Spanish for
# Unfold, which ships none. They live apart so makemessages does not obsolete them.
LOCALE_PATHS = [BASE_DIR / "locale", BASE_DIR / "locale_unfold"]
USE_TZ = True

# Static files (admin and branding), served by runserver in development
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

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
    "TITLE": "Laundry API",
    "DESCRIPTION": "API of the laundry management system (cashier, drop-off orders, machines).",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

# --- Django Admin con Unfold ---
UNFOLD = {
    "SITE_TITLE": _("Laundry"),
    "SITE_HEADER": _("Laundry"),
    "SITE_SUBHEADER": _("Administration"),
    # Provisional branding until the laundry provides its logo and colors.
    "SITE_SYMBOL": "local_laundry_service",
    "SITE_FAVICONS": [
        {
            "rel": "icon",
            "sizes": "any",
            "type": "image/svg+xml",
            "href": lambda request: static("favicon.svg"),
        },
    ],
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
    # Sidebar grouped by business area (mvp.md §2). Each stage adds its own
    # area and models; items are only shown to users with the view permission.
    "SIDEBAR": {
        "show_search": False,
        "show_all_applications": False,
        "navigation": [
            {
                "title": _("Operation"),
                "separator": False,
                "items": [
                    {
                        "title": _("Customers"),
                        "icon": "contacts",
                        "link": reverse_lazy("admin:customers_customer_changelist"),
                        "permission": lambda request: request.user.has_perm(
                            "customers.manage_customers"
                        ),
                    },
                    {
                        "title": _("Cash sessions"),
                        "icon": "point_of_sale",
                        "link": reverse_lazy("admin:sales_cashsession_changelist"),
                        "permission": lambda request: request.user.has_perm(
                            "sales.view_all_cash_sessions"
                        ),
                    },
                ],
            },
            {
                "title": _("Catalog"),
                "separator": True,
                "items": [
                    {
                        "title": _("Services and prices"),
                        "icon": "local_laundry_service",
                        "link": reverse_lazy("admin:sales_service_changelist"),
                        "permission": lambda request: request.user.has_perm(
                            "sales.manage_catalog"
                        ),
                    },
                ],
            },
            {
                "title": _("Inventory"),
                "separator": True,
                "items": [
                    {
                        "title": _("Products"),
                        "icon": "inventory_2",
                        "link": reverse_lazy("admin:inventory_product_changelist"),
                        "permission": "inventory.admin.can_view_inventory",
                    },
                    {
                        "title": _("Stock movements"),
                        "icon": "swap_vert",
                        "link": reverse_lazy("admin:inventory_stockmovement_changelist"),
                        "permission": "inventory.admin.can_view_inventory",
                    },
                    {
                        "title": _("Consumption per load"),
                        "icon": "water_drop",
                        "link": reverse_lazy("admin:inventory_loadconsumption_changelist"),
                        "permission": lambda request: request.user.has_perm(
                            "sales.manage_catalog"
                        ),
                    },
                ],
            },
            {
                "title": _("Users and permissions"),
                "separator": True,
                "items": [
                    {
                        "title": _("Users"),
                        "icon": "person",
                        "link": reverse_lazy("admin:core_user_changelist"),
                        "permission": lambda request: request.user.has_perm("core.manage_users"),
                    },
                    {
                        "title": _("Roles"),
                        "icon": "groups",
                        "link": reverse_lazy("admin:auth_group_changelist"),
                        "permission": lambda request: request.user.has_perm("core.manage_users"),
                    },
                    {
                        "title": _("Branches"),
                        "icon": "store",
                        "link": reverse_lazy("admin:core_branch_changelist"),
                        "permission": lambda request: request.user.has_perm("core.view_branch"),
                    },
                ],
            },
            {
                "title": _("Logs"),
                "separator": True,
                "items": [
                    {
                        "title": _("Permissions"),
                        "icon": "history",
                        "link": reverse_lazy("admin:core_permissionlog_changelist"),
                        "permission": lambda request: request.user.has_perm(
                            "core.view_permissionlog"
                        ),
                    },
                ],
            },
        ],
    },
}
