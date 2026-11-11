"""The shared response for a failure whose text Floppy did not write."""

from http import HTTPStatus as HTTP  # noqa: N814

from django.test import SimpleTestCase

from api.errors import failure_response


class FailureResponseTests(SimpleTestCase):
    """The exception goes to the log, never to the body."""

    def test_exception_text_is_logged_not_returned(self):
        error = RuntimeError("secret /srv/private/path")
        with self.assertLogs("api.errors", level="WARNING") as logs:
            response = failure_response(
                "Could not resolve item.", error, status=HTTP.BAD_GATEWAY
            )
        self.assertEqual(response.status_code, HTTP.BAD_GATEWAY)
        self.assertEqual(response.data, {"detail": "Could not resolve item."})
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(
            logs.records[0].getMessage(),
            "Could not resolve item. error=RuntimeError",
        )
        # The record factory renders the traceback once, behind its redaction.
        self.assertIn("RuntimeError", logs.records[0].exc_text)

    def test_traceback_can_be_left_out_of_the_log(self):
        error = RuntimeError("https://hooks.example/token-abc")
        with self.assertLogs("api.errors", level="WARNING") as logs:
            failure_response(
                "Failed.", error, status=HTTP.BAD_GATEWAY, traceback=False
            )
        self.assertFalse(logs.records[0].exc_info)
        self.assertFalse(logs.records[0].exc_text)
        self.assertNotIn("token-abc", logs.output[0])
