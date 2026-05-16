from __future__ import annotations

from django.apps import AppConfig


class ManDbConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "man_db"
    verbose_name = "Man DB"
