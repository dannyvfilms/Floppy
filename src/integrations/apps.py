from importlib import import_module

from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    """Integrations app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations"

    def import_models(self) -> None:
        """Load OAuth models that live outside the legacy monolithic models module."""
        super().import_models()
        import_module(f"{self.name}.oauth_models")

    def ready(self):
        """Import integration state signals when the app is ready."""
        import_module("integrations.signals_state")
