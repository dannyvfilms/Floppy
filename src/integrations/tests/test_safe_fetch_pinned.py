"""Offline regression tests for the additive pinned self-hosted HTTP API."""

import io
import ipaddress
import socket
import time
from unittest.mock import Mock, patch
from urllib.parse import urlparse

import requests
from django.test import SimpleTestCase

from integrations import safe_fetch


def public(*addresses):
    """Return a deterministic DNS resolver that supplies the given addresses."""
    return patch.object(
        safe_fetch,
        "socket",
        Mock(
            getaddrinfo=Mock(
                return_value=[(0, 0, 0, "", (address, 0)) for address in addresses]
            ),
            gaierror=OSError,
            SHUT_RDWR=socket.SHUT_RDWR,
        ),
    )


def _response(status, location=None):
    return Mock(
        status_code=status,
        headers={"Location": location} if location else {},
    )


class PinnedSelfHostedRequestTests(SimpleTestCase):
    """Validate the complete request and redirect policy without network I/O."""

    def test_request_connects_to_original_validated_address(self):
        with (
            public("192.168.40.20") as dns,
            patch.object(
                safe_fetch,
                "_send_pinned_self_hosted",
                return_value=_response(200),
            ) as transport,
        ):
            result = safe_fetch.send_to_self_hosted_pinned(
                "GET",
                "http://radarr.home:7878/api/v3/movie",
                headers={"X-Api-Key": "secret"},
                timeout=20,
            )

        self.assertEqual(result.status_code, 200)
        dns.getaddrinfo.assert_called_once()
        transport.assert_called_once()

        args, kwargs = transport.call_args
        self.assertEqual(args[0], "GET")
        self.assertEqual(args[1].hostname, "radarr.home")
        self.assertEqual(args[2], ipaddress.ip_address("192.168.40.20"))
        self.assertEqual(kwargs["headers"]["X-Api-Key"], "secret")
        self.assertFalse(kwargs["allow_redirects"])

    def test_redirect_reuses_original_ip_without_second_dns_lookup(self):
        redirect = _response(302, "/next")
        success = _response(200)

        with (
            public("192.168.40.20") as dns,
            patch.object(
                safe_fetch,
                "_send_pinned_self_hosted",
                side_effect=[redirect, success],
            ) as transport,
        ):
            result = safe_fetch.send_to_self_hosted_pinned(
                "GET",
                "http://radarr.home:7878/api",
                headers={"X-Api-Key": "secret"},
            )

        self.assertIs(result, success)
        dns.getaddrinfo.assert_called_once()
        self.assertEqual(transport.call_count, 2)

        for call in transport.call_args_list:
            self.assertEqual(
                call.args[2],
                ipaddress.ip_address("192.168.40.20"),
            )

        self.assertEqual(
            transport.call_args_list[1].args[1].path,
            "/next",
        )
        redirect.close.assert_called_once()

    def test_cross_host_redirect_never_sends_second_request(self):
        redirect = _response(302, "http://other.home:7878/collect")

        with (
            public("192.168.40.20"),
            patch.object(
                safe_fetch,
                "_send_pinned_self_hosted",
                return_value=redirect,
            ) as transport,
            self.assertRaises(safe_fetch.SelfHostedUrlError) as caught,
        ):
            safe_fetch.send_to_self_hosted_pinned(
                "GET",
                "http://radarr.home:7878/api",
                headers={"X-Api-Key": "secret"},
            )

        self.assertEqual(caught.exception.reason_code, "cross_host_redirect")
        transport.assert_called_once()
        redirect.close.assert_called_once()

    def test_https_downgrade_never_sends_second_request(self):
        redirect = _response(302, "http://radarr.home:7878/next")

        with (
            public("192.168.40.20"),
            patch.object(
                safe_fetch,
                "_send_pinned_self_hosted",
                return_value=redirect,
            ) as transport,
            self.assertRaises(safe_fetch.SelfHostedUrlError) as caught,
        ):
            safe_fetch.send_to_self_hosted_pinned("GET", "https://radarr.home:7878/api")

        self.assertEqual(caught.exception.reason_code, "https_downgrade")
        transport.assert_called_once()
        redirect.close.assert_called_once()

    def test_cross_port_redirect_never_sends_second_request(self):
        redirect = _response(302, "http://radarr.home:6379/")

        with (
            public("192.168.40.20"),
            patch.object(
                safe_fetch,
                "_send_pinned_self_hosted",
                return_value=redirect,
            ) as transport,
            self.assertRaises(safe_fetch.SelfHostedUrlError) as caught,
        ):
            safe_fetch.send_to_self_hosted_pinned("GET", "http://radarr.home:7878/api")

        self.assertEqual(caught.exception.reason_code, "cross_port_redirect")
        transport.assert_called_once()

    def test_redirect_with_embedded_credentials_is_refused(self):
        redirect = _response(302, "http://user:password@radarr.home:7878/next")

        with (
            public("192.168.40.20"),
            patch.object(
                safe_fetch,
                "_send_pinned_self_hosted",
                return_value=redirect,
            ) as transport,
            self.assertRaises(safe_fetch.SelfHostedUrlError) as caught,
        ):
            safe_fetch.send_to_self_hosted_pinned("GET", "http://radarr.home:7878/api")

        self.assertEqual(caught.exception.reason_code, "credentials_in_url")
        transport.assert_called_once()

    def test_forbidden_metadata_address_never_reaches_transport(self):
        with (
            public("169.254.169.254"),
            patch.object(safe_fetch, "_send_pinned_self_hosted") as transport,
            self.assertRaises(safe_fetch.SelfHostedUrlError) as caught,
        ):
            safe_fetch.send_to_self_hosted_pinned("GET", "http://metadata.home/latest")

        self.assertEqual(caught.exception.reason_code, "forbidden_address")
        transport.assert_not_called()

    def test_unresolvable_host_never_reaches_transport(self):
        with (
            patch.object(
                safe_fetch.socket,
                "getaddrinfo",
                side_effect=socket.gaierror("unavailable"),
            ),
            patch.object(safe_fetch, "_send_pinned_self_hosted") as transport,
            self.assertRaises(safe_fetch.SelfHostedUrlError) as caught,
        ):
            safe_fetch.send_to_self_hosted_pinned("GET", "http://unknown.home/api")

        self.assertEqual(caught.exception.reason_code, "unresolvable_host")
        transport.assert_not_called()

    def test_post_302_becomes_get_without_resending_body(self):
        with (
            public("192.168.40.20"),
            patch.object(
                safe_fetch,
                "_send_pinned_self_hosted",
                side_effect=[_response(302, "/next"), _response(200)],
            ) as transport,
        ):
            safe_fetch.send_to_self_hosted_pinned(
                "POST",
                "http://radarr.home:7878/command",
                json={"name": "MoviesSearch"},
                params={"first": "only"},
            )

        self.assertEqual(
            [call.args[0] for call in transport.call_args_list],
            ["POST", "GET"],
        )
        second_kwargs = transport.call_args_list[1].kwargs
        self.assertNotIn("json", second_kwargs)
        self.assertNotIn("params", second_kwargs)

    def test_post_307_preserves_method_and_request_body(self):
        with (
            public("192.168.40.20"),
            patch.object(
                safe_fetch,
                "_send_pinned_self_hosted",
                side_effect=[_response(307, "/next"), _response(200)],
            ) as transport,
        ):
            safe_fetch.send_to_self_hosted_pinned(
                "POST",
                "http://radarr.home:7878/command",
                json={"name": "MoviesSearch"},
                params={"first": "only"},
            )

        self.assertEqual(
            [call.args[0] for call in transport.call_args_list],
            ["POST", "POST"],
        )
        second_kwargs = transport.call_args_list[1].kwargs
        self.assertEqual(second_kwargs["json"], {"name": "MoviesSearch"})
        self.assertNotIn("params", second_kwargs)

    def test_http_to_https_default_port_upgrade_is_supported(self):
        with (
            public("192.168.40.20") as dns,
            patch.object(
                safe_fetch,
                "_send_pinned_self_hosted",
                side_effect=[
                    _response(301, "https://radarr.home/api"),
                    _response(200),
                ],
            ) as transport,
        ):
            result = safe_fetch.send_to_self_hosted_pinned(
                "GET", "http://radarr.home/api"
            )

        self.assertEqual(result.status_code, 200)
        self.assertEqual(transport.call_count, 2)
        self.assertEqual(transport.call_args_list[1].args[1].scheme, "https")
        dns.getaddrinfo.assert_called_once()

    def test_missing_redirect_location_closes_response(self):
        redirect = _response(302)

        with (
            public("192.168.40.20"),
            patch.object(
                safe_fetch,
                "_send_pinned_self_hosted",
                return_value=redirect,
            ) as transport,
            self.assertRaises(safe_fetch.SelfHostedUrlError) as caught,
        ):
            safe_fetch.send_to_self_hosted_pinned("GET", "http://radarr.home:7878/api")

        self.assertEqual(caught.exception.reason_code, "invalid_redirect")
        transport.assert_called_once()
        redirect.close.assert_called_once()


class _MemoryRaw:
    """Minimal urllib3-like raw source with no external network access."""

    def __init__(self, payload):
        self.buffer = io.BytesIO(payload)
        self.read_calls = 0

    def read(self, amt=None, **_kwargs):
        self.read_calls += 1
        return self.buffer.read(amt)

    def stream(self, amt=8192, **_kwargs):
        while chunk := self.read(min(amt, 3)):
            yield chunk

    def close(self):
        self.buffer.close()

    def release_conn(self):
        pass


class PinnedResponseBudgetTests(SimpleTestCase):
    """Bound buffered and streamed bodies while preserving Requests' API."""

    def _request(self, payload, *, max_bytes=20, stream=False, headers=None):
        response = requests.Response()
        response.status_code = 200
        response.headers = headers or {}
        response.raw = _MemoryRaw(payload)

        session = Mock()
        session.request.return_value = response
        with patch.object(safe_fetch, "_pinned_session", return_value=session):
            try:
                returned = safe_fetch._send_pinned_self_hosted(
                    "GET",
                    urlparse("http://server.home:8080/api"),
                    ipaddress.ip_address("192.168.1.12"),
                    deadline=time.monotonic() + 10,
                    max_bytes=max_bytes,
                    stream=stream,
                    timeout=5,
                )
            except Exception:
                session.close.assert_called()
                raise
        return returned, session

    def test_buffered_body_is_available_for_content_and_json(self):
        response, session = self._request(b'{"ok":true}', max_bytes=20)
        self.assertEqual(response.content, b'{"ok":true}')
        self.assertEqual(response.json(), {"ok": True})
        session.close.assert_called()

    def test_oversized_body_without_content_length_is_refused(self):
        with self.assertRaises(safe_fetch.SelfHostedUrlError) as caught:
            self._request(b"large" * 10, max_bytes=10)
        self.assertEqual(caught.exception.reason_code, "response_too_large")

    def test_declared_oversized_body_is_refused_before_read(self):
        with self.assertRaises(safe_fetch.SelfHostedUrlError) as caught:
            self._request(b"abc", max_bytes=10, headers={"Content-Length": "1000"})
        self.assertEqual(caught.exception.reason_code, "response_too_large")

    def test_streaming_response_is_closed_by_caller(self):
        response, session = self._request(b"abcdefgh", stream=True)
        session.close.assert_not_called()
        self.assertEqual(b"".join(response.iter_content(3)), b"abcdefgh")
        response.close()
        session.close.assert_called()

    def test_streaming_above_budget_closes_connection(self):
        response, session = self._request(
            b"abcdefghijklmnopqrstuvwxyz", max_bytes=7, stream=True
        )
        with self.assertRaises(safe_fetch.SelfHostedUrlError) as caught:
            b"".join(response.iter_content(3))
        self.assertEqual(caught.exception.reason_code, "response_too_large")
        session.close.assert_called()

    def test_implicit_raw_read_is_bounded(self):
        response, session = self._request(b"abcdef", max_bytes=5, stream=True)
        with self.assertRaises(safe_fetch.SelfHostedUrlError) as caught:
            response.raw.read()
        self.assertEqual(caught.exception.reason_code, "response_too_large")
        session.close.assert_called()

    def test_expired_body_deadline_closes_connection(self):
        response, session = self._request(b"abc", max_bytes=20, stream=True)
        response.raw._deadline = time.monotonic() - 1
        with self.assertRaises(safe_fetch.SelfHostedUrlError) as caught:
            next(response.iter_content(3))
        self.assertEqual(caught.exception.reason_code, "deadline_exceeded")
        session.close.assert_called()

    def test_legacy_api_still_exists(self):
        self.assertTrue(callable(safe_fetch.send_to_self_hosted))

    def test_mixed_dns_answers_are_refused_before_connection(self):
        with (
            public("192.168.1.10", "169.254.169.254"),
            patch.object(safe_fetch, "_send_pinned_self_hosted") as transport,
            self.assertRaises(safe_fetch.SelfHostedUrlError) as caught,
        ):
            safe_fetch.send_to_self_hosted_pinned("GET", "http://server.home/")
        self.assertEqual(caught.exception.reason_code, "forbidden_address")
        transport.assert_not_called()

    def test_mapped_ipv6_metadata_address_is_refused(self):
        with (
            public("::ffff:169.254.169.254"),
            patch.object(safe_fetch, "_send_pinned_self_hosted") as transport,
            self.assertRaises(safe_fetch.SelfHostedUrlError) as caught,
        ):
            safe_fetch.send_to_self_hosted_pinned("GET", "http://server.home/")
        self.assertEqual(caught.exception.reason_code, "forbidden_address")
        transport.assert_not_called()
