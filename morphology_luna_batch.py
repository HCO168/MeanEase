#!/usr/bin/env python3
"""Prepare and manage GPT-5.6 Luna Batch jobs for MeanEase morphology drafts.

The model output is a review candidate, not a lexical authority. This tool never
writes model output into the production CSV automatically.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MODEL = "gpt-5.6-luna"
API_BASE = "https://api.openai.com/v1"
BATCH_ENDPOINT = "/v1/responses"
DEFAULT_BATCH_SIZE = 25
DEFAULT_MAX_OUTPUT_TOKENS = 20000
DEFAULT_INPUT = Path("us_core_7000_authentic.csv")
DEFAULT_WORKDIR = Path("tmp/morphology-luna")
STATUSES = {"ok", "not_decomposable", "needs_review"}
CONFIDENCES = {"high", "medium", "low"}
PART_TYPES = {"prefix", "root", "base", "suffix", "combining_form"}
FORM_RE = re.compile(r"^-?[A-Za-z]+(?:'[A-Za-z]+)?-?$")
HISTORY_RE = re.compile(
    r"中古|古英语|古法语|拉丁语|希腊语|法语|日耳曼语|Middle\s+English|Middle\s+French|"
    r"Old\s+English|Old\s+French|Latin|Greek|French|Germanic|Proto-|原始印欧|原始日耳曼|"
    r"借自|传入|词源来自|源自.+(?:语|文)",
    re.IGNORECASE,
)

PROMPT = """你为英语学习应用 MeanEase 生成“构词拆解（morphological decomposition）”草稿，不是历史词源。
对每个输入词判断现代学习上能否可靠拆成有意义的前缀、词根、基础词、后缀或构词成分。

硬规则：
1. 禁止写历史传入链；不要回答中古英语、古英语、古法语、拉丁语/希腊语传入英语等历史来源。
2. 目标是“最少但足够解释构词”的学习型拆解，不是拆得越深越好。优先寻找能解释目标词结构的最浅可靠层级；如果外层词缀加一个清楚、可识别的现代英语基础词已经足够，就保留该基础词整体，不因还能找到更小片段而继续递归拆解。
3. 只有当保留完整基础词会丢失重要、稳定且对学习者有价值的构词关系时，才继续拆到 bound root 或更细的派生层级。bound root 可以不能独立成现代英语单词，但必须是稳定、可复用、语义清楚的学习型成分。
4. 不要把相邻的多个派生成分为了省事合并成一个更大的“后缀/前缀”，如果这些成分在目标词的派生链中各自承担清楚、独立且对学习有用的作用；同时也不要为了展示更多成分而过度拆解一个本来已经足够清楚的现代基础词。
5. 每个词素的 meaning_zh 必须解释它在当前单词里实际贡献的学习含义。仅有拼写相似不能证明它就是某个常见前缀、后缀或词根；不得把一个成分在其他单词中的常见意思机械套到当前单词。若切分形式上看似可能，但任一成分在当前单词中的语义不能可靠解释，status=needs_review。
6. status=ok 只用于“切分与每个成分在当前单词中的语义都可靠”的情况；无法得到可靠且有学习价值的拆解时用 not_decomposable；存在合理候选但切分或语义仍不确定时用 needs_review。not_decomposable 和 needs_review 的 parts 都必须为空数组。
7. 禁止按字母相邻硬拆。parts 必须按目标词实际表面拼写从左到右；不要在 parts 中把表面变体替换成规范化形式。prefix 的 form 末尾带 -，suffix 的 form 开头带 -，root/base 不带边界连字符。
8. 若拼接涉及字母脱落、增加、替换、辅音同化或其他对学习者有用的形式变化，写进 spelling_note；没有调整时为空字符串。
9. confidence 反映你对“这个切分以及各成分在当前单词中的解释”的把握；不要因为 JSON 结构完整就给高置信度。

判定顺序：
A. 先判断这个词是否存在可靠且有学习价值的构词拆解；没有则 not_decomposable。
B. 先测试外层词缀 + 可识别现代基础词的浅层拆解是否已经足够。
C. 只有在确有额外学习价值时，才把基础词进一步拆成稳定的 bound root 或连续派生成分。
D. 对每个候选成分逐一验证：边界是否真实、类型是否合理、在当前单词中的语义是否成立、整体是否能解释目标词。
E. 只要某一步仍依赖猜测、机械类比或无法可靠说明的语义，就返回 needs_review，不输出候选 parts。

必须为输入中的每个 word 返回且只返回一个 item；word 原样复制。"""


def result_schema() -> dict[str, Any]:
    part = {
        "type": "object",
        "properties": {
            "form": {"type": "string"},
            "type": {"type": "string", "enum": sorted(PART_TYPES)},
            "meaning_zh": {"type": "string"},
        },
        "required": ["form", "type", "meaning_zh"],
        "additionalProperties": False,
    }
    item = {
        "type": "object",
        "properties": {
            "word": {"type": "string"},
            "status": {"type": "string", "enum": sorted(STATUSES)},
            "parts": {"type": "array", "items": part},
            "spelling_note": {"type": "string"},
            "confidence": {"type": "string", "enum": sorted(CONFIDENCES)},
        },
        "required": ["word", "status", "parts", "spelling_note", "confidence"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"items": {"type": "array", "items": item}},
        "required": ["items"],
        "additionalProperties": False,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def concise(value: str, limit: int = 90) -> str:
    value = " ".join((value or "").split())
    return value[:limit]


def load_words(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    words: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        word = (row.get("word") or "").strip()
        key = word.casefold()
        if not word or key in seen:
            continue
        seen.add(key)
        words.append(
            {
                "word": word,
                "base_word": concise(row.get("base_word", ""), 40),
                "pos": concise(row.get("pos", ""), 40),
                "meaning": concise(row.get("meaning", ""), 90),
            }
        )
    return words


def chunks(values: list[Any], size: int):
    for index in range(0, len(values), size):
        yield index, values[index : index + size]


def default_reasoning_effort(model: str) -> str:
    if model.startswith("gpt-5-nano"):
        return "minimal"
    return "none"


def batch_request(
    custom_id: str,
    words: list[dict[str, str]],
    model: str,
    reasoning_effort: str,
) -> dict[str, Any]:
    input_text = PROMPT + "\n\n待拆解词（JSON）：\n" + json.dumps(words, ensure_ascii=False, separators=(",", ":"))
    return {
        "custom_id": custom_id,
        "method": "POST",
        "url": BATCH_ENDPOINT,
        "body": {
            "model": model,
            "reasoning": {"effort": reasoning_effort},
            "input": input_text,
            "max_output_tokens": DEFAULT_MAX_OUTPUT_TOKENS,
            "store": False,
            "text": {
                "verbosity": "low",
                "format": {
                    "type": "json_schema",
                    "name": "meanease_morphology_batch",
                    "strict": True,
                    "schema": result_schema(),
                },
            },
        },
    }


def prepare(args: argparse.Namespace) -> int:
    model = getattr(args, "model", MODEL)
    reasoning_effort = getattr(args, "reasoning_effort", None) or default_reasoning_effort(model)
    words = load_words(args.input)
    if not words:
        raise ValueError("input CSV contains no words")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    request_count = 0
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        for start, group in chunks(words, args.batch_size):
            end = start + len(group) - 1
            request = batch_request(f"morph-{start:05d}-{end:05d}", group, model, reasoning_effort)
            handle.write(json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n")
            request_count += 1
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "reasoning_effort": reasoning_effort,
        "endpoint": BATCH_ENDPOINT,
        "source_csv": str(args.input),
        "source_csv_sha256": sha256_file(args.input),
        "input_jsonl": str(args.output),
        "input_jsonl_sha256": sha256_file(args.output),
        "word_count": len(words),
        "request_count": request_count,
        "words_per_request": args.batch_size,
        "input_bytes": args.output.stat().st_size,
    }
    manifest_path = args.output.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


def api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set; set it in your local shell, never paste it into project files")
    return key


def api_json(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Authorization": f"Bearer {api_key()}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(API_BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"OpenAI API HTTP {exc.code}: {message}") from exc


def api_bytes(path: str) -> bytes:
    request = urllib.request.Request(API_BASE + path, headers={"Authorization": f"Bearer {api_key()}"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"OpenAI API HTTP {exc.code}: {message}") from exc


def upload_batch_file(path: Path) -> dict[str, Any]:
    if path.stat().st_size > 200 * 1024 * 1024:
        raise ValueError("Batch input exceeds the 200 MB API limit")
    boundary = "----MeanEaseBatch" + uuid.uuid4().hex
    file_bytes = path.read_bytes()
    body = b"".join(
        [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"purpose\"\r\n\r\nbatch\r\n".encode(),
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\nContent-Type: application/jsonl\r\n\r\n".encode(),
            file_bytes,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    request = urllib.request.Request(
        API_BASE + "/files",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key()}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"OpenAI file upload HTTP {exc.code}: {message}") from exc


def input_model(path: Path) -> str:
    models: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            if not raw_line.strip():
                continue
            request = json.loads(raw_line)
            model = str((request.get("body") or {}).get("model") or "").strip()
            if not model:
                raise ValueError("Batch input contains a request without body.model")
            models.add(model)
    if len(models) != 1:
        raise ValueError(f"Batch input must use exactly one model, found: {sorted(models)}")
    return next(iter(models))


def submit(args: argparse.Namespace) -> int:
    if not args.input.is_file():
        raise FileNotFoundError(args.input)
    model = input_model(args.input)
    uploaded = upload_batch_file(args.input)
    batch = api_json(
        "POST",
        "/batches",
        {
            "input_file_id": uploaded["id"],
            "endpoint": BATCH_ENDPOINT,
            "completion_window": "24h",
            "metadata": {"description": "MeanEase 20000-word morphology draft"},
        },
    )
    state = {
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "input_path": str(args.input),
        "input_sha256": sha256_file(args.input),
        "input_file_id": uploaded["id"],
        "batch_id": batch["id"],
        "status": batch.get("status"),
    }
    args.state.parent.mkdir(parents=True, exist_ok=True)
    args.state.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(state, indent=2))
    return 0


def load_state(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def status(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    batch = api_json("GET", f"/batches/{state['batch_id']}")
    shown = {
        "batch_id": batch.get("id"),
        "status": batch.get("status"),
        "request_counts": batch.get("request_counts"),
        "output_file_id": batch.get("output_file_id"),
        "error_file_id": batch.get("error_file_id"),
        "created_at": batch.get("created_at"),
        "completed_at": batch.get("completed_at"),
    }
    print(json.dumps(shown, ensure_ascii=False, indent=2))
    return 0


def status_summary(args: argparse.Namespace) -> int:
    state_paths = sorted(args.state_dir.glob(args.pattern))
    if not state_paths:
        raise FileNotFoundError(f"no state files matched {args.state_dir / args.pattern}")

    status_counts: dict[str, int] = {}
    request_counts: dict[str, int] = {}
    batches: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for state_path in state_paths:
        try:
            state = load_state(state_path)
            batch_id = str(state["batch_id"])
            batch = api_json("GET", f"/batches/{batch_id}")
            status_value = str(batch.get("status") or "unknown")
            status_counts[status_value] = status_counts.get(status_value, 0) + 1
            counts = batch.get("request_counts") or {}
            for key, value in counts.items():
                if isinstance(value, int):
                    request_counts[key] = request_counts.get(key, 0) + value
            batches.append({
                "state": str(state_path),
                "batch_id": batch.get("id") or batch_id,
                "model": state.get("model"),
                "status": status_value,
                "request_counts": counts,
            })
        except (OSError, KeyError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
            errors.append({"state": str(state_path), "error": str(exc)})

    shown = {
        "batches": batches,
        "errors": errors,
        "batch_count": len(state_paths),
        "status_counts": dict(sorted(status_counts.items())),
        "request_counts": dict(sorted(request_counts.items())),
        "error_count": len(errors),
    }
    print(json.dumps(shown, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


def download(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    batch = api_json("GET", f"/batches/{state['batch_id']}")
    output_file_id = batch.get("output_file_id")
    error_file_id = batch.get("error_file_id")
    if not output_file_id and not error_file_id:
        raise RuntimeError(f"batch has no output or error file yet (status={batch.get('status')})")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if output_file_id:
        args.output.write_bytes(api_bytes(f"/files/{output_file_id}/content"))
        print(f"wrote {args.output} ({args.output.stat().st_size} bytes)")
    if error_file_id and args.errors:
        args.errors.parent.mkdir(parents=True, exist_ok=True)
        args.errors.write_bytes(api_bytes(f"/files/{error_file_id}/content"))
        print(f"wrote {args.errors} ({args.errors.stat().st_size} bytes)")
    return 0


def response_output_text(body: dict[str, Any]) -> str:
    texts: list[str] = []
    for output in body.get("output") or []:
        if output.get("type") != "message":
            continue
        for content in output.get("content") or []:
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                texts.append(content["text"])
    return "".join(texts)


def normalized_spelling(parts: list[dict[str, Any]]) -> str:
    return "".join(str(part.get("form", "")).strip("-") for part in parts).casefold()


def validate_item(item: dict[str, Any], known_words: set[str]) -> list[str]:
    issues: list[str] = []
    word = str(item.get("word", "")).strip()
    status_value = item.get("status")
    parts = item.get("parts")
    note = str(item.get("spelling_note", ""))
    confidence = item.get("confidence")
    if word.casefold() not in known_words:
        issues.append("unknown_word")
    if status_value not in STATUSES:
        issues.append("invalid_status")
    if confidence not in CONFIDENCES:
        issues.append("invalid_confidence")
    if not isinstance(parts, list):
        return issues + ["parts_not_array"]
    if status_value == "ok" and len(parts) < 2:
        issues.append("ok_requires_multiple_parts")
    if status_value != "ok" and parts:
        issues.append("non_ok_must_have_empty_parts")
    for part in parts:
        form = str(part.get("form", ""))
        part_type = part.get("type")
        meaning = str(part.get("meaning_zh", ""))
        if part_type not in PART_TYPES:
            issues.append("invalid_part_type")
        if not FORM_RE.fullmatch(form):
            issues.append("invalid_part_form")
        if part_type == "prefix" and not form.endswith("-"):
            issues.append("prefix_boundary_missing")
        if part_type == "suffix" and not form.startswith("-"):
            issues.append("suffix_boundary_missing")
        if part_type in {"root", "base"} and (form.startswith("-") or form.endswith("-")):
            issues.append("root_or_base_has_boundary")
        if not meaning.strip():
            issues.append("empty_component_meaning")
        if HISTORY_RE.search(meaning):
            issues.append("historical_etymology_in_meaning")
    if HISTORY_RE.search(note):
        issues.append("historical_etymology_in_spelling_note")
    if status_value == "ok" and not note and normalized_spelling(parts) != word.casefold():
        issues.append("spelling_mismatch_without_note")
    return sorted(set(issues))


def concise_word_meaning(value: str) -> str:
    value = concise(value, 80)
    return value.split("；", 1)[0].strip(" ,，。;")


def render_note(word: str, parts: list[dict[str, Any]], spelling_note: str, word_meaning: str) -> str:
    decomposition = "-".join(str(part["form"]).strip("-") for part in parts)
    explanations: list[str] = []
    for part in parts:
        form = str(part["form"])
        meaning = str(part["meaning_zh"]).strip("；。 ")
        if part["type"] == "root":
            meaning += "（词根）"
        elif part["type"] == "combining_form":
            meaning += "（构词成分）"
        explanations.append(f"{form}：{meaning}")
    pieces = [f"{word} / {decomposition}", *explanations]
    if spelling_note:
        pieces.append(f"拼写：{spelling_note.strip('；。 ')}")
    if word_meaning:
        pieces.append(f"{word}：{word_meaning}")
    return "；".join(pieces) + "。"


def parse_results(args: argparse.Namespace) -> int:
    source_rows = load_words(args.input_csv)
    known_words = {row["word"].casefold() for row in source_rows}
    meaning_by_word = {row["word"].casefold(): row["meaning"] for row in source_rows}
    candidates: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    models_used: set[str] = set()
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    with args.results.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                continue
            line = json.loads(raw_line)
            response = line.get("response")
            if not response or response.get("status_code") != 200:
                failures.append({"line": line_number, "custom_id": line.get("custom_id"), "error": line.get("error") or response})
                continue
            body = response.get("body") or {}
            if body.get("model"):
                models_used.add(str(body["model"]))
            body_usage = body.get("usage") or {}
            for key in usage:
                usage[key] += int(body_usage.get(key, 0) or 0)
            text = response_output_text(body)
            try:
                parsed = json.loads(text)
            except Exception as exc:
                failures.append({"line": line_number, "custom_id": line.get("custom_id"), "error": f"invalid output JSON: {exc}"})
                continue
            for item in parsed.get("items") or []:
                word_key = str(item.get("word", "")).casefold()
                issues = validate_item(item, known_words)
                if word_key in candidates:
                    issues.append("duplicate_word_output")
                candidate = {
                    **item,
                    "issues": sorted(set(issues)),
                    "note": "",
                    "model": body.get("model") or MODEL,
                    "batch_custom_id": line.get("custom_id"),
                }
                if item.get("status") == "ok" and not issues:
                    candidate["note"] = render_note(
                        str(item["word"]),
                        item["parts"],
                        str(item.get("spelling_note", "")),
                        concise_word_meaning(meaning_by_word.get(word_key, "")),
                    )
                candidates[word_key] = candidate
    missing = sorted(known_words - set(candidates))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        for row in source_rows:
            candidate = candidates.get(row["word"].casefold())
            if candidate:
                handle.write(json.dumps(candidate, ensure_ascii=False, separators=(",", ":")) + "\n")
    review_path = args.output.with_name(args.output.stem + ".needs-review.jsonl")
    with review_path.open("w", encoding="utf-8", newline="\n") as handle:
        for candidate in candidates.values():
            if candidate.get("status") == "needs_review" or candidate.get("confidence") != "high" or candidate.get("issues"):
                handle.write(json.dumps(candidate, ensure_ascii=False, separators=(",", ":")) + "\n")
        for failure in failures:
            handle.write(json.dumps({"kind": "request_failure", **failure}, ensure_ascii=False, separators=(",", ":")) + "\n")
        for word in missing:
            handle.write(json.dumps({"kind": "missing_output", "word": word}, ensure_ascii=False, separators=(",", ":")) + "\n")
    summary = {
        "model": next(iter(models_used)) if len(models_used) == 1 else ("mixed" if models_used else MODEL),
        "models": sorted(models_used),
        "source_words": len(known_words),
        "returned_words": len(candidates),
        "missing_words": len(missing),
        "request_failures": len(failures),
        "status_counts": {status_name: sum(c.get("status") == status_name for c in candidates.values()) for status_name in sorted(STATUSES)},
        "confidence_counts": {confidence: sum(c.get("confidence") == confidence for c in candidates.values()) for confidence in sorted(CONFIDENCES)},
        "valid_ok_high": sum(c.get("status") == "ok" and c.get("confidence") == "high" and not c.get("issues") for c in candidates.values()),
        "usage": usage,
        "candidate_file": str(args.output),
        "review_file": str(review_path),
    }
    summary_path = args.output.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not failures and not missing else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare", help="create Batch API JSONL from the vocabulary CSV")
    prepare_parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    prepare_parser.add_argument("--output", type=Path, default=DEFAULT_WORKDIR / "input.jsonl")
    prepare_parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    prepare_parser.add_argument("--model", default=MODEL)
    prepare_parser.add_argument("--reasoning-effort", choices=["none", "minimal", "low", "medium", "high"])
    prepare_parser.set_defaults(func=prepare)

    submit_parser = subparsers.add_parser("submit", help="upload JSONL and create a 24h Batch API job")
    submit_parser.add_argument("--input", type=Path, default=DEFAULT_WORKDIR / "input.jsonl")
    submit_parser.add_argument("--state", type=Path, default=DEFAULT_WORKDIR / "batch-state.json")
    submit_parser.set_defaults(func=submit)

    status_parser = subparsers.add_parser("status", help="show current batch status")
    status_parser.add_argument("--state", type=Path, default=DEFAULT_WORKDIR / "batch-state.json")
    status_parser.set_defaults(func=status)

    summary_parser = subparsers.add_parser("status-summary", help="summarize live status across many Batch state files")
    summary_parser.add_argument("--state-dir", type=Path, default=DEFAULT_WORKDIR)
    summary_parser.add_argument("--pattern", default="*-state.json")
    summary_parser.set_defaults(func=status_summary)

    download_parser = subparsers.add_parser("download", help="download completed batch output")
    download_parser.add_argument("--state", type=Path, default=DEFAULT_WORKDIR / "batch-state.json")
    download_parser.add_argument("--output", type=Path, default=DEFAULT_WORKDIR / "output.jsonl")
    download_parser.add_argument("--errors", type=Path, default=DEFAULT_WORKDIR / "errors.jsonl")
    download_parser.set_defaults(func=download)

    parse_parser = subparsers.add_parser("parse", help="validate model output and render review candidates")
    parse_parser.add_argument("--results", type=Path, default=DEFAULT_WORKDIR / "output.jsonl")
    parse_parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT)
    parse_parser.add_argument("--output", type=Path, default=DEFAULT_WORKDIR / "candidates.jsonl")
    parse_parser.set_defaults(func=parse_results)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if getattr(args, "batch_size", DEFAULT_BATCH_SIZE) < 1 or getattr(args, "batch_size", DEFAULT_BATCH_SIZE) > 100:
        raise ValueError("--batch-size must be between 1 and 100")
    return int(args.func(args))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
