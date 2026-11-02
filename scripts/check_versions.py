"""Consistency checks between manifest.json, requirements_test.txt and (optionally) a git tag.

Usage:
    python scripts/check_versions.py            # manifest pin == requirements_test.txt pin
    python scripts/check_versions.py v0.1.0     # ... and manifest version == tag
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "custom_components" / "zeptrionair" / "manifest.json"
REQUIREMENTS = ROOT / "requirements_test.txt"
LIBRARY = "zeptrionair-api"


def library_pin(lines: list[str]) -> str | None:
    for line in lines:
        match = re.match(rf"^\s*{LIBRARY}\s*==\s*([^\s#]+)", line)
        if match:
            return match.group(1)
    return None


def main(argv: list[str]) -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    errors = []
    manifest_pin = library_pin(manifest.get("requirements", []))
    test_pin = library_pin(REQUIREMENTS.read_text(encoding="utf-8").splitlines())
    if manifest_pin is None:
        errors.append(f"manifest.json does not pin {LIBRARY}==x.y.z")
    if manifest_pin != test_pin:
        errors.append(
            f"{LIBRARY} pin differs: manifest {manifest_pin}, requirements_test {test_pin}"
        )
    if argv:
        tag = argv[0].removeprefix("refs/tags/").removeprefix("v")
        if manifest.get("version") != tag:
            errors.append(f"manifest.json version {manifest.get('version')} != tag {tag}")
    for error in errors:
        print(f"::error::{error}")
    if not errors:
        print(f"OK: {LIBRARY}=={manifest_pin}, integration version {manifest.get('version')}")
    print(f"library_version={manifest_pin}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
