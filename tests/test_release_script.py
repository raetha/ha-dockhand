"""Tests for scripts/release.py, which CI uses to check the changelog and publish releases."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import zipfile

import pytest

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "release.py"
_spec = importlib.util.spec_from_file_location("release_script", _PATH)
assert _spec and _spec.loader
release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release)

CHANGELOG = """# Changelog

## [Unreleased]

### Added

- New thing.

## [1.1.0] - 2026-11-03

### Fixed

- A fix.

## [1.0.0] — 2026-07-21

- First.

[Unreleased]: https://example.com/compare/v1.1.0...HEAD
[1.1.0]: https://example.com/compare/v1.0.0...v1.1.0
"""


def test_sections_read_both_date_separators_and_stop_at_link_references():
    found = release.sections(CHANGELOG)
    assert list(found) == ["Unreleased", "1.1.0", "1.0.0"]
    assert found["1.0.0"] == "- First."


def test_check_requires_a_dated_section_only_for_a_release():
    assert release.check(CHANGELOG, "1.1.0") == []
    assert release.check(CHANGELOG, "1.2.0") == []  # expected next version on dev
    assert release.check(CHANGELOG, "1.1.0", release=True) == []
    assert len(release.check(CHANGELOG, "1.2.0", release=True)) == 1
    assert len(release.check(CHANGELOG.replace("## [Unreleased]", ""), "1.1.0")) == 1


def test_dev_version_sorts_above_the_installed_release():
    assert release.dev_version("1.11.2", 12, tagged=True) == "1.11.3-dev.12"
    assert release.dev_version("1.12.0", 13, tagged=False) == "1.12.0-dev.13"
    with pytest.raises(ValueError):
        release.dev_version("1.12.0b1", 1, tagged=True)


def test_notes_use_the_section_and_mark_test_builds():
    assert release.notes(CHANGELOG, "1.1.0").startswith(
        "### Fixed\n\n- A fix.\n\n**Install**"
    )
    assert release.notes(CHANGELOG, "Unreleased", 7).startswith("**Test build 7**")
    with pytest.raises(ValueError):
        release.notes(CHANGELOG, "9.9.9")


def test_the_repository_changelog_passes_its_own_check():
    assert release.main(["check"]) == 0


def test_package_puts_files_at_the_zip_root_and_stamps_test_builds(tmp_path):
    source = tmp_path / "dockhand"
    (source / "translations").mkdir(parents=True)
    (source / "__pycache__").mkdir()
    (source / "manifest.json").write_text(
        '{\n  "domain": "dockhand",\n  "name": "Dockhand",\n  "version": "1.11.2"\n}\n'
    )
    (source / "__init__.py").write_text("")
    (source / "translations" / "en.json").write_text("{}")
    (source / "__pycache__" / "x.cpython-314.pyc").write_bytes(b"")

    names = release.package(tmp_path / "out.zip", "1.11.3-dev.4", source)
    assert sorted(names) == ["__init__.py", "manifest.json", "translations/en.json"]
    with zipfile.ZipFile(tmp_path / "out.zip") as archive:
        manifest = archive.read("manifest.json").decode()
    assert json.loads(manifest)["version"] == "1.11.3-dev.4"
    assert manifest.index('"domain"') < manifest.index('"version"')

    release.package(tmp_path / "plain.zip", None, source)
    with zipfile.ZipFile(tmp_path / "plain.zip") as archive:
        assert json.loads(archive.read("manifest.json"))["version"] == "1.11.2"


def test_stamp_version_needs_exactly_one_version_line():
    with pytest.raises(ValueError):
        release.stamp_version('{\n  "domain": "dockhand"\n}\n', "1.0.0")
