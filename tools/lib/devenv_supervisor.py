"""Auto-start/stop the per-checkout devenv services around tools/ entry points.

When a tools/ entry point is launched from inside a `devenv shell`
(signalled by the DEVENV_ROOT env var) and the services it needs
(postgres, rabbitmq, memcached, redis) aren't already up, start them
with `devenv up -d` before the entry point gets going, and tear them
down with `devenv processes down` when the entry point exits.

This trades a 5-15s startup cost on each invocation for not having
long-lived `devenv up` processes burning CPU/RAM between sessions.
It is a no-op outside a devenv shell (so a vagrant or tools/provision
setup is unaffected), and a no-op when services are already running
(so `devenv up` started in another terminal is left alone -- the
entry point only stops what it itself started).
"""

import atexit
import os
import shutil
import socket
import subprocess
import sys


def _in_devenv_shell() -> bool:
    return bool(os.environ.get("DEVENV_ROOT"))


def _devenv_available() -> bool:
    return shutil.which("devenv") is not None


def _script_name() -> str:
    """Basename of the currently-running entry point script.

    Used as a banner prefix on log messages so the output clearly
    identifies its origin (run-dev, test-backend, ...).
    """
    return os.path.basename(sys.argv[0]) or "devenv-supervisor"


def _postgres_reachable(timeout: float = 0.5) -> bool:
    """Cheap check for whether the per-checkout postgres is up.

    devenv's postgres module exports PGHOST (a unix-socket directory
    in our setup) and PGPORT.  We don't run a real query -- we just
    check the listener exists, which is enough to distinguish
    "services up" from "services down".
    """
    host = os.environ.get("PGHOST")
    port = os.environ.get("PGPORT")
    if not host or not port:
        return False
    try:
        port_int = int(port)
    except ValueError:
        return False

    if host.startswith("/"):
        # Unix-socket directory: postgres listens on
        # `<dir>/.s.PGSQL.<port>`.  An existence check is racy with
        # service startup, but we follow it with an actual connect
        # to make the answer authoritative.
        sock_path = os.path.join(host, f".s.PGSQL.{port}")
        if not os.path.exists(sock_path):
            return False
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            try:
                s.connect(sock_path)
            except OSError:
                return False
            return True

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        try:
            s.connect((host, port_int))
        except OSError:
            return False
        return True


def reexec_under_devenv_shell_if_needed() -> None:
    """Re-exec into `devenv shell` if this checkout needs it.

    `tools/devenv-worktree` writes a `devenv.local.nix` into each new
    worktree (with a non-zero `zulip.portOffset`); a user can opt into
    devenv on the main checkout the same way.  In either case, running
    a tools/ entry point from a plain shell -- with `DEVENV_ROOT`
    unset -- bypasses the PGHOST/PGPORT/etc. env exports that point at
    the per-checkout services, so the entry point falls through to the
    system PostgreSQL/RabbitMQ.

    Transparently re-exec the current entry point under `devenv shell`
    when that mismatch is detected.  The re-exec replaces this process;
    on the second pass `DEVENV_ROOT` is set and this function is a
    no-op.

    No-op for vagrant / tools/provision setups (no devenv.local.nix),
    and no-op when already inside the right shell.  If devenv.local.nix
    is present but the `devenv` binary is gone (e.g. profile rebuild
    between sessions), hard-fail rather than silently falling through
    to the wrong services.
    """
    if _in_devenv_shell():
        return
    if not os.path.exists("devenv.local.nix"):
        return

    script = _script_name()
    if not _devenv_available():
        print(
            f"{script}: devenv.local.nix is present but the `devenv` binary\n"
            "isn't on PATH, so the per-checkout services can't be started\n"
            "and falling through to the system PostgreSQL/RabbitMQ would\n"
            "silently break worktree isolation.  Install devenv\n"
            "(https://devenv.sh) or remove devenv.local.nix to opt out.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Use the absolute path so the re-exec'd entry point finds itself
    # regardless of any cwd shuffling devenv shell does internally.
    self_path = os.path.abspath(sys.argv[0])
    print(f"{script}: re-entering `devenv shell` for per-checkout services...", flush=True)
    os.execvp("devenv", ["devenv", "shell", "--", self_path, *sys.argv[1:]])


def ensure_services() -> bool:
    """Start devenv services if needed, and register cleanup at exit.

    Returns True iff this call started them.  Returns False when
    services were already up, or when we're not in a devenv shell at
    all -- in both cases the caller has nothing to clean up.
    """
    if not _in_devenv_shell():
        return False
    if not _devenv_available():
        # DEVENV_ROOT was set but the binary is gone (e.g. profile
        # rebuild between sessions).  Don't try to manage anything;
        # let the user notice when the entry point fails to connect.
        return False
    if _postgres_reachable():
        return False

    script = _script_name()
    print(
        f"{script}: starting devenv services (postgres, rabbitmq, memcached, redis)...",
        flush=True,
    )
    # Register cleanup BEFORE `devenv up -d` so a half-started
    # supervisor (e.g. `up -d` exits non-zero after some services
    # came up) still gets torn down.  `processes down` against a
    # never-started supervisor is harmless.
    atexit.register(stop_services)
    try:
        subprocess.run(["devenv", "up", "-d"], check=True)
    except subprocess.CalledProcessError as e:
        print(
            f"{script}: 'devenv up -d' failed (exit {e.returncode}); aborting.",
            file=sys.stderr,
        )
        sys.exit(1)

    # `devenv up -d` returns once supervisord is up, but the
    # individual services may still be in the middle of starting.
    # Wait for them to report ready before letting the entry point's
    # children try to connect.  Use devenv's default --timeout (120s
    # as of devenv 1.x); on a cold-cache laptop postgres template
    # initialization alone can take 30-60s, and an override that's
    # tight enough to surface here is more likely to produce false
    # readiness failures than to save real time.  Ctrl-C during the
    # wait is delivered to the foreground process group; the child
    # exits 130, so we see CalledProcessError(returncode=130) below
    # and atexit tears services down via the registration above.
    try:
        subprocess.run(["devenv", "processes", "wait"], check=True)
    except subprocess.CalledProcessError as e:
        # SIGINT to the child surfaces as exit 130; treat as the
        # user intentionally aborting startup, not as "didn't become
        # ready", and let atexit do the cleanup.
        if e.returncode == 130:
            print(f"{script}: startup interrupted; tearing services down.", file=sys.stderr)
        else:
            print(
                f"{script}: devenv services did not become ready (exit {e.returncode});"
                " tearing them down and aborting.",
                file=sys.stderr,
            )
        sys.exit(1)
    return True


_stopped = False


def stop_services() -> None:
    """Tear down services started by `ensure_services()`.

    Best-effort: failures are reported but don't propagate, so a
    cleanup-time error doesn't mask whatever caused run-dev to exit.
    Idempotent -- safe to call from atexit and explicitly from a
    caller without printing the banner twice.
    """
    global _stopped
    if _stopped:
        return
    _stopped = True
    script = _script_name()
    print(f"{script}: stopping devenv services...")
    # Use Popen + wait(timeout=...) so we can kill the child on
    # timeout; subprocess.run() raises TimeoutExpired but leaves the
    # child running, which would leave a stuck `devenv processes
    # down` invocation holding open file descriptors against the
    # supervisor's socket.
    proc = subprocess.Popen(["devenv", "processes", "down"])
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        print(
            f"{script}: 'devenv processes down' timed out; services may still be running."
            " Run it manually if needed.",
            file=sys.stderr,
        )
