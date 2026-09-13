import os

from celery import Celery

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("floppy")

app.config_from_object("django.conf:settings", namespace="CELERY")

# The dedicated interactive worker only consumes the task modules listed in
# CELERY_IMPORTS. Avoid autodiscovering every background task and importer into
# that long-lived process. Background and combined workers retain the complete
# task registry.
if os.environ.get("FLOPPY_PROCESS_ROLE") != "interactive":
    app.autodiscover_tasks()
