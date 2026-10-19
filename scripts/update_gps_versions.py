# !/usr/bin/env python3
"""Update gps/versions.json after GPS geometry changes on GitHub."""

import argparse
import json
import math
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GPS_DIR = ROOT / "gps"
VERSIONS_PATH = GPS_DIR / "versions.json"


def git(*args):
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Git command failed")
    return result.stdout


def read_json(path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def check_point(point, label):
    if not isinstance(point, dict):
        raise ValueError(f"{label}: expected a coordinate object")
    x, y = point.get("x"), point.get("y")
    if (
        isinstance(x, bool) or isinstance(y, bool)
        or not isinstance(x, (int, float))
        or not isinstance(y, (int, float))
        or not math.isfinite(x) or not math.isfinite(y)
        or not -180 <= x <= 180 or not -90 <= y <= 90
    ):
        raise ValueError(f"{label}: invalid GPS coordinates")
    return {"x": x, "y": y}


def geometry(data, label):
    if not isinstance(data, dict) or data.get("formatVersion") != 1:
        raise ValueError(f"{label}: invalid GPS formatVersion")
    center = check_point(data.get("courseCenter"), f"{label} center")
    holes = data.get("holes")
    if not isinstance(holes, list) or len(holes) != 18:
        raise ValueError(f"{label}: expected exactly 18 holes")
    coordinates = []
    numbers = []
    for hole in holes:
        if not isinstance(hole, dict):
            raise ValueError(f"{label}: invalid hole")
        number = hole.get("number")
        if type(number) is not int or number not in range(1, 19):
            raise ValueError(f"{label}: invalid hole number {number}")
        numbers.append(number)
        controls = hole.get("controlPoints", [])
        if not isinstance(controls, list):
            raise ValueError(f"{label} hole {number}: invalid controlPoints")
        coordinates.append({
            "number": number,
            "tee": check_point(hole.get("tee"), f"{label} hole {number} tee"),
            "controlPoints": [
                check_point(p, f"{label} hole {number} controlPoints")
                for p in controls
            ],
            "green": check_point(hole.get("green"), f"{label} hole {number} green"),
        })
    if sorted(numbers) != list(range(1, 19)):
        raise ValueError(f"{label}: hole numbers are not unique 1-18")
    coordinates.sort(key=lambda hole: hole["number"])
    return {"courseCenter": center, "holes": coordinates}


def previous_json(revision, path):
    if set(revision) == {"0"}:
        return None
    result = subprocess.run(
        ["git", "show", f"{revision}:{path}"],
        cwd=ROOT, capture_output=True, text=True
    )
    if result.returncode:
        return None  # The file did not exist before this push.
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", required=True, help="Previous Git commit SHA")
    args = parser.parse_args()

    registry = read_json(VERSIONS_PATH)
    if registry.get("formatVersion") != 1 or not isinstance(registry.get("gps"), dict):
        raise ValueError("gps/versions.json: invalid format")
    versions = registry["gps"]
    for code, version in versions.items():
        if not isinstance(code, str) or type(version) is not int or version < 1:
            raise ValueError(f"Invalid GPS version for {code}")

    modified = set()
    if set(args.before) != {"0"}:
        modified = set(git(
            "diff", "--name-only", "--diff-filter=ACMRT",
            args.before, "HEAD", "--", "gps/"
        ).splitlines())

    changed = False
    seen = set()
    for path in sorted(GPS_DIR.glob("*/*_GPS.json")):
        relative = path.relative_to(ROOT).as_posix()
        data = read_json(path)
        code = data.get("courseCode")
        if not isinstance(code, str) or path.name != f"{code}_GPS.json":
            raise ValueError(f"{relative}: courseCode differs from filename")
        if code in seen:
            raise ValueError(f"Duplicate GPS courseCode: {code}")
        seen.add(code)
        current_geometry = geometry(data, relative)

        if code not in versions:
            versions[code] = 1
            changed = True
            print(f"[NEW] {code}: version 1")
        elif relative in modified:
            old = previous_json(args.before, relative)
            if old is not None and geometry(old, relative) != current_geometry:
                versions[code] += 1
                changed = True
                print(f"[UPDATED] {code}: version {versions[code]}")
            else:
                print(f"[UNCHANGED GPS] {code}: version {versions[code]}")

    if changed:
        VERSIONS_PATH.write_text(
            json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print("gps/versions.json updated")
    else:
        print("No GPS version change needed")


if __name__ == "__main__":
    main()
