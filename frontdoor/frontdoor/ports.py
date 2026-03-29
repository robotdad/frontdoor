"""Port reservation helpers for the frontdoor service."""

import socket

# ---------------------------------------------------------------------------
# Reserved port set
# ---------------------------------------------------------------------------
# Ranges include a +10 buffer beyond the well-known port to avoid conflicts.

RESERVED_PORTS: set[int] = set()

# Web frameworks
for _range in [
    (3000, 3011),  # React / Node dev-servers
    (4000, 4011),  # Various dev frameworks
    (4200, 4211),  # Angular CLI
    (5000, 5011),  # Flask / generic dev
    (5173, 5184),  # Vite
    (8000, 8011),  # Django / FastAPI dev
    (8080, 8091),  # Generic HTTP alt
]:
    RESERVED_PORTS.update(range(*_range))

# Amplifier ecosystem
RESERVED_PORTS.update(range(8410, 8421))

# Notebooks / monitoring
RESERVED_PORTS.update(range(8888, 8899))  # Jupyter
RESERVED_PORTS.update(range(9090, 9101))  # Prometheus

# Databases (single well-known ports)
RESERVED_PORTS.update({3306, 5432, 6379, 27017})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def is_reserved(port: int) -> bool:
    """Return True if *port* appears in the RESERVED_PORTS set."""
    return port in RESERVED_PORTS


_MIN_PORT = 0
_MAX_PORT = 65535


def next_available_port(start: int = 8440) -> int:
    """Return the first port >= *start* that is neither reserved nor in use.

    A port is considered *in use* when a TCP connection to ``('localhost',
    port)`` succeeds within *timeout* seconds.

    Raises:
        ValueError: if *start* is outside the valid TCP port range 0-65535.
        RuntimeError: if no available port exists between *start* and 65535.
    """
    if not (_MIN_PORT <= start <= _MAX_PORT):
        raise ValueError(
            f"start={start!r} is not a valid port number; "
            f"must be in the range {_MIN_PORT}-{_MAX_PORT}."
        )
    port = start
    while port <= _MAX_PORT:
        if is_reserved(port):
            port += 1
            continue
        try:
            with socket.create_connection(("localhost", port), timeout=1):
                pass
            # Connection succeeded → port is in use, try next
            port += 1
        except OSError:
            # Connection refused / timed-out → port is free
            return port
    raise RuntimeError(f"No available port found between {start} and {_MAX_PORT}.")
