#!/usr/bin/env python3
"""
Assert the console needs no network at runtime.

A venue with a captive portal is the assumed demo condition, so any external
host in the console source is a demo that shows a grey rectangle to judges.

Replaces a Makefile one-liner that used `grep -P`, which BSD grep on macOS does
not support: the grep errored, the `||` branch ran, and the check reported OK
unconditionally. It was verified vacuous by injecting a CDN URL and watching it
pass. This version is verified to fail on the same input.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "console" / "src"

URL = re.compile(r"""https?://([A-Za-z0-9.-]+)""")

# Hosts that never cause a runtime fetch.
ALLOWED = {
    "localhost", "127.0.0.1", "0.0.0.0",
    # Spec and namespace identifiers, not fetched.
    "www.w3.org", "www.opengis.net", "schemas.opengis.net",
}
# Comment-only references (docs, citations) are fine; only code matters.
COMMENT = re.compile(r"^\s*(//|\*|/\*|#)")


def main() -> int:
    if not SRC.exists():
        print(f"FAIL: {SRC} not found")
        return 1

    findings = []
    files = sorted([*SRC.rglob("*.ts"), *SRC.rglob("*.tsx"),
                    *SRC.rglob("*.css"), *(ROOT / "console").glob("*.html")])
    for f in files:
        for n, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
            if COMMENT.match(line):
                continue
            for host in URL.findall(line):
                if host in ALLOWED:
                    continue
                findings.append((f.relative_to(ROOT), n, host, line.strip()[:90]))

    print(f"scanned {len(files)} console source files")
    if findings:
        print(f"FAIL: {len(findings)} external host reference(s) in console source")
        for path, n, host, line in findings:
            print(f"  {path}:{n}  {host}")
            print(f"      {line}")
        return 1
    print("OK: console references no external hosts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
