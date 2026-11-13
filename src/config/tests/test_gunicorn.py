import sys
from pathlib import Path
from unittest import mock, skipIf

from django.test import SimpleTestCase

from config import gunicorn as gunicorn_config

# gunicorn is not available on Windows
if sys.platform != "win32":
    from gunicorn.app.wsgiapp import run


@skipIf(sys.platform == "win32", "gunicorn is not fully supported on Windows")
class GunicornConfigTests(SimpleTestCase):
    """Test Gunicorn configuration."""

    @mock.patch("django.core.cache.caches")
    @mock.patch("django.db.connections")
    def test_pre_fork_closes_database_connections_and_pools(
        self,
        connections,
        caches,
    ):
        """Workers must not inherit the master's process-local database pool."""
        pooled_connection = mock.Mock()
        unpooled_connection = mock.Mock(spec=[])
        connections.all.return_value = [pooled_connection, unpooled_connection]
        caches.all.return_value = []

        gunicorn_config.pre_fork(None, None)

        connections.close_all.assert_called_once_with()
        pooled_connection.close_pool.assert_called_once_with()

    @mock.patch("django.core.cache.caches")
    @mock.patch("django.db.connections")
    def test_pre_fork_disconnects_redis_connection_pool(self, connections, caches):
        """Workers must not inherit the master's Redis socket (issue #335)."""
        connections.all.return_value = []
        redis_cache = mock.Mock()
        non_redis_cache = mock.Mock(spec=[])
        caches.all.return_value = [redis_cache, non_redis_cache]

        gunicorn_config.pre_fork(None, None)

        redis_cache.client.do_close_clients.assert_called_once_with()

    def test_accepted_connections_are_capped_at_the_thread_count(self):
        """A worker must not hoard connections it has no free thread for."""
        self.assertEqual(gunicorn_config.worker_connections, gunicorn_config.threads)

    def test_nginx_serves_the_service_worker_without_gunicorn(self):
        """/serviceworker.js must not depend on a free Gunicorn thread."""
        nginx_conf = (Path(__file__).resolve().parents[3] / "nginx.conf").read_text()
        self.assertIn("location = /serviceworker.js {", nginx_conf)
        self.assertIn("alias /floppy/staticfiles/js/serviceworker.js;", nginx_conf)

    def test_when_ready_preloads_url_conf_before_freezing(self):
        """Workers must inherit the imported URLconf, not each import it."""
        calls = []
        server = mock.Mock()
        with (
            mock.patch.object(gunicorn_config, "_record_crash_markers"),
            mock.patch("django.urls.get_resolver") as get_resolver,
            mock.patch.object(gunicorn_config.gc, "collect"),
            mock.patch.object(
                gunicorn_config.gc,
                "freeze",
                side_effect=lambda: calls.append("freeze"),
            ),
        ):
            type(get_resolver.return_value).url_patterns = mock.PropertyMock(
                side_effect=lambda: calls.append("urlconf") or [],
            )
            gunicorn_config.when_ready(server)

        self.assertEqual(calls, ["urlconf", "freeze"])

    def test_when_ready_survives_a_broken_url_conf(self):
        """A failed preload must not stop the server; workers report it."""
        server = mock.Mock()
        with (
            mock.patch.object(gunicorn_config, "_record_crash_markers"),
            mock.patch("django.urls.get_resolver", side_effect=ImportError("boom")),
            mock.patch.object(gunicorn_config.gc, "collect"),
            mock.patch.object(gunicorn_config.gc, "freeze") as freeze,
        ):
            gunicorn_config.when_ready(server)

        server.log.exception.assert_called_once()
        freeze.assert_called_once_with()

    def test_config(self):
        """Test that the Gunicorn configuration file is valid."""
        argv = [
            "gunicorn",
            "--check-config",
            "--config",
            "python:config.gunicorn",
            "config.wsgi",
        ]
        mock_argv = mock.patch.object(sys, "argv", argv)

        with self.assertRaises(SystemExit) as cm, mock_argv:
            run()

        exit_code = cm.exception.args[0]
        self.assertEqual(exit_code, 0)


class StopSignalRecordingTests(SimpleTestCase):
    """The master notes which signal stops it, then handles it as before."""

    def _server(self):
        class Arbiter:
            calls = []

            def handle_term(self):
                self.calls.append("term")
                raise StopIteration

            def handle_int(self):
                self.calls.append("int")
                raise StopIteration

            def handle_quit(self):
                self.calls.append("quit")
                raise StopIteration

        return Arbiter()

    def test_each_stop_signal_is_noted_and_still_stops_the_server(self):
        for name, expected in (
            ("term", "SIGTERM"),
            ("int", "SIGINT"),
            ("quit", "SIGQUIT"),
        ):
            with self.subTest(name):
                server = self._server()
                gunicorn_config._record_stop_signals(server)

                with mock.patch("config.run_state.note_stop_signal") as note:
                    with self.assertRaises(StopIteration):
                        getattr(server, f"handle_{name}")()

                note.assert_called_once_with(expected)
                self.assertEqual(server.calls, [name])

    def test_a_failing_note_does_not_stop_the_shutdown(self):
        server = self._server()
        gunicorn_config._record_stop_signals(server)

        with mock.patch(
            "config.run_state.note_stop_signal", side_effect=OSError("disk full")
        ):
            with self.assertRaises(StopIteration):
                server.handle_term()

        self.assertEqual(server.calls, ["term"])
