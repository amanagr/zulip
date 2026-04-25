"""Helpers for tools/run-dev that benefit from being unit-testable."""

import socket

# Each run-dev instance reserves 6 consecutive ports starting from
# its base port (proxy, Django, Tornado, webpack, help center, tusd).
# The fallback range below leaves a 20-port gap between successive
# bases so we can run up to four dev servers in parallel without
# overlap.  TEST_BASE_PORT (9981) sits inside the gap between 9991
# and 9971, claiming 9981..9986; that range never collides with the
# fallback proxy bases or their derived ports.
PORTS_PER_INSTANCE = 6
DEFAULT_BASE_PORT = 9991
TEST_BASE_PORT = 9981
FALLBACK_BASE_PORTS = [DEFAULT_BASE_PORT, 9971, 9961, 9951]


def is_port_available(port: int, interface: str | None) -> bool:
    # Best-effort: probe the same interface run-dev will eventually
    # bind to, so a port held by another process on a different
    # interface isn't reported as available.  When --interface is None
    # (Vagrant/zulipdev mode listens on all interfaces), bind to "" to
    # match aiohttp's behaviour.
    bind_host = "" if interface is None else interface
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
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
    """
    if requested is not None:
        return requested
    for candidate in FALLBACK_BASE_PORTS:
        if is_port_range_available(candidate, interface):
            return candidate
    return None
