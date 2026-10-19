"""Settings for the automated test suite (pytest)."""

from .dev import *  # noqa: F403

# Fast password hashing so tests run quickly.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
