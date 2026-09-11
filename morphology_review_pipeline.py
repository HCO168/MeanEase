#!/usr/bin/env python3
"""Prepare, validate, and merge auditable Chinese morphology review batches.

Reviewers work on JSONL batches instead of directly editing the production CSV.
This program never generates a word-formation explanation. It only carries
manual reviewer output, checks its source contract, and writes a new CSV after
the entire selected batch has passed validation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import urllib.parse
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


ENGRA_SOURCE = "https://github.com/eslsoft/engra"
ENGRA_LICENSE = "MIT"
WIKTIONARY_SOURCE_PREFIX = "https://en.wiktionary.org/wiki/"
WIKTIONARY_LICENSE = "CC BY-SA 4.0"
REVIEW_STATUSES = {"accepted", "uncertain", "not_decomposable", "needs_review"}
INFLECTIONAL_ENDINGS = {"s", "es", "ed", "ing"}
LANGUAGE_LABELS = {
    "原始印欧语", "原始西日耳曼语", "原始日耳曼语", "中古英语", "古英语", "晚期拉丁语",
    "中世纪拉丁语", "通俗拉丁语", "拉丁语", "古希腊语", "希腊语", "古法语", "中古法语",
    "法语", "古诺斯语", "意大利语", "西班牙语", "德语", "荷兰语", "阿拉伯语", "梵语",
    "英语", "日语", "汉语",
}
SOURCE_TYPE_LABELS = {"人名", "地名", "专名"}
HAN_RE = re.compile(r"[\u4e00-\u9fff]")
WORD_RE = re.compile(r"^[A-Za-z][A-Za-z'-]*$")
MORPHEME_RE = re.compile(r"^[a-z]+$")
FORM_HEAD_RE = re.compile(r"^([A-Za-z][A-Za-z'-]*) / ([a-z]+(?:-[a-z]+)+)；(.+)$")
ORIGIN_RE = re.compile(r"^([A-Za-z][A-Za-z'-]*)：(.+)；今义：(.+)。$")
SHORTENING_RE = re.compile(r"^(缩写自|截短自) (.+)$")
SHORTENING_TERM_RE = re.compile(r"^[A-Za-z][A-Za-z' -]{0,80}$")


class ReviewError(ValueError):
    """An input, batch, or review record violates the fail-closed contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def word_key(word: str) -> str:
    return word.strip().casefold()


def has_han(text: str) -> bool:
    return bool(HAN_RE.search(text))


def has_unsafe_cell_prefix(value: str) -> bool:
    return value.startswith(("=", "+", "-", "@"))


def canonical_wiktionary_source(word: str) -> str:
    return WIKTIONARY_SOURCE_PREFIX + urllib.parse.quote(word.replace(" ", "_"), safe="-_()'")


def is_allowed_manual_source(word: str, source: str, licence: str) -> bool:
    return (source == ENGRA_SOURCE and licence == ENGRA_LICENSE) or (
        source == canonical_wiktionary_source(word) and licence == WIKTIONARY_LICENSE
    )


def is_supported_source_label(label: str) -> bool:
    return label in LANGUAGE_LABELS | SOURCE_TYPE_LABELS or bool(re.fullmatch(r"[\u4e00-\u9fff·-]+语", label))


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    required = {"word", "meaning", "etymology", "etymology_source", "etymology_license"}
    missing = sorted(required - set(fields))
    if missing:
        raise ReviewError(f"CSV 缺少字段：{', '.join(missing)}")
    keys = [word_key(row.get("word", "")) for row in rows]
    if not all(keys):
        raise ReviewError("CSV 含空 word，不能建立审校批次")
    duplicates = [key for key, count in Counter(keys).items() if count > 1]
    if duplicates:
        raise ReviewError(f"CSV 含重复 word：{', '.join(duplicates[:5])}")
    return rows, fields


def write_csv_atomically(path: Path, fields: list[str], rows: Iterable[dict[str, str]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise")
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _validate_formation(word: str, note: str) -> list[str]:
    match = FORM_HEAD_RE.fullmatch(note)
    if not match:
        return ["构词短注必须是“word / prefix-root-suffix；…；word：中文释义。”格式"]
    note_word, decomposition, remainder = match.groups()
    if word_key(note_word) != word_key(word):
        return ["构词短注开头的单词与 CSV word 不一致"]
    parts = decomposition.split("-")
    if len(parts) < 2 or any(not MORPHEME_RE.fullmatch(part) for part in parts):
        return ["构词拆分至少要有两个小写字母词素"]
    if "".join(parts) != word_key(word):
        return ["构词拆分拼接后必须与 word 完全一致；拼写变化要转为词源摘要或人工复核"]
    if any(part in INFLECTIONAL_ENDINGS for part in parts):
        return ["不能把 -s、-es、-ed、-ing 这类屈折变化作为构词后缀"]
    segments = remainder.split("；")
    if len(segments) < len(set(parts)) + 1:
        return ["每个词素和完整单词都必须有中文解释"]
    glosses: dict[str, str] = {}
    final_gloss = ""
    for segment in segments:
        if "：" not in segment:
            return ["构词短注的每一段都必须包含中文冒号"]
        label, gloss = (piece.strip() for piece in segment.split("：", 1))
        normalized_label = label.strip("-").casefold()
        if word_key(label) == word_key(word):
            final_gloss = gloss
        else:
            glosses[normalized_label] = gloss
        if not has_han(gloss):
            return [f"“{label}”缺少中文解释"]
    missing = [part for part in set(parts) if part not in glosses]
    if missing:
        return [f"以下词素缺少解释：{', '.join(missing)}"]
    if not final_gloss or not has_han(final_gloss):
        return ["完整单词必须有中文释义"]
    return []


def _validate_origin(word: str, note: str) -> list[str]:
    match = ORIGIN_RE.fullmatch(note)
    if not match:
        return ["词源摘要必须以“word：”开头、以“；今义：中文释义。”结尾"]
    note_word, body, meaning = match.groups()
    body = body.strip()
    if word_key(note_word) != word_key(word):
        return ["词源摘要开头的单词与 CSV word 不一致"]
    if not has_han(meaning):
        return ["词源摘要的今义缺少中文释义"]
    if any(marker in body for marker in ("可能", "大概", "推测", "不确定")):
        return ["词源摘要不能以猜测性措辞替代人工核对"]
    shortening = SHORTENING_RE.fullmatch(body)
    if shortening:
        _action, source_word = shortening.groups()
        if not SHORTENING_TERM_RE.fullmatch(source_word.strip()):
            return ["缩写/截短摘要必须有英文原词"]
        return []
    if body.startswith("英语缩写") and any(character.isalpha() for character in body):
        return []
    source_position = body.find("源自")
    if source_position >= 0:
        chain = body[source_position + len("源自"):]
        nodes = chain.split("，可追溯至")
        if not 1 <= len(nodes) <= 2:
            return ["词源链只能保留一到两个来源节点"]
        seen_pairs: set[tuple[str, str]] = set()
        seen_terms: set[str] = set()
        for node in nodes:
            node_match = re.fullmatch(r"([^ ]+) (.+)", node.strip())
            if not node_match:
                return ["每个词源节点必须写成“语言 词项”"]
            language, term = node_match.groups()
            term = term.strip()
            if not is_supported_source_label(language):
                return [f"不受支持的词源语言标签：{language}"]
            if not term or not any(character.isalpha() for character in term):
                return ["词源节点缺少原语言词项"]
            pair = (language, term.casefold())
            if pair in seen_pairs or term.casefold() in seen_terms:
                return ["词源链不能重复同一词项"]
            seen_pairs.add(pair)
            seen_terms.add(term.casefold())
        return []
    if (body.startswith("借自") and any(character.isalpha() for character in body)) or (
        body.startswith("由") and (
            "构成" in body or "组合而来" in body or "发展而来" in body or "进入英语" in body
        )
    ):
        return []
    return ["词源摘要必须说明可核对的来源、借入关系、缩写关系或组合关系"]


def validate_etymology(word: str, note: str, source: str, licence: str) -> list[str]:
    """Return validation errors; an empty list means the row is safe to publish."""
    note, source, licence = note.strip(), source.strip(), licence.strip()
    if not note:
        return [] if not source and not licence else ["空构词说明必须同时清空来源和许可证"]
    if not WORD_RE.fullmatch(word.strip()):
        return ["word 不是受支持的英文单词形式"]
    if has_unsafe_cell_prefix(note):
        return ["构词说明不能以电子表格公式前缀开头"]
    if source == ENGRA_SOURCE and licence == ENGRA_LICENSE:
        return _validate_formation(word, note)
    if source.startswith(WIKTIONARY_SOURCE_PREFIX) and licence == WIKTIONARY_LICENSE:
        return _validate_formation(word, note) if " / " in note else _validate_origin(word, note)
    return ["非空构词说明必须使用受支持的来源和许可证组合"]


def audit_rows(rows: Iterable[dict[str, str]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    invalid_examples: list[dict[str, Any]] = []
    formula_risks = 0
    total = 0
    for row in rows:
        total += 1
        word = row.get("word", "").strip()
        note = row.get("etymology", "").strip()
        source = row.get("etymology_source", "").strip()
        licence = row.get("etymology_license", "").strip()
        if any(has_unsafe_cell_prefix(str(value).strip()) for value in row.values() if value):
            formula_risks += 1
        if not note:
            counts["empty"] += 1
            errors = validate_etymology(word, note, source, licence)
        elif source == ENGRA_SOURCE and licence == ENGRA_LICENSE:
            counts["formation"] += 1
            errors = validate_etymology(word, note, source, licence)
        elif source.startswith(WIKTIONARY_SOURCE_PREFIX) and licence == WIKTIONARY_LICENSE:
            counts["origin"] += 1
            errors = validate_etymology(word, note, source, licence)
        else:
            counts["unsupported_provenance"] += 1
            errors = validate_etymology(word, note, source, licence)
        if errors and len(invalid_examples) < 20:
            invalid_examples.append({"word": word, "errors": errors})
        if errors:
            counts["invalid"] += 1
    return {
        "rows": total,
        "formation_count": counts["formation"],
        "origin_count": counts["origin"],
        "empty_count": counts["empty"],
        "unsupported_provenance_count": counts["unsupported_provenance"],
        "format_invalid_count": counts["invalid"],
        "formula_risk_count": formula_risks,
        "coverage": round((total - counts["empty"]) / total, 4) if total else 0.0,
        "invalid_examples": invalid_examples,
    }


def batch_record(batch_id: str, row: dict[str, str]) -> dict[str, str]:
    return {
        "batch_id": batch_id,
        "word_key": word_key(row.get("word", "")),
        "word": row.get("word", "").strip(),
        "base_word": row.get("base_word", "").strip(),
        "meaning": row.get("meaning", "").strip(),
        "existing_note": row.get("etymology", "").strip(),
        "existing_source": row.get("etymology_source", "").strip(),
        "existing_license": row.get("etymology_license", "").strip(),
    }


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def prepare_batches(input_path: Path, output_dir: Path, batch_size: int) -> dict[str, Any]:
    if batch_size < 1 or batch_size > 300:
        raise ReviewError("batch-size 必须在 1 到 300 之间")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ReviewError(f"批次目录不是空目录：{output_dir}")
    rows, _fields = read_csv(input_path)
    snapshot = sha256_file(input_path)
    batches_dir = output_dir / "batches"
    batches_dir.mkdir(parents=True)
    batches = []
    for index, start in enumerate(range(0, len(rows), batch_size), start=1):
        end = min(start + batch_size, len(rows))
        batch_id = f"{snapshot[:12]}-{index:04d}"
        filename = f"{batch_id}.jsonl"
        write_jsonl(batches_dir / filename, (batch_record(batch_id, row) for row in rows[start:end]))
        batches.append({"id": batch_id, "file": f"batches/{filename}", "start": start, "end": end, "count": end - start})
    manifest = {
        "schema": 1,
        "input_file": input_path.name,
        "input_sha256": snapshot,
        "row_count": len(rows),
        "batch_size": batch_size,
        "batches": batches,
    }
    (output_dir / "responses").mkdir()
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ReviewError(f"{path}:{line_number} 不是 JSON：{exc.msg}") from exc
        if not isinstance(record, dict):
            raise ReviewError(f"{path}:{line_number} 必须是 JSON 对象")
        records.append(record)
    return records


def _check_response_record(record: dict[str, Any], expected: dict[str, str]) -> None:
    required = {
        "batch_id", "word_key", "word", "status", "note", "source_basis", "source_license",
        "evidence_summary", "review_flags",
    }
    missing = sorted(required - set(record))
    if missing:
        raise ReviewError(f"审校记录缺少字段：{', '.join(missing)}")
    if record["batch_id"] != expected["batch_id"]:
        raise ReviewError(f"{expected['word']} 的 batch_id 不正确")
    if record["word_key"] != expected["word_key"] or word_key(str(record["word"])) != expected["word_key"]:
        raise ReviewError(f"审校记录单词不匹配：{record.get('word')!r}")
    if record["status"] not in REVIEW_STATUSES:
        raise ReviewError(f"{expected['word']} 的 status 不受支持：{record['status']!r}")
    if not isinstance(record["review_flags"], list) or not all(isinstance(flag, str) for flag in record["review_flags"]):
        raise ReviewError(f"{expected['word']} 的 review_flags 必须是字符串数组")
    note = str(record["note"] or "").strip()
    source_basis = str(record["source_basis"] or "").strip()
    source_license = str(record["source_license"] or "").strip()
    evidence_summary = str(record["evidence_summary"] or "").strip()
    if record["status"] == "accepted":
        keeps_existing_provenance = (
            source_basis == expected["existing_source"] and source_license == expected["existing_license"]
        )
        if not keeps_existing_provenance and not is_allowed_manual_source(expected["word"], source_basis, source_license):
            raise ReviewError(
                f"{expected['word']} 只能保留既有来源，或在人工核对后使用对应的 Wiktionary 页面或 engra/MIT"
            )
        if not has_han(evidence_summary):
            raise ReviewError(f"{expected['word']} 的 accepted 记录必须留下中文人工核对摘要")
        errors = validate_etymology(expected["word"], note, source_basis, source_license)
        if errors:
            raise ReviewError(f"{expected['word']} 的 accepted 说明无效：{'；'.join(errors)}")
    elif note or source_basis or source_license or evidence_summary:
        raise ReviewError(f"{expected['word']} 的 {record['status']} 记录不能携带待发布说明或来源")


def merge_reviews(
    input_path: Path,
    manifest_path: Path,
    responses_dir: Path,
    output_path: Path,
    report_path: Path | None,
    selected_batch_ids: set[str] | None = None,
) -> dict[str, Any]:
    if input_path.resolve() == output_path.resolve():
        raise ReviewError("为避免直接覆写正式词库，--output 必须是不同文件")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != 1:
        raise ReviewError("不支持的 manifest schema")
    actual_snapshot = sha256_file(input_path)
    if actual_snapshot != manifest.get("input_sha256"):
        raise ReviewError("输入 CSV 已改变，拒绝把旧批次结果合并到新快照")
    rows, fields = read_csv(input_path)
    if len(rows) != manifest.get("row_count"):
        raise ReviewError("输入 CSV 行数与 manifest 不一致")
    all_batch_specs = {spec["id"]: spec for spec in manifest.get("batches", [])}
    if selected_batch_ids:
        unknown_batches = sorted(selected_batch_ids - set(all_batch_specs))
        if unknown_batches:
            raise ReviewError(f"manifest 中不存在指定批次：{', '.join(unknown_batches)}")
        batch_specs = {batch_id: all_batch_specs[batch_id] for batch_id in selected_batch_ids}
    else:
        batch_specs = all_batch_specs
    expected_by_batch: dict[str, dict[str, dict[str, str]]] = {}
    for spec in batch_specs.values():
        records = read_jsonl(manifest_path.parent / spec["file"])
        expected = {record["word_key"]: record for record in records}
        if len(expected) != spec["count"]:
            raise ReviewError(f"批次输入损坏：{spec['id']}")
        expected_by_batch[spec["id"]] = expected
    response_paths = sorted(responses_dir.glob("*.jsonl"))
    if not response_paths:
        raise ReviewError("responses 目录中没有审校 JSONL")
    responses_by_batch: dict[str, dict[str, dict[str, Any]]] = {}
    for response_path in response_paths:
        for record in read_jsonl(response_path):
            batch_id = record.get("batch_id")
            if batch_id not in all_batch_specs:
                raise ReviewError(f"未知 batch_id：{batch_id!r}")
            if batch_id not in expected_by_batch:
                continue
            key = record.get("word_key")
            if not isinstance(key, str) or key in responses_by_batch.setdefault(batch_id, {}):
                raise ReviewError(f"{response_path} 含重复或无效 word_key：{key!r}")
            expected = expected_by_batch[batch_id].get(key)
            if expected is None:
                raise ReviewError(f"{response_path} 含不属于该批次的单词：{key!r}")
            _check_response_record(record, expected)
            responses_by_batch[batch_id][key] = record
    for batch_id, responses in responses_by_batch.items():
        expected = expected_by_batch[batch_id]
        if set(responses) != set(expected):
            missing = sorted(set(expected) - set(responses))
            extra = sorted(set(responses) - set(expected))
            raise ReviewError(f"批次 {batch_id} 不是完整响应；缺少 {missing[:3]}，额外 {extra[:3]}")
    row_by_key = {word_key(row["word"]): row for row in rows}
    counts: Counter[str] = Counter()
    for responses in responses_by_batch.values():
        for key, record in responses.items():
            row = row_by_key[key]
            status = record["status"]
            counts[status] += 1
            if status == "accepted":
                row["etymology"] = str(record["note"]).strip()
                row["etymology_source"] = str(record["source_basis"]).strip()
                row["etymology_license"] = str(record["source_license"]).strip()
            elif status == "not_decomposable":
                row["etymology"] = ""
                row["etymology_source"] = ""
                row["etymology_license"] = ""
    for row in rows:
        errors = validate_etymology(row["word"], row.get("etymology", ""), row.get("etymology_source", ""), row.get("etymology_license", ""))
        if row.get("etymology", "").strip() and errors and word_key(row["word"]) in {
            key for responses in responses_by_batch.values() for key in responses
        }:
            raise ReviewError(f"合并后 {row['word']} 未通过构词验收：{'；'.join(errors)}")
    write_csv_atomically(output_path, fields, rows)
    report = {
        "input_sha256": actual_snapshot,
        "completed_batches": sorted(responses_by_batch),
        "selected_batch_ids": sorted(selected_batch_ids) if selected_batch_ids else None,
        "review_status_counts": dict(sorted(counts.items())),
        "morphology_audit": audit_rows(rows),
    }
    if report_path:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="按固定快照生成 JSONL 审校批次")
    prepare.add_argument("--input", type=Path, required=True)
    prepare.add_argument("--output-dir", type=Path, required=True)
    prepare.add_argument("--batch-size", type=int, default=200)
    merge = commands.add_parser("merge", help="校验并合并完整审校批次到新 CSV")
    merge.add_argument("--input", type=Path, required=True)
    merge.add_argument("--manifest", type=Path, required=True)
    merge.add_argument("--responses-dir", type=Path, required=True)
    merge.add_argument("--output", type=Path, required=True)
    merge.add_argument("--report", type=Path)
    merge.add_argument("--batch-id", action="append", help="只合并指定的完整 batch_id；其他响应文件保留但不读取")
    audit = commands.add_parser("audit", help="统计并校验构词说明格式")
    audit.add_argument("--input", type=Path, required=True)
    audit.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            manifest = prepare_batches(args.input, args.output_dir, args.batch_size)
            print(f"Prepared {manifest['row_count']:,} words in {len(manifest['batches'])} batches; snapshot {manifest['input_sha256']}.")
        elif args.command == "merge":
            report = merge_reviews(
                args.input, args.manifest, args.responses_dir, args.output, args.report, set(args.batch_id or []) or None
            )
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            rows, _fields = read_csv(args.input)
            report = audit_rows(rows)
            if args.json:
                print(json.dumps(report, ensure_ascii=False, indent=2))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if not report["format_invalid_count"] and not report["formula_risk_count"] else 1
    except (OSError, ReviewError, json.JSONDecodeError) as exc:
        print(f"Morphology review pipeline failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
