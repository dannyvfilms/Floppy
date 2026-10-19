"""Exercise the broker wire format, including rejection of legacy pickle."""

import json
import os
import pickle
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from celery import Celery
from django.conf import settings
from django.test import SimpleTestCase
from kombu.exceptions import ContentDisallowed
from kombu.serialization import loads


class CelerySerializationTests(SimpleTestCase):
    def test_json_task_publishes_and_decodes_without_eager_mode(self):
        app = Celery("security-test", broker="memory://")
        self.addCleanup(app.close)
        app.conf.update(
            task_serializer=settings.CELERY_TASK_SERIALIZER,
            accept_content=settings.CELERY_ACCEPT_CONTENT,
            result_serializer=settings.CELERY_RESULT_SERIALIZER,
            result_accept_content=settings.CELERY_RESULT_ACCEPT_CONTENT,
        )
        payload = {
            "user_id": 42,
            "file": "/data/import-staging/.upload-test.csv",
            "item_ids": [1, 2],
            "event": {"timestamp": datetime(2026, 1, 1, tzinfo=UTC), "raw": b"data"},
        }
        with app.connection_for_write() as connection:
            queue = connection.SimpleQueue(
                "security-test", accept=app.conf.accept_content
            )
            self.addCleanup(queue.close)
            app.send_task(
                "security-test.echo",
                kwargs=payload,
                queue="security-test",
                connection=connection,
            )
            message = queue.get(block=False)
            self.assertEqual(message.content_type, "application/json")
            self.assertEqual(message.payload[1], payload)
            message.ack()
        self.assertEqual(app.conf.result_serializer, "json")
        self.assertEqual(app.conf.result_accept_content, ["json"])

    def test_worker_refuses_pickle_even_for_an_innocuous_payload(self):
        for content_type in ["application/x-python-serialize", "application/x-pickle"]:
            with (
                self.subTest(content_type=content_type),
                self.assertRaises(ContentDisallowed),
            ):
                loads(
                    pickle.dumps({"user_id": 42}),
                    content_type=content_type,
                    content_encoding="binary",
                    accept={"application/json"},
                )
        self.assertEqual(settings.CELERY_ACCEPT_CONTENT, ["json"])


class SecureCookieConfigurationTests(SimpleTestCase):
    def test_cookie_flags_can_be_enabled_without_trusting_forwarded_headers(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import json; from config import settings as s; "
                    "print(json.dumps([s.SESSION_COOKIE_SECURE, s.CSRF_COOKIE_SECURE, "
                    "s.SECURE_PROXY_SSL_HEADER, s.USE_X_FORWARDED_HOST, s.USE_X_FORWARDED_PORT]))"
                ),
            ],
            env={
                **os.environ,
                "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
                "SECRET": "test-only",  # pragma: allowlist secret
                "SESSION_COOKIE_SECURE": "True",
                "CSRF_COOKIE_SECURE": "True",
                "USE_X_FORWARDED": "False",
                "USE_X_FORWARDED_PROTO": "False",
                "USE_X_FORWARDED_HOST": "False",
                "USE_X_FORWARDED_PORT": "False",
            },
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        self.assertEqual(json.loads(result.stdout), [True, True, None, False, False])
