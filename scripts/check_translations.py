"""Check that every translation has exactly the keys of en.json and the same placeholders.

Usage: python scripts/check_translations.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "custom_components" / "zeptrionair"
TRANSLATIONS = ROOT / "translations"
REQUIRED_LANGUAGES = ("en", "de", "fr", "it")
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def flatten(data: object, prefix: str = "") -> dict[str, str]:
    if isinstance(data, dict):
        out: dict[str, str] = {}
        for key, value in data.items():
            out.update(flatten(value, f"{prefix}{key}."))
        return out
    return {prefix.rstrip("."): str(data)}


def main() -> int:
    errors: list[str] = []
    files = {path.stem: path for path in TRANSLATIONS.glob("*.json")}
    for language in REQUIRED_LANGUAGES:
        if language not in files:
            errors.append(f"missing translations/{language}.json")
    reference = flatten(json.loads(files["en"].read_text(encoding="utf-8")))
    for language, path in sorted(files.items()):
        if language == "en":
            continue
        other = flatten(json.loads(path.read_text(encoding="utf-8")))
        for key in sorted(reference.keys() - other.keys()):
            errors.append(f"{language}: missing {key}")
        for key in sorted(other.keys() - reference.keys()):
            errors.append(f"{language}: extra {key}")
        for key in sorted(reference.keys() & other.keys()):
            expected = set(PLACEHOLDER.findall(reference[key]))
            found = set(PLACEHOLDER.findall(other[key]))
            if expected != found:
                errors.append(
                    f"{language}: {key} placeholders {sorted(found)} != {sorted(expected)}"
                )
            if not other[key].strip():
                errors.append(f"{language}: {key} is empty")
    for error in errors:
        print(error)
    if not errors:
        print(f"OK: {', '.join(sorted(files))} match en.json ({len(reference)} keys)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
