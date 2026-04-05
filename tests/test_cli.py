"""Tests for frontdoor-admin CLI."""

import json
from unittest.mock import patch

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
        full_result = runner.invoke(main, ["--help"])
        assert len(result.output) < len(full_result.output)

    def test_unknown_command(self):
        """Unknown command shows error."""
        runner = CliRunner()
        result = runner.invoke(main, ["nonexistent"])
        assert result.exit_code != 0


class TestSubcommandHelp:
    def test_services_help(self):
        """services --help shows help."""
        runner = CliRunner()
        result = runner.invoke(main, ["services", "--help"])
        assert result.exit_code == 0

    def test_app_register_help(self):
        """app register --help shows required options."""
        runner = CliRunner()
        result = runner.invoke(main, ["app", "register", "--help"])
        assert result.exit_code == 0
        assert "--internal-port" in result.output
        assert "--external-port" in result.output
        assert "--exec-start" in result.output


class TestBoxConfig:
    def test_box_add_and_list(self, tmp_path):
        """box add creates config file, box list reads it."""
        runner = CliRunner()

        with patch("frontdoor.cli.Path.home", return_value=tmp_path):
            add_result = runner.invoke(
                main, ["box", "add", "testbox", "--url", "https://test.ts.net"]
            )
            assert add_result.exit_code == 0

            list_result = runner.invoke(main, ["box", "list"])
            assert list_result.exit_code == 0
            data = json.loads(list_result.output)
            assert any(b["name"] == "testbox" for b in data)
