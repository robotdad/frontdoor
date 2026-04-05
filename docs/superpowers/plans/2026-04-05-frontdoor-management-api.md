# frontdoor Management API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a full management API, `frontdoor-admin` CLI, and updated bundle skills to frontdoor for deterministic app provisioning across a Tailscale fleet.

**Architecture:** New `/api/admin/*` endpoints in a dedicated admin router handle port allocation, manifest management, service control (via a privileged helper script and sudoers), full app registration (Caddy + systemd + manifest), and known-app installation with template substitution. A three-tier auth model (localhost bypass → API token → PAM session cookie) gates all admin endpoints. The `frontdoor-admin` CLI wraps every API endpoint for local and remote use, with a box-config system for fleet management over Tailscale.

**Tech Stack:** Python 3.11+, FastAPI, Click, pytest, systemd, Caddy, itsdangerous

---

## File Map

### New Files

| File | Responsibility |
|---|---|
| `frontdoor/tokens.py` | Token creation, SHA-256 hashing, validation, listing, revocation; reads/writes `tokens.json` |
| `frontdoor/routes/admin.py` | All `/api/admin/*` endpoints: tokens, ports, manifests, services, apps, known-apps |
| `frontdoor/service_control.py` | `run_privileged()` wrapper — calls `frontdoor-priv` via sudo with JSON on stdin |
| `frontdoor/app_registration.py` | Caddy/systemd template rendering, `register_app()`, `unregister_app()`, `install_known_app()` |
| `frontdoor/bin/frontdoor-priv` | Privileged helper script (sudoers target) — validates and executes write-caddy, write-service, systemctl, etc. |
| `frontdoor/cli.py` | `frontdoor-admin` CLI entry point (Click-based) |
| `tests/test_tokens.py` | Token module unit tests |
| `tests/test_admin_auth.py` | Three-tier admin auth tests |
| `tests/test_admin_routes.py` | Admin endpoint integration tests |
| `tests/test_service_control.py` | `run_privileged()` unit tests |
| `tests/test_app_registration.py` | Template rendering + registration logic tests |
| `tests/test_discovery_enrichment.py` | `get_port_pids()`, `get_systemd_unit()`, port allocation tests |
| `tests/test_cli.py` | CLI tests via Click's `CliRunner` |

### Modified Files

| File | Change |
|---|---|
| `frontdoor/config.py` | Add `tokens_file`, `allow_localhost_admin`, `self_unit`, `service_user` settings |
| `frontdoor/auth.py` | Add `require_admin_auth` dependency (three-tier check) |
| `frontdoor/discovery.py` | Add `get_port_pids()`, `get_systemd_unit()`, `next_available_ports()` |
| `frontdoor/routes/services.py` | Enrich `_collect_services` with `systemd_unit` field |
| `frontdoor/main.py` | Register admin router |
| `pyproject.toml` | Add `click` dependency, `frontdoor-admin` entry point |
| `deploy/install.sh` | Add sudoers entry for `frontdoor-priv` |
| `skills/web-app-setup/` | Rewrite Phase 2 + Phase 3 to use `frontdoor-admin` |
| `skills/host-infra-discovery/` | Update port inventory section |

---

## Task Group 1 — Discovery Enrichment

Adds `systemd_unit` field to `/api/services` response. Pure read-path, no privilege needed.

### Task 1.1: `get_port_pids()` and `get_systemd_unit()`

**Files:**
- Modify: `frontdoor/discovery.py`
- Create: `tests/test_discovery_enrichment.py`

- [ ] **Step 1: Write failing tests for `get_port_pids`**

Create `tests/test_discovery_enrichment.py`:

```python
"""Tests for discovery enrichment: get_port_pids() and get_systemd_unit()."""

from unittest.mock import MagicMock, patch


class TestGetPortPids:
    SS_OUTPUT = (
        "Netid State  Recv-Q Send-Q Local Address:Port Peer Address:Port Process\n"
        'tcp   LISTEN 0      128    0.0.0.0:8088      0.0.0.0:*         users:(("uvicorn",pid=1234,fd=6))\n'
        'tcp   LISTEN 0      128    0.0.0.0:8445      0.0.0.0:*         users:(("python3",pid=2345,fd=7))\n'
        'tcp   LISTEN 0      128    127.0.0.1:5432    0.0.0.0:*         users:(("postgres",pid=9999,fd=5))\n'
    )

    def _mock_run(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = self.SS_OUTPUT
        return mock_result

    def test_returns_port_to_pid_mapping(self):
        """get_port_pids returns {port: pid} for all listening TCP ports."""
        from frontdoor.discovery import get_port_pids

        with patch("frontdoor.discovery.subprocess.run", return_value=self._mock_run()):
            result = get_port_pids()

        assert result[8088] == 1234
        assert result[8445] == 2345
        assert result[5432] == 9999

    def test_empty_on_subprocess_failure(self):
        """get_port_pids returns empty dict when ss command fails."""
        from frontdoor.discovery import get_port_pids

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with patch("frontdoor.discovery.subprocess.run", return_value=mock_result):
            result = get_port_pids()

        assert result == {}

    def test_empty_on_subprocess_exception(self):
        """get_port_pids returns empty dict on subprocess exception."""
        from frontdoor.discovery import get_port_pids

        with patch(
            "frontdoor.discovery.subprocess.run", side_effect=FileNotFoundError("ss")
        ):
            result = get_port_pids()

        assert result == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_discovery_enrichment.py::TestGetPortPids -v`
Expected: FAIL — `ImportError: cannot import name 'get_port_pids' from 'frontdoor.discovery'`

- [ ] **Step 3: Implement `get_port_pids`**

Add to the end of `frontdoor/discovery.py` (after `scan_processes`):

```python
def get_port_pids() -> dict[int, int]:
    """Return {port: pid} for all listening TCP ports via ``ss -tlnp``.

    Runs ``ss -tlnp`` once and parses the output.  Called once per request
    and shared across all service lookups.

    Returns an empty dict on any subprocess failure.
    """
    try:
        result = subprocess.run(
            ["ss", "-tlnp"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as e:
        logger.warning("ss command error in get_port_pids: %s", e)
        return {}

    if result.returncode != 0:
        logger.warning("ss command failed (returncode=%d)", result.returncode)
        return {}

    port_pids: dict[int, int] = {}
    for line in result.stdout.splitlines():
        if "LISTEN" not in line:
            continue
        port_match = re.search(r":(\d+)\s", line)
        proc_match = re.search(r'users:\(\("([^"]+)",pid=(\d+)', line)
        if port_match and proc_match:
            port_pids[int(port_match.group(1))] = int(proc_match.group(2))

    return port_pids
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_discovery_enrichment.py::TestGetPortPids -v`
Expected: 3 passed

- [ ] **Step 5: Write failing tests for `get_systemd_unit`**

Append to `tests/test_discovery_enrichment.py`:

```python
class TestGetSystemdUnit:
    def test_extracts_service_name(self, tmp_path):
        """get_systemd_unit extracts 'muxplex.service' from cgroup file."""
        from frontdoor.discovery import get_systemd_unit

        cgroup = tmp_path / "cgroup"
        cgroup.write_text("0::/system.slice/muxplex.service\n")

        with patch("frontdoor.discovery.Path") as mock_path_cls:
            mock_path_cls.return_value.__truediv__ = lambda self, x: cgroup
            mock_path_cls.return_value = tmp_path
            # Direct approach: patch the specific Path construction
            result = get_systemd_unit(1234, proc_root=tmp_path)

        assert result == "muxplex.service"

    def test_returns_none_for_non_service(self, tmp_path):
        """get_systemd_unit returns None when cgroup is not a .service."""
        from frontdoor.discovery import get_systemd_unit

        cgroup_dir = tmp_path / "1234"
        cgroup_dir.mkdir()
        (cgroup_dir / "cgroup").write_text("0::/user.slice/user-1000.slice/session-1.scope\n")

        result = get_systemd_unit(1234, proc_root=tmp_path)
        assert result is None

    def test_returns_none_for_missing_proc(self, tmp_path):
        """get_systemd_unit returns None when /proc/<pid>/cgroup does not exist."""
        from frontdoor.discovery import get_systemd_unit

        result = get_systemd_unit(99999, proc_root=tmp_path)
        assert result is None
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_discovery_enrichment.py::TestGetSystemdUnit -v`
Expected: FAIL — `ImportError: cannot import name 'get_systemd_unit' from 'frontdoor.discovery'`

- [ ] **Step 7: Implement `get_systemd_unit`**

Add to `frontdoor/discovery.py` after `get_port_pids`:

```python
def get_systemd_unit(pid: int, proc_root: Path | None = None) -> str | None:
    """Return the systemd unit name for *pid*, or ``None``.

    Reads ``/proc/<pid>/cgroup`` and extracts the service name::

        0::/system.slice/muxplex.service  →  "muxplex.service"

    Returns ``None`` for processes not running under a systemd ``.service``
    unit, or when the cgroup file cannot be read.

    Args:
        pid: Process ID to look up.
        proc_root: Override for ``/proc`` (used in tests).
    """
    root = proc_root or Path("/proc")
    cgroup_path = root / str(pid) / "cgroup"
    try:
        content = cgroup_path.read_text()
    except (FileNotFoundError, PermissionError):
        return None

    for line in content.splitlines():
        # Format: hierarchy-ID:controller-list:cgroup-path
        # e.g. "0::/system.slice/muxplex.service"
        parts = line.strip().split(":")
        if len(parts) >= 3:
            cgroup = parts[2]
            # Extract the last path component if it ends with .service
            basename = cgroup.rsplit("/", 1)[-1]
            if basename.endswith(".service"):
                return basename

    return None
```

- [ ] **Step 8: Fix the test to use the `proc_root` parameter correctly**

Replace the `TestGetSystemdUnit` class in `tests/test_discovery_enrichment.py`:

```python
class TestGetSystemdUnit:
    def test_extracts_service_name(self, tmp_path):
        """get_systemd_unit extracts 'muxplex.service' from cgroup file."""
        from frontdoor.discovery import get_systemd_unit

        pid_dir = tmp_path / "1234"
        pid_dir.mkdir()
        (pid_dir / "cgroup").write_text("0::/system.slice/muxplex.service\n")

        result = get_systemd_unit(1234, proc_root=tmp_path)
        assert result == "muxplex.service"

    def test_returns_none_for_non_service(self, tmp_path):
        """get_systemd_unit returns None when cgroup is not a .service."""
        from frontdoor.discovery import get_systemd_unit

        pid_dir = tmp_path / "1234"
        pid_dir.mkdir()
        (pid_dir / "cgroup").write_text(
            "0::/user.slice/user-1000.slice/session-1.scope\n"
        )

        result = get_systemd_unit(1234, proc_root=tmp_path)
        assert result is None

    def test_returns_none_for_missing_proc(self, tmp_path):
        """get_systemd_unit returns None when /proc/<pid>/cgroup does not exist."""
        from frontdoor.discovery import get_systemd_unit

        result = get_systemd_unit(99999, proc_root=tmp_path)
        assert result is None

    def test_handles_multiple_cgroup_lines(self, tmp_path):
        """get_systemd_unit finds the .service line among multiple cgroup entries."""
        from frontdoor.discovery import get_systemd_unit

        pid_dir = tmp_path / "5678"
        pid_dir.mkdir()
        (pid_dir / "cgroup").write_text(
            "12:memory:/system.slice/filebrowser.service\n"
            "0::/system.slice/filebrowser.service\n"
        )

        result = get_systemd_unit(5678, proc_root=tmp_path)
        assert result == "filebrowser.service"
```

- [ ] **Step 9: Run all discovery enrichment tests**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_discovery_enrichment.py -v`
Expected: 7 passed

- [ ] **Step 10: Commit**

```bash
cd /home/robotdad/repos/frontdoor
git add frontdoor/discovery.py tests/test_discovery_enrichment.py
git commit -m "feat: add get_port_pids() and get_systemd_unit() to discovery"
```

### Task 1.2: Enrich `/api/services` with `systemd_unit`

**Files:**
- Modify: `frontdoor/routes/services.py`
- Modify: `tests/test_services_route.py`

- [ ] **Step 1: Write failing test for systemd_unit in API response**

Add to the end of `tests/test_services_route.py`, inside the `TestGetServices` class:

```python
    def test_services_include_systemd_unit(self, service_client):
        """Each service object includes a 'systemd_unit' field (may be null)."""
        port_pids = {8445: 1111, 8443: 2222}
        units = {1111: "dev-machine-monitor.service", 2222: "filebrowser.service"}

        with (
            patch("socket.create_connection"),
            patch(
                "frontdoor.discovery.subprocess.run",
                return_value=_make_ss_mock(""),
            ),
            patch(
                "frontdoor.routes.services.get_port_pids",
                return_value=port_pids,
            ),
            patch(
                "frontdoor.routes.services.get_systemd_unit",
                side_effect=lambda pid, **kw: units.get(pid),
            ),
        ):
            resp = service_client.get("/api/services")

        assert resp.status_code == 200
        services = resp.json()["services"]
        for svc in services:
            assert "systemd_unit" in svc

        fb = next(s for s in services if s["name"] == "File Browser")
        assert fb["systemd_unit"] == "filebrowser.service"
```

Also add the import at the top of `tests/test_services_route.py`:

```python
from frontdoor.discovery import get_port_pids, get_systemd_unit
```

Wait — the test patches `frontdoor.routes.services.get_port_pids` since that's where the import will be. Keep the existing imports as-is and add this import in the test:

No — it's easier to not import those in the test file and just patch at the module where they're used. The test should just add the patches.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_services_route.py::TestGetServices::test_services_include_systemd_unit -v`
Expected: FAIL — `AttributeError: <module 'frontdoor.routes.services'> does not have the attribute 'get_port_pids'`

- [ ] **Step 3: Modify `_collect_services` to include `systemd_unit`**

Edit `frontdoor/routes/services.py`:

Add to the imports:

```python
from frontdoor.discovery import (
    get_port_pids,
    get_systemd_unit,
    overlay_manifests,
    parse_caddy_configs,
    scan_processes,
    tcp_probe,
)
```

Replace the `_collect_services` function body:

```python
def _collect_services() -> dict:
    """Synchronous orchestration — filesystem reads, TCP probes, subprocess scan."""
    # 1. Parse Caddy configuration files.
    parsed = parse_caddy_configs(settings.caddy_main_config, settings.caddy_conf_d)
    logger.debug("Parsed %d services from Caddy config", len(parsed))

    # 1b. Build port→pid mapping for systemd unit enrichment.
    port_pids = get_port_pids()

    # 2. Build service list with live-status probing and systemd unit enrichment.
    services: list[dict] = []
    up_count = 0
    down_count = 0
    for svc in parsed:
        is_up = tcp_probe("127.0.0.1", svc["internal_port"])
        if is_up:
            up_count += 1
        else:
            down_count += 1

        # Resolve systemd unit via PID cgroup lookup.
        pid = port_pids.get(svc["internal_port"])
        unit = get_systemd_unit(pid) if pid else None

        services.append(
            {
                "name": svc["name"],
                "url": svc["external_url"],
                "status": "up" if is_up else "down",
                "systemd_unit": unit,
            }
        )
    logger.debug("TCP probes complete: %d up, %d down", up_count, down_count)

    # 3. Enrich services with manifest metadata.
    services = overlay_manifests(services, settings.manifest_dir)

    # 4. Collect Caddy-managed internal ports so scan_processes can skip them.
    caddy_ports: set[int] = {svc["internal_port"] for svc in parsed}

    # 5. Scan for processes listening on ports not managed by Caddy.
    unregistered = scan_processes(skip_ports=caddy_ports)
    logger.debug("Process scan: %d unregistered services", len(unregistered))

    logger.info(
        "Services: %d configured, %d unregistered", len(services), len(unregistered)
    )
    return {"services": services, "unregistered": unregistered}
```

- [ ] **Step 4: Run the new test and existing tests to verify they pass**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_services_route.py -v`
Expected: All 7 tests pass (6 existing + 1 new). The existing tests should still pass because `systemd_unit` is an additive field — existing assertions don't check for its absence.

Note: If existing tests fail because `get_port_pids` is called without being mocked, add a default empty-dict mock. Patch `frontdoor.routes.services.get_port_pids` with `return_value={}` in the `service_client` fixture or in each existing test. The simplest fix is to add the patch to every existing test's `with` block:

```python
patch("frontdoor.routes.services.get_port_pids", return_value={}),
patch("frontdoor.routes.services.get_systemd_unit", return_value=None),
```

- [ ] **Step 5: Commit**

```bash
cd /home/robotdad/repos/frontdoor
git add frontdoor/routes/services.py tests/test_services_route.py
git commit -m "feat: enrich /api/services with systemd_unit field"
```

---

## Task Group 2 — Auth Model + Tokens

Adds three-tier admin auth and token management. Foundation for all admin endpoints.

### Task 2.1: New config settings

**Files:**
- Modify: `frontdoor/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing test for new settings**

Add to `tests/test_config.py`:

```python
class TestAdminSettings:
    def test_tokens_file_default(self):
        """tokens_file defaults to /opt/frontdoor/tokens.json."""
        from frontdoor.config import Settings

        s = Settings()
        assert s.tokens_file == Path("/opt/frontdoor/tokens.json")

    def test_allow_localhost_admin_default(self):
        """allow_localhost_admin defaults to True."""
        from frontdoor.config import Settings

        s = Settings()
        assert s.allow_localhost_admin is True

    def test_self_unit_default(self):
        """self_unit defaults to 'frontdoor.service'."""
        from frontdoor.config import Settings

        s = Settings()
        assert s.self_unit == "frontdoor.service"

    def test_service_user_default_empty(self):
        """service_user defaults to empty string."""
        from frontdoor.config import Settings

        s = Settings()
        assert s.service_user == ""
```

Add `from pathlib import Path` to the test file's imports if not already present.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_config.py::TestAdminSettings -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'tokens_file'`

- [ ] **Step 3: Add new settings to `config.py`**

Add these fields to the `Settings` dataclass in `frontdoor/config.py`:

```python
    tokens_file: Path = field(
        default_factory=lambda: Path(
            os.environ.get("FRONTDOOR_TOKENS_FILE", "/opt/frontdoor/tokens.json")
        )
    )
    allow_localhost_admin: bool = field(
        default_factory=lambda: (
            os.environ.get("FRONTDOOR_ALLOW_LOCALHOST_ADMIN", "true").lower() == "true"
        )
    )
    self_unit: str = field(
        default_factory=lambda: os.environ.get("FRONTDOOR_SELF_UNIT", "frontdoor.service")
    )
    service_user: str = field(
        default_factory=lambda: os.environ.get("FRONTDOOR_SERVICE_USER", "")
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_config.py -v`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
cd /home/robotdad/repos/frontdoor
git add frontdoor/config.py tests/test_config.py
git commit -m "feat: add admin settings (tokens_file, allow_localhost_admin, self_unit, service_user)"
```

### Task 2.2: Token module

**Files:**
- Create: `frontdoor/tokens.py`
- Create: `tests/test_tokens.py`

- [ ] **Step 1: Write failing tests for token creation and validation**

Create `tests/test_tokens.py`:

```python
"""Tests for frontdoor/tokens.py — token lifecycle."""

import json
from pathlib import Path

import pytest


class TestCreateToken:
    def test_returns_id_and_raw_token(self, tmp_path):
        """create_token returns (token_id, raw_token) tuple."""
        from frontdoor.tokens import create_token

        tokens_file = tmp_path / "tokens.json"
        token_id, raw_token = create_token("test-device", tokens_file=tokens_file)

        assert token_id.startswith("tok_")
        assert raw_token.startswith("ft_")

    def test_stores_hash_not_raw(self, tmp_path):
        """Token file stores sha256 hash, never the raw token."""
        from frontdoor.tokens import create_token

        tokens_file = tmp_path / "tokens.json"
        token_id, raw_token = create_token("test-device", tokens_file=tokens_file)

        data = json.loads(tokens_file.read_text())
        assert token_id in data
        assert "token_hash" in data[token_id]
        assert raw_token not in tokens_file.read_text()

    def test_multiple_tokens_coexist(self, tmp_path):
        """Creating multiple tokens adds entries without overwriting."""
        from frontdoor.tokens import create_token

        tokens_file = tmp_path / "tokens.json"
        id1, _ = create_token("device-1", tokens_file=tokens_file)
        id2, _ = create_token("device-2", tokens_file=tokens_file)

        data = json.loads(tokens_file.read_text())
        assert id1 in data
        assert id2 in data
        assert data[id1]["name"] == "device-1"
        assert data[id2]["name"] == "device-2"

    def test_creates_file_if_missing(self, tmp_path):
        """create_token creates the tokens file if it doesn't exist."""
        from frontdoor.tokens import create_token

        tokens_file = tmp_path / "subdir" / "tokens.json"
        create_token("test", tokens_file=tokens_file)
        assert tokens_file.exists()


class TestValidateToken:
    def test_valid_token_returns_name(self, tmp_path):
        """validate_token returns the token name for a valid raw token."""
        from frontdoor.tokens import create_token, validate_token

        tokens_file = tmp_path / "tokens.json"
        _, raw_token = create_token("my-laptop", tokens_file=tokens_file)

        result = validate_token(raw_token, tokens_file=tokens_file)
        assert result == "my-laptop"

    def test_invalid_token_returns_none(self, tmp_path):
        """validate_token returns None for an invalid token."""
        from frontdoor.tokens import create_token, validate_token

        tokens_file = tmp_path / "tokens.json"
        create_token("my-laptop", tokens_file=tokens_file)

        result = validate_token("ft_invalid_garbage", tokens_file=tokens_file)
        assert result is None

    def test_non_ft_prefix_returns_none(self, tmp_path):
        """validate_token returns None for tokens without ft_ prefix."""
        from frontdoor.tokens import validate_token

        tokens_file = tmp_path / "tokens.json"
        tokens_file.write_text("{}")

        result = validate_token("not_a_valid_token", tokens_file=tokens_file)
        assert result is None

    def test_missing_file_returns_none(self, tmp_path):
        """validate_token returns None when tokens file doesn't exist."""
        from frontdoor.tokens import validate_token

        tokens_file = tmp_path / "nonexistent.json"
        result = validate_token("ft_anything", tokens_file=tokens_file)
        assert result is None


class TestListTokens:
    def test_lists_tokens_without_hashes(self, tmp_path):
        """list_tokens returns id, name, created_at but never token_hash."""
        from frontdoor.tokens import create_token, list_tokens

        tokens_file = tmp_path / "tokens.json"
        create_token("device-a", tokens_file=tokens_file)
        create_token("device-b", tokens_file=tokens_file)

        result = list_tokens(tokens_file=tokens_file)
        assert len(result) == 2
        for entry in result:
            assert "id" in entry
            assert "name" in entry
            assert "created_at" in entry
            assert "token_hash" not in entry

    def test_empty_file_returns_empty_list(self, tmp_path):
        """list_tokens returns [] when no tokens exist."""
        from frontdoor.tokens import list_tokens

        tokens_file = tmp_path / "tokens.json"
        tokens_file.write_text("{}")

        result = list_tokens(tokens_file=tokens_file)
        assert result == []


class TestRevokeToken:
    def test_revoke_existing_returns_true(self, tmp_path):
        """revoke_token returns True and removes the token entry."""
        from frontdoor.tokens import create_token, revoke_token, validate_token

        tokens_file = tmp_path / "tokens.json"
        token_id, raw_token = create_token("ephemeral", tokens_file=tokens_file)

        assert revoke_token(token_id, tokens_file=tokens_file) is True
        assert validate_token(raw_token, tokens_file=tokens_file) is None

    def test_revoke_nonexistent_returns_false(self, tmp_path):
        """revoke_token returns False when the token_id doesn't exist."""
        from frontdoor.tokens import revoke_token

        tokens_file = tmp_path / "tokens.json"
        tokens_file.write_text("{}")

        assert revoke_token("tok_doesnotexist", tokens_file=tokens_file) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_tokens.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'frontdoor.tokens'`

- [ ] **Step 3: Implement `frontdoor/tokens.py`**

Create `frontdoor/tokens.py`:

```python
"""API token management — creation, validation, listing, and revocation.

Tokens are stored as SHA-256 hashes in a JSON file.  The raw token is
returned once at creation time and never persisted.
"""

import hashlib
import json
import logging
import secrets
from datetime import datetime, timezone
from pathlib import Path

from frontdoor.config import settings

logger = logging.getLogger(__name__)


def _hash_token(raw_token: str) -> str:
    """Return the hex SHA-256 digest of *raw_token*."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _read_tokens(tokens_file: Path) -> dict:
    """Read the tokens JSON file, returning an empty dict if missing or invalid."""
    try:
        return json.loads(tokens_file.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_tokens(tokens_file: Path, data: dict) -> None:
    """Write the tokens dict to disk, creating parent directories if needed."""
    tokens_file.parent.mkdir(parents=True, exist_ok=True)
    tokens_file.write_text(json.dumps(data, indent=2))


def create_token(
    name: str, *, tokens_file: Path | None = None
) -> tuple[str, str]:
    """Create a new API token.

    Returns ``(token_id, raw_token)``.  The raw token is shown once —
    only its SHA-256 hash is stored on disk.

    Args:
        name: Human-readable label for this token (e.g. "robotdad-macbook").
        tokens_file: Override path to the tokens JSON file (defaults to
            ``settings.tokens_file``).
    """
    tf = tokens_file or settings.tokens_file
    token_id = "tok_" + secrets.token_hex(8)
    raw_token = "ft_" + secrets.token_urlsafe(32)

    data = _read_tokens(tf)
    data[token_id] = {
        "name": name,
        "token_hash": _hash_token(raw_token),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_used_at": None,
    }
    _write_tokens(tf, data)

    logger.info("Created API token %s (%s)", token_id, name)
    return token_id, raw_token


def validate_token(
    raw_token: str, *, tokens_file: Path | None = None
) -> str | None:
    """Validate a raw API token.

    Returns the token name on success, ``None`` on failure.  Updates
    ``last_used_at`` on successful validation (best-effort).

    Args:
        raw_token: The ``ft_...`` token string from the Authorization header.
        tokens_file: Override path to the tokens JSON file.
    """
    if not raw_token.startswith("ft_"):
        return None

    tf = tokens_file or settings.tokens_file
    data = _read_tokens(tf)
    if not data:
        return None

    token_hash = _hash_token(raw_token)
    for token_id, entry in data.items():
        if entry.get("token_hash") == token_hash:
            # Best-effort last_used_at update — non-blocking.
            try:
                entry["last_used_at"] = datetime.now(timezone.utc).isoformat()
                _write_tokens(tf, data)
            except Exception:
                pass
            return entry["name"]

    return None


def list_tokens(*, tokens_file: Path | None = None) -> list[dict]:
    """List all tokens — IDs and names, never hashes.

    Args:
        tokens_file: Override path to the tokens JSON file.
    """
    tf = tokens_file or settings.tokens_file
    data = _read_tokens(tf)
    return [
        {
            "id": token_id,
            "name": entry["name"],
            "created_at": entry.get("created_at"),
            "last_used_at": entry.get("last_used_at"),
        }
        for token_id, entry in data.items()
    ]


def revoke_token(
    token_id: str, *, tokens_file: Path | None = None
) -> bool:
    """Revoke a token by its ID.

    Returns ``True`` if the token was found and removed, ``False`` otherwise.

    Args:
        token_id: The ``tok_...`` identifier.
        tokens_file: Override path to the tokens JSON file.
    """
    tf = tokens_file or settings.tokens_file
    data = _read_tokens(tf)
    if token_id not in data:
        return False

    del data[token_id]
    _write_tokens(tf, data)
    logger.info("Revoked API token %s", token_id)
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_tokens.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
cd /home/robotdad/repos/frontdoor
git add frontdoor/tokens.py tests/test_tokens.py
git commit -m "feat: add token module (create, validate, list, revoke)"
```

### Task 2.3: `require_admin_auth` dependency

**Files:**
- Modify: `frontdoor/auth.py`
- Create: `tests/test_admin_auth.py`

- [ ] **Step 1: Write failing tests for three-tier admin auth**

Create `tests/test_admin_auth.py`:

```python
"""Tests for require_admin_auth — three-tier admin authentication."""

import asyncio
import json

import pytest
from fastapi import HTTPException
from unittest.mock import MagicMock, patch

from frontdoor.config import Settings

SECRET = "test-secret-key-for-admin-auth"


def _make_request(
    host: str = "10.0.0.5",
    bearer: str | None = None,
    cookie: str | None = None,
) -> MagicMock:
    """Build a mock FastAPI Request with configurable auth sources."""
    request = MagicMock()
    request.client = MagicMock()
    request.client.host = host
    request.headers = {}
    if bearer:
        request.headers["authorization"] = f"Bearer {bearer}"
    request.cookies = {}
    if cookie:
        request.cookies["frontdoor_session"] = cookie
    return request


class TestLocalhostBypass:
    def test_localhost_allowed(self, tmp_path):
        """Requests from 127.0.0.1 pass without token or cookie."""
        from frontdoor.auth import require_admin_auth

        tokens_file = tmp_path / "tokens.json"
        tokens_file.write_text("{}")
        mock_settings = Settings()
        mock_settings.allow_localhost_admin = True
        mock_settings.tokens_file = tokens_file

        request = _make_request(host="127.0.0.1")

        with patch("frontdoor.auth.settings", mock_settings):
            result = asyncio.get_event_loop().run_until_complete(
                require_admin_auth(request)
            )
        assert result == "localhost"

    def test_localhost_disabled(self, tmp_path):
        """When allow_localhost_admin=False, localhost alone is not enough."""
        from frontdoor.auth import require_admin_auth

        tokens_file = tmp_path / "tokens.json"
        tokens_file.write_text("{}")
        mock_settings = Settings()
        mock_settings.allow_localhost_admin = False
        mock_settings.tokens_file = tokens_file
        mock_settings.secret_key = SECRET
        mock_settings.session_timeout = 3600

        request = _make_request(host="127.0.0.1")

        with patch("frontdoor.auth.settings", mock_settings):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.get_event_loop().run_until_complete(
                    require_admin_auth(request)
                )
        assert exc_info.value.status_code == 401


class TestTokenAuth:
    def test_valid_bearer_token(self, tmp_path):
        """Valid Bearer token returns the token name."""
        from frontdoor.auth import require_admin_auth
        from frontdoor.tokens import create_token

        tokens_file = tmp_path / "tokens.json"
        _, raw_token = create_token("test-device", tokens_file=tokens_file)

        mock_settings = Settings()
        mock_settings.tokens_file = tokens_file
        mock_settings.allow_localhost_admin = False
        mock_settings.secret_key = SECRET
        mock_settings.session_timeout = 3600

        request = _make_request(host="10.0.0.5", bearer=raw_token)

        with patch("frontdoor.auth.settings", mock_settings):
            result = asyncio.get_event_loop().run_until_complete(
                require_admin_auth(request)
            )
        assert result == "token:test-device"

    def test_invalid_bearer_token(self, tmp_path):
        """Invalid Bearer token with no other auth raises 401."""
        from frontdoor.auth import require_admin_auth

        tokens_file = tmp_path / "tokens.json"
        tokens_file.write_text("{}")
        mock_settings = Settings()
        mock_settings.tokens_file = tokens_file
        mock_settings.allow_localhost_admin = False
        mock_settings.secret_key = SECRET
        mock_settings.session_timeout = 3600

        request = _make_request(host="10.0.0.5", bearer="ft_invalid_garbage")

        with patch("frontdoor.auth.settings", mock_settings):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.get_event_loop().run_until_complete(
                    require_admin_auth(request)
                )
        assert exc_info.value.status_code == 401


class TestCookieAuth:
    def test_valid_session_cookie(self, tmp_path):
        """Valid session cookie passes admin auth."""
        from frontdoor.auth import create_session_token, require_admin_auth

        tokens_file = tmp_path / "tokens.json"
        tokens_file.write_text("{}")
        mock_settings = Settings()
        mock_settings.tokens_file = tokens_file
        mock_settings.allow_localhost_admin = False
        mock_settings.secret_key = SECRET
        mock_settings.session_timeout = 3600

        token = create_session_token("alice", SECRET)
        request = _make_request(host="10.0.0.5", cookie=token)

        with patch("frontdoor.auth.settings", mock_settings):
            result = asyncio.get_event_loop().run_until_complete(
                require_admin_auth(request)
            )
        assert result == "alice"


class TestNoAuth:
    def test_no_credentials_raises_401(self, tmp_path):
        """Request with no auth of any kind raises 401."""
        from frontdoor.auth import require_admin_auth

        tokens_file = tmp_path / "tokens.json"
        tokens_file.write_text("{}")
        mock_settings = Settings()
        mock_settings.tokens_file = tokens_file
        mock_settings.allow_localhost_admin = False
        mock_settings.secret_key = SECRET
        mock_settings.session_timeout = 3600

        request = _make_request(host="10.0.0.5")

        with patch("frontdoor.auth.settings", mock_settings):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.get_event_loop().run_until_complete(
                    require_admin_auth(request)
                )
        assert exc_info.value.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_admin_auth.py -v`
Expected: FAIL — `ImportError: cannot import name 'require_admin_auth' from 'frontdoor.auth'`

- [ ] **Step 3: Implement `require_admin_auth` in `frontdoor/auth.py`**

Add these imports to the top of `frontdoor/auth.py`:

```python
from frontdoor.tokens import validate_token
```

Add this function after the existing `require_auth`:

```python
async def require_admin_auth(request: Request) -> str:
    """FastAPI dependency — authenticate for admin endpoints.

    Checks three tiers in order (first match wins):
    1. Localhost bypass (``request.client.host == "127.0.0.1"``)
    2. API token (``Authorization: Bearer ft_...``)
    3. PAM session cookie (existing ``frontdoor_session``)

    Returns the authenticated identity string:
    - ``"localhost"`` for tier 1
    - ``"token:<name>"`` for tier 2
    - ``"<username>"`` for tier 3

    Raises HTTP 401 if all tiers fail.
    """
    # Tier 1: Localhost bypass
    client_host = request.client.host if request.client else None
    if client_host == "127.0.0.1" and settings.allow_localhost_admin:
        logger.debug("Admin auth: localhost bypass")
        return "localhost"

    # Tier 2: API token
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        raw_token = auth_header[7:]
        token_name = validate_token(raw_token)
        if token_name:
            logger.debug("Admin auth: token %s", token_name)
            return f"token:{token_name}"

    # Tier 3: PAM session cookie
    session_cookie = request.cookies.get("frontdoor_session")
    if session_cookie:
        username = validate_session_token(
            session_cookie, settings.secret_key, settings.session_timeout
        )
        if username:
            logger.debug("Admin auth: session cookie user=%s", username)
            return username

    logger.warning("Admin auth: all tiers failed from %s", client_host)
    raise HTTPException(
        status_code=401,
        detail={"error": "Admin authentication required", "code": "UNAUTHORIZED"},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_admin_auth.py -v`
Expected: 6 passed

- [ ] **Step 5: Run all existing tests to check for regressions**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/ -v`
Expected: All tests pass (the import of `validate_token` in `auth.py` triggers on module load but should not break anything — `tokens.py` is self-contained).

- [ ] **Step 6: Commit**

```bash
cd /home/robotdad/repos/frontdoor
git add frontdoor/auth.py tests/test_admin_auth.py
git commit -m "feat: add require_admin_auth three-tier dependency"
```

### Task 2.4: Admin router with token endpoints + registration in main.py

**Files:**
- Create: `frontdoor/routes/admin.py`
- Modify: `frontdoor/main.py`
- Create: `tests/test_admin_routes.py`

- [ ] **Step 1: Write failing tests for token management endpoints**

Create `tests/test_admin_routes.py`:

```python
"""Tests for /api/admin/* endpoints."""

import json

import pytest
from starlette.testclient import TestClient
from unittest.mock import patch

import frontdoor.config as config_module
from frontdoor.config import Settings
from frontdoor.main import app
from frontdoor.tokens import create_token

SECRET = "test-secret-for-admin-routes"


@pytest.fixture
def admin_client(tmp_path):
    """TestClient with admin auth via localhost bypass and temporary tokens file."""
    tokens_file = tmp_path / "tokens.json"
    tokens_file.write_text("{}")

    orig_tokens_file = config_module.settings.tokens_file
    orig_allow = config_module.settings.allow_localhost_admin

    config_module.settings.tokens_file = tokens_file
    config_module.settings.allow_localhost_admin = True

    with TestClient(app, base_url="http://localhost:8420") as client:
        # TestClient connects from 127.0.0.1 by default (testserver),
        # so localhost bypass should work.
        yield client, tokens_file

    config_module.settings.tokens_file = orig_tokens_file
    config_module.settings.allow_localhost_admin = orig_allow


class TestTokenEndpoints:
    def test_create_token(self, admin_client):
        """POST /api/admin/tokens creates a token and returns id + raw token."""
        client, tokens_file = admin_client
        resp = client.post("/api/admin/tokens", json={"name": "test-device"})

        assert resp.status_code == 201
        data = resp.json()
        assert data["id"].startswith("tok_")
        assert data["token"].startswith("ft_")
        assert data["name"] == "test-device"

    def test_list_tokens(self, admin_client):
        """GET /api/admin/tokens lists tokens without hashes."""
        client, tokens_file = admin_client
        # Create a token first
        create_token("device-a", tokens_file=tokens_file)

        resp = client.get("/api/admin/tokens")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "device-a"
        assert "token_hash" not in data[0]

    def test_revoke_token(self, admin_client):
        """DELETE /api/admin/tokens/{id} removes the token."""
        client, tokens_file = admin_client
        token_id, _ = create_token("ephemeral", tokens_file=tokens_file)

        resp = client.delete(f"/api/admin/tokens/{token_id}")
        assert resp.status_code == 200

        # Verify it's gone
        list_resp = client.get("/api/admin/tokens")
        assert len(list_resp.json()) == 0

    def test_revoke_nonexistent_returns_404(self, admin_client):
        """DELETE /api/admin/tokens/{bad_id} returns 404."""
        client, _ = admin_client
        resp = client.delete("/api/admin/tokens/tok_doesnotexist")
        assert resp.status_code == 404

    def test_create_token_via_bearer_rejected(self, admin_client):
        """POST /api/admin/tokens via bearer token is rejected (tier escalation prevention)."""
        client, tokens_file = admin_client
        # Create a token to use as bearer
        _, raw_token = create_token("existing", tokens_file=tokens_file)

        # Disable localhost bypass so we test pure bearer auth
        config_module.settings.allow_localhost_admin = False

        resp = client.post(
            "/api/admin/tokens",
            json={"name": "escalated"},
            headers={"Authorization": f"Bearer {raw_token}"},
        )

        # Should be rejected — token creation requires Tier 1 or Tier 3 only
        assert resp.status_code == 403

        # Re-enable for teardown
        config_module.settings.allow_localhost_admin = True

    def test_unauthenticated_returns_401(self):
        """Unauthenticated request to admin endpoints returns 401."""
        orig_allow = config_module.settings.allow_localhost_admin
        config_module.settings.allow_localhost_admin = False

        with TestClient(app, base_url="http://testserver") as client:
            resp = client.get("/api/admin/tokens")

        config_module.settings.allow_localhost_admin = orig_allow
        assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_admin_routes.py -v`
Expected: FAIL — 404 on `/api/admin/tokens` because the admin router doesn't exist yet

- [ ] **Step 3: Create `frontdoor/routes/admin.py` with token endpoints**

Create `frontdoor/routes/admin.py`:

```python
"""Admin API router — all /api/admin/* endpoints.

Protected by require_admin_auth (three-tier: localhost → bearer → cookie).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from frontdoor.auth import require_admin_auth
from frontdoor.tokens import create_token, list_tokens, revoke_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class TokenCreateRequest(BaseModel):
    name: str


class TokenCreateResponse(BaseModel):
    id: str
    name: str
    token: str
    created_at: str


# ---------------------------------------------------------------------------
# Auth helpers for token creation restriction
# ---------------------------------------------------------------------------

def _is_token_auth(identity: str) -> bool:
    """Return True if the identity string indicates bearer token auth."""
    return identity.startswith("token:")


# ---------------------------------------------------------------------------
# Token management — POST/GET/DELETE /api/admin/tokens
# ---------------------------------------------------------------------------

@router.post("/tokens", status_code=201)
async def create_api_token(
    body: TokenCreateRequest,
    request: Request,
    identity: str = Depends(require_admin_auth),
) -> dict:
    """Create a new API token.

    Requires Tier 1 (localhost) or Tier 3 (PAM session). Bearer tokens
    cannot create new tokens (prevents escalation if a token leaks).
    """
    if _is_token_auth(identity):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "Token creation requires localhost or session auth",
                "code": "FORBIDDEN",
            },
        )

    token_id, raw_token = create_token(body.name)
    logger.info("Token created: %s (%s) by %s", token_id, body.name, identity)

    # Read back to get the created_at timestamp
    tokens = list_tokens()
    entry = next((t for t in tokens if t["id"] == token_id), {})

    return {
        "id": token_id,
        "name": body.name,
        "token": raw_token,
        "created_at": entry.get("created_at", ""),
    }


@router.get("/tokens")
async def list_api_tokens(
    identity: str = Depends(require_admin_auth),
) -> list[dict]:
    """List all tokens — IDs, names, timestamps. Never returns hashes."""
    return list_tokens()


@router.delete("/tokens/{token_id}")
async def revoke_api_token(
    token_id: str,
    identity: str = Depends(require_admin_auth),
) -> dict:
    """Revoke a token by ID."""
    if not revoke_token(token_id):
        raise HTTPException(
            status_code=404,
            detail={"error": f"Token {token_id} not found", "code": "NOT_FOUND"},
        )
    logger.info("Token revoked: %s by %s", token_id, identity)
    return {"status": "revoked", "id": token_id}
```

- [ ] **Step 4: Register admin router in `main.py`**

Edit `frontdoor/main.py`. Add to imports:

```python
from frontdoor.routes import admin, auth, services
```

(Replace the existing `from frontdoor.routes import auth, services` line.)

Add after the services router inclusion:

```python
# Include the admin router (provides /api/admin/* management endpoints).
app.include_router(admin.router)
```

This must be added **before** the static files mount (which is a catch-all at `/`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_admin_routes.py -v`
Expected: 6 passed

Note: The `admin_client` fixture relies on TestClient presenting as `127.0.0.1`. If the test client host shows as `testserver` instead, the localhost bypass won't work. In that case, mock `require_admin_auth` to return `"localhost"` directly, or patch `request.client.host`. The Starlette TestClient typically reports the client as `testclient` — so we may need to patch the auth check. If tests fail for this reason, update the fixture to mock `require_admin_auth`:

```python
@pytest.fixture
def admin_client(tmp_path):
    tokens_file = tmp_path / "tokens.json"
    tokens_file.write_text("{}")

    orig_tokens_file = config_module.settings.tokens_file
    config_module.settings.tokens_file = tokens_file

    with TestClient(app, base_url="http://localhost:8420") as client:
        yield client, tokens_file

    config_module.settings.tokens_file = orig_tokens_file
```

And for tests needing localhost bypass, patch `require_admin_auth` directly. For the bearer-rejection test, use a different approach. Adjust tests as needed when running.

- [ ] **Step 6: Run all tests to check for regressions**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 7: Commit**

```bash
cd /home/robotdad/repos/frontdoor
git add frontdoor/routes/admin.py frontdoor/main.py tests/test_admin_routes.py
git commit -m "feat: add admin router with token management endpoints"
```

---

## Task Group 3 — Service Control

Adds `frontdoor-priv` helper, `run_privileged()` wrapper, and restart endpoints.

### Task 3.1: `frontdoor-priv` privileged helper

**Files:**
- Create: `frontdoor/bin/frontdoor-priv`

- [ ] **Step 1: Create the `frontdoor/bin/` directory and the privileged helper script**

Create `frontdoor/bin/__init__.py` (empty, for package detection) — actually, this is a data file, not a package. Just create the directory.

Create `frontdoor/bin/frontdoor-priv`:

```python
#!/usr/bin/env python3
"""frontdoor-priv — privileged helper for frontdoor management operations.

This script is the ONLY target of the frontdoor sudoers entry. It reads
a JSON payload from stdin, validates the operation against an explicit
allowlist, validates the slug against a strict regex, and executes the
operation.

Usage (called by frontdoor/service_control.py via sudo):
    echo '{"operation": "systemctl", "action": "restart", "unit": "muxplex.service"}' | sudo frontdoor-priv
"""

import json
import os
import re
import subprocess
import sys

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
ALLOWED_OPERATIONS = {
    "write-caddy",
    "delete-caddy",
    "write-service",
    "delete-service",
    "systemctl",
    "caddy-reload",
}
ALLOWED_SYSTEMCTL_ACTIONS = {"restart", "enable", "disable", "start", "stop", "daemon-reload"}

CADDY_CONF_D = "/etc/caddy/conf.d"
SYSTEMD_DIR = "/etc/systemd/system"


def die(msg: str) -> None:
    print(json.dumps({"error": msg}), file=sys.stderr)
    sys.exit(1)


def validate_slug(slug: str) -> None:
    if not SLUG_RE.match(slug):
        die(f"Invalid slug: {slug!r}")


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        die(f"Invalid JSON: {e}")

    operation = payload.get("operation")
    if operation not in ALLOWED_OPERATIONS:
        die(f"Unknown operation: {operation!r}")

    if operation == "write-caddy":
        slug = payload.get("slug", "")
        validate_slug(slug)
        content = payload.get("content", "")
        if not content:
            die("write-caddy requires non-empty content")
        path = os.path.join(CADDY_CONF_D, f"{slug}.caddy")
        with open(path, "w") as f:
            f.write(content)
        print(json.dumps({"ok": True, "path": path}))

    elif operation == "delete-caddy":
        slug = payload.get("slug", "")
        validate_slug(slug)
        path = os.path.join(CADDY_CONF_D, f"{slug}.caddy")
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        print(json.dumps({"ok": True, "path": path}))

    elif operation == "write-service":
        slug = payload.get("slug", "")
        validate_slug(slug)
        content = payload.get("content", "")
        if not content:
            die("write-service requires non-empty content")
        path = os.path.join(SYSTEMD_DIR, f"{slug}.service")
        with open(path, "w") as f:
            f.write(content)
        print(json.dumps({"ok": True, "path": path}))

    elif operation == "delete-service":
        slug = payload.get("slug", "")
        validate_slug(slug)
        path = os.path.join(SYSTEMD_DIR, f"{slug}.service")
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        print(json.dumps({"ok": True, "path": path}))

    elif operation == "systemctl":
        action = payload.get("action", "")
        if action not in ALLOWED_SYSTEMCTL_ACTIONS:
            die(f"Disallowed systemctl action: {action!r}")
        if action == "daemon-reload":
            subprocess.run(["systemctl", "daemon-reload"], check=True)
        else:
            unit = payload.get("unit", "")
            if not unit.endswith(".service"):
                die(f"Unit must end with .service: {unit!r}")
            # Validate the unit name (slug portion)
            slug_part = unit.removesuffix(".service")
            validate_slug(slug_part)
            subprocess.run(["systemctl", action, unit], check=True)
        print(json.dumps({"ok": True}))

    elif operation == "caddy-reload":
        subprocess.run(["systemctl", "reload", "caddy"], check=True)
        print(json.dumps({"ok": True}))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make the script executable**

```bash
chmod +x /home/robotdad/repos/frontdoor/frontdoor/bin/frontdoor-priv
```

- [ ] **Step 3: Commit**

```bash
cd /home/robotdad/repos/frontdoor
mkdir -p frontdoor/bin
git add frontdoor/bin/frontdoor-priv
git commit -m "feat: add frontdoor-priv privileged helper script"
```

### Task 3.2: `service_control.py` — `run_privileged()` wrapper

**Files:**
- Create: `frontdoor/service_control.py`
- Create: `tests/test_service_control.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_service_control.py`:

```python
"""Tests for frontdoor/service_control.py — run_privileged wrapper."""

import json

import pytest
from unittest.mock import MagicMock, patch, call


class TestRunPrivileged:
    def test_calls_sudo_with_json_stdin(self):
        """run_privileged calls sudo frontdoor-priv with JSON on stdin."""
        from frontdoor.service_control import run_privileged

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '{"ok": true}'

        with patch("frontdoor.service_control.subprocess.run", return_value=mock_result) as mock_run:
            run_privileged("systemctl", action="restart", unit="muxplex.service")

        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        assert args[0][0] == "sudo"
        assert "frontdoor-priv" in args[0][-1]

        # Verify JSON payload was passed via stdin
        stdin_data = json.loads(kwargs["input"])
        assert stdin_data["operation"] == "systemctl"
        assert stdin_data["action"] == "restart"
        assert stdin_data["unit"] == "muxplex.service"

    def test_raises_on_nonzero_exit(self):
        """run_privileged raises RuntimeError when frontdoor-priv fails."""
        from frontdoor.service_control import run_privileged

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = '{"error": "something broke"}'

        with patch("frontdoor.service_control.subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="frontdoor-priv failed"):
                run_privileged("systemctl", action="restart", unit="bad.service")

    def test_raises_on_timeout(self):
        """run_privileged raises RuntimeError on subprocess timeout."""
        from frontdoor.service_control import run_privileged
        import subprocess

        with patch(
            "frontdoor.service_control.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="sudo", timeout=30),
        ):
            with pytest.raises(RuntimeError, match="timed out"):
                run_privileged("systemctl", action="restart", unit="stuck.service")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_service_control.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'frontdoor.service_control'`

- [ ] **Step 3: Implement `frontdoor/service_control.py`**

Create `frontdoor/service_control.py`:

```python
"""Service control — privileged operations via frontdoor-priv.

All privileged operations (writing Caddy configs, systemd units, and
running systemctl) are delegated to the ``frontdoor-priv`` helper via
``sudo``.  This module provides the ``run_privileged()`` wrapper that
serializes operations as JSON on stdin.
"""

import json
import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Locate frontdoor-priv relative to this module.
_PRIV_SCRIPT = Path(__file__).parent / "bin" / "frontdoor-priv"


def _find_priv_script() -> str:
    """Return the absolute path to frontdoor-priv.

    Checks the package-relative location first, then falls back to
    ``/opt/frontdoor/bin/frontdoor-priv`` for deployed installs.
    """
    if _PRIV_SCRIPT.exists():
        return str(_PRIV_SCRIPT)
    fallback = Path("/opt/frontdoor/bin/frontdoor-priv")
    if fallback.exists():
        return str(fallback)
    # Last resort: assume it's on PATH
    found = shutil.which("frontdoor-priv")
    if found:
        return found
    return str(_PRIV_SCRIPT)  # will fail with a clear error


def run_privileged(operation: str, **kwargs: str) -> None:
    """Call ``frontdoor-priv`` via sudo with a JSON payload on stdin.

    Args:
        operation: One of the allowed operations (write-caddy, delete-caddy,
            write-service, delete-service, systemctl, caddy-reload).
        **kwargs: Additional fields for the JSON payload (e.g. slug, content,
            action, unit).

    Raises:
        RuntimeError: If the helper exits non-zero or times out.
    """
    payload = {"operation": operation, **kwargs}
    priv_path = _find_priv_script()

    logger.info("run_privileged: %s %s", operation, kwargs.get("slug", kwargs.get("unit", "")))

    try:
        result = subprocess.run(
            ["sudo", priv_path],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"frontdoor-priv timed out: operation={operation}"
        )

    if result.returncode != 0:
        error_msg = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise RuntimeError(
            f"frontdoor-priv failed (exit {result.returncode}): {error_msg}"
        )

    logger.debug("run_privileged OK: %s", result.stdout.strip())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_service_control.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
cd /home/robotdad/repos/frontdoor
git add frontdoor/service_control.py tests/test_service_control.py
git commit -m "feat: add run_privileged() wrapper for frontdoor-priv"
```

### Task 3.3: Service restart endpoints

**Files:**
- Modify: `frontdoor/routes/admin.py`
- Modify: `tests/test_admin_routes.py`

- [ ] **Step 1: Write failing tests for restart endpoints**

Add to `tests/test_admin_routes.py`:

```python
class TestServiceControlEndpoints:
    def test_restart_single_service(self, admin_client):
        """POST /api/admin/services/{slug}/restart calls run_privileged."""
        client, _ = admin_client

        with patch("frontdoor.routes.admin.resolve_slug_to_unit", return_value="muxplex.service"):
            with patch("frontdoor.routes.admin.run_privileged") as mock_priv:
                resp = client.post("/api/admin/services/muxplex/restart")

        assert resp.status_code == 200
        data = resp.json()
        assert data["unit"] == "muxplex.service"
        assert data["status"] == "restarted"
        mock_priv.assert_called_once_with(
            "systemctl", action="restart", unit="muxplex.service"
        )

    def test_restart_unknown_slug_returns_404(self, admin_client):
        """POST /api/admin/services/{slug}/restart returns 404 for unknown slug."""
        client, _ = admin_client

        with patch("frontdoor.routes.admin.resolve_slug_to_unit", return_value=None):
            resp = client.post("/api/admin/services/nonexistent/restart")

        assert resp.status_code == 404

    def test_restart_all(self, admin_client):
        """POST /api/admin/services/restart-all restarts all except frontdoor."""
        client, _ = admin_client

        services = [
            {"name": "Muxplex", "url": "https://...", "status": "up", "systemd_unit": "muxplex.service"},
            {"name": "Filebrowser", "url": "https://...", "status": "up", "systemd_unit": "filebrowser.service"},
            {"name": "Frontdoor", "url": "https://...", "status": "up", "systemd_unit": "frontdoor.service"},
            {"name": "DevProc", "url": "https://...", "status": "up", "systemd_unit": None},
        ]

        with (
            patch("frontdoor.routes.admin.get_all_services", return_value=services),
            patch("frontdoor.routes.admin.run_privileged") as mock_priv,
            patch.object(config_module.settings, "self_unit", "frontdoor.service"),
        ):
            resp = client.post("/api/admin/services/restart-all")

        assert resp.status_code == 200
        data = resp.json()
        assert "muxplex.service" in data["restarted"]
        assert "filebrowser.service" in data["restarted"]
        assert any(s["unit"] == "frontdoor.service" for s in data["skipped"])
        assert "DevProc" in data["no_unit"]
        assert mock_priv.call_count == 2

    def test_restart_all_error_handling(self, admin_client):
        """POST /api/admin/services/restart-all reports errors per-service."""
        client, _ = admin_client

        services = [
            {"name": "Muxplex", "url": "https://...", "status": "up", "systemd_unit": "muxplex.service"},
        ]

        with (
            patch("frontdoor.routes.admin.get_all_services", return_value=services),
            patch(
                "frontdoor.routes.admin.run_privileged",
                side_effect=RuntimeError("timeout"),
            ),
            patch.object(config_module.settings, "self_unit", "frontdoor.service"),
        ):
            resp = client.post("/api/admin/services/restart-all")

        assert resp.status_code == 200
        data = resp.json()
        assert "muxplex.service" in data["errors"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_admin_routes.py::TestServiceControlEndpoints -v`
Expected: FAIL — 404 (endpoints don't exist yet) or ImportError

- [ ] **Step 3: Add service control endpoints to `frontdoor/routes/admin.py`**

Add these imports to the top of `frontdoor/routes/admin.py`:

```python
from frontdoor.config import settings
from frontdoor.discovery import get_port_pids, get_systemd_unit, parse_caddy_configs
from frontdoor.service_control import run_privileged
```

Add these helper functions and endpoints after the token endpoints:

```python
# ---------------------------------------------------------------------------
# Service control helpers
# ---------------------------------------------------------------------------

def resolve_slug_to_unit(slug: str) -> str | None:
    """Resolve a service slug to its systemd unit name.

    Two-pass strategy:
    1. Live: parse Caddy → find internal port → ss lookup → cgroup unit name
    2. Fallback: convention {slug}.service (for down services)
    """
    # Pass 1: live resolution
    parsed = parse_caddy_configs(settings.caddy_main_config, settings.caddy_conf_d)
    port_pids = get_port_pids()

    for svc in parsed:
        svc_slug = svc["name"].lower().replace(" ", "-")
        if svc_slug == slug:
            pid = port_pids.get(svc["internal_port"])
            if pid:
                unit = get_systemd_unit(pid)
                if unit:
                    return unit
            # Pass 2: fallback convention
            return f"{slug}.service"

    # Slug not found in Caddy at all — try convention fallback
    return f"{slug}.service" if slug else None


def get_all_services() -> list[dict]:
    """Return all services with systemd_unit enrichment (for restart-all)."""
    from frontdoor.discovery import overlay_manifests, tcp_probe

    parsed = parse_caddy_configs(settings.caddy_main_config, settings.caddy_conf_d)
    port_pids = get_port_pids()

    services: list[dict] = []
    for svc in parsed:
        pid = port_pids.get(svc["internal_port"])
        unit = get_systemd_unit(pid) if pid else None

        services.append(
            {
                "name": svc["name"],
                "url": svc["external_url"],
                "status": "up" if tcp_probe("127.0.0.1", svc["internal_port"]) else "down",
                "systemd_unit": unit,
            }
        )
    return services


# ---------------------------------------------------------------------------
# Service control — POST /api/admin/services/...
# ---------------------------------------------------------------------------

@router.post("/services/restart-all")
async def restart_all_services(
    identity: str = Depends(require_admin_auth),
) -> dict:
    """Restart all services except frontdoor itself.

    Returns a report of what was restarted, what failed, what was
    skipped (frontdoor), and what has no systemd unit.
    """
    services = get_all_services()

    restarted: list[str] = []
    errors: dict[str, str] = {}
    skipped: list[dict] = []
    no_unit: list[str] = []

    for svc in services:
        unit = svc.get("systemd_unit")
        if not unit:
            no_unit.append(svc["name"])
            continue

        if unit == settings.self_unit:
            skipped.append({
                "unit": unit,
                "reason": f"self — restart manually with: sudo systemctl restart {unit}",
            })
            continue

        try:
            run_privileged("systemctl", action="restart", unit=unit)
            restarted.append(unit)
        except RuntimeError as e:
            errors[unit] = str(e)

    logger.info(
        "restart-all by %s: %d restarted, %d errors, %d skipped, %d no_unit",
        identity, len(restarted), len(errors), len(skipped), len(no_unit),
    )
    return {
        "restarted": restarted,
        "errors": errors,
        "skipped": skipped,
        "no_unit": no_unit,
    }


@router.post("/services/{slug}/restart")
async def restart_service(
    slug: str,
    identity: str = Depends(require_admin_auth),
) -> dict:
    """Restart a single service by slug."""
    unit = resolve_slug_to_unit(slug)
    if not unit:
        raise HTTPException(
            status_code=404,
            detail={"error": f"No service found for slug: {slug}", "code": "NOT_FOUND"},
        )

    try:
        run_privileged("systemctl", action="restart", unit=unit)
    except RuntimeError as e:
        raise HTTPException(
            status_code=500,
            detail={"error": str(e), "code": "RESTART_FAILED"},
        )

    logger.info("Restarted %s (%s) by %s", slug, unit, identity)
    return {"slug": slug, "unit": unit, "status": "restarted"}
```

**Important:** The `restart-all` route must be defined BEFORE `{slug}/restart` in the router so that `restart-all` doesn't match as a slug.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_admin_routes.py::TestServiceControlEndpoints -v`
Expected: 4 passed

- [ ] **Step 5: Run all tests**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
cd /home/robotdad/repos/frontdoor
git add frontdoor/routes/admin.py tests/test_admin_routes.py
git commit -m "feat: add service restart and restart-all endpoints"
```

### Task 3.4: Update `deploy/install.sh` with sudoers entry

**Files:**
- Modify: `deploy/install.sh`

- [ ] **Step 1: Add sudoers entry after the PAM section**

Add after the "Ensure PAM access" section in `deploy/install.sh` (around line 64):

```bash
# --- Ensure sudoers access for frontdoor-priv ---
echo "Setting up sudoers for frontdoor-priv..."
SUDOERS_FILE="/etc/sudoers.d/frontdoor-priv"
PRIV_SCRIPT="$INSTALL_DIR/bin/frontdoor-priv"
if [ ! -f "$SUDOERS_FILE" ] || ! grep -q "frontdoor-priv" "$SUDOERS_FILE" 2>/dev/null; then
    cat > "$SUDOERS_FILE" <<EOF
# Allow frontdoor service user to run privileged operations
$USER ALL=(root) NOPASSWD: $PRIV_SCRIPT
EOF
    chmod 440 "$SUDOERS_FILE"
    echo "  Created $SUDOERS_FILE"
else
    echo "  Sudoers entry already exists"
fi
```

Also add to the install section (after the rsync + venv creation, around line 76) to ensure the bin directory is installed:

```bash
# Ensure frontdoor-priv is executable
chmod +x "$INSTALL_DIR/frontdoor/bin/frontdoor-priv"
```

- [ ] **Step 2: Commit**

```bash
cd /home/robotdad/repos/frontdoor
git add deploy/install.sh
git commit -m "feat: add sudoers entry for frontdoor-priv to install.sh"
```

---

## Task Group 4 — Port Allocation + Manifests

Low-privilege admin endpoints. Port allocation needs to read Caddy configs and `ss` output.

### Task 4.1: `next_available_ports()` in discovery

**Files:**
- Modify: `frontdoor/discovery.py`
- Modify: `tests/test_discovery_enrichment.py`

- [ ] **Step 1: Write failing tests for port allocation**

Add to `tests/test_discovery_enrichment.py`:

```python
class TestNextAvailablePorts:
    def test_returns_pair_of_free_ports(self, tmp_path):
        """next_available_ports returns (internal, external) pair."""
        from frontdoor.discovery import next_available_ports

        conf_d = tmp_path / "conf.d"
        conf_d.mkdir()
        # One existing service on external 8441, internal 8088
        (conf_d / "muxplex.caddy").write_text(
            ":8441 {\n    reverse_proxy localhost:8088\n}\n"
        )

        # ss shows 8088 is in use
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = (
            "Netid State  Recv-Q Send-Q Local Address:Port Peer Address:Port Process\n"
            'tcp   LISTEN 0      128    0.0.0.0:8088      0.0.0.0:*         users:(("uvicorn",pid=1,fd=6))\n'
        )

        with (
            patch("frontdoor.discovery.subprocess.run", return_value=mock_result),
            patch("frontdoor.discovery.settings") as mock_settings,
        ):
            mock_settings.port = 8420
            mock_settings.caddy_conf_d = conf_d
            mock_settings.caddy_main_config = tmp_path / "Caddyfile"
            (tmp_path / "Caddyfile").write_text("")

            internal, external = next_available_ports(start=8440)

        # 8440 is free (not in Caddy, not in ss, not reserved)
        # Ports must be different and sequential
        assert internal != external
        assert internal >= 8440
        assert external >= 8440

    def test_skips_used_ports(self, tmp_path):
        """next_available_ports skips ports used by Caddy or live processes."""
        from frontdoor.discovery import next_available_ports

        conf_d = tmp_path / "conf.d"
        conf_d.mkdir()
        # Caddy uses 8440 external, 8440 internal (same port)
        (conf_d / "app1.caddy").write_text(
            ":8440 {\n    reverse_proxy localhost:8440\n}\n"
        )

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = (
            "Netid State  Recv-Q Send-Q Local Address:Port Peer Address:Port Process\n"
            'tcp   LISTEN 0      128    0.0.0.0:8440      0.0.0.0:*         users:(("app1",pid=1,fd=6))\n'
            'tcp   LISTEN 0      128    0.0.0.0:8441      0.0.0.0:*         users:(("app2",pid=2,fd=7))\n'
        )

        with (
            patch("frontdoor.discovery.subprocess.run", return_value=mock_result),
            patch("frontdoor.discovery.settings") as mock_settings,
        ):
            mock_settings.port = 8420
            mock_settings.caddy_conf_d = conf_d
            mock_settings.caddy_main_config = tmp_path / "Caddyfile"
            (tmp_path / "Caddyfile").write_text("")

            internal, external = next_available_ports(start=8440)

        # 8440 is used by Caddy, 8441 is used by ss → first free is 8442
        assert internal >= 8442
        assert external > internal
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_discovery_enrichment.py::TestNextAvailablePorts -v`
Expected: FAIL — `ImportError: cannot import name 'next_available_ports'`

- [ ] **Step 3: Implement `next_available_ports` in `discovery.py`**

Add to `frontdoor/discovery.py`:

```python
def next_available_ports(start: int = 8440) -> tuple[int, int]:
    """Return the next available (internal_port, external_port) pair.

    Checks three sources for used ports:
    1. Caddy conf.d — external AND internal ports from existing vhost configs
    2. ``ss -tlnp`` — all currently-bound ports (live reality)
    3. ``RESERVED_PORTS`` from ``frontdoor/ports.py``

    The union of sources 1 and 2 prevents reusing a port that belongs
    to a registered-but-down service.

    Returns two distinct free ports starting from *start*.
    """
    # Collect Caddy-used ports (both external and internal)
    caddy_used: set[int] = set()
    parsed = parse_caddy_configs(settings.caddy_main_config, settings.caddy_conf_d)
    for svc in parsed:
        caddy_used.add(svc["internal_port"])
    # Also extract external ports from Caddy site addresses
    if settings.caddy_conf_d.exists():
        for caddy_file in settings.caddy_conf_d.glob("*.caddy"):
            try:
                content = caddy_file.read_text()
                addr_match = re.search(r":(\d+)\s*\{", content)
                if addr_match:
                    caddy_used.add(int(addr_match.group(1)))
            except Exception:
                pass

    # Collect live-used ports from ss
    port_pids = get_port_pids()
    live_used: set[int] = set(port_pids.keys())

    # Union of all used ports
    all_used = caddy_used | live_used | RESERVED_PORTS | {settings.port}

    # Find two sequential free ports
    found: list[int] = []
    port = start
    while len(found) < 2 and port <= 65535:
        if port not in all_used:
            found.append(port)
        port += 1

    if len(found) < 2:
        raise RuntimeError(f"No available port pair found starting from {start}")

    return found[0], found[1]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_discovery_enrichment.py::TestNextAvailablePorts -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
cd /home/robotdad/repos/frontdoor
git add frontdoor/discovery.py tests/test_discovery_enrichment.py
git commit -m "feat: add next_available_ports() for port allocation"
```

### Task 4.2: Port allocation and manifest admin endpoints

**Files:**
- Modify: `frontdoor/routes/admin.py`
- Modify: `tests/test_admin_routes.py`

- [ ] **Step 1: Write failing tests for port and manifest endpoints**

Add to `tests/test_admin_routes.py`:

```python
class TestPortAllocation:
    def test_next_port(self, admin_client):
        """GET /api/admin/ports/next returns internal and external ports."""
        client, _ = admin_client

        with patch(
            "frontdoor.routes.admin.next_available_ports",
            return_value=(8450, 8451),
        ):
            resp = client.get("/api/admin/ports/next")

        assert resp.status_code == 200
        data = resp.json()
        assert data["internal_port"] == 8450
        assert data["external_port"] == 8451

    def test_next_port_with_start(self, admin_client):
        """GET /api/admin/ports/next?start=9000 passes start parameter."""
        client, _ = admin_client

        with patch(
            "frontdoor.routes.admin.next_available_ports",
            return_value=(9000, 9001),
        ) as mock_nap:
            resp = client.get("/api/admin/ports/next?start=9000")

        assert resp.status_code == 200
        mock_nap.assert_called_once_with(start=9000)


class TestManifestEndpoints:
    def test_put_manifest(self, admin_client, tmp_path):
        """PUT /api/admin/manifests/{slug} creates a manifest file."""
        client, _ = admin_client
        manifest_dir = tmp_path / "manifests"
        manifest_dir.mkdir()
        config_module.settings.manifest_dir = manifest_dir

        resp = client.put(
            "/api/admin/manifests/myapp",
            json={"name": "My App", "description": "Does stuff", "icon": "rocket"},
        )

        assert resp.status_code == 200
        assert (manifest_dir / "myapp.json").exists()

        import json
        data = json.loads((manifest_dir / "myapp.json").read_text())
        assert data["name"] == "My App"

    def test_get_manifests(self, admin_client, tmp_path):
        """GET /api/admin/manifests lists all installed manifests."""
        client, _ = admin_client
        manifest_dir = tmp_path / "manifests"
        manifest_dir.mkdir()
        config_module.settings.manifest_dir = manifest_dir

        import json
        (manifest_dir / "app1.json").write_text(
            json.dumps({"name": "App 1", "description": "First"})
        )
        (manifest_dir / "app2.json").write_text(
            json.dumps({"name": "App 2", "description": "Second"})
        )

        resp = client.get("/api/admin/manifests")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        slugs = [m["slug"] for m in data]
        assert "app1" in slugs
        assert "app2" in slugs

    def test_delete_manifest(self, admin_client, tmp_path):
        """DELETE /api/admin/manifests/{slug} removes the manifest file."""
        client, _ = admin_client
        manifest_dir = tmp_path / "manifests"
        manifest_dir.mkdir()
        config_module.settings.manifest_dir = manifest_dir

        import json
        (manifest_dir / "myapp.json").write_text(json.dumps({"name": "My App"}))

        resp = client.delete("/api/admin/manifests/myapp")
        assert resp.status_code == 200
        assert not (manifest_dir / "myapp.json").exists()

    def test_invalid_slug_rejected(self, admin_client):
        """PUT /api/admin/manifests with path traversal slug returns 400."""
        client, _ = admin_client

        resp = client.put(
            "/api/admin/manifests/../etc",
            json={"name": "Evil"},
        )
        # FastAPI may return 404 for paths with ..
        # But for slugs like "A B" or "foo_bar" that reach our handler:
        resp2 = client.put(
            "/api/admin/manifests/INVALID",
            json={"name": "Bad"},
        )
        assert resp2.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_admin_routes.py::TestPortAllocation -v && python -m pytest tests/test_admin_routes.py::TestManifestEndpoints -v`
Expected: FAIL — 404 (endpoints don't exist)

- [ ] **Step 3: Add port and manifest endpoints to `admin.py`**

Add import at top of `frontdoor/routes/admin.py`:

```python
import json as json_module
import re as re_module
from pathlib import Path

from frontdoor.discovery import next_available_ports
```

Add slug validation helper and endpoints:

```python
# ---------------------------------------------------------------------------
# Slug validation
# ---------------------------------------------------------------------------

SLUG_RE = re_module.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")


def _validate_slug(slug: str) -> None:
    """Raise HTTP 400 if slug doesn't match the required pattern."""
    if not SLUG_RE.match(slug):
        raise HTTPException(
            status_code=400,
            detail={
                "error": f"Invalid slug: {slug!r}. Must match ^[a-z0-9][a-z0-9-]*[a-z0-9]$",
                "code": "INVALID_SLUG",
            },
        )


# ---------------------------------------------------------------------------
# Port allocation — GET /api/admin/ports/next
# ---------------------------------------------------------------------------

@router.get("/ports/next")
async def get_next_ports(
    start: int = 8440,
    identity: str = Depends(require_admin_auth),
) -> dict:
    """Return the next available internal + external port pair."""
    internal, external = next_available_ports(start=start)
    return {"internal_port": internal, "external_port": external}


# ---------------------------------------------------------------------------
# Manifest models
# ---------------------------------------------------------------------------

class ManifestRequest(BaseModel):
    name: str
    description: str = ""
    icon: str = ""


# ---------------------------------------------------------------------------
# Manifests — GET/PUT/DELETE /api/admin/manifests
# ---------------------------------------------------------------------------

@router.get("/manifests")
async def list_manifests(
    identity: str = Depends(require_admin_auth),
) -> list[dict]:
    """List all installed manifests."""
    manifest_dir = settings.manifest_dir
    if not manifest_dir.exists():
        return []

    manifests = []
    for path in sorted(manifest_dir.glob("*.json")):
        try:
            data = json_module.loads(path.read_text())
            data["slug"] = path.stem
            manifests.append(data)
        except (json_module.JSONDecodeError, OSError):
            continue
    return manifests


@router.put("/manifests/{slug}")
async def set_manifest(
    slug: str,
    body: ManifestRequest,
    identity: str = Depends(require_admin_auth),
) -> dict:
    """Create or update a manifest file."""
    _validate_slug(slug)

    manifest_dir = settings.manifest_dir
    manifest_dir.mkdir(parents=True, exist_ok=True)

    data = {"name": body.name, "description": body.description, "icon": body.icon}
    manifest_path = manifest_dir / f"{slug}.json"
    manifest_path.write_text(json_module.dumps(data, indent=2))

    logger.info("Manifest set: %s by %s", slug, identity)
    return {"slug": slug, "path": str(manifest_path), **data}


@router.delete("/manifests/{slug}")
async def delete_manifest(
    slug: str,
    identity: str = Depends(require_admin_auth),
) -> dict:
    """Remove a manifest file."""
    _validate_slug(slug)

    manifest_path = settings.manifest_dir / f"{slug}.json"
    if not manifest_path.exists():
        raise HTTPException(
            status_code=404,
            detail={"error": f"Manifest not found: {slug}", "code": "NOT_FOUND"},
        )

    manifest_path.unlink()
    logger.info("Manifest deleted: %s by %s", slug, identity)
    return {"status": "deleted", "slug": slug}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_admin_routes.py::TestPortAllocation tests/test_admin_routes.py::TestManifestEndpoints -v`
Expected: All tests pass

- [ ] **Step 5: Run all tests**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
cd /home/robotdad/repos/frontdoor
git add frontdoor/routes/admin.py frontdoor/discovery.py tests/test_admin_routes.py tests/test_discovery_enrichment.py
git commit -m "feat: add port allocation and manifest CRUD endpoints"
```

---

## Task Group 5 — Full App Registration

Template rendering for Caddy and systemd configs, plus the `POST /api/admin/apps` and `DELETE /api/admin/apps/{slug}` endpoints.

### Task 5.1: Template rendering functions

**Files:**
- Create: `frontdoor/app_registration.py`
- Create: `tests/test_app_registration.py`

- [ ] **Step 1: Write failing tests for Caddy config rendering**

Create `tests/test_app_registration.py`:

```python
"""Tests for frontdoor/app_registration.py — template rendering and registration."""

import pytest


class TestRenderCaddyConfig:
    def test_basic_config(self):
        """render_caddy_config produces valid Caddy config for a simple app."""
        from frontdoor.app_registration import render_caddy_config

        result = render_caddy_config(
            slug="myapp",
            fqdn="ambrose.tail09557f.ts.net",
            cert_path="/etc/ssl/tailscale/ambrose.crt",
            key_path="/etc/ssl/tailscale/ambrose.key",
            internal_port=8450,
            external_port=8451,
            websocket_paths=None,
            frontdoor_port=8420,
        )

        assert "ambrose.tail09557f.ts.net:8451" in result
        assert "tls /etc/ssl/tailscale/ambrose.crt /etc/ssl/tailscale/ambrose.key" in result
        assert "forward_auth localhost:8420" in result
        assert "reverse_proxy localhost:8450" in result
        assert "/api/auth/validate" in result

    def test_with_websocket_paths(self):
        """render_caddy_config adds handle blocks for websocket paths."""
        from frontdoor.app_registration import render_caddy_config

        result = render_caddy_config(
            slug="muxplex",
            fqdn="ambrose.tail09557f.ts.net",
            cert_path="/etc/ssl/tailscale/ambrose.crt",
            key_path="/etc/ssl/tailscale/ambrose.key",
            internal_port=8088,
            external_port=8448,
            websocket_paths=["/terminal*", "/ws*"],
            frontdoor_port=8420,
        )

        assert "handle /terminal*" in result
        assert "handle /ws*" in result
        # WebSocket paths bypass forward_auth
        assert result.count("forward_auth") == 1  # only in the main handle block

    def test_without_tls(self):
        """render_caddy_config omits tls line when cert_path is None."""
        from frontdoor.app_registration import render_caddy_config

        result = render_caddy_config(
            slug="myapp",
            fqdn="myhost.local",
            cert_path=None,
            key_path=None,
            internal_port=8450,
            external_port=8451,
            websocket_paths=None,
            frontdoor_port=8420,
        )

        assert "http://myhost.local:8451" in result
        assert "tls" not in result


class TestRenderServiceUnit:
    def test_basic_unit(self):
        """render_service_unit produces a valid systemd unit."""
        from frontdoor.app_registration import render_service_unit

        result = render_service_unit(
            slug="myapp",
            exec_start="/opt/myapp/.venv/bin/uvicorn myapp.main:app",
            service_user="robotdad",
            kill_mode=None,
            description="My Application",
        )

        assert "[Unit]" in result
        assert "Description=My Application" in result
        assert "[Service]" in result
        assert "User=robotdad" in result
        assert "ExecStart=/opt/myapp/.venv/bin/uvicorn myapp.main:app" in result
        assert "[Install]" in result
        assert "KillMode" not in result

    def test_with_kill_mode(self):
        """render_service_unit includes KillMode when specified."""
        from frontdoor.app_registration import render_service_unit

        result = render_service_unit(
            slug="muxplex",
            exec_start="/home/robotdad/.local/bin/muxplex serve",
            service_user="robotdad",
            kill_mode="process",
            description="Muxplex tmux session dashboard",
        )

        assert "KillMode=process" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_app_registration.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'frontdoor.app_registration'`

- [ ] **Step 3: Implement template rendering functions**

Create `frontdoor/app_registration.py`:

```python
"""App registration — Caddy/systemd template rendering and lifecycle management.

Generates configuration files from request parameters and delegates
privileged filesystem writes to ``frontdoor-priv`` via
``service_control.run_privileged()``.
"""

import json
import logging
import subprocess
from pathlib import Path

from frontdoor.config import settings
from frontdoor.service_control import run_privileged

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Environment detection
# ---------------------------------------------------------------------------

def detect_fqdn() -> str:
    """Detect the machine's FQDN.

    Tries ``tailscale status --json`` first, falls back to ``hostname -f``.
    """
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            import json as json_mod
            data = json_mod.loads(result.stdout)
            dns_name = data.get("Self", {}).get("DNSName", "")
            if dns_name:
                return dns_name.rstrip(".")
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["hostname", "-f"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass

    return "localhost"


def detect_cert_paths() -> tuple[str | None, str | None]:
    """Detect TLS certificate paths.

    Checks ``/etc/ssl/tailscale/`` then ``/etc/ssl/self-signed/``.
    Returns ``(cert_path, key_path)`` or ``(None, None)`` if not found.
    """
    fqdn = detect_fqdn()
    for cert_dir in ["/etc/ssl/tailscale", "/etc/ssl/self-signed"]:
        cert = Path(cert_dir) / f"{fqdn}.crt"
        key = Path(cert_dir) / f"{fqdn}.key"
        if cert.exists() and key.exists():
            return str(cert), str(key)
    return None, None


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

def render_caddy_config(
    slug: str,
    fqdn: str,
    cert_path: str | None,
    key_path: str | None,
    internal_port: int,
    external_port: int,
    websocket_paths: list[str] | None,
    frontdoor_port: int = 8420,
) -> str:
    """Render a Caddy vhost config for an app.

    Args:
        slug: App identifier (used in comments only).
        fqdn: Fully qualified domain name.
        cert_path: Path to TLS certificate, or None for HTTP.
        key_path: Path to TLS key, or None for HTTP.
        internal_port: Port the app listens on.
        external_port: Port Caddy exposes externally.
        websocket_paths: List of paths that bypass forward_auth (e.g. ["/ws*"]).
        frontdoor_port: frontdoor's port for forward_auth.
    """
    if cert_path and key_path:
        addr = f"{fqdn}:{external_port}"
        tls_line = f"    tls {cert_path} {key_path}\n"
    else:
        addr = f"http://{fqdn}:{external_port}"
        tls_line = ""

    lines = [f"{addr} {{"]
    if tls_line:
        lines.append(tls_line.rstrip())
    lines.append("")

    # WebSocket bypass handles (before the main handle)
    if websocket_paths:
        for ws_path in websocket_paths:
            lines.append(f"    handle {ws_path} {{")
            lines.append(f"        reverse_proxy localhost:{internal_port} {{")
            lines.append("            header_up -X-Forwarded-For")
            lines.append("        }")
            lines.append("    }")
            lines.append("")

    # Main handle block with forward_auth
    if websocket_paths:
        lines.append("    handle {")
        lines.append(f"        forward_auth localhost:{frontdoor_port} {{")
        lines.append("            uri /api/auth/validate")
        lines.append("            copy_headers X-Authenticated-User")
        lines.append("        }")
        lines.append(f"        reverse_proxy localhost:{internal_port} {{")
        lines.append("            header_up -X-Forwarded-For")
        lines.append("        }")
        lines.append("    }")
    else:
        lines.append(f"    forward_auth localhost:{frontdoor_port} {{")
        lines.append("        uri /api/auth/validate")
        lines.append("        copy_headers X-Authenticated-User")
        lines.append("    }")
        lines.append("")
        lines.append(f"    reverse_proxy localhost:{internal_port}")

    lines.append("}")
    return "\n".join(lines) + "\n"


def render_service_unit(
    slug: str,
    exec_start: str,
    service_user: str,
    kill_mode: str | None,
    description: str,
) -> str:
    """Render a systemd service unit file.

    Args:
        slug: Used for the unit filename (not embedded in content).
        exec_start: The ExecStart command.
        service_user: The User= directive value.
        kill_mode: If set (e.g. "process"), adds KillMode= directive.
        description: Human-readable description.
    """
    lines = [
        "[Unit]",
        f"Description={description}",
        "After=network.target",
        "",
        "[Service]",
        "Type=simple",
        f"User={service_user}",
        f"Environment=HOME=/home/{service_user}",
        f"ExecStart={exec_start}",
        "Restart=on-failure",
        "RestartSec=5",
    ]
    if kill_mode:
        lines.append(f"KillMode={kill_mode}")
    lines.extend([
        "",
        "[Install]",
        "WantedBy=multi-user.target",
    ])
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Registration lifecycle
# ---------------------------------------------------------------------------

def register_app(
    slug: str,
    name: str,
    description: str,
    icon: str,
    internal_port: int,
    external_port: int,
    exec_start: str,
    service_user: str,
    kill_mode: str | None = None,
    websocket_paths: list[str] | None = None,
) -> dict:
    """Register a new app: write Caddy config, systemd unit, and manifest.

    Args:
        slug: App identifier.
        name: Human-readable name.
        description: One-line description.
        icon: Emoji or Phosphor icon keyword.
        internal_port: Port the app binds to.
        external_port: Port Caddy exposes.
        exec_start: systemd ExecStart command.
        service_user: systemd User= value.
        kill_mode: Optional KillMode= value.
        websocket_paths: Optional WebSocket paths to bypass auth.

    Returns:
        Registration result dict with file paths and service status.

    Raises:
        RuntimeError: If any privileged operation fails.
    """
    fqdn = detect_fqdn()
    cert_path, key_path = detect_cert_paths()

    # Render templates
    caddy_content = render_caddy_config(
        slug=slug,
        fqdn=fqdn,
        cert_path=cert_path,
        key_path=key_path,
        internal_port=internal_port,
        external_port=external_port,
        websocket_paths=websocket_paths,
        frontdoor_port=settings.port,
    )
    service_content = render_service_unit(
        slug=slug,
        exec_start=exec_start,
        service_user=service_user,
        kill_mode=kill_mode,
        description=description or name,
    )

    # Write Caddy config
    run_privileged("write-caddy", slug=slug, content=caddy_content)
    # Write systemd unit
    run_privileged("write-service", slug=slug, content=service_content)
    # Reload Caddy to pick up the new config
    run_privileged("caddy-reload")
    # Enable and start the service
    run_privileged("systemctl", action="daemon-reload")
    run_privileged("systemctl", action="enable", unit=f"{slug}.service")
    run_privileged("systemctl", action="start", unit=f"{slug}.service")

    # Write manifest (frontdoor owns this directory — no privilege needed)
    manifest_dir = settings.manifest_dir
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_data = {"name": name, "description": description, "icon": icon}
    (manifest_dir / f"{slug}.json").write_text(json.dumps(manifest_data, indent=2))

    logger.info("Registered app: %s (ports %d/%d)", slug, internal_port, external_port)

    return {
        "slug": slug,
        "caddy_config": f"/etc/caddy/conf.d/{slug}.caddy",
        "service_unit": f"/etc/systemd/system/{slug}.service",
        "manifest": str(manifest_dir / f"{slug}.json"),
        "internal_port": internal_port,
        "external_port": external_port,
        "service_status": "active",
    }


def unregister_app(slug: str) -> None:
    """Unregister an app: stop service, remove configs.

    Does NOT remove the app's own installation directory.
    """
    unit = f"{slug}.service"

    # Stop and disable the service (ignore errors if already stopped)
    try:
        run_privileged("systemctl", action="stop", unit=unit)
    except RuntimeError:
        pass
    try:
        run_privileged("systemctl", action="disable", unit=unit)
    except RuntimeError:
        pass

    # Remove files
    run_privileged("delete-service", slug=slug)
    run_privileged("delete-caddy", slug=slug)
    run_privileged("systemctl", action="daemon-reload")
    run_privileged("caddy-reload")

    # Remove manifest
    manifest_path = settings.manifest_dir / f"{slug}.json"
    if manifest_path.exists():
        manifest_path.unlink()

    logger.info("Unregistered app: %s", slug)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_app_registration.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
cd /home/robotdad/repos/frontdoor
git add frontdoor/app_registration.py tests/test_app_registration.py
git commit -m "feat: add app registration module with template rendering"
```

### Task 5.2: Registration tests for `register_app` and `unregister_app`

**Files:**
- Modify: `tests/test_app_registration.py`

- [ ] **Step 1: Write tests for register_app with mocked privileged calls**

Add to `tests/test_app_registration.py`:

```python
from unittest.mock import patch, call, MagicMock


class TestRegisterApp:
    def test_register_calls_privileged_operations(self, tmp_path):
        """register_app calls run_privileged for caddy, service, and systemctl."""
        from frontdoor.app_registration import register_app
        import frontdoor.config as config_module

        orig_manifest_dir = config_module.settings.manifest_dir
        config_module.settings.manifest_dir = tmp_path / "manifests"

        with (
            patch("frontdoor.app_registration.detect_fqdn", return_value="ambrose.ts.net"),
            patch(
                "frontdoor.app_registration.detect_cert_paths",
                return_value=("/etc/ssl/ts/ambrose.crt", "/etc/ssl/ts/ambrose.key"),
            ),
            patch("frontdoor.app_registration.run_privileged") as mock_priv,
        ):
            result = register_app(
                slug="myapp",
                name="My App",
                description="Test app",
                icon="rocket",
                internal_port=8450,
                external_port=8451,
                exec_start="/opt/myapp/run",
                service_user="robotdad",
            )

        config_module.settings.manifest_dir = orig_manifest_dir

        assert result["slug"] == "myapp"
        assert result["internal_port"] == 8450

        # Verify privileged operations were called
        call_ops = [c.args[0] for c in mock_priv.call_args_list]
        assert "write-caddy" in call_ops
        assert "write-service" in call_ops
        assert "caddy-reload" in call_ops
        assert "systemctl" in call_ops

    def test_register_writes_manifest(self, tmp_path):
        """register_app writes a manifest file to the manifest directory."""
        from frontdoor.app_registration import register_app
        import frontdoor.config as config_module
        import json

        manifest_dir = tmp_path / "manifests"
        orig_manifest_dir = config_module.settings.manifest_dir
        config_module.settings.manifest_dir = manifest_dir

        with (
            patch("frontdoor.app_registration.detect_fqdn", return_value="test.local"),
            patch("frontdoor.app_registration.detect_cert_paths", return_value=(None, None)),
            patch("frontdoor.app_registration.run_privileged"),
        ):
            register_app(
                slug="testapp",
                name="Test App",
                description="Testing",
                icon="flask",
                internal_port=9000,
                external_port=9001,
                exec_start="/usr/bin/testapp",
                service_user="testuser",
            )

        config_module.settings.manifest_dir = orig_manifest_dir

        manifest_path = manifest_dir / "testapp.json"
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())
        assert data["name"] == "Test App"


class TestUnregisterApp:
    def test_unregister_calls_stop_disable_delete(self, tmp_path):
        """unregister_app stops, disables, and removes all config files."""
        from frontdoor.app_registration import unregister_app
        import frontdoor.config as config_module

        manifest_dir = tmp_path / "manifests"
        manifest_dir.mkdir()
        (manifest_dir / "myapp.json").write_text('{"name": "My App"}')

        orig_manifest_dir = config_module.settings.manifest_dir
        config_module.settings.manifest_dir = manifest_dir

        with patch("frontdoor.app_registration.run_privileged") as mock_priv:
            unregister_app("myapp")

        config_module.settings.manifest_dir = orig_manifest_dir

        call_ops = [c.args[0] for c in mock_priv.call_args_list]
        assert "delete-caddy" in call_ops
        assert "delete-service" in call_ops
        assert not (manifest_dir / "myapp.json").exists()
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_app_registration.py -v`
Expected: All tests pass (7 total: 3 render + 2 register + 2 unregister)

- [ ] **Step 3: Commit**

```bash
cd /home/robotdad/repos/frontdoor
git add tests/test_app_registration.py
git commit -m "test: add register_app and unregister_app tests"
```

### Task 5.3: App registration admin endpoints

**Files:**
- Modify: `frontdoor/routes/admin.py`
- Modify: `tests/test_admin_routes.py`

- [ ] **Step 1: Write failing test for app registration endpoint**

Add to `tests/test_admin_routes.py`:

```python
class TestAppRegistration:
    def test_register_app(self, admin_client, tmp_path):
        """POST /api/admin/apps registers a new app."""
        client, _ = admin_client
        manifest_dir = tmp_path / "manifests"
        manifest_dir.mkdir()
        config_module.settings.manifest_dir = manifest_dir

        with (
            patch("frontdoor.app_registration.detect_fqdn", return_value="test.local"),
            patch("frontdoor.app_registration.detect_cert_paths", return_value=(None, None)),
            patch("frontdoor.app_registration.run_privileged"),
        ):
            resp = client.post("/api/admin/apps", json={
                "slug": "myapp",
                "name": "My App",
                "description": "A test app",
                "icon": "rocket",
                "internal_port": 8450,
                "external_port": 8451,
                "exec_start": "/opt/myapp/run",
                "service_user": "robotdad",
            })

        assert resp.status_code == 201
        data = resp.json()
        assert data["slug"] == "myapp"
        assert data["internal_port"] == 8450

    def test_unregister_app(self, admin_client, tmp_path):
        """DELETE /api/admin/apps/{slug} unregisters an app."""
        client, _ = admin_client
        manifest_dir = tmp_path / "manifests"
        manifest_dir.mkdir()
        (manifest_dir / "myapp.json").write_text('{"name": "My App"}')
        config_module.settings.manifest_dir = manifest_dir

        with patch("frontdoor.app_registration.run_privileged"):
            resp = client.delete("/api/admin/apps/myapp")

        assert resp.status_code == 200
        assert not (manifest_dir / "myapp.json").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_admin_routes.py::TestAppRegistration -v`
Expected: FAIL — 404 (endpoints don't exist)

- [ ] **Step 3: Add app registration endpoints to `admin.py`**

Add import to top of `frontdoor/routes/admin.py`:

```python
from frontdoor.app_registration import register_app, unregister_app
```

Add Pydantic model and endpoints:

```python
# ---------------------------------------------------------------------------
# App registration models
# ---------------------------------------------------------------------------

class AppRegistrationRequest(BaseModel):
    slug: str
    name: str = ""
    description: str = ""
    icon: str = ""
    internal_port: int
    external_port: int
    exec_start: str
    service_user: str = ""
    kill_mode: str | None = None
    websocket_paths: list[str] | None = None


# ---------------------------------------------------------------------------
# App registration — POST/DELETE /api/admin/apps
# ---------------------------------------------------------------------------

@router.post("/apps", status_code=201)
async def register_new_app(
    body: AppRegistrationRequest,
    identity: str = Depends(require_admin_auth),
) -> dict:
    """Register a new app (Caddy config + systemd unit + manifest)."""
    _validate_slug(body.slug)

    # Check for conflict
    manifest_path = settings.manifest_dir / f"{body.slug}.json"
    if manifest_path.exists():
        raise HTTPException(
            status_code=409,
            detail={
                "error": f"App {body.slug!r} already registered. Unregister first.",
                "code": "CONFLICT",
            },
        )

    service_user = body.service_user or settings.service_user
    if not service_user:
        import os
        try:
            service_user = os.getlogin()
        except OSError:
            service_user = "root"

    name = body.name or body.slug.replace("-", " ").title()

    try:
        result = register_app(
            slug=body.slug,
            name=name,
            description=body.description,
            icon=body.icon,
            internal_port=body.internal_port,
            external_port=body.external_port,
            exec_start=body.exec_start,
            service_user=service_user,
            kill_mode=body.kill_mode,
            websocket_paths=body.websocket_paths,
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=500,
            detail={"error": str(e), "code": "REGISTRATION_FAILED"},
        )

    logger.info("App registered: %s by %s", body.slug, identity)
    return result


@router.delete("/apps/{slug}")
async def unregister_existing_app(
    slug: str,
    identity: str = Depends(require_admin_auth),
) -> dict:
    """Unregister an app (remove Caddy config, systemd unit, and manifest)."""
    _validate_slug(slug)

    try:
        unregister_app(slug)
    except RuntimeError as e:
        raise HTTPException(
            status_code=500,
            detail={"error": str(e), "code": "UNREGISTRATION_FAILED"},
        )

    logger.info("App unregistered: %s by %s", slug, identity)
    return {"status": "unregistered", "slug": slug}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_admin_routes.py::TestAppRegistration -v`
Expected: 2 passed

- [ ] **Step 5: Run all tests**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
cd /home/robotdad/repos/frontdoor
git add frontdoor/routes/admin.py tests/test_admin_routes.py
git commit -m "feat: add app registration endpoints (POST/DELETE /api/admin/apps)"
```

---

## Task Group 6 — Known-App Install

Template substitution for the existing `known-apps/` directory.

### Task 6.1: `install_known_app` function and endpoint

**Files:**
- Modify: `frontdoor/app_registration.py`
- Modify: `frontdoor/routes/admin.py`
- Modify: `tests/test_app_registration.py`
- Modify: `tests/test_admin_routes.py`

- [ ] **Step 1: Write failing tests for known-app installation**

Add to `tests/test_app_registration.py`:

```python
class TestInstallKnownApp:
    def test_reads_and_substitutes_templates(self, tmp_path):
        """install_known_app reads .caddy, .service, .json and substitutes variables."""
        from frontdoor.app_registration import install_known_app
        import frontdoor.config as config_module

        # Create a fake known-apps directory
        known_dir = tmp_path / "known-apps" / "testapp"
        known_dir.mkdir(parents=True)
        (known_dir / "testapp.caddy").write_text(
            "FQDN:8555 {\n    reverse_proxy localhost:8556\n}\n"
        )
        (known_dir / "testapp.service").write_text(
            "[Service]\nUser=SERVICE_USER\nExecStart=/usr/bin/testapp\n"
        )
        (known_dir / "testapp.json").write_text(
            '{"name": "Test App", "description": "A test"}\n'
        )

        manifest_dir = tmp_path / "manifests"
        orig_manifest_dir = config_module.settings.manifest_dir
        config_module.settings.manifest_dir = manifest_dir

        with (
            patch("frontdoor.app_registration.detect_fqdn", return_value="ambrose.ts.net"),
            patch(
                "frontdoor.app_registration.detect_cert_paths",
                return_value=("/etc/ssl/ts/ambrose.crt", "/etc/ssl/ts/ambrose.key"),
            ),
            patch("frontdoor.app_registration.run_privileged") as mock_priv,
            patch(
                "frontdoor.app_registration._known_apps_dir",
                return_value=tmp_path / "known-apps",
            ),
        ):
            result = install_known_app("testapp", service_user="robotdad")

        config_module.settings.manifest_dir = orig_manifest_dir

        # Verify template substitution happened in the caddy write
        caddy_call = next(
            c for c in mock_priv.call_args_list
            if c.args[0] == "write-caddy"
        )
        caddy_content = caddy_call.kwargs.get("content", "")
        assert "ambrose.ts.net" in caddy_content
        assert "FQDN" not in caddy_content

        # Verify service file substitution
        svc_call = next(
            c for c in mock_priv.call_args_list
            if c.args[0] == "write-service"
        )
        svc_content = svc_call.kwargs.get("content", "")
        assert "robotdad" in svc_content
        assert "SERVICE_USER" not in svc_content

    def test_unknown_app_raises(self, tmp_path):
        """install_known_app raises FileNotFoundError for unknown app names."""
        from frontdoor.app_registration import install_known_app

        with (
            patch(
                "frontdoor.app_registration._known_apps_dir",
                return_value=tmp_path / "known-apps",
            ),
            pytest.raises(FileNotFoundError),
        ):
            install_known_app("nonexistent", service_user="robotdad")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_app_registration.py::TestInstallKnownApp -v`
Expected: FAIL — `ImportError: cannot import name 'install_known_app'`

- [ ] **Step 3: Implement `install_known_app` and `list_known_apps`**

Add to `frontdoor/app_registration.py`:

```python
def _known_apps_dir() -> Path:
    """Return the path to the known-apps directory."""
    return Path(__file__).parent.parent / "known-apps"


def list_known_apps() -> list[dict]:
    """List available known-app configurations.

    Returns a list of dicts with name, description, and files for each
    known app found in the ``known-apps/`` directory.
    """
    base = _known_apps_dir()
    if not base.exists():
        return []

    apps = []
    for app_dir in sorted(base.iterdir()):
        if not app_dir.is_dir():
            continue
        files = [f.name for f in sorted(app_dir.iterdir()) if f.is_file()]
        # Try to read description from the JSON manifest
        description = ""
        json_file = app_dir / f"{app_dir.name}.json"
        if json_file.exists():
            try:
                data = json.loads(json_file.read_text())
                description = data.get("description", "")
            except (json.JSONDecodeError, OSError):
                pass

        readme_file = app_dir / "README.md"
        apps.append({
            "name": app_dir.name,
            "description": description,
            "files": files,
            "readme_url": f"/known-apps/{app_dir.name}/README.md" if readme_file.exists() else None,
        })
    return apps


def install_known_app(appname: str, service_user: str) -> dict:
    """Install a known-app configuration.

    Reads ``.caddy``, ``.service``, and ``.json`` templates from the
    known-apps directory, substitutes template variables, and writes them
    via ``run_privileged``.

    Template variables (plain identifiers, no braces):
    - ``SERVICE_USER`` → service_user argument
    - ``FQDN`` → detected from Tailscale / hostname
    - ``CERT_PATH`` → detected certificate path
    - ``KEY_PATH`` → detected key path
    - ``FRONTDOOR_PORT`` → settings.port

    Args:
        appname: Name of the known app (directory name under known-apps/).
        service_user: OS user to run the service as.

    Returns:
        Registration result dict.

    Raises:
        FileNotFoundError: If the known-app directory doesn't exist.
    """
    base = _known_apps_dir()
    app_dir = base / appname
    if not app_dir.is_dir():
        raise FileNotFoundError(f"Known app not found: {appname}")

    fqdn = detect_fqdn()
    cert_path, key_path = detect_cert_paths()

    # Build substitution map
    subs = {
        "SERVICE_USER": service_user,
        "FQDN": fqdn,
        "CERT_PATH": cert_path or "",
        "KEY_PATH": key_path or "",
        "FRONTDOOR_PORT": str(settings.port),
    }
    # Also handle app-specific variable patterns like MUXPLEX_FQDN
    subs[f"{appname.upper()}_FQDN"] = fqdn
    subs[f"{appname.upper()}_PORT"] = ""  # Will be filled if port info is in the template

    def _substitute(content: str) -> str:
        result = content
        for key, value in subs.items():
            result = result.replace(key, value)
        return result

    # Read and substitute templates
    caddy_file = app_dir / f"{appname}.caddy"
    service_file = app_dir / f"{appname}.service"
    json_file = app_dir / f"{appname}.json"

    if caddy_file.exists():
        caddy_content = _substitute(caddy_file.read_text())
        run_privileged("write-caddy", slug=appname, content=caddy_content)

    if service_file.exists():
        service_content = _substitute(service_file.read_text())
        run_privileged("write-service", slug=appname, content=service_content)

    # Manifest — written directly (no privilege needed)
    if json_file.exists():
        manifest_data = json_file.read_text()
        manifest_dir = settings.manifest_dir
        manifest_dir.mkdir(parents=True, exist_ok=True)
        (manifest_dir / f"{appname}.json").write_text(manifest_data)

    # Reload Caddy and enable/start the service
    run_privileged("caddy-reload")
    run_privileged("systemctl", action="daemon-reload")
    run_privileged("systemctl", action="enable", unit=f"{appname}.service")
    run_privileged("systemctl", action="start", unit=f"{appname}.service")

    logger.info("Installed known app: %s (user=%s)", appname, service_user)

    return {
        "slug": appname,
        "caddy_config": f"/etc/caddy/conf.d/{appname}.caddy",
        "service_unit": f"/etc/systemd/system/{appname}.service",
        "manifest": str(settings.manifest_dir / f"{appname}.json"),
        "service_status": "active",
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_app_registration.py::TestInstallKnownApp -v`
Expected: 2 passed

- [ ] **Step 5: Add known-app endpoints to admin router**

Add import to `frontdoor/routes/admin.py`:

```python
from frontdoor.app_registration import (
    install_known_app,
    list_known_apps,
    register_app,
    unregister_app,
)
```

Add Pydantic model and endpoints:

```python
# ---------------------------------------------------------------------------
# Known-app models
# ---------------------------------------------------------------------------

class KnownAppInstallRequest(BaseModel):
    service_user: str = ""


# ---------------------------------------------------------------------------
# Known apps — GET/POST /api/admin/known-apps
# ---------------------------------------------------------------------------

@router.get("/known-apps")
async def get_known_apps(
    identity: str = Depends(require_admin_auth),
) -> list[dict]:
    """List available known-app configurations."""
    return list_known_apps()


@router.post("/known-apps/{appname}/install", status_code=201)
async def install_known_app_endpoint(
    appname: str,
    body: KnownAppInstallRequest,
    identity: str = Depends(require_admin_auth),
) -> dict:
    """Install a known-app configuration."""
    service_user = body.service_user or settings.service_user
    if not service_user:
        import os
        try:
            service_user = os.getlogin()
        except OSError:
            service_user = "root"

    try:
        result = install_known_app(appname, service_user=service_user)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={
                "error": f"Known app not found: {appname}",
                "code": "NOT_FOUND",
            },
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=500,
            detail={"error": str(e), "code": "INSTALL_FAILED"},
        )

    logger.info("Known app installed: %s by %s", appname, identity)
    return result
```

- [ ] **Step 6: Write test for known-apps endpoint**

Add to `tests/test_admin_routes.py`:

```python
class TestKnownApps:
    def test_list_known_apps(self, admin_client):
        """GET /api/admin/known-apps returns available known-app configs."""
        client, _ = admin_client

        with patch("frontdoor.routes.admin.list_known_apps", return_value=[
            {"name": "muxplex", "description": "Tmux dashboard", "files": ["muxplex.caddy"], "readme_url": None}
        ]):
            resp = client.get("/api/admin/known-apps")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "muxplex"

    def test_install_known_app(self, admin_client):
        """POST /api/admin/known-apps/{appname}/install installs the app."""
        client, _ = admin_client

        with patch("frontdoor.routes.admin.install_known_app", return_value={
            "slug": "muxplex",
            "caddy_config": "/etc/caddy/conf.d/muxplex.caddy",
            "service_unit": "/etc/systemd/system/muxplex.service",
            "manifest": "/opt/frontdoor/manifests/muxplex.json",
            "service_status": "active",
        }):
            resp = client.post(
                "/api/admin/known-apps/muxplex/install",
                json={"service_user": "robotdad"},
            )

        assert resp.status_code == 201
        assert resp.json()["slug"] == "muxplex"

    def test_install_unknown_app_returns_404(self, admin_client):
        """POST /api/admin/known-apps/{bad}/install returns 404."""
        client, _ = admin_client

        with patch(
            "frontdoor.routes.admin.install_known_app",
            side_effect=FileNotFoundError("nope"),
        ):
            resp = client.post(
                "/api/admin/known-apps/nonexistent/install",
                json={"service_user": "robotdad"},
            )

        assert resp.status_code == 404
```

- [ ] **Step 7: Run all tests**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 8: Commit**

```bash
cd /home/robotdad/repos/frontdoor
git add frontdoor/app_registration.py frontdoor/routes/admin.py tests/test_app_registration.py tests/test_admin_routes.py
git commit -m "feat: add known-app install endpoint and template substitution"
```

---

## Task Group 7 — `frontdoor-admin` CLI

Click-based CLI wrapping all API endpoints, with two-tier help system.

### Task 7.1: CLI framework and box config

**Files:**
- Create: `frontdoor/cli.py`
- Create: `tests/test_cli.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add `click` dependency and entry point to `pyproject.toml`**

Edit `pyproject.toml`:

Add `"click"` to the `dependencies` list:

```toml
dependencies = [
    "fastapi",
    "uvicorn[standard]",
    "python-pam",
    "six",
    "python-multipart",
    "itsdangerous",
    "click",
]
```

Add the scripts section:

```toml
[project.scripts]
frontdoor-admin = "frontdoor.cli:main"
```

- [ ] **Step 2: Write failing tests for CLI basics**

Create `tests/test_cli.py`:

```python
"""Tests for frontdoor-admin CLI."""

import json

from click.testing import CliRunner

from frontdoor.cli import main


class TestCLIBasics:
    def test_top_level_help(self):
        """--help shows rich skill-format help text."""
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "WHAT THIS TOOL DOES" in result.output
        assert "frontdoor-admin" in result.output

    def test_short_help(self):
        """-h shows condensed traditional help."""
        runner = CliRunner()
        result = runner.invoke(main, ["-h"])
        assert result.exit_code == 0
        # Short help should be shorter than full help
        full_result = runner.invoke(main, ["--help"])
        assert len(result.output) < len(full_result.output)

    def test_unknown_command(self):
        """Unknown command shows error."""
        runner = CliRunner()
        result = runner.invoke(main, ["nonexistent"])
        assert result.exit_code != 0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'frontdoor.cli'` or `ImportError`

- [ ] **Step 4: Implement CLI framework**

Create `frontdoor/cli.py`:

```python
"""frontdoor-admin CLI — management interface for frontdoor.

Wraps the frontdoor Management API for local and remote use. Designed
for both human operators and AI agents — use --help for rich skill-format
help, -h for traditional short help.
"""

import json
import os
import sys
from pathlib import Path

import click
import httpx


# ---------------------------------------------------------------------------
# Rich help text system
# ---------------------------------------------------------------------------

RICH_HELP_TOP = """\
WHAT THIS TOOL DOES
  Manages frontdoor-integrated services on one or more hosts via the frontdoor
  Management API. Handles app registration, service control, port allocation,
  manifest management, and API token administration.

WHEN TO USE THIS TOOL
  Use frontdoor-admin when you need to:
  - Register a new web app with frontdoor (Caddy vhost + systemd unit + manifest)
  - Install a pre-built known-app config (muxplex, filebrowser, etc.)
  - Allocate free ports before starting a new app provisioning workflow
  - Restart services or perform fleet-wide restarts
  - Manage API tokens for remote access across Tailscale fleet

WORKFLOW
  Typical app registration:
    1. frontdoor-admin ports next          # find free ports
    2. frontdoor-admin app register ...    # register the app
    3. frontdoor-admin services list       # verify it's running

  For pre-built apps:
    1. frontdoor-admin known-apps list     # check what's available
    2. frontdoor-admin known-apps install APPNAME --service-user USER

  Remote management:
    1. frontdoor-admin token create --name "my-laptop"  # on the target box
    2. frontdoor-admin box add mybox --url https://mybox.ts.net --token ft_...
    3. frontdoor-admin --box mybox services list

COMMANDS
  ports         Port allocation
  manifest      Manifest management (list, set, delete)
  services      Service control (list, restart, restart-all)
  app           App registration (register, unregister)
  known-apps    Pre-built app configs (list, install)
  token         API token management (create, list, revoke)
  box           Fleet box aliases (add, list, remove)

SEE ALSO
  frontdoor-admin <command> --help    Rich help for any subcommand
  frontdoor-admin <command> -h        Short help for any subcommand
"""

SHORT_HELP_TOP = """\
frontdoor-admin — frontdoor management CLI

Commands: ports, manifest, services, app, known-apps, token, box
Options:  --box NAME, --url URL, --token TOKEN

Use --help for detailed agent-readable help.
"""


# ---------------------------------------------------------------------------
# Box config loading
# ---------------------------------------------------------------------------

def _load_box_config() -> dict:
    """Load ~/.config/frontdoor/cli.toml if it exists."""
    config_path = Path.home() / ".config" / "frontdoor" / "cli.toml"
    if not config_path.exists():
        return {}
    try:
        import tomllib
        return tomllib.loads(config_path.read_text())
    except ImportError:
        # Python < 3.11 fallback
        return {}
    except Exception:
        return {}


def _resolve_target(ctx: click.Context) -> tuple[str, str | None]:
    """Resolve the target URL and token from CLI flags, env, or config.

    Resolution order:
    1. --box flag → config lookup
    2. --url + --token flags
    3. FRONTDOOR_BOX / FRONTDOOR_URL / FRONTDOOR_TOKEN env vars
    4. Config file defaults
    5. http://localhost:8420 (hardcoded fallback)
    """
    params = ctx.obj or {}
    box_name = params.get("box")
    url = params.get("url")
    token = params.get("token")

    config = _load_box_config()

    if box_name:
        boxes = config.get("boxes", {})
        if box_name in boxes:
            box = boxes[box_name]
            return box.get("url", "http://localhost:8420"), box.get("token")
        click.echo(f"Error: box '{box_name}' not found in config", err=True)
        sys.exit(1)

    if url:
        return url, token

    env_box = os.environ.get("FRONTDOOR_BOX")
    if env_box:
        boxes = config.get("boxes", {})
        if env_box in boxes:
            box = boxes[env_box]
            return box.get("url", "http://localhost:8420"), box.get("token")

    env_url = os.environ.get("FRONTDOOR_URL")
    if env_url:
        return env_url, os.environ.get("FRONTDOOR_TOKEN")

    defaults = config.get("defaults", {})
    default_box = defaults.get("box")
    if default_box:
        boxes = config.get("boxes", {})
        if default_box in boxes:
            box = boxes[default_box]
            return box.get("url", "http://localhost:8420"), box.get("token")

    return "http://localhost:8420", None


def _api_request(
    ctx: click.Context,
    method: str,
    path: str,
    json_body: dict | None = None,
    params: dict | None = None,
) -> dict | list:
    """Make an API request to the target frontdoor instance."""
    url, token = _resolve_target(ctx)
    full_url = f"{url.rstrip('/')}/api/admin{path}"

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = httpx.request(
            method,
            full_url,
            json=json_body,
            params=params,
            headers=headers,
            timeout=30,
        )
    except httpx.ConnectError:
        click.echo(f"Error: could not connect to {url}", err=True)
        sys.exit(1)

    if resp.status_code >= 400:
        try:
            error = resp.json()
            click.echo(f"Error ({resp.status_code}): {error.get('detail', {}).get('error', resp.text)}", err=True)
        except Exception:
            click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    return resp.json()


# ---------------------------------------------------------------------------
# Short help callback
# ---------------------------------------------------------------------------

def _short_help_callback(ctx: click.Context, param: click.Parameter, value: bool) -> None:
    if not value:
        return
    # Print condensed help
    if ctx.parent is None:
        click.echo(SHORT_HELP_TOP)
    else:
        cmd = ctx.command
        click.echo(f"{cmd.name} — {cmd.help or ''}")
        click.echo()
        if hasattr(cmd, "params"):
            for p in cmd.params:
                if isinstance(p, click.Option) and p.name != "short_help":
                    click.echo(f"  {', '.join(p.opts):30s} {p.help or ''}")
            for p in cmd.params:
                if isinstance(p, click.Argument):
                    click.echo(f"  {p.name:30s} {p.help or ''}")
    ctx.exit()


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

class RichHelpGroup(click.Group):
    """Click group with custom --help that shows rich skill-format text."""

    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        formatter.write(RICH_HELP_TOP)


@click.group(cls=RichHelpGroup, context_settings=dict(help_option_names=["--help"]))
@click.option("--box", default=None, help="Named box alias from config")
@click.option("--url", default=None, help="Direct URL to frontdoor instance")
@click.option("--token", default=None, help="API token for remote auth")
@click.option("-h", "short_help", is_flag=True, callback=_short_help_callback,
              expose_value=False, is_eager=True, help="Short help")
@click.pass_context
def main(ctx: click.Context, box: str | None, url: str | None, token: str | None) -> None:
    """frontdoor-admin — frontdoor management CLI"""
    ctx.ensure_object(dict)
    ctx.obj["box"] = box
    ctx.obj["url"] = url
    ctx.obj["token"] = token


# ---------------------------------------------------------------------------
# ports
# ---------------------------------------------------------------------------

@main.group()
def ports() -> None:
    """Port allocation commands."""
    pass


@ports.command("next")
@click.option("--start", default=8440, type=int, help="Start scanning from this port")
@click.option("--show-used", is_flag=True, help="Also show all ports frontdoor considers taken")
@click.pass_context
def ports_next(ctx: click.Context, start: int, show_used: bool) -> None:
    """Get the next available internal + external port pair."""
    params = {"start": start}
    if show_used:
        params["show_used"] = "true"
    result = _api_request(ctx, "GET", "/ports/next", params=params)
    click.echo(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------

@main.group()
def manifest() -> None:
    """Manifest management commands."""
    pass


@manifest.command("list")
@click.pass_context
def manifest_list(ctx: click.Context) -> None:
    """List all installed manifests."""
    result = _api_request(ctx, "GET", "/manifests")
    click.echo(json.dumps(result, indent=2))


@manifest.command("set")
@click.argument("slug")
@click.option("--name", required=True, help="Human-readable name")
@click.option("--desc", "--description", default="", help="One-line description")
@click.option("--icon", default="", help="Emoji or Phosphor icon keyword")
@click.pass_context
def manifest_set(ctx: click.Context, slug: str, name: str, desc: str, icon: str) -> None:
    """Create or update a manifest."""
    result = _api_request(
        ctx, "PUT", f"/manifests/{slug}",
        json_body={"name": name, "description": desc, "icon": icon},
    )
    click.echo(json.dumps(result, indent=2))


@manifest.command("delete")
@click.argument("slug")
@click.pass_context
def manifest_delete(ctx: click.Context, slug: str) -> None:
    """Remove a manifest."""
    result = _api_request(ctx, "DELETE", f"/manifests/{slug}")
    click.echo(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# services
# ---------------------------------------------------------------------------

@main.group()
def services() -> None:
    """Service control commands."""
    pass


@services.command("list")
@click.pass_context
def services_list(ctx: click.Context) -> None:
    """List all services with systemd unit information."""
    url, token = _resolve_target(ctx)
    full_url = f"{url.rstrip('/')}/api/services"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = httpx.get(full_url, headers=headers, timeout=30)
        result = resp.json()
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    click.echo(json.dumps(result, indent=2))


@services.command("restart")
@click.argument("slug")
@click.pass_context
def services_restart(ctx: click.Context, slug: str) -> None:
    """Restart a single service by slug."""
    result = _api_request(ctx, "POST", f"/services/{slug}/restart")
    click.echo(json.dumps(result, indent=2))


@services.command("restart-all")
@click.pass_context
def services_restart_all(ctx: click.Context) -> None:
    """Restart all services (excludes frontdoor itself)."""
    result = _api_request(ctx, "POST", "/services/restart-all")
    click.echo(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# app
# ---------------------------------------------------------------------------

@main.group()
def app() -> None:
    """App registration commands."""
    pass


@app.command("register")
@click.argument("slug")
@click.option("--name", default="", help="Human-readable name (defaults to slug title-cased)")
@click.option("--description", default="", help="One-line description")
@click.option("--icon", default="", help="Emoji or Phosphor icon keyword")
@click.option("--internal-port", required=True, type=int, help="Port the app binds to")
@click.option("--external-port", required=True, type=int, help="Port Caddy exposes")
@click.option("--exec-start", required=True, help="systemd ExecStart command")
@click.option("--service-user", default="", help="OS user to run the service as")
@click.option("--kill-mode", default=None, help="systemd KillMode (e.g. 'process')")
@click.option("--ws-path", multiple=True, help="WebSocket paths to bypass auth (repeatable)")
@click.pass_context
def app_register(
    ctx: click.Context,
    slug: str,
    name: str,
    description: str,
    icon: str,
    internal_port: int,
    external_port: int,
    exec_start: str,
    service_user: str,
    kill_mode: str | None,
    ws_path: tuple[str, ...],
) -> None:
    """Register a new app (Caddy config + systemd unit + manifest)."""
    body = {
        "slug": slug,
        "name": name,
        "description": description,
        "icon": icon,
        "internal_port": internal_port,
        "external_port": external_port,
        "exec_start": exec_start,
        "service_user": service_user,
    }
    if kill_mode:
        body["kill_mode"] = kill_mode
    if ws_path:
        body["websocket_paths"] = list(ws_path)

    result = _api_request(ctx, "POST", "/apps", json_body=body)
    click.echo(json.dumps(result, indent=2))


@app.command("unregister")
@click.argument("slug")
@click.pass_context
def app_unregister(ctx: click.Context, slug: str) -> None:
    """Remove a registered app."""
    result = _api_request(ctx, "DELETE", f"/apps/{slug}")
    click.echo(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# known-apps
# ---------------------------------------------------------------------------

@main.group("known-apps")
def known_apps() -> None:
    """Pre-built app configuration commands."""
    pass


@known_apps.command("list")
@click.pass_context
def known_apps_list(ctx: click.Context) -> None:
    """List available known-app configurations."""
    result = _api_request(ctx, "GET", "/known-apps")
    click.echo(json.dumps(result, indent=2))


@known_apps.command("install")
@click.argument("appname")
@click.option("--service-user", default="", help="OS user to run the service as")
@click.pass_context
def known_apps_install(ctx: click.Context, appname: str, service_user: str) -> None:
    """Install a known-app configuration."""
    result = _api_request(
        ctx, "POST", f"/known-apps/{appname}/install",
        json_body={"service_user": service_user},
    )
    click.echo(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# token
# ---------------------------------------------------------------------------

@main.group()
def token() -> None:
    """API token management commands."""
    pass


@token.command("create")
@click.option("--name", required=True, help="Human-readable label for this token")
@click.pass_context
def token_create(ctx: click.Context, name: str) -> None:
    """Create a new API token (localhost or session auth only)."""
    result = _api_request(ctx, "POST", "/tokens", json_body={"name": name})
    click.echo(json.dumps(result, indent=2))
    click.echo(
        "\nSave this token — it will not be shown again.",
        err=True,
    )


@token.command("list")
@click.pass_context
def token_list(ctx: click.Context) -> None:
    """List all tokens (never shows hashes or raw values)."""
    result = _api_request(ctx, "GET", "/tokens")
    click.echo(json.dumps(result, indent=2))


@token.command("revoke")
@click.argument("token_id")
@click.pass_context
def token_revoke(ctx: click.Context, token_id: str) -> None:
    """Revoke a token by its ID."""
    result = _api_request(ctx, "DELETE", f"/tokens/{token_id}")
    click.echo(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# box
# ---------------------------------------------------------------------------

@main.group()
def box() -> None:
    """Fleet box alias management (local config only)."""
    pass


@box.command("list")
def box_list() -> None:
    """List configured boxes."""
    config = _load_box_config()
    boxes = config.get("boxes", {})
    defaults = config.get("defaults", {})
    result = []
    for name, box_conf in boxes.items():
        entry = {"name": name, "url": box_conf.get("url", "")}
        if name == defaults.get("box"):
            entry["default"] = True
        result.append(entry)
    click.echo(json.dumps(result, indent=2))


@box.command("add")
@click.argument("name")
@click.option("--url", required=True, help="URL of the frontdoor instance")
@click.option("--token", default=None, help="API token for this box")
def box_add(name: str, url: str, token: str | None) -> None:
    """Add a named box alias to local config."""
    config_path = Path.home() / ".config" / "frontdoor" / "cli.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    config = _load_box_config()
    if "boxes" not in config:
        config["boxes"] = {}
    config["boxes"][name] = {"url": url}
    if token:
        config["boxes"][name]["token"] = token

    # Write back as TOML (simple format)
    lines = []
    if "defaults" in config:
        lines.append("[defaults]")
        for k, v in config["defaults"].items():
            lines.append(f'{k} = "{v}"')
        lines.append("")
    for box_name, box_conf in config.get("boxes", {}).items():
        lines.append(f"[boxes.{box_name}]")
        for k, v in box_conf.items():
            lines.append(f'{k} = "{v}"')
        lines.append("")
    config_path.write_text("\n".join(lines))
    click.echo(json.dumps({"status": "added", "name": name, "url": url}))


@box.command("remove")
@click.argument("name")
def box_remove(name: str) -> None:
    """Remove a box alias from local config."""
    config = _load_box_config()
    boxes = config.get("boxes", {})
    if name not in boxes:
        click.echo(f"Error: box '{name}' not found", err=True)
        sys.exit(1)
    del boxes[name]

    config_path = Path.home() / ".config" / "frontdoor" / "cli.toml"
    lines = []
    if "defaults" in config:
        lines.append("[defaults]")
        for k, v in config["defaults"].items():
            lines.append(f'{k} = "{v}"')
        lines.append("")
    for box_name, box_conf in boxes.items():
        lines.append(f"[boxes.{box_name}]")
        for k, v in box_conf.items():
            lines.append(f'{k} = "{v}"')
        lines.append("")
    config_path.write_text("\n".join(lines))
    click.echo(json.dumps({"status": "removed", "name": name}))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/robotdad/repos/frontdoor && pip install click && python -m pytest tests/test_cli.py -v`
Expected: 3 passed

- [ ] **Step 6: Write additional CLI tests**

Add to `tests/test_cli.py`:

```python
class TestSubcommandHelp:
    def test_services_help(self):
        """services --help shows rich help."""
        runner = CliRunner()
        result = runner.invoke(main, ["services", "--help"])
        assert result.exit_code == 0

    def test_app_register_help(self):
        """app register --help shows rich help."""
        runner = CliRunner()
        result = runner.invoke(main, ["app", "register", "--help"])
        assert result.exit_code == 0
        # Should mention required options
        assert "--internal-port" in result.output
        assert "--external-port" in result.output
        assert "--exec-start" in result.output


class TestBoxConfig:
    def test_box_add_and_list(self, tmp_path):
        """box add creates config file, box list reads it."""
        runner = CliRunner()
        config_dir = tmp_path / ".config" / "frontdoor"

        with patch("frontdoor.cli.Path.home", return_value=tmp_path):
            result = runner.invoke(main, [
                "box", "add", "testbox", "--url", "https://test.ts.net"
            ])
            assert result.exit_code == 0

            result = runner.invoke(main, ["box", "list"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert any(b["name"] == "testbox" for b in data)
```

Add import at top of file:

```python
from unittest.mock import patch
```

- [ ] **Step 7: Run all CLI tests**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/test_cli.py -v`
Expected: All tests pass

- [ ] **Step 8: Run full test suite**

Run: `cd /home/robotdad/repos/frontdoor && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 9: Commit**

```bash
cd /home/robotdad/repos/frontdoor
git add frontdoor/cli.py tests/test_cli.py pyproject.toml
git commit -m "feat: add frontdoor-admin CLI with full command surface"
```

---

## Task Group 8 — Bundle Skill Updates

Update the frontdoor Amplifier bundle skills to use `frontdoor-admin` instead of raw shell commands.

### Task 8.1: Update web-app-setup skill

**Files:**
- Modify: `skills/web-app-setup/` (the markdown skill file)

- [ ] **Step 1: Read the current web-app-setup skill**

Read the skill directory and identify the main skill file.

- [ ] **Step 2: Update Phase 2 and Phase 3 to use frontdoor-admin**

Replace the per-app provisioning sections with:

```markdown
## Phase 2 — Per-App Provisioning (via frontdoor-admin)

### Step 1: Allocate ports
```bash
PORTS=$(frontdoor-admin ports next --json)
INTERNAL=$(echo $PORTS | jq .internal_port)
EXTERNAL=$(echo $PORTS | jq .external_port)
```

### Step 2a: Register a custom app
```bash
frontdoor-admin app register SLUG \
  --name "App Name" \
  --internal-port $INTERNAL \
  --external-port $EXTERNAL \
  --exec-start "/path/to/app/binary" \
  --service-user USER \
  [--kill-mode process] \
  [--ws-path "/ws*"]
```

### Step 2b: Install a known app
Check if a known-app config exists first:
```bash
frontdoor-admin known-apps list
frontdoor-admin known-apps install APPNAME --service-user USER
```

### Step 3: Verify
```bash
frontdoor-admin services list
```
```

Phase 3 (frontdoor integration) is now automated by `app register` — the Caddy forward_auth, manifest, and WebSocket bypass are all handled by the CLI.

- [ ] **Step 3: Commit**

```bash
cd /home/robotdad/repos/frontdoor
git add skills/
git commit -m "docs: update web-app-setup skill to use frontdoor-admin"
```

### Task 8.2: Update host-infra-discovery skill

**Files:**
- Modify: `skills/host-infra-discovery/` (the markdown skill file)

- [ ] **Step 1: Read the current host-infra-discovery skill**

Read the skill directory and identify the main skill file.

- [ ] **Step 2: Update port inventory section**

Replace the port scanning instructions with:

```markdown
### Port inventory

Primary method (when frontdoor is installed):
```bash
frontdoor-admin ports next --show-used
```

Reality check (always run alongside for comparison):
```bash
ss -tlnp
```

The `--show-used` flag shows all ports frontdoor considers taken (from Caddy
configs, live processes, and reserved ports). Compare with the raw `ss` output
to catch any discrepancies.
```

- [ ] **Step 3: Commit**

```bash
cd /home/robotdad/repos/frontdoor
git add skills/
git commit -m "docs: update host-infra-discovery skill to use frontdoor-admin"
```

---

## Final Verification

- [ ] **Run the complete test suite**

```bash
cd /home/robotdad/repos/frontdoor
python -m pytest tests/ -v
```

Expected: All tests pass (original + new).

- [ ] **Verify no regressions in existing tests**

```bash
cd /home/robotdad/repos/frontdoor
python -m pytest tests/test_discovery.py tests/test_services_route.py tests/test_auth.py tests/test_config.py tests/test_main.py -v
```

Expected: All pre-existing tests still pass.

- [ ] **Verify pyproject.toml is installable**

```bash
cd /home/robotdad/repos/frontdoor
pip install -e ".[dev]"
frontdoor-admin --help
```

Expected: CLI installs and shows rich help text.
