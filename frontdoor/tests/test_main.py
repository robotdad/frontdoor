"""Tests for frontdoor application entry point."""

from pathlib import Path

import frontdoor.main as main_module


class TestStaticMount:
    """Verify the static directory is resolved to the correct package-local path."""

    def test_static_dir_points_inside_package(self):
        """_static_dir must live inside the frontdoor package, not the repo root."""
        main_py = Path(main_module.__file__)
        package_dir = main_py.parent  # frontdoor/
        assert main_module._static_dir == package_dir / "static", (
            f"_static_dir should be {package_dir / 'static'!r}, "
            f"got {main_module._static_dir!r}"
        )

    def test_static_dir_exists(self):
        """The resolved static directory must actually exist on disk."""
        assert main_module._static_dir.is_dir(), (
            f"Static directory does not exist: {main_module._static_dir}"
        )

    def test_static_dir_contains_login_html(self):
        """login.html must be present in the static directory."""
        login_html = main_module._static_dir / "login.html"
        assert login_html.is_file(), (
            f"login.html not found in static dir: {main_module._static_dir}"
        )
