import os
import socket
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

try:
    from tools.lib import devenv_supervisor
except ImportError:
    print("ERROR!!! You need to run this via tools/test-tools.")
    sys.exit(1)


class InDevenvShellTest(unittest.TestCase):
    def test_returns_false_without_devenv_root(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(devenv_supervisor._in_devenv_shell())

    def test_returns_true_with_devenv_root(self) -> None:
        with patch.dict("os.environ", {"DEVENV_ROOT": "/nonexistent/devenv-stub"}, clear=True):
            self.assertTrue(devenv_supervisor._in_devenv_shell())

    def test_empty_devenv_root_treated_as_unset(self) -> None:
        # An empty string is the "exported but not actually inside devenv"
        # case (e.g., a stale shell init); we should not treat it as
        # being inside the shell, since the rest of the env exports
        # (PGHOST, etc.) won't be set either.
        with patch.dict("os.environ", {"DEVENV_ROOT": ""}, clear=True):
            self.assertFalse(devenv_supervisor._in_devenv_shell())


class PostgresReachableTest(unittest.TestCase):
    def test_returns_false_when_pghost_unset(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(devenv_supervisor._postgres_reachable())

    def test_returns_false_when_pgport_unset(self) -> None:
        with patch.dict("os.environ", {"PGHOST": "/nonexistent/pg-sock"}, clear=True):
            self.assertFalse(devenv_supervisor._postgres_reachable())

    def test_returns_false_when_pgport_malformed(self) -> None:
        with patch.dict(
            "os.environ", {"PGHOST": "/nonexistent/pg-sock", "PGPORT": "garbage"}, clear=True
        ):
            self.assertFalse(devenv_supervisor._postgres_reachable())

    def test_unix_socket_missing_returns_false(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict("os.environ", {"PGHOST": tmp, "PGPORT": "5432"}, clear=True),
        ):
            # No `.s.PGSQL.5432` in tmp.
            self.assertFalse(devenv_supervisor._postgres_reachable())

    def test_unix_socket_reachable_returns_true(self) -> None:
        # Create a real listening unix socket so the existence + connect
        # check both pass; this exercises the entire happy path on
        # the unix-socket branch.
        with tempfile.TemporaryDirectory() as tmp:
            sock_path = os.path.join(tmp, ".s.PGSQL.5432")
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                server.bind(sock_path)
                server.listen(1)
                with patch.dict(
                    "os.environ", {"PGHOST": tmp, "PGPORT": "5432"}, clear=True
                ):
                    self.assertTrue(devenv_supervisor._postgres_reachable())
            finally:
                server.close()

    def test_tcp_unreachable_returns_false(self) -> None:
        # Bind a socket without listening, then close it — guarantees
        # the chosen port is not accepting connections in the test
        # window.  Race-free relative to the connect attempt below
        # because we close before connecting.
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        with patch.dict(
            "os.environ", {"PGHOST": "127.0.0.1", "PGPORT": str(port)}, clear=True
        ):
            self.assertFalse(devenv_supervisor._postgres_reachable())

    def test_tcp_reachable_returns_true(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            port = server.getsockname()[1]
            with patch.dict(
                "os.environ", {"PGHOST": "127.0.0.1", "PGPORT": str(port)}, clear=True
            ):
                self.assertTrue(devenv_supervisor._postgres_reachable())
        finally:
            server.close()


class EnsureServicesTest(unittest.TestCase):
    def test_no_op_outside_devenv_shell(self) -> None:
        # Without DEVENV_ROOT set, ensure_services must not run any
        # subprocess (so vagrant / tools/provision setups pass through
        # untouched).
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("tools.lib.devenv_supervisor.subprocess.run") as mocked_run,
        ):
            self.assertFalse(devenv_supervisor.ensure_services())
            mocked_run.assert_not_called()

    def test_no_op_when_postgres_already_reachable(self) -> None:
        # Inside devenv shell but services already up: ensure_services
        # must skip `devenv up -d` (so a manually-started supervisor
        # in another terminal isn't stomped).
        with (
            patch.dict(
                "os.environ", {"DEVENV_ROOT": "/nonexistent/devenv-stub"}, clear=True
            ),
            patch(
                "tools.lib.devenv_supervisor._devenv_available", return_value=True
            ),
            patch(
                "tools.lib.devenv_supervisor._postgres_reachable", return_value=True
            ),
            patch("tools.lib.devenv_supervisor.subprocess.run") as mocked_run,
        ):
            self.assertFalse(devenv_supervisor.ensure_services())
            mocked_run.assert_not_called()

    def test_no_op_when_devenv_binary_missing(self) -> None:
        # DEVENV_ROOT was set (we're in a devenv shell from a previous
        # session) but the `devenv` binary is gone (profile rebuild,
        # PATH change).  Don't try to call it.
        with (
            patch.dict(
                "os.environ", {"DEVENV_ROOT": "/nonexistent/devenv-stub"}, clear=True
            ),
            patch(
                "tools.lib.devenv_supervisor._devenv_available", return_value=False
            ),
            patch("tools.lib.devenv_supervisor.subprocess.run") as mocked_run,
        ):
            self.assertFalse(devenv_supervisor.ensure_services())
            mocked_run.assert_not_called()


class ReexecUnderDevenvShellTest(unittest.TestCase):
    def test_no_op_when_already_in_devenv_shell(self) -> None:
        with (
            patch.dict(
                "os.environ", {"DEVENV_ROOT": "/nonexistent/devenv-stub"}, clear=True
            ),
            patch("tools.lib.devenv_supervisor.os.execvp") as mocked_execvp,
        ):
            devenv_supervisor.reexec_under_devenv_shell_if_needed()
            mocked_execvp.assert_not_called()

    def test_no_op_without_devenv_local_nix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                with (
                    patch.dict("os.environ", {}, clear=True),
                    patch(
                        "tools.lib.devenv_supervisor.os.execvp"
                    ) as mocked_execvp,
                ):
                    devenv_supervisor.reexec_under_devenv_shell_if_needed()
                    mocked_execvp.assert_not_called()
            finally:
                os.chdir(cwd)

    def test_hard_fails_when_devenv_binary_missing(self) -> None:
        # devenv.local.nix exists but `devenv` isn't on PATH: refuse
        # rather than silently using the system services (which
        # would mutate state shared across worktrees).
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                with open("devenv.local.nix", "w") as f:
                    f.write("{ ... }: {}\n")
                with (
                    patch.dict("os.environ", {}, clear=True),
                    patch(
                        "tools.lib.devenv_supervisor._devenv_available",
                        return_value=False,
                    ),
                    patch(
                        "tools.lib.devenv_supervisor.os.execvp"
                    ) as mocked_execvp,
                    self.assertRaises(SystemExit) as cm,
                ):
                    devenv_supervisor.reexec_under_devenv_shell_if_needed()
                self.assertEqual(cm.exception.code, 1)
                mocked_execvp.assert_not_called()
            finally:
                os.chdir(cwd)

    def test_execs_into_devenv_shell_when_configured(self) -> None:
        # Happy path: devenv.local.nix is present, devenv is on PATH,
        # we're not yet in a devenv shell.  reexec must call
        # os.execvp("devenv", ["devenv", "shell", "--", <self>, *argv[1:]]).
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                with open("devenv.local.nix", "w") as f:
                    f.write("{ ... }: {}\n")
                with (
                    patch.dict("os.environ", {}, clear=True),
                    patch(
                        "tools.lib.devenv_supervisor._devenv_available",
                        return_value=True,
                    ),
                    patch(
                        "tools.lib.devenv_supervisor.os.execvp"
                    ) as mocked_execvp,
                    patch.object(sys, "argv", ["tools/run-dev", "--minify"]),
                ):
                    devenv_supervisor.reexec_under_devenv_shell_if_needed()
                mocked_execvp.assert_called_once()
                args, _ = mocked_execvp.call_args
                self.assertEqual(args[0], "devenv")
                self.assertEqual(args[1][:3], ["devenv", "shell", "--"])
                # Self path is absolute and ends in tools/run-dev.
                self.assertTrue(os.path.isabs(args[1][3]))
                self.assertTrue(args[1][3].endswith("tools/run-dev"))
                # Original argv tail is forwarded verbatim.
                self.assertEqual(args[1][4:], ["--minify"])
            finally:
                os.chdir(cwd)


class StopServicesTest(unittest.TestCase):
    def test_idempotent(self) -> None:
        # First call runs `devenv processes down`; second call is a
        # no-op via the _stopped guard.  Both atexit and explicit
        # callers rely on this.
        with patch("tools.lib.devenv_supervisor.subprocess.Popen") as mocked_popen:
            mocked_popen.return_value = MagicMock(wait=MagicMock(return_value=0))
            # Reset the module-global guard for a clean test.
            with patch.object(devenv_supervisor, "_stopped", False):
                devenv_supervisor.stop_services()
                devenv_supervisor.stop_services()
                self.assertEqual(mocked_popen.call_count, 1)

    def test_kills_child_on_timeout(self) -> None:
        # When `devenv processes down` exceeds the timeout, the child
        # must be killed and reaped so we don't leak a stuck
        # supervisor connection.
        import subprocess as subprocess_module

        proc = MagicMock()
        proc.wait = MagicMock(
            side_effect=[subprocess_module.TimeoutExpired(cmd="devenv", timeout=30), 0]
        )
        with (
            patch(
                "tools.lib.devenv_supervisor.subprocess.Popen", return_value=proc
            ),
            patch.object(devenv_supervisor, "_stopped", False),
        ):
            devenv_supervisor.stop_services()
        proc.kill.assert_called_once()
        # wait() must be called twice: once with the timeout (which
        # raised), again after kill() to reap.
        self.assertEqual(proc.wait.call_count, 2)
