#!/usr/bin/env python3
"""Audit a Vocab Coach CSV and fail when critical quality gates are missed."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path


REQUIRED = {"word", "phonetic", "pos", "meaning", "level", "level_source", "placement_eligible", "collocation", "morphology", "morphology_source", "morphology_license", "example_en", "example_zh", "example_source", "example_license"}
GENERIC_PATTERNS = {
    "meaning": re.compile(r"^(常用核心词|核心常用词|高频日常核心词|日常核心词|核心高频词)$"),
    "collocation": re.compile(r"^(use|apply|take)\s+", re.I),
    "morphology": re.compile(r"现代美语高频基础词汇|源自印欧/日耳曼/古英语核心词根演变"),
    "example_en": re.compile(r"It is (essential|practical) to (understand|master)|widely utilized across academic", re.I),
}


def audit(path: Path) -> dict:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = set(reader.fieldnames or [])
        rows = list(reader)

    words = [row.get("word", "").strip().casefold() for row in rows]
    nonempty_words = [word for word in words if word]
    result = {
        "file": str(path),
        "rows": len(rows),
        "missing_columns": sorted(REQUIRED - headers),
        "legacy_columns": sorted(headers & {"etymology", "etymology_source", "etymology_license"}),
        "empty_words": len(rows) - len(nonempty_words),
        "duplicate_words": sum(count - 1 for count in Counter(nonempty_words).values() if count > 1),
        "coverage": {},
        "generic": {},
        "fake_phonetic": 0,
        "provenance_mismatches": 0,
    }
    for field in REQUIRED - {"word"}:
        result["coverage"][field] = round(sum(bool(row.get(field, "").strip()) for row in rows) / max(1, len(rows)), 4)
    for field, pattern in GENERIC_PATTERNS.items():
        result["generic"][field] = sum(bool(pattern.search(row.get(field, ""))) for row in rows)
    result["fake_phonetic"] = sum(
        row.get("phonetic", "").strip("/[] ").casefold() == row.get("word", "").strip().casefold()
        for row in rows
    )
    result["provenance_mismatches"] = sum(
        bool(row.get("morphology", "").strip())
        != bool(row.get("morphology_source", "").strip() and row.get("morphology_license", "").strip())
        for row in rows
    )
    result["provenance_mismatches"] += sum(
        bool(row.get("example_en", "").strip() and row.get("example_zh", "").strip())
        != bool(row.get("example_source", "").strip() and row.get("example_license", "").strip())
        for row in rows
    )
    result["critical_ok"] = not result["missing_columns"] and not result["legacy_columns"] and not result["empty_words"] and not result["duplicate_words"] and not result["provenance_mismatches"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    reports = [audit(path) for path in args.files]
    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
    else:
        for report in reports:
            print(f"{report['file']}: {report['rows']} rows")
            print(f"  missing columns: {report['missing_columns'] or 'none'}")
            print(f"  legacy columns: {report['legacy_columns'] or 'none'}")
            print(f"  duplicates: {report['duplicate_words']}; fake phonetics: {report['fake_phonetic']}")
            print(f"  provenance mismatches: {report['provenance_mismatches']}")
            print(f"  coverage: {report['coverage']}")
            print(f"  generic templates: {report['generic']}")
    return 0 if all(report["critical_ok"] for report in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
