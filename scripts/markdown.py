"""Markdown prose is written one line per paragraph or list item, so whatever
renders it wraps it: GitHub's release pages (the changelog's notes) turn every
line break into a visible one.

python3 scripts/markdown.py --check FILE...   fail on a line broken mid-paragraph
python3 scripts/markdown.py FILE...           join those lines

In CHANGELOG.md only [Unreleased] is checked: released sections are frozen.
"""

import re
import sys
from pathlib import Path

BLOCK_START = re.compile(
    r"^\s*(#|[-*+]\s|\d+[.)]\s|\||>|```|~~~|<|\[[^\]]+\]:\s|---\s*$|\*\*\*\s*$)"
)
RELEASED = re.compile(r"^## \[\d")


def reflow(text: str, changelog: bool) -> tuple[str, list[int]]:
    out: list[str] = []
    joined: list[int] = []
    fence = False
    comment = False
    frozen = False
    prev_kind = "blank"  # blank | prose | other
    for n, line in enumerate(text.split("\n"), start=1):
        if frozen:
            out.append(line)
            continue
        if changelog and RELEASED.match(line):
            frozen = True
            out.append(line)
            continue
        stripped = line.strip()
        if comment:
            out.append(line)
            if "-->" in line:
                comment = False
            prev_kind = "other"
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence = not fence
            out.append(line)
            prev_kind = "other"
            continue
        if fence:
            out.append(line)
            continue
        if stripped.startswith("<!--") and "-->" not in stripped:
            comment = True
            out.append(line)
            prev_kind = "other"
            continue
        if not stripped:
            out.append(line)
            prev_kind = "blank"
            continue
        starts_block = bool(BLOCK_START.match(line))
        if prev_kind == "prose" and not starts_block and not out[-1].endswith("  "):
            out[-1] = out[-1].rstrip() + " " + stripped
            joined.append(n)
            continue
        out.append(line)
        heading_or_table = stripped.startswith(("#", "|"))
        prev_kind = "other" if heading_or_table else "prose"
    return "\n".join(out), joined


def main(argv: list[str]) -> int:
    check = "--check" in argv
    bad = 0
    for name in (a for a in argv if a != "--check"):
        path = Path(name)
        text = path.read_text(encoding="utf-8")
        new, joined = reflow(text, path.name == "CHANGELOG.md")
        if joined:
            bad += 1
            if check:
                print(
                    f"::error file={name},line={joined[0]}::a line breaks inside a "
                    "paragraph or list item: write it as one line and let the "
                    "renderer wrap it (python3 scripts/markdown.py joins them)"
                )
            else:
                path.write_text(new, encoding="utf-8")
                print(f"{name}: joined {len(joined)} lines")
    return 1 if check and bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
