#!/usr/bin/env python3
"""Audit a Vocab Coach CSV and fail when critical quality gates are missed."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

from morphology_review_pipeline import audit_rows as audit_morphology_rows


REQUIRED = {"word", "phonetic", "pos", "meaning", "level", "level_source", "placement_eligible", "collocation", "etymology", "etymology_source", "etymology_license", "example_en", "example_zh", "example_source", "example_license"}
GENERIC_PATTERNS = {
    "meaning": re.compile(r"^(常用核心词|核心常用词|高频日常核心词|日常核心词|核心高频词)$"),
    "collocation": re.compile(r"^(use|apply|take)\s+", re.I),
    "etymology": re.compile(r"现代美语高频基础词汇|源自印欧/日耳曼/古英语核心词根演变"),
    "example_en": re.compile(r"It is (essential|practical) to (understand|master)|widely utilized across academic", re.I),
}


def audit(path: Path, *, strict_morphology: bool = False) -> dict:
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
        "empty_words": len(rows) - len(nonempty_words),
        "duplicate_words": sum(count - 1 for count in Counter(nonempty_words).values() if count > 1),
        "coverage": {},
        "generic": {},
        "fake_phonetic": 0,
        "provenance_mismatches": 0,
        "morphology": audit_morphology_rows(rows),
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
        bool(row.get("etymology", "").strip())
        != bool(row.get("etymology_source", "").strip() and row.get("etymology_license", "").strip())
        for row in rows
    )
    result["provenance_mismatches"] += sum(
        bool(row.get("example_en", "").strip() and row.get("example_zh", "").strip())
        != bool(row.get("example_source", "").strip() and row.get("example_license", "").strip())
        for row in rows
    )
    result["critical_ok"] = not result["missing_columns"] and not result["empty_words"] and not result["duplicate_words"] and not result["provenance_mismatches"]
    if strict_morphology:
        result["critical_ok"] = result["critical_ok"] and not result["morphology"]["format_invalid_count"] and not result["morphology"]["formula_risk_count"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict-morphology", action="store_true", help="将构词格式与公式风险作为阻断项")
    args = parser.parse_args()
    reports = [audit(path, strict_morphology=args.strict_morphology) for path in args.files]
    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
    else:
        for report in reports:
            print(f"{report['file']}: {report['rows']} rows")
            print(f"  missing columns: {report['missing_columns'] or 'none'}")
            print(f"  duplicates: {report['duplicate_words']}; fake phonetics: {report['fake_phonetic']}")
            print(f"  provenance mismatches: {report['provenance_mismatches']}")
            morphology = report["morphology"]
            print(
                "  morphology: "
                f"formation={morphology['formation_count']}; origin={morphology['origin_count']}; "
                f"empty={morphology['empty_count']}; invalid={morphology['format_invalid_count']}"
            )
            print(f"  coverage: {report['coverage']}")
            print(f"  generic templates: {report['generic']}")
    return 0 if all(report["critical_ok"] for report in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
