"""scripts/markdown.py: prose one line per paragraph or list item."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "markdown.py"
spec = importlib.util.spec_from_file_location("markdown_script", SCRIPT)
assert spec is not None and spec.loader is not None
markdown = importlib.util.module_from_spec(spec)
spec.loader.exec_module(markdown)


def test_joins_prose_and_leaves_blocks_alone():
    text = (
        "# Title\n"
        "A paragraph\nwrapped.\n\n"
        "- An item\n  wrapped.\n  - A sub-item\n"
        "| a |\n| b |\n\n"
        "```\ncode\nlines\n```\n"
        "<!--\nnote\nlines\n-->\n"
        "Hard break  \nkept.\n"
    )
    new, joined = markdown.reflow(text, changelog=False)
    assert new == (
        "# Title\n"
        "A paragraph wrapped.\n\n"
        "- An item wrapped.\n  - A sub-item\n"
        "| a |\n| b |\n\n"
        "```\ncode\nlines\n```\n"
        "<!--\nnote\nlines\n-->\n"
        "Hard break  \nkept.\n"
    )
    assert joined == [3, 6]


def test_released_changelog_sections_are_left_as_they_are():
    text = "## [Unreleased]\n\n- New\n  item.\n\n## [1.0.0] - 2026-01-01\n\n- Old\n  item.\n"
    new, joined = markdown.reflow(text, changelog=True)
    assert new.endswith("- Old\n  item.\n")
    assert "- New item." in new
    assert joined == [4]


def test_check_and_fix(tmp_path, capsys):
    path = tmp_path / "doc.md"
    path.write_text("Wrapped\nline.\n", encoding="utf-8")
    assert markdown.main(["--check", str(path)]) == 1
    assert "::error" in capsys.readouterr().out
    assert markdown.main([str(path)]) == 0
    assert path.read_text(encoding="utf-8") == "Wrapped line.\n"
    assert markdown.main(["--check", str(path)]) == 0


def test_the_repository_passes():
    root = SCRIPT.parent.parent
    files = [str(p) for p in root.glob("*.md")] + [
        str(p) for p in (root / "docs").glob("*.md")
    ]
    assert markdown.main(["--check", *files]) == 0
