#!/usr/bin/env python3
"""Release helpers for CI (.github/workflows/build.yml) and release pull requests.

python3 scripts/release.py check
    CHANGELOG.md has [Unreleased] and a section for manifest.json's version.
python3 scripts/release.py version
    manifest.json's version.
python3 scripts/release.py dev-version <run> <tagged>
    The test build's version: the next patch once the current version is
    tagged (<tagged> = true|false), so HACS offers it over the installed
    release.
python3 scripts/release.py notes <version> [--test-build <run>]
    Release notes: that changelog section plus install text ("Unreleased"
    for test builds).
python3 scripts/release.py package <zip> [--version <version>]
    The release asset HACS installs (hacs.json's zip_release): the
    integration's files at the zip's root, since HACS extracts it into
    custom_components/dockhand/. --version stamps a test build's version into
    its manifest.json, so Home Assistant and diagnostics show it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INTEGRATION = ROOT / "custom_components" / "dockhand"
MANIFEST = INTEGRATION / "manifest.json"
CHANGELOG = ROOT / "CHANGELOG.md"
REPO = "https://github.com/raetha/ha-dockhand"

# Older sections use an em dash before the date, newer ones a hyphen: both are read.
_HEADING = re.compile(r"^## \[([^\]]+)\](?:\s*[-—]\s*\S+)?\s*$")
_LINK_REF = re.compile(r"^\[[^\]]+\]:\s")
_PLAIN_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_MANIFEST_VERSION = re.compile(r'^(  "version": )"[^"]*"', re.MULTILINE)


def sections(changelog: str) -> dict[str, str]:
    """Return changelog sections by heading name ("Unreleased", "1.11.2", ...)."""
    out: dict[str, str] = {}
    name: str | None = None
    lines: list[str] = []
    for line in changelog.splitlines():
        heading = _HEADING.match(line)
        if heading or _LINK_REF.match(line):
            if name is not None:
                out[name] = "\n".join(lines).strip()
            name = heading.group(1) if heading else None
            lines = []
        elif name is not None:
            lines.append(line)
    if name is not None:
        out[name] = "\n".join(lines).strip()
    return out


def check(changelog: str, version: str) -> list[str]:
    """Return the problems that should fail CI."""
    found = sections(changelog)
    problems = []
    if "Unreleased" not in found:
        problems.append('CHANGELOG.md has no "## [Unreleased]" section')
    if version not in found:
        problems.append(f"CHANGELOG.md has no section for version {version}")
    return problems


def dev_version(version: str, run: int, tagged: bool) -> str:
    match = _PLAIN_VERSION.match(version)
    if not match:
        raise ValueError(f"not a plain X.Y.Z version: {version}")
    major, minor, patch = (int(part) for part in match.groups())
    base = f"{major}.{minor}.{patch + 1}" if tagged else version
    return f"{base}-dev.{run}"


def notes(changelog: str, version: str, test_build: int | None = None) -> str:
    body = sections(changelog).get(version)
    if body is None:
        raise ValueError(f"CHANGELOG.md has no section for {version}")
    install = (
        f"**Install** with HACS (search for Dockhand, or add `{REPO}` as a custom "
        "repository of type Integration), restart Home Assistant, then add the "
        "Dockhand integration under Settings → Devices & services. The "
        "[Dockhand Cards](https://github.com/raetha/ha-dockhand-cards) add "
        f"dashboard cards for it.\n\nMore: [README]({REPO}#readme)"
    )
    parts = []
    if test_build is not None:
        parts.append(
            f"**Test build {test_build}** from `dev`, for trying what's coming. "
            "To get it, enable and turn on the Dockhand **Pre-release** switch "
            "HACS adds (disabled by default); HACS then offers it as an update. "
            "The changes since the last release:"
        )
    parts += [body or "_No changes listed yet._", install]
    return "\n\n".join(parts) + "\n"


def stamp_version(manifest: str, version: str) -> str:
    """Set manifest.json's version, keeping the file's own key order and layout."""
    stamped, count = _MANIFEST_VERSION.subn(rf'\1"{version}"', manifest)
    if count != 1:
        raise ValueError("manifest.json has no single version line")
    return stamped


def package(
    target: Path, version: str | None = None, source: Path = INTEGRATION
) -> list[str]:
    """Write the HACS release zip and return its member names."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            relative = path.relative_to(source)
            if (
                path.is_dir()
                or "__pycache__" in relative.parts
                or path.suffix == ".pyc"
            ):
                continue
            if relative.as_posix() == "manifest.json" and version is not None:
                manifest = path.read_text(encoding="utf-8")
                archive.writestr("manifest.json", stamp_version(manifest, version))
            else:
                archive.write(path, relative.as_posix())
        return archive.namelist()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("version")
    dev = sub.add_parser("dev-version")
    dev.add_argument("run", type=int)
    dev.add_argument("tagged", choices=["true", "false"])
    note = sub.add_parser("notes")
    note.add_argument("version")
    note.add_argument("--test-build", type=int)
    pack = sub.add_parser("package")
    pack.add_argument("zip", type=Path)
    pack.add_argument("--version")
    args = parser.parse_args(argv)

    changelog = CHANGELOG.read_text(encoding="utf-8")
    version = json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]
    if args.cmd == "check":
        problems = check(changelog, version)
        for problem in problems:
            print(f"::error file=CHANGELOG.md::{problem}", file=sys.stderr)
        if problems:
            return 1
        print(f"CHANGELOG.md OK for {version}")
    elif args.cmd == "version":
        print(version)
    elif args.cmd == "dev-version":
        print(dev_version(version, args.run, args.tagged == "true"))
    elif args.cmd == "notes":
        sys.stdout.write(notes(changelog, args.version, args.test_build))
    else:
        members = package(args.zip, args.version)
        print(f"{args.zip}: {len(members)} files, version {args.version or version}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
