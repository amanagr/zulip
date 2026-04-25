"""Helpers for tools/run-dev that benefit from being unit-testable."""

import os
import socket

# Each run-dev instance reserves 6 consecutive ports starting from
# its base port (proxy, Django, Tornado, webpack, help center, tusd).
# The fallback range below leaves a 20-port gap between successive
# bases so we can run up to four dev servers in parallel without
# overlap.  TEST_BASE_PORT defaults to 9981, sitting inside the gap
# between 9991 and 9971 and claiming 9981..9986; that range never
# collides with the fallback proxy bases or their derived ports.
#
# When BASE_PORT is set in the environment (e.g. by a per-worktree
# devenv.local.nix that shifts every service port), TEST_BASE_PORT
# shifts by the same amount so two worktrees can run the test
# suite in parallel without colliding on 9981..9986.
PORTS_PER_INSTANCE = 6
DEFAULT_BASE_PORT = 9991
DEFAULT_TEST_BASE_PORT = 9981
# Importing this module must not raise if BASE_PORT is malformed:
# tools/run-dev imports run_dev_helpers at startup before it has a
# chance to reject the bad value, so a `BASE_PORT=garbage` in the
# user's shell would otherwise crash run-dev with a traceback.
try:
    _runtime_base_port = int(os.environ.get("BASE_PORT") or DEFAULT_BASE_PORT)
except ValueError:
    _runtime_base_port = DEFAULT_BASE_PORT
TEST_BASE_PORT = DEFAULT_TEST_BASE_PORT + (_runtime_base_port - DEFAULT_BASE_PORT)
FALLBACK_BASE_PORTS = [DEFAULT_BASE_PORT, 9971, 9961, 9951]


def is_port_available(port: int, interface: str | None) -> bool:
    # Best-effort: probe the same interface run-dev will eventually
    # bind to, so a port held by another process on a different
    # interface isn't reported as available.  When --interface is None
    # (Vagrant/zulipdev mode listens on all interfaces), bind to "" to
    # match aiohttp's behaviour.
    bind_host = "" if interface is None else interface
    # Match the address family to the interface so a probe with an
    # IPv6 literal (`::1`) doesn't always look busy on AF_INET.
    try:
        family = socket.getaddrinfo(
            bind_host or None, port, type=socket.SOCK_STREAM, flags=socket.AI_PASSIVE
        )[0][0]
    except socket.gaierror:
        family = socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as s:
        try:
            s.bind((bind_host, port))
        except OSError:
            return False
        return True


def is_port_range_available(base: int, interface: str | None) -> bool:
    return all(is_port_available(base + offset, interface) for offset in range(PORTS_PER_INSTANCE))


def pick_base_port(requested: int | None, interface: str | None) -> int | None:
    """Return the base port to use, or None if every fallback range is busy.

    Probes the entire 6-port range for each candidate, not just the
    proxy port; otherwise a stray Tornado on +2 would let run-dev
    start on a base that's doomed to fail later.  The probe is
    best-effort (TOCTOU-prone) — a mismatch surfaces as a clear bind
    failure when the listener actually starts.

    When neither the --base-port flag nor a BASE_PORT env var is
    given, scan FALLBACK_BASE_PORTS for the first 6-port range that's
    free.  When BASE_PORT is set (e.g. by a per-worktree
    devenv.local.nix), trust it as-is rather than falling back; the
    fallback range starts at 9991 = main checkout's services, so a
    silent fallback would land in the wrong worktree's port space.
    """
    if requested is not None:
        return requested
    env_base = os.environ.get("BASE_PORT")
    if env_base:
        try:
            return int(env_base)
        except ValueError:
            pass
    for candidate in FALLBACK_BASE_PORTS:
        if is_port_range_available(candidate, interface):
            return candidate
    return None
