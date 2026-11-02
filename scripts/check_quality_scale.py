"""Check quality_scale.yaml against Home Assistant core's current rule list.

Home Assistant adds, renames and retires quality scale rules over time, and
hassfest only validates quality_scale.yaml for core integrations, so nothing
else tells a custom integration its file has gone stale. This fetches the
rule list hassfest itself uses (script/hassfest/quality_scale.py on core's
dev branch) and fails if quality_scale.yaml:
  - is missing a rule, or lists one core no longer has
  - has a status other than done / todo / exempt
  - has a todo or exempt rule without a comment saying why

It doesn't judge whether a rule marked done really is done — that's the
audit in docs/quality-scale.md.

Usage:
  python3 scripts/check_quality_scale.py              # fetch from GitHub
  python3 scripts/check_quality_scale.py PATH         # a local copy of core's
                                                      # quality_scale.py
"""

import re
import sys
import urllib.request
from pathlib import Path

RULES_URL = (
    "https://raw.githubusercontent.com/home-assistant/core/dev/"
    "script/hassfest/quality_scale.py"
)
REPO_ROOT = Path(__file__).resolve().parent.parent
QUALITY_SCALE_YAML = REPO_ROOT / "custom_components/dockhand/quality_scale.yaml"
STATUSES = {"done", "todo", "exempt"}


def core_rules(source: str) -> dict[str, str]:
    """Rule name -> tier, from core's quality_scale.py."""
    rules = dict(
        re.findall(r'Rule\(\s*"([a-z0-9-]+)",\s*ScaledQualityScaleTiers\.(\w+)', source)
    )
    if len(rules) < 40:  # the format changed; better to fail than pass silently
        sys.exit(f"Found only {len(rules)} rules in core's quality_scale.py")
    return {name: tier.lower() for name, tier in rules.items()}


def our_rules(text: str) -> dict[str, tuple[str, bool]]:
    """Rule name -> (status, has a comment), from quality_scale.yaml.

    A deliberately small parser for this file's own layout (two-space rule
    keys under `rules:`, four-space `status:`/`comment:`), so the check
    needs nothing beyond the standard library.
    """
    rules: dict[str, tuple[str, bool]] = {}
    current = None
    for line in text.splitlines():
        if m := re.match(r"^  ([a-z0-9-]+):\s*(\S*)\s*$", line):
            current = m.group(1)
            rules[current] = (m.group(2), False)  # `rule: done` shorthand
        elif current and (m := re.match(r"^    status:\s*(\S+)", line)):
            rules[current] = (m.group(1), rules[current][1])
        elif current and re.match(r"^    comment:", line):
            rules[current] = (rules[current][0], True)
    return rules


def main() -> int:
    if len(sys.argv) > 1:
        source = Path(sys.argv[1]).read_text(encoding="utf-8")
    else:
        with urllib.request.urlopen(RULES_URL, timeout=30) as resp:
            source = resp.read().decode()
    expected = core_rules(source)
    ours = our_rules(QUALITY_SCALE_YAML.read_text(encoding="utf-8"))

    problems = [
        f"missing rule: {name} ({tier})"
        for name, tier in expected.items()
        if name not in ours
    ]
    problems += [
        f"rule no longer in Home Assistant: {name}"
        for name in ours
        if name not in expected
    ]
    for name, (status, has_comment) in ours.items():
        if status not in STATUSES:
            problems.append(f"{name}: unknown status {status!r}")
        elif status != "done" and not has_comment:
            problems.append(f"{name}: {status} without a comment saying why")

    if problems:
        print("quality_scale.yaml is out of date with Home Assistant's rules:")
        print("\n".join(f"  - {p}" for p in problems))
        print("See docs/quality-scale.md for how to review a new or changed rule.")
        return 1
    todo = [name for name, (status, _) in ours.items() if status == "todo"]
    print(f"quality_scale.yaml covers all {len(expected)} rules.")
    if todo:
        print(f"Still todo: {', '.join(todo)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
