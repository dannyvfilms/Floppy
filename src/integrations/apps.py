from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    """Integrations app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations"

    def ready(self):
        """Import signals when the app is ready."""
        from importlib import import_module

        import_module("integrations.signals_state")
