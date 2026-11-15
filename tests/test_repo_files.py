"""Checks on the repository's own files. They need no Home Assistant and no network."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
INTEGRATION = ROOT / "custom_components" / "vega_library"
JSON_FILES = [
    ROOT / "hacs.json",
    INTEGRATION / "manifest.json",
    INTEGRATION / "translations" / "en.json",
    INTEGRATION / "strings.json",
]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", [p for p in JSON_FILES if p.exists()], ids=lambda p: p.name)
def test_json_file_is_valid(path: Path) -> None:
    """A stray or missing comma here breaks installs without any error in Home Assistant."""
    load(path)


def test_strings_and_english_translation_match() -> None:
    """Home Assistant reads translations/en.json. While strings.json exists, keep it identical."""
    strings = INTEGRATION / "strings.json"
    if not strings.exists():
        pytest.skip("strings.json has been removed")
    assert load(strings) == load(INTEGRATION / "translations" / "en.json")


def test_release_zip_name_matches_hacs_json() -> None:
    """hacs.json names the release file to install; the release workflow has to attach
    a file with exactly that name, or the release cannot be installed."""
    hacs = load(ROOT / "hacs.json")
    if not hacs.get("zip_release"):
        pytest.skip("not using zip releases")
    filename = hacs["filename"]
    assert filename.endswith(".zip")
    workflows = list((ROOT / ".github" / "workflows").glob("release.y*ml"))
    assert workflows, "zip_release is on but there is no release workflow"
    assert any(filename in workflow.read_text(encoding="utf-8") for workflow in workflows)
