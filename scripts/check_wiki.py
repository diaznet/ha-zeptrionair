"""Check (and with --fix, update) a local clone of the GitHub wiki.

    git clone https://github.com/diaznet/ha-zeptrionair.wiki.git
    python scripts/check_wiki.py ../ha-zeptrionair.wiki --fix

--fix writes the language switcher (first line of every page), _Sidebar.md and _Footer.md
from _NAMES. Without it, it only checks. Checks: every page exists in every language, no
unknown pages, every wiki link and #anchor resolves, and no real identifiers.
"""

from __future__ import annotations

import os
import re
import sys
import unicodedata
from pathlib import Path

LANGUAGES = {"en": "English", "de": "Deutsch", "fr": "Français", "it": "Italiano"}

# Every page's file name (without .md) per language, in sidebar order. English has no prefix.
_NAMES: dict[str, list[str]] = {
    "en": [
        "Home",
        "Installation",
        "Setup",
        "Lights-and-dimmers",
        "Covers",
        "Slats",
        "Scenes",
        "Keys-events-and-LEDs",
        "Smartbuttons",
        "Actions",
        "Automation-examples",
        "Options",
        "Troubleshooting",
        "FAQ",
    ],
    "de": [
        "de-Startseite",
        "de-Installation",
        "de-Einrichtung",
        "de-Lichter-und-Dimmer",
        "de-Storen",
        "de-Lamellen",
        "de-Szenen",
        "de-Tasten-Ereignisse-und-LEDs",
        "de-Smartbuttons",
        "de-Aktionen",
        "de-Automationsbeispiele",
        "de-Optionen",
        "de-Fehlerbehebung",
        "de-FAQ",
    ],
    "fr": [
        "fr-Accueil",
        "fr-Installation",
        "fr-Configuration",
        "fr-Lumieres-et-variateurs",
        "fr-Stores",
        "fr-Lamelles",
        "fr-Scenes",
        "fr-Touches-evenements-et-LED",
        "fr-Smartbuttons",
        "fr-Actions",
        "fr-Exemples-d-automatisations",
        "fr-Options",
        "fr-Depannage",
        "fr-FAQ",
    ],
    "it": [
        "it-Home",
        "it-Installazione",
        "it-Configurazione",
        "it-Luci-e-dimmer",
        "it-Tapparelle",
        "it-Lamelle",
        "it-Scene",
        "it-Tasti-eventi-e-LED",
        "it-Smartbutton",
        "it-Azioni",
        "it-Esempi-di-automazioni",
        "it-Opzioni",
        "it-Risoluzione-dei-problemi",
        "it-FAQ",
    ],
}
PAGES: list[dict[str, str]] = [
    {lang: names[i] for lang, names in _NAMES.items()} for i in range(len(_NAMES["en"]))
]

HOME_LABELS = {"en": "Home", "de": "Startseite", "fr": "Accueil", "it": "Home"}
SPECIAL = {"_Sidebar", "_Footer"}
SWITCHER_MARK = "<!-- languages -->"
FOOTER = (
    "[Feller zeptrionAir for Home Assistant](https://github.com/diaznet/ha-zeptrionair) · "
    "[Issues](https://github.com/diaznet/ha-zeptrionair/issues) · "
    "[Changelog](https://github.com/diaznet/ha-zeptrionair/blob/main/CHANGELOG.md)\n"
)

# Real identifiers must never appear: private networks other than the documented examples,
# real hostnames/domains, and serial-like numbers.
FORBIDDEN = [
    re.compile(r"\b10\.\d+\.\d+\.\d+\b"),
    re.compile(r"\b172\.(1[6-9]|2\d|3[01])\.\d+\.\d+\b"),
    re.compile(r"\b192\.168\.(?!1\.)\d+\.\d+\b"),
    re.compile(r"\bzapp-(?!12345678\b)\d{8}\b", re.IGNORECASE),
    re.compile(r"\b(19|20)\d{6}\b"),
]
# Your own hostnames/domains: a regex in WIKI_FORBIDDEN (kept out of the repository).
if os.environ.get("WIKI_FORBIDDEN"):
    FORBIDDEN.append(re.compile(os.environ["WIKI_FORBIDDEN"], re.IGNORECASE))

LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")


def slug(heading: str) -> str:
    """GitHub's heading anchor: lower case, punctuation dropped, spaces to hyphens."""
    text = re.sub(r"<[^>]+>", "", heading)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = text.replace("`", "").replace("*", "").strip().lower()
    out = []
    for char in text:
        if char in " -":
            out.append("-" if char == " " else char)
        elif char == "_" or unicodedata.category(char)[0] in "LN":
            out.append(char)
    return "".join(out)


def anchors(text: str) -> set[str]:
    found: set[str] = set()
    counts: dict[str, int] = {}
    in_code = False
    for line in text.splitlines():
        if FENCE.match(line):
            in_code = not in_code
            continue
        match = None if in_code else HEADING.match(line)
        if match:
            base = slug(match.group(2))
            n = counts.get(base, 0)
            counts[base] = n + 1
            found.add(base if n == 0 else f"{base}-{n}")
    return found


def links(text: str) -> list[str]:
    result = []
    in_code = False
    for line in text.splitlines():
        if FENCE.match(line):
            in_code = not in_code
            continue
        if not in_code:
            result.extend(LINK.findall(re.sub(r"`[^`]*`", "", line)))
    return result


def switcher(row: dict[str, str], lang: str) -> str:
    parts = [
        f"**{name}**" if code == lang else f"[{name}]({row[code]})"
        for code, name in LANGUAGES.items()
    ]
    # The marker goes last: a line starting with an HTML comment is rendered as raw HTML.
    return " · ".join(parts) + f" {SWITCHER_MARK}\n"


def sidebar(titles: dict[str, str]) -> str:
    lines = [
        " · ".join(f"[{name}]({PAGES[0][code]})" for code, name in LANGUAGES.items()),
        "",
    ]
    for code, name in LANGUAGES.items():
        lines.append(f"<details{' open' if code == 'en' else ''}><summary>{name}</summary>")
        lines.append("")
        lines.append(f"- [{HOME_LABELS[code]}]({PAGES[0][code]})")
        lines.extend(f"- [{titles[row[code]]}]({row[code]})" for row in PAGES[1:])
        lines.append("")
        lines.append("</details>")
        lines.append("")
    return "\n".join(lines)


def title(text: str, page: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return page


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    fix = "--fix" in sys.argv
    if len(args) != 1:
        print(__doc__)
        return 2
    wiki = Path(args[0])
    errors: list[str] = []
    expected = {row[code] for row in PAGES for code in LANGUAGES}

    present = {p.stem for p in wiki.glob("*.md")}
    for page in sorted(expected - present):
        errors.append(f"{page}.md: missing")
    for page in sorted(present - expected - SPECIAL):
        errors.append(f"{page}.md: not in PAGES")

    texts: dict[str, str] = {}
    for row in PAGES:
        for code in LANGUAGES:
            path = wiki / f"{row[code]}.md"
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            first, _, rest = text.partition("\n")
            body = rest if SWITCHER_MARK in first else text
            wanted = switcher(row, code) + "\n" + body.lstrip("\n")
            if text != wanted:
                if fix:
                    path.write_text(wanted, encoding="utf-8", newline="\n")
                    text = wanted
                else:
                    errors.append(f"{path.name}: language switcher outdated (run with --fix)")
            texts[row[code]] = text

    titles = {page: title(text, page) for page, text in texts.items()}
    generated = {"_Sidebar": sidebar(titles) if not errors else None, "_Footer": FOOTER}
    for name, content in generated.items():
        path = wiki / f"{name}.md"
        if content is None:
            continue
        if fix:
            path.write_text(content, encoding="utf-8", newline="\n")
        elif not path.exists() or path.read_text(encoding="utf-8") != content:
            errors.append(f"{name}.md: outdated (run with --fix)")
        texts[name] = path.read_text(encoding="utf-8") if path.exists() else content

    page_anchors = {page: anchors(text) for page, text in texts.items()}
    for page, text in texts.items():
        for target in links(text):
            if re.match(r"[a-z]+:", target):
                continue  # external
            name, _, anchor = target.partition("#")
            name = name or page
            if name not in page_anchors:
                errors.append(f"{page}.md: link to unknown page {target}")
            elif anchor and anchor not in page_anchors[name]:
                errors.append(f"{page}.md: link to unknown anchor {target}")
        for pattern in FORBIDDEN:
            for match in pattern.finditer(text):
                errors.append(f"{page}.md: forbidden identifier {match.group(0)!r}")

    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        return 1
    print(f"OK: {len(PAGES)} pages x {len(LANGUAGES)} languages, links and anchors resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
