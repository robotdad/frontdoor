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


class TestNextAvailablePorts:
    def test_returns_pair_of_free_ports(self, tmp_path):
        """next_available_ports returns (internal, external) pair."""
        from frontdoor.discovery import next_available_ports
        from unittest.mock import MagicMock, patch

        conf_d = tmp_path / "conf.d"
        conf_d.mkdir()
        (conf_d / "muxplex.caddy").write_text(
            ":8441 {\n    reverse_proxy localhost:8088\n}\n"
        )

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

        assert internal != external
        assert internal >= 8440
        assert external >= 8440

    def test_skips_used_ports(self, tmp_path):
        """next_available_ports skips ports used by Caddy or live processes."""
        from frontdoor.discovery import next_available_ports
        from unittest.mock import MagicMock, patch

        conf_d = tmp_path / "conf.d"
        conf_d.mkdir()
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

        assert internal >= 8442
        assert external > internal
