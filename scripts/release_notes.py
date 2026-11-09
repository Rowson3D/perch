"""Release notes from CHANGELOG.md.

python scripts/release_notes.py --versions          # every version in the changelog, newest first
python scripts/release_notes.py 0.2.0               # that version's notes (Markdown)
python scripts/release_notes.py 0.2.0 --assets DIR  # ...plus a SHA-256 table for the files in DIR
"""

import argparse
import hashlib
import pathlib
import re
import sys

CHANGELOG = pathlib.Path(__file__).resolve().parent.parent / "CHANGELOG.md"
HEADING = re.compile(r"^## \[(?P<version>[^\]]+)\](?: - (?P<date>\S+))?\s*$", re.M)


def sections(text):
    """{version: body} in changelog order."""
    matches = list(HEADING.finditer(text))
    out = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out[m["version"]] = text[m.end() : end].strip()
    return out


def checksums(folder):
    rows = ["### Checksums (SHA-256)", "", "| File | SHA-256 |", "|---|---|"]
    for f in sorted(pathlib.Path(folder).iterdir(), key=lambda p: p.name.lower()):
        if f.is_file():
            rows.append(f"| `{f.name}` | `{hashlib.sha256(f.read_bytes()).hexdigest()}` |")
    return "\n".join(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("version", nargs="?")
    ap.add_argument("--versions", action="store_true")
    ap.add_argument("--assets")
    args = ap.parse_args()
    found = sections(CHANGELOG.read_text(encoding="utf-8"))
    if args.versions:
        print("\n".join(found))
        return
    version = (args.version or "").lstrip("v")
    if version not in found:
        sys.exit(f"{version or '(none)'} is not in CHANGELOG.md")
    notes = found[version]
    if args.assets:
        notes += "\n\n" + checksums(args.assets)
    sys.stdout.reconfigure(encoding="utf-8")
    print(notes)


if __name__ == "__main__":
    main()
