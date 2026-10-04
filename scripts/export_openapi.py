from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

SNAPSHOT = ROOT / "docs" / "openapi-v1.json"


def build_document() -> dict[str, Any]:
    from api.app import create_app

    return create_app().openapi()


def render(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def canonical(json_text: str) -> str:
    return render(json.loads(json_text))


def first_difference(left: Any, right: Any, path: str = "$") -> str | None:
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            location = f"{path}.{key}"
            if key not in left:
                return f"{location} is missing from the snapshot"
            if key not in right:
                return f"{location} is not in the live schema"
            difference = first_difference(left[key], right[key], location)
            if difference:
                return difference
        return None
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return (
                f"{path} has {len(left)} item(s) in the snapshot and "
                f"{len(right)} in the live schema"
            )
        for index, (stored, live) in enumerate(zip(left, right, strict=True)):
            difference = first_difference(stored, live, f"{path}[{index}]")
            if difference:
                return difference
        return None
    if type(left) is not type(right):
        return (
            f"{path} is {type(left).__name__} in the snapshot and "
            f"{type(right).__name__} in the live schema"
        )
    if left != right:
        return f"{path} is {left!r} in the snapshot and {right!r} in the live schema"
    return None


def _check(strict: bool) -> int:
    if not SNAPSHOT.is_file():
        print(
            f"{SNAPSHOT.name} is missing; run `python scripts/export_openapi.py`.",
            file=sys.stderr,
        )
        return 1

    live = build_document()
    live_text = render(live)
    stored_text = SNAPSHOT.read_text()
    try:
        stored = json.loads(stored_text)
    except json.JSONDecodeError as exc:
        print(f"docs/openapi-v1.json is not valid JSON: {exc}", file=sys.stderr)
        return 1

    if stored != live:
        difference = first_difference(stored, live)
        print(
            "docs/openapi-v1.json does not match the live schema: "
            f"{difference}.\n"
            "If the contract changed on purpose, update docs/API_V1.md and run "
            "`python scripts/export_openapi.py`. If only the generated document "
            "moved, check the installed FastAPI/pydantic versions with "
            '`pip install -e ".[dev]"`.',
            file=sys.stderr,
        )
        return 1

    if stored_text != live_text:
        message = (
            "docs/openapi-v1.json matches the live schema but is not in "
            "canonical form (whitespace only); run `python scripts/"
            "export_openapi.py` to normalize it."
        )
        if strict:
            print(message, file=sys.stderr)
            return 1
        print(f"note: {message}")

    print("docs/openapi-v1.json matches the live schema.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit with status 1 when the snapshot differs from the live schema.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="With --check, also fail when the file is not canonically rendered.",
    )
    arguments = parser.parse_args()

    if arguments.check:
        return _check(arguments.strict)

    rendered = render(build_document())

    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(rendered)
    print(f"Wrote {SNAPSHOT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
