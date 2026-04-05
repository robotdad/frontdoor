"""Tests for frontdoor/service_control.py — run_privileged wrapper."""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from frontdoor.service_control import run_privileged


class TestRunPrivileged:
    def test_calls_sudo_with_json_stdin(self):
        """run_privileged calls sudo frontdoor-priv with JSON on stdin."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '{"ok": true}'

        with patch(
            "frontdoor.service_control.subprocess.run", return_value=mock_result
        ) as mock_run:
            run_privileged("systemctl", action="restart", unit="muxplex.service")

        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        assert args[0][0] == "sudo"
        assert "frontdoor-priv" in args[0][-1]

        stdin_data = json.loads(kwargs["input"])
        assert stdin_data["operation"] == "systemctl"
        assert stdin_data["action"] == "restart"
        assert stdin_data["unit"] == "muxplex.service"

    def test_raises_on_nonzero_exit(self):
        """run_privileged raises RuntimeError when frontdoor-priv fails."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = '{"error": "something broke"}'
        mock_result.stdout = ""

        with patch(
            "frontdoor.service_control.subprocess.run", return_value=mock_result
        ):
            with pytest.raises(RuntimeError, match="frontdoor-priv failed"):
                run_privileged("systemctl", action="restart", unit="bad.service")

    def test_raises_on_timeout(self):
        """run_privileged raises RuntimeError on subprocess timeout."""
        with patch(
            "frontdoor.service_control.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="sudo", timeout=30),
        ):
            with pytest.raises(RuntimeError, match="timed out"):
                run_privileged("systemctl", action="restart", unit="stuck.service")
