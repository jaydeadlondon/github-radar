#!/usr/bin/env python
"""Write the frozen v1 OpenAPI document to ``docs/openapi-v1.json``.

Run from the repository root::

    python scripts/export_openapi.py            # write the snapshot
    python scripts/export_openapi.py --check    # fail when it is out of date

``--check`` is part of the release checklist: the API contract must not drift
without the snapshot being regenerated in the same commit.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

SNAPSHOT = ROOT / "docs" / "openapi-v1.json"


def build_document() -> dict:
    from api.app import create_app

    return create_app().openapi()


def render(document: dict) -> str:
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit with status 1 when the snapshot differs from the live schema.",
    )
    arguments = parser.parse_args()

    rendered = render(build_document())
    if arguments.check:
        current = SNAPSHOT.read_text() if SNAPSHOT.is_file() else ""
        if current != rendered:
            print(
                "docs/openapi-v1.json is out of date; "
                "run `python scripts/export_openapi.py` and commit the result.",
                file=sys.stderr,
            )
            return 1
        print("docs/openapi-v1.json matches the live schema.")
        return 0

    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(rendered)
    print(f"Wrote {SNAPSHOT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
