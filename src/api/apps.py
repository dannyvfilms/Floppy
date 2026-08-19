from django.apps import AppConfig


class ApiConfig(AppConfig):
    """Default app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "api"

    def ready(self):
        """Import signals when the app is ready."""
        import api.schema  # noqa: F401

        # FORK: register fork-only media types in the upstream lookup tables.
        from api.fork_helpers import install_fork_media_types

        install_fork_media_types()
