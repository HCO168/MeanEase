#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

DEFAULT_INPUT = Path('us_core_7000_authentic.csv')
DEFAULT_CANDIDATES = Path('tmp/morphology-luna/candidates.jsonl')
DEFAULT_SOURCE = 'https://developers.openai.com/api/docs/models/gpt-5.6-luna'
DEFAULT_LICENSE = 'HCONET project content; AI-assisted with OpenAI GPT-5.6 Luna Batch'


def load_candidates(path: Path) -> dict[str, dict]:
    result: dict[str, dict] = {}
    with path.open(encoding='utf-8') as handle:
        for line in handle:
            if not line.strip():
                continue
            item = json.loads(line)
            key = str(item.get('word', '')).casefold()
            if not key or key in result:
                raise ValueError(f'duplicate or empty candidate word: {item.get("word")!r}')
            result[key] = item
    return result


def accepted(item: dict) -> bool:
    return (
        item.get('status') == 'ok'
        and item.get('confidence') == 'high'
        and not item.get('issues')
        and not item.get('warnings')
        and bool(str(item.get('note', '')).strip())
    )


def main() -> int:
    parser = argparse.ArgumentParser(description='Apply reviewed-safe morphology candidates to a vocabulary CSV.')
    parser.add_argument('--input', type=Path, default=DEFAULT_INPUT)
    parser.add_argument('--candidates', type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source', default=DEFAULT_SOURCE)
    parser.add_argument('--license', dest='license_text', default=DEFAULT_LICENSE)
    parser.add_argument('--expected-accepted', type=int)
    args = parser.parse_args()

    candidates = load_candidates(args.candidates)
    with args.input.open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        rows = list(reader)
    if not fieldnames:
        raise ValueError('input CSV has no header')
    required = {'word', 'morphology', 'morphology_source', 'morphology_license'}
    if not required.issubset(fieldnames):
        raise ValueError(f'missing required columns: {sorted(required - set(fieldnames))}')

    selected = {word: item for word, item in candidates.items() if accepted(item)}
    if args.expected_accepted is not None and len(selected) != args.expected_accepted:
        raise ValueError(f'accepted count mismatch: {len(selected)} != {args.expected_accepted}')

    input_words = {row['word'].casefold() for row in rows}
    missing = sorted(set(selected) - input_words)
    if missing:
        raise ValueError(f'accepted candidates missing from input CSV: {missing[:10]}')

    changed = 0
    for row in rows:
        item = selected.get(row['word'].casefold())
        if not item:
            continue
        if row['morphology'].strip() or row['morphology_source'].strip() or row['morphology_license'].strip():
            raise ValueError(f'refusing to overwrite existing morphology data for {row["word"]}')
        row['morphology'] = str(item['note']).strip()
        row['morphology_source'] = args.source
        row['morphology_license'] = args.license_text
        changed += 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator='\r\n')
        writer.writeheader()
        writer.writerows(rows)

    print(json.dumps({
        'input_rows': len(rows),
        'candidate_rows': len(candidates),
        'accepted_rows': len(selected),
        'written_rows': changed,
        'output': str(args.output),
        'source': args.source,
        'license': args.license_text,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
