"""Auto-start/stop the per-checkout devenv services around tools/run-dev.

When run-dev is launched from inside a `devenv shell` (signalled by
the DEVENV_ROOT env var) and the services it needs (postgres,
rabbitmq, memcached, redis) aren't already up, start them with
`devenv up -d` before run-dev gets going, and tear them down with
`devenv processes down` when run-dev exits.

This trades a 5-15s startup cost on each run-dev invocation for not
having long-lived `devenv up` processes burning CPU/RAM between
sessions.  It is a no-op outside a devenv shell (so a vagrant or
tools/provision setup is unaffected), and a no-op when services are
already running (so `devenv up` started in another terminal is left
alone -- run-dev only stops what it itself started).
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
        # let the user notice when run-dev fails to connect.
        return False
    if _postgres_reachable():
        return False

    print("run-dev: starting devenv services (postgres, rabbitmq, memcached, redis)...", flush=True)
    # Register cleanup BEFORE `devenv up -d` so a half-started
    # supervisor (e.g. `up -d` exits non-zero after some services
    # came up) still gets torn down.  `processes down` against a
    # never-started supervisor is harmless.
    atexit.register(stop_services)
    try:
        subprocess.run(["devenv", "up", "-d"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"run-dev: 'devenv up -d' failed (exit {e.returncode}); aborting.", file=sys.stderr)
        sys.exit(1)

    # `devenv up -d` returns once supervisord is up, but the
    # individual services may still be in the middle of starting.
    # Wait for them to report ready before letting run-dev's
    # children try to connect.  Ctrl-C during the wait is delivered
    # to the foreground process group; the child exits 130, so we
    # see CalledProcessError(returncode=130) below and atexit tears
    # services down via the registration above.
    try:
        subprocess.run(["devenv", "processes", "wait", "--timeout", "60"], check=True)
    except subprocess.CalledProcessError as e:
        # SIGINT to the child surfaces as exit 130; treat as the
        # user intentionally aborting startup, not as "didn't become
        # ready", and let atexit do the cleanup.
        if e.returncode == 130:
            print("run-dev: startup interrupted; tearing services down.", file=sys.stderr)
        else:
            print(
                f"run-dev: devenv services did not become ready (exit {e.returncode});"
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
    print("run-dev: stopping devenv services...")
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
            "run-dev: 'devenv processes down' timed out; services may still be running."
            " Run it manually if needed.",
            file=sys.stderr,
        )
