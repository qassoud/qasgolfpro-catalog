#!/usr/bin/env python3
"""Safely register new course JSON files in QasGolfPro catalog.json.

Only new or changed JSON files under courses/ are inspected. Existing catalog entries
remain in their original order; no entry is ever deleted or marked verified by this
script. New files must pass structural checks before they can be registered.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog.json"
COURSES = ROOT / "courses"


def load_json(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as f:
            value = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path.relative_to(ROOT)}: cannot read valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path.relative_to(ROOT)}: expected a JSON object")
    return value


def run_git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, text=True,
                            capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def number(value: object) -> bool:
    return type(value) in (int, float) and 0 < value < 10000


def validate_course(path: Path, countries: dict[str, str]) -> dict:
    doc = load_json(path)
    if doc.get("formatVersion") != 1 or not isinstance(doc.get("course"), dict):
        raise ValueError(f"{path}: requires formatVersion=1 and a 'course' object")
    course = doc["course"]
    code = course.get("code")
    country = course.get("countryCode")
    if not nonempty(code) or path.name != f"{code}.json":
        raise ValueError(f"{path}: course.code does not match filename")
    expected_folder = countries.get(country)
    if expected_folder is None or path.parent.name != expected_folder:
        raise ValueError(f"{path}: countryCode/folder disagree: {country!r}")
    if not nonempty(course.get("name")) or not nonempty(course.get("city")):
        raise ValueError(f"{path}: course.name and course.city are required")
    version = course.get("dataVersion")
    if type(version) is not int or version < 1:
        raise ValueError(f"{path}: dataVersion must be a positive integer")
    if type(course.get("isVerified")) is not bool:
        raise ValueError(f"{path}: isVerified must be a boolean")
    if course.get("numberOfHoles") != 18:
        raise ValueError(f"{path}: only 18-hole course files are accepted")
    holes = course.get("holes")
    if not isinstance(holes, list) or len(holes) != 18:
        raise ValueError(f"{path}: expected 18 hole objects")
    by_number = {}
    stroke_indexes = set()
    for h in holes:
        if not isinstance(h, dict):
            raise ValueError(f"{path}: invalid hole object")
        n, par, stroke = h.get("number"), h.get("par"), h.get("strokeIndex")
        if type(n) is not int or n not in range(1, 19) or n in by_number:
            raise ValueError(f"{path}: duplicate or invalid hole number {n}")
        if type(par) is not int or par not in (3, 4, 5, 6):
            raise ValueError(f"{path}: hole {n} has invalid par {par}")
        if type(stroke) is not int or stroke not in range(1, 19) or stroke in stroke_indexes:
            raise ValueError(f"{path}: hole {n} has duplicate/invalid strokeIndex {stroke}")
        if h.get("code") != f"{code}_{n:02d}":
            raise ValueError(f"{path}: hole {n} has wrong code")
        stroke_indexes.add(stroke)
        by_number[n] = par
    if sorted(by_number) != list(range(1, 19)) or sum(by_number.values()) != course.get("totalPar"):
        raise ValueError(f"{path}: missing holes or totalPar does not match hole PARs")

    tees = course.get("tees")
    if not isinstance(tees, list) or not tees:
        raise ValueError(f"{path}: no tees found")
    tee_codes = set()
    for tee in tees:
        if not isinstance(tee, dict) or not nonempty(tee.get("code")):
            raise ValueError(f"{path}: tee has no code")
        if tee["code"] in tee_codes or not tee["code"].startswith(f"{code}_"):
            raise ValueError(f"{path}: duplicate/wrong tee code {tee['code']}")
        tee_codes.add(tee["code"])
        distances = tee.get("distances")
        if not isinstance(distances, list) or len(distances) != 18:
            raise ValueError(f"{path}: tee {tee['code']} must have 18 distances")
        dist_by_hole = {}
        for dist in distances:
            if not isinstance(dist, dict):
                raise ValueError(f"{path}: tee {tee['code']} has invalid distance")
            hole_code = dist.get("holeCode")
            if hole_code in dist_by_hole or hole_code not in {f"{code}_{n:02d}" for n in range(1, 19)}:
                raise ValueError(f"{path}: tee {tee['code']} has unknown/duplicate hole {hole_code}")
            if not number(dist.get("meters")) or not number(dist.get("yards")):
                raise ValueError(f"{path}: tee {tee['code']} hole {hole_code} lacks meters/yards")
            dist_by_hole[hole_code] = dist
        if not number(tee.get("totalMeters")) or not number(tee.get("totalYards")):
            raise ValueError(f"{path}: tee {tee['code']} lacks totals")
        if abs(sum(d["meters"] for d in distances) - tee["totalMeters"]) > 1 or abs(
            sum(d["yards"] for d in distances) - tee["totalYards"]
        ) > 1:
            raise ValueError(f"{path}: tee {tee['code']} totals disagree with hole distances")
        ratings = tee.get("ratings")
        if isinstance(ratings, list) and ratings:
            for rating in ratings:
                if not isinstance(rating, dict) or rating.get("playerCategory") not in ("MEN", "WOMEN"):
                    raise ValueError(f"{path}: tee {tee['code']} has invalid rating category")
                if not number(rating.get("courseRating")) or not number(rating.get("slopeRating")):
                    raise ValueError(f"{path}: tee {tee['code']} lacks Course Rating/Slope")
                if rating["slopeRating"] > 155 or rating["slopeRating"] < 55:
                    raise ValueError(f"{path}: tee {tee['code']} has impossible Slope")
        elif not (number(tee.get("courseRating")) and number(tee.get("slope"))
                  and 55 <= tee["slope"] <= 155):
            raise ValueError(f"{path}: tee {tee['code']} requires genuine Course Rating/Slope")

    return {
        "code": code,
        "name": course["name"],
        "country": country,
        "city": course["city"],
        "file": path.relative_to(ROOT).as_posix(),
        "dataVersion": version,
        "verified": course["isVerified"],
    }


def write_preserving_existing_format(original: str, current: dict,
                                     added: list[dict], version_changes: dict[str, int]) -> None:
    """Apply only targeted edits, keeping all unrelated catalog bytes untouched."""
    marker = re.search(r'"courses"\s*:\s*\[', original)
    if marker is None:
        raise ValueError("catalog.json: could not locate the courses array")
    start = marker.end() - 1
    parsed, end = json.JSONDecoder().raw_decode(original, start)
    if not isinstance(parsed, list):
        raise ValueError("catalog.json: courses must be an array")

    # Locate existing entries by decoding each object inside the array.
    edits: list[tuple[int, int, str]] = []
    index = start + 1
    decoder = json.JSONDecoder()
    while index < end - 1:
        while index < end - 1 and original[index] in ' \t\r\n,':
            index += 1
        if index >= end - 1:
            break
        obj, obj_end = decoder.raw_decode(original, index)
        if isinstance(obj, dict) and obj.get("code") in version_changes:
            span = original[index:obj_end]
            hits = list(re.finditer(r'"dataVersion"\s*:\s*(\d+)', span))
            if len(hits) != 1:
                raise ValueError(f"catalog.json: missing/ambiguous dataVersion for {obj['code']}")
            hit = hits[0]
            edits.append((index + hit.start(1), index + hit.end(1),
                          str(version_changes[obj['code']])))
        index = obj_end

    for first, last, replacement in sorted(edits, reverse=True):
        original = original[:first] + replacement + original[last:]

    if added:
        marker = re.search(r'"courses"\s*:\s*\[', original)
        start = marker.end() - 1
        _, end = json.JSONDecoder().raw_decode(original, start)
        closing = end - 1
        before = original[:closing]
        without_space = before.rstrip()
        trailing_space = before[len(without_space):]
        added_lines = []
        for entry in added:
            formatted = json.dumps(entry, ensure_ascii=False, indent=2)
            added_lines.append('    ' + formatted.replace('\n', '\n    '))
        insert = (',' if parsed else '') + '\n' + ',\n'.join(added_lines)
        original = without_space + insert + trailing_space + original[closing:]

    # Prove that textual patching produced exactly the validated in-memory catalog.
    if json.loads(original) != current:
        raise ValueError("Safety check failed: catalog patch does not match intended data")
    CATALOG.write_text(original, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", help="Commit before the current push; optional for manual scan")
    parser.add_argument("--dry-run", action="store_true", help="Check without writing catalog.json")
    args = parser.parse_args()

    original_content = CATALOG.read_text(encoding="utf-8")
    catalog = load_json(CATALOG)
    entries, countries_list = catalog.get("courses"), catalog.get("countries")
    if not isinstance(entries, list) or not isinstance(countries_list, list):
        raise ValueError("catalog.json: expected 'courses' and 'countries' lists")
    countries = {x["code"]: x["folder"] for x in countries_list}
    by_code, by_path = {}, {}
    for e in entries:
        if not isinstance(e, dict) or not nonempty(e.get("code")) or not nonempty(e.get("file")):
            raise ValueError("catalog.json: invalid existing entry")
        if e["code"] in by_code or e["file"] in by_path:
            raise ValueError(f"catalog.json: duplicate course code/path: {e['code']}")
        by_code[e["code"]] = e
        by_path[e["file"]] = e

    candidate_paths = set()
    if args.before and set(args.before) != {"0"}:
        changes = run_git("diff", "--name-only", "--diff-filter=ACMRT",
                          args.before, "HEAD", "--", "courses/")
        candidate_paths.update(ROOT / name for name in changes.splitlines()
                               if name.endswith(".json"))
    # On a manual run, also find new files not already indexed in catalog.json.
    for p in COURSES.rglob("*.json"):
        if p.relative_to(ROOT).as_posix() not in by_path:
            candidate_paths.add(p)

    updated = False
    added_entries: list[dict] = []
    version_changes: dict[str, int] = {}
    for path in sorted(candidate_paths):
        if not path.is_file():
            continue  # Deleted files remain indexed and will be reported by validate_catalog.py.
        entry = validate_course(path, countries)
        code = entry["code"]
        old = by_code.get(code)
        if old is None:
            if entry["file"] in by_path:
                raise ValueError(f"{entry['file']}: path already registered to another code")
            entries.append(entry)  # Never reorder or replace existing entries.
            added_entries.append(entry)
            by_code[code] = entry
            by_path[entry["file"]] = entry
            updated = True
            print(f"[ADDED] {code}: version {entry['dataVersion']}")
            continue
        if old["file"] != entry["file"]:
            raise ValueError(f"{code}: existing path {old['file']} differs from {entry['file']}")
        if old.get("country") != entry["country"]:
            raise ValueError(f"{code}: country changed; requires manual review")
        existing_version = old.get("dataVersion")
        if type(existing_version) is not int or entry["dataVersion"] < existing_version:
            raise ValueError(f"{code}: dataVersion must not decrease")
        if entry["dataVersion"] > existing_version:
            old["dataVersion"] = entry["dataVersion"]
            version_changes[code] = entry["dataVersion"]
            updated = True
            print(f"[VERSION] {code}: {existing_version} -> {entry['dataVersion']}")
        # Intentionally preserve existing name, city and verified flag; changes
        # to these published metadata fields require an explicit review.

    if updated and not args.dry_run:
        write_preserving_existing_format(original_content, catalog, added_entries, version_changes)
        print("[SAVED] catalog.json")
    else:
        print("[NO WRITE] No changes needed or dry-run enabled")
    print(f"Catalog entries: {len(entries)}")


if __name__ == "__main__":
    main()
