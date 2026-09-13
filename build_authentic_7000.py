#!/usr/bin/env python3
"""Build an honest 20,000-word study deck from ECDICT.

The script keeps the order of the supplied core-word list, downloads ECDICT's
UTF-8 CSV, and replaces only fields that ECDICT actually provides.  It does
not invent collocations, etymologies, or example sentences.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import urllib.request
from pathlib import Path


ECDICT_URL = "https://raw.githubusercontent.com/skywind3000/ECDICT/master/ecdict.csv"
FIELDS = [
    "word",
    "base_word",
    "phonetic",
    "pos",
    "meaning",
    "level",
    "collocation",
    "morphology",
    "morphology_source",
    "morphology_license",
    "example_en",
    "example_zh",
    "example_source",
    "example_license",
]


def clean_text(value: str) -> str:
    decoded = value.replace("\\r", "").replace("\\n", "\n").replace("\r", "")
    parts = [part.strip() for part in decoded.split("\n") if part.strip()]
    general = [part for part in parts if not re.match(r"^(?:[a-z.]+\s+)?\[[^]]+\]", part, re.IGNORECASE)]
    if general:
        parts = general
    return "；".join(parts[:5])


def normalize_pos(raw_pos: str, translation: str) -> str:
    """Prefer explicit dictionary labels; never guess verb transitivity."""
    explicit = []
    for tag in ("vt.", "vi.", "v.", "n.", "adj.", "adv.", "prep.", "conj.", "pron.", "art.", "num.", "int."):
        if re.search(rf"(?<![A-Za-z]){re.escape(tag)}", translation, re.IGNORECASE):
            explicit.append(tag)
    if explicit:
        return "/".join(dict.fromkeys(explicit))

    mapped = []
    for item in raw_pos.split("/"):
        key = item.split(":", 1)[0].strip().lower()
        label = {
            "n": "n.",
            "v": "v.",
            "a": "adj.",
            "j": "adj.",
            "r": "adv.",
            "adv": "adv.",
            "p": "prep.",
            "c": "conj.",
            "u": "num.",
        }.get(key)
        if label and label not in mapped:
            mapped.append(label)
    return "/".join(mapped)


def extract_base_word(word: str, exchange: str) -> str:
    match = re.search(r"(?:^|/)0:([^/]+)", exchange or "")
    return match.group(1).strip().casefold() if match else word.casefold()


def load_target_words(path: Path, limit: int) -> list[str]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = csv.DictReader(handle)
        words = [row.get("word", "").strip() for row in rows]
    result = []
    seen = set()
    for word in words:
        key = word.casefold()
        if word and key not in seen:
            seen.add(key)
            result.append(word)
        if len(result) == limit:
            break
    return result


def read_ecdict(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": "vocab-coach-builder/1.0"})
    with urllib.request.urlopen(request, timeout=90) as response:
        stream = io.TextIOWrapper(response, encoding="utf-8-sig", newline="")
        yield from csv.DictReader(stream)


def fetch_targets(url: str, wanted: set[str]) -> dict[str, dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for row in read_ecdict(url):
        key = row.get("word", "").strip().casefold()
        if key in wanted:
            found[key] = row
            if len(found) == len(wanted):
                break
    return found


def frequency_ranked_rows(url: str, limit: int) -> list[dict[str, str]]:
    """Select actual dictionary words by ECDICT's contemporary frequency rank."""
    candidates = []
    word_pattern = re.compile(r"^[A-Za-z]+(?:[-'][A-Za-z]+)?$")
    for row in read_ecdict(url):
        word = row.get("word", "").strip()
        translation = row.get("translation", "").strip()
        try:
            rank = int(row.get("frq", ""))
        except (TypeError, ValueError):
            continue
        if rank > 0 and translation and word_pattern.fullmatch(word):
            candidates.append((rank, word.casefold(), row))
    candidates.sort(key=lambda item: (item[0], item[1]))
    selected = []
    seen = set()
    for _, key, row in candidates:
        if key not in seen:
            seen.add(key)
            selected.append(row)
        if len(selected) == limit:
            break
    return selected


def build(input_path: Path | None, output_path: Path, limit: int, url: str) -> tuple[int, int]:
    if input_path:
        words = load_target_words(input_path, limit)
        if not words:
            raise ValueError(f"No words found in {input_path}")
        print(f"Reading ECDICT for {len(words)} supplied target words...", flush=True)
        records = fetch_targets(url, {word.casefold() for word in words})
        sources = [(word, records.get(word.casefold())) for word in words]
    else:
        print(f"Selecting the top {limit} entries by ECDICT frequency rank...", flush=True)
        ranked = frequency_ranked_rows(url, limit)
        sources = [(row["word"].strip().casefold(), row) for row in ranked]

    matched = 0
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for word, source in sources:
            if source:
                matched += 1
                phonetic = source.get("phonetic", "").strip()
                translation = clean_text(source.get("translation", ""))
                pos = normalize_pos(source.get("pos", ""), translation)
                base_word = extract_base_word(word, source.get("exchange", ""))
            else:
                phonetic = translation = pos = ""
                base_word = word.casefold()
            writer.writerow(
                {
                    "word": word,
                    "base_word": base_word,
                    "phonetic": f"/{phonetic.strip('/[] ')}/" if phonetic else "",
                    "pos": pos,
                    "meaning": translation,
                    "level": "",
                    "collocation": "",
                    "morphology": "",
                    "morphology_source": "",
                    "morphology_license": "",
                    "example_en": "",
                    "example_zh": "",
                    "example_source": "",
                    "example_license": "",
                }
            )
    return len(sources), matched


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Optional CSV whose word order should be preserved")
    parser.add_argument("--output", type=Path, default=Path("us_core_7000_authentic.csv"))
    parser.add_argument("--limit", type=int, default=20000)
    parser.add_argument("--url", default=ECDICT_URL, help="ECDICT CSV URL or file URL")
    args = parser.parse_args()

    if args.input and not args.input.is_file():
        print(f"Input file not found: {args.input}", file=sys.stderr)
        return 2
    try:
        total, matched = build(args.input, args.output, args.limit, args.url)
    except Exception as exc:
        print(f"Build failed: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {total} rows to {args.output}; ECDICT matched {matched} ({matched / total:.1%}).")
    print("Unverified collocations, morphology notes, and examples were intentionally left blank.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
