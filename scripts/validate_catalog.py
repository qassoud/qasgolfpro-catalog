#!/usr/bin/env python3
"""Validate catalog.json against the course JSON files in this repository."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "catalog.json"
COURSES_DIR = ROOT / "courses"


def display(value: Any) -> str:
    return str(value) if value not in (None, "") else "<missing>"


def main() -> int:
    errors: list[str] = []

    try:
        with CATALOG_PATH.open(encoding="utf-8") as catalog_file:
            catalog = json.load(catalog_file)
    except FileNotFoundError:
        print("[ERROR] catalog.json: file is missing.", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(
            f"[ERROR] catalog.json:{exc.lineno}:{exc.colno}: invalid JSON: {exc.msg}",
            file=sys.stderr,
        )
        return 1

    if not isinstance(catalog, dict):
        print("[ERROR] catalog.json: root value must be a JSON object.", file=sys.stderr)
        return 1

    entries = catalog.get("courses")
    if not isinstance(entries, list):
        print("[ERROR] catalog.json: 'courses' must be an array.", file=sys.stderr)
        return 1

    codes: dict[str, list[str]] = defaultdict(list)
    referenced_paths: set[str] = set()

    for index, entry in enumerate(entries):
        label = f"catalog.json courses[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"[INVALID] {label}: expected an object.")
            continue

        code_value = entry.get("code")
        code = code_value if isinstance(code_value, str) and code_value.strip() else None
        file_value = entry.get("file")
        file_path = file_value if isinstance(file_value, str) and file_value.strip() else None

        if code is None:
            errors.append(f"[INVALID] {label}: code=<missing> has no non-empty string 'code'.")
        if file_path is None:
            errors.append(
                f"[INVALID] code={display(code)} path=<missing>: no non-empty string 'file' in {label}."
            )
            continue

        normalized = Path(file_path)
        if normalized.is_absolute() or ".." in normalized.parts:
            errors.append(
                f"[INVALID] code={display(code)} path={file_path!r}: file path must stay inside the repository."
            )
            continue

        normalized_path = normalized.as_posix()
        referenced_paths.add(normalized_path)

        if code is not None:
            codes[code].append(normalized_path)

        target = ROOT / normalized
        if not target.is_file():
            errors.append(
                f"[MISSING] code={display(code)} path={normalized_path}: referenced file does not exist."
            )

    for code, paths in sorted(codes.items()):
        if len(paths) > 1:
            errors.append(
                f"[DUPLICATE] code={code}: appears {len(paths)} times at paths: "
                + ", ".join(paths)
                + "."
            )

    if COURSES_DIR.exists():
        json_files = {
            path.relative_to(ROOT).as_posix()
            for path in COURSES_DIR.rglob("*.json")
            if path.is_file()
        }
    else:
        json_files = set()
        errors.append("[MISSING] path=courses/: course directory does not exist.")

    for orphan in sorted(json_files - referenced_paths):
        orphan_path = ROOT / orphan
        try:
            with orphan_path.open(encoding="utf-8") as orphan_file:
                orphan_data = json.load(orphan_file)
            orphan_code = (
                orphan_data.get("code")
                if isinstance(orphan_data, dict)
                else None
            )
        except (OSError, json.JSONDecodeError):
            orphan_code = None
        errors.append(
            f"[ORPHAN] catalog_code=<none> file_code={display(orphan_code)} "
            f"path={orphan}: JSON file is not referenced by catalog.json."
        )

    if errors:
        print("Catalog validation failed:", file=sys.stderr)
        for error in errors:
            print(f" - {error}", file=sys.stderr)
        return 1

    print(
        f"Catalog validation passed: {len(entries)} catalog entries, "
        f"{len(json_files)} course JSON files, unique codes and no orphans."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
