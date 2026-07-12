#!/usr/bin/env python3
"""Generate a markdown API reference for Dockhand by scanning its SvelteKit
route handlers (src/routes/api/**/+server.ts).

Dockhand has no published OpenAPI spec (see Finsys/dockhand#814, still open).
This script extracts what's mechanically derivable from the route source:
HTTP methods, the leading doc comment (if any), and any local TypeScript
interfaces defined in the same file (a decent proxy for response/request
shape, though not authoritative — always verify against the actual route
code for anything security- or data-loss-sensitive before relying on it).

Usage:
    git clone --depth 1 https://github.com/Finsys/dockhand.git /tmp/dockhand-src
    python3 generate_dockhand_api_docs.py /tmp/dockhand-src docs/DOCKHAND_API.md

Re-run this after bumping DOCKHAND_LAST_REVIEWED (see CONTRIBUTING.md) so the
reference tracks whatever Dockhand release we last reviewed.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

METHOD_RE = re.compile(r"^export const (GET|POST|PUT|PATCH|DELETE)\b", re.MULTILINE)
BLOCK_COMMENT_RE = re.compile(r"/\*\*(.*?)\*/", re.DOTALL)
INTERFACE_RE = re.compile(r"(?:export )?interface (\w+)\s*\{")


def clean_comment(raw: str) -> str:
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        line = re.sub(r"^\*\s?", "", line)
        if line:
            lines.append(line)
    return " ".join(lines).strip()


def route_path(routes_root: Path, server_file: Path) -> str:
    rel = server_file.parent.relative_to(routes_root)
    path = "/" + str(rel).replace("\\", "/")
    if path == "/.":
        path = "/"
    return path


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    src_root = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    routes_root = src_root / "src" / "routes" / "api"
    if not routes_root.is_dir():
        print(f"Could not find {routes_root} — is this a Dockhand checkout?")
        sys.exit(1)

    entries = []
    for server_file in sorted(routes_root.rglob("+server.ts")):
        text = server_file.read_text(encoding="utf-8", errors="replace")
        methods = sorted(set(METHOD_RE.findall(text)))
        if not methods:
            continue

        # Leading doc comment, if the file has one before the first import/method.
        first_comment = None
        m = BLOCK_COMMENT_RE.search(text)
        if m and m.start() < 400:  # only count comments near the top of the file
            first_comment = clean_comment(m.group(1))

        interfaces = INTERFACE_RE.findall(text)

        entries.append({
            "path": route_path(routes_root, server_file),
            "methods": methods,
            "comment": first_comment,
            "interfaces": interfaces,
            "file": str(server_file.relative_to(src_root)),
        })

    # Group by top-level resource (first path segment).
    groups: dict[str, list[dict]] = {}
    for e in entries:
        top = e["path"].strip("/").split("/")[0] or "root"
        groups.setdefault(top, []).append(e)

    lines = [
        "# Dockhand REST API — generated reference",
        "",
        "> Auto-generated from Dockhand's `src/routes/api/**/+server.ts` source",
        "> (SvelteKit route handlers) via `scripts/generate_dockhand_api_docs.py`.",
        "> Dockhand does not publish an OpenAPI spec (Finsys/dockhand#814 is open,",
        "> unimplemented, as of this generation). This is a best-effort mechanical",
        "> extraction — method + any leading doc comment + locally-declared",
        "> TypeScript interfaces. It is NOT authoritative for request/response",
        "> shapes; verify against source before depending on exact fields.",
        "",
        f"Total routes discovered: {len(entries)}",
        "",
    ]

    for group in sorted(groups):
        lines.append(f"## {group}")
        lines.append("")
        for e in sorted(groups[group], key=lambda x: x["path"]):
            methods = ", ".join(e["methods"])
            lines.append(f"### `{methods}` `{e['path']}`")
            if e["comment"]:
                lines.append(f"{e['comment']}")
            if e["interfaces"]:
                lines.append(f"- Local interfaces: `{'`, `'.join(e['interfaces'])}`")
            lines.append(f"- Source: `{e['file']}`")
            lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {len(entries)} routes to {out_path}")


if __name__ == "__main__":
    main()
