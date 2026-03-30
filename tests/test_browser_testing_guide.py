"""Tests verifying the browser testing guide and updated DEV_GUIDE.md exist with required content."""

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def test_browser_testing_md_exists():
    """tests/BROWSER_TESTING.md must exist."""
    guide = REPO_ROOT / "tests" / "BROWSER_TESTING.md"
    assert guide.exists(), "tests/BROWSER_TESTING.md does not exist"


def test_browser_testing_md_title():
    """tests/BROWSER_TESTING.md must start with '# Browser Testing Guide' title."""
    guide = REPO_ROOT / "tests" / "BROWSER_TESTING.md"
    content = guide.read_text()
    lines = content.splitlines()
    assert lines[0] == "# Browser Testing Guide", (
        f"Expected first line to be '# Browser Testing Guide', got: {lines[0]!r}"
    )


def test_browser_testing_md_covers_when_to_use():
    """tests/BROWSER_TESTING.md must explain when to use browser tests."""
    guide = REPO_ROOT / "tests" / "BROWSER_TESTING.md"
    content = guide.read_text()
    assert "when to use" in content.lower() or "When to Use" in content, (
        "BROWSER_TESTING.md must cover when to use browser tests"
    )


def test_browser_testing_md_covers_prerequisites():
    """tests/BROWSER_TESTING.md must cover prerequisites including dev server on port 58080."""
    guide = REPO_ROOT / "tests" / "BROWSER_TESTING.md"
    content = guide.read_text()
    assert "58080" in content, (
        "BROWSER_TESTING.md must mention port 58080 as the dev server prerequisite"
    )


def test_browser_testing_md_covers_baseline_verify_pattern():
    """tests/BROWSER_TESTING.md must document the baseline-before/verify-after pattern."""
    guide = REPO_ROOT / "tests" / "BROWSER_TESTING.md"
    content = guide.read_text()
    assert "baseline" in content.lower(), (
        "BROWSER_TESTING.md must document the baseline-before/verify-after pattern"
    )


def test_browser_testing_md_covers_plain_english_scenarios():
    """tests/BROWSER_TESTING.md must explain how to write new test scenarios."""
    guide = REPO_ROOT / "tests" / "BROWSER_TESTING.md"
    content = guide.read_text()
    assert "plain" in content.lower() or "scenario" in content.lower(), (
        "BROWSER_TESTING.md must explain writing plain-English test scenarios"
    )


def test_browser_testing_md_has_comparison_table():
    """tests/BROWSER_TESTING.md must have a comparison table of static vs browser tests."""
    guide = REPO_ROOT / "tests" / "BROWSER_TESTING.md"
    content = guide.read_text()
    # Markdown table rows use | separators
    has_table = "|" in content and ("static" in content.lower() or "browser" in content.lower())
    assert has_table, (
        "BROWSER_TESTING.md must contain a comparison table of static-analysis vs browser tests"
    )


def test_dev_guide_has_testing_section():
    """DEV_GUIDE.md must end with a Testing section."""
    dev_guide = REPO_ROOT / "DEV_GUIDE.md"
    content = dev_guide.read_text()
    assert "## Testing" in content, (
        "DEV_GUIDE.md must contain a '## Testing' section"
    )


def test_dev_guide_testing_section_covers_pytest():
    """DEV_GUIDE.md Testing section must mention pytest (Python backend tests)."""
    dev_guide = REPO_ROOT / "DEV_GUIDE.md"
    content = dev_guide.read_text()
    # Find testing section and check pytest appears after it
    testing_idx = content.rfind("## Testing")
    assert testing_idx != -1, "No '## Testing' section found"
    testing_section = content[testing_idx:]
    assert "pytest" in testing_section, (
        "DEV_GUIDE.md Testing section must mention pytest for Python backend tests"
    )


def test_dev_guide_testing_section_covers_static_analysis():
    """DEV_GUIDE.md Testing section must cover Python static-analysis tests of JS/CSS."""
    dev_guide = REPO_ROOT / "DEV_GUIDE.md"
    content = dev_guide.read_text()
    testing_idx = content.rfind("## Testing")
    assert testing_idx != -1, "No '## Testing' section found"
    testing_section = content[testing_idx:]
    assert "static" in testing_section.lower() or "js" in testing_section.lower(), (
        "DEV_GUIDE.md Testing section must cover static-analysis tests of JS/CSS"
    )


def test_dev_guide_testing_section_covers_browser_tests():
    """DEV_GUIDE.md Testing section must cover browser-based behavioral tests."""
    dev_guide = REPO_ROOT / "DEV_GUIDE.md"
    content = dev_guide.read_text()
    testing_idx = content.rfind("## Testing")
    assert testing_idx != -1, "No '## Testing' section found"
    testing_section = content[testing_idx:]
    assert "browser" in testing_section.lower(), (
        "DEV_GUIDE.md Testing section must cover browser-based behavioral tests"
    )


def test_dev_guide_testing_section_references_browser_testing_md():
    """DEV_GUIDE.md Testing section must reference tests/BROWSER_TESTING.md."""
    dev_guide = REPO_ROOT / "DEV_GUIDE.md"
    content = dev_guide.read_text()
    testing_idx = content.rfind("## Testing")
    assert testing_idx != -1, "No '## Testing' section found"
    testing_section = content[testing_idx:]
    assert "BROWSER_TESTING.md" in testing_section, (
        "DEV_GUIDE.md Testing section must reference tests/BROWSER_TESTING.md"
    )


def test_dev_guide_testing_section_is_at_end():
    """DEV_GUIDE.md Testing section must appear near the end of the file (tail -10 shows it)."""
    dev_guide = REPO_ROOT / "DEV_GUIDE.md"
    content = dev_guide.read_text()
    lines = content.splitlines()
    last_10 = "\n".join(lines[-10:])
    assert "Testing" in last_10 or "pytest" in last_10 or "browser" in last_10.lower(), (
        "DEV_GUIDE.md Testing section must be near the end of the file (visible in tail -10)"
    )
