from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SECRET_KEY = "tests"
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "man_db",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "test_db",
        "USER": "test_user",
        "PASSWORD": "test_password",
        "HOST": "127.0.0.1",
        "PORT": 5432,
    },
    "analytics": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "analytics_db",
        "USER": "analytics_user",
        "PASSWORD": "analytics_password",
        "HOST": "127.0.0.1",
        "PORT": 5432,
    },
}
