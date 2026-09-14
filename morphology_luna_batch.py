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
PROMPT_VERSION = "v7-maximal-learning"
PART_TYPES = {"prefix", "root", "base", "suffix", "combining_form", "mnemonic_anchor", "spelling_fragment"}
FORM_RE = re.compile(r"^-?[A-Za-z]+(?:'[A-Za-z]+)?-?$")
SPELLING_CHANGE_CLAIM_RE = re.compile(r"脱落|删除|删去|省略|双写|加倍|变为|改为|替换")
SPELLING_CHANGE_NEGATION_RE = re.compile(r"不双写|无需双写|不加倍|不脱落|不删除|不省略|不改变|无变化|保持|保留")

HISTORY_RE = re.compile(
    r"中古|古英语|古法语|拉丁语|希腊语|法语|日耳曼语|Middle\s+English|Middle\s+French|"
    r"Old\s+English|Old\s+French|Latin|Greek|French|Germanic|Proto-|原始印欧|原始日耳曼|"
    r"借自|传入|词源来自|源自.+(?:语|文)",
    re.IGNORECASE,
)

PRODUCTIVE_PREFIXES = (
    "anti", "de", "dis", "en", "fore", "inter", "mis", "non", "over", "pre", "re",
    "sub", "super", "trans", "un", "under",
)
PRODUCTIVE_SUFFIXES = (
    "able", "al", "ance", "ence", "ed", "en", "er", "ful", "hood", "ian", "ing", "ism",
    "ist", "ity", "ive", "ize", "less", "ly", "ment", "ness", "ous", "ship", "y",
)

PROMPT = """你为英语学习应用 MeanEase 生成“最大化学习型拆解（maximal learning decomposition）”草稿。目标是把单词尽可能细地拆成对记忆有帮助的连续片段，同时明确区分真实构词成分和纯记忆/拼写片段。

硬规则：
1. 第一优先级是真实构词：尽可能递归识别 prefix、bound root、现代英语 base、suffix、combining form。只要一个较大的 base 内部还能可靠拆出稳定、可复用且对学习有价值的真实构词成分，就继续拆，不要停在较大的 base。
2. 真实构词已经无法继续时，为了帮助拼写记忆，可以使用 mnemonic_anchor 和 spelling_fragment。mnemonic_anchor 是目标词中连续出现、容易识别和记忆的英语词/稳定片段，但不要求它在目标词中承担真实现代构词意义；meaning_zh 必须明确写“仅作记忆锚点，不表示现代构词义”。spelling_fragment 只覆盖剩余字母，meaning_zh 必须明确写“拼写片段，无独立构词义”。
3. 最大化拆解不等于任意切字母。优先真实词素，其次才是确实有助于记忆的 anchor + fragment。不得为了增加片段数量把一个本来更好记的整体机械切成无意义的两三字母串；与目标词毫无学习关联的缩写、编程术语或偶然同形不能作为 mnemonic_anchor。
4. 所有 parts 必须按目标拼写从左到右覆盖整个单词；真实词素发生规则拼写变化时可以保留完整构词形式并在 spelling_note 解释。mnemonic_anchor / spelling_fragment 则按目标词中的实际表面拼写填写，不制造虚假拼写变化。
5. 对真实构词成分，meaning_zh 必须解释它在当前单词中实际贡献的意义。对 mnemonic_anchor，meaning_zh 只说明记忆联想并明确它不表示现代构词义；对 spelling_fragment，只写拼写作用，不赋予虚假语义。
6. status=ok 用于存在可靠真实构词拆解，或存在明确有帮助且不误导的学习型拆解。只有既没有可靠构词拆解、也找不到有价值的记忆拆解时才用 not_decomposable。仍有合理候选但会明显误导时用 needs_review。not_decomposable / needs_review 的 parts 必须为空数组。
7. prefix 的 form 末尾带 -，suffix 的 form 开头带 -；root/base/combining_form/mnemonic_anchor/spelling_fragment 不使用边界连字符。
8. 若真实词素拼接涉及字母脱落、增加、替换、辅音同化等，写进 spelling_note；没有真实拼写调整时为空字符串。不要把纯记忆分段描述成历史词源或真实词素变化。
9. 禁止输出历史传入链；不要回答中古英语、古英语、古法语、拉丁语/希腊语传入英语等历史来源。
10. confidence 反映你对“这种拆法是否真实或确实有学习价值且不误导”的把握，不要因为 JSON 结构完整就给高置信度。

参考示例：
unhelpful => un-<prefix> + help<base> + -ful<suffix>；high
interrogation => inter-<prefix> + rog<root> + -ate<suffix> + -ion<suffix>；high
creation => create<base> + -ion<suffix>；spelling_note="create 加 -ion 时词尾 e 脱落"；high
window => wind<mnemonic_anchor> + ow<spelling_fragment>；wind 的 meaning_zh="wind（风），仅作记忆锚点，不表示现代构词义"；ow 的 meaning_zh="拼写片段，无独立构词义"
uncle => not_decomposable；parts=[]；只有在找不到比整词更有帮助且不误导的拆法时才这样返回。

判定顺序：
A. 先递归寻找最细且可靠的真实构词成分；不要因为已经找到一个完整 base 就停止。
B. 若真实构词无法覆盖到更细，检查能否用一个或多个有明显记忆价值的 mnemonic_anchor，加必要的 spelling_fragment 覆盖剩余拼写。
C. 比较候选时，优先真实构词信息更多、片段更细且仍然稳定可解释的方案；若真实构词程度相同，选择更容易记忆且更少误导的方案。
D. 不允许把与当前词无关的偶然同形片段强行解释成词根或词缀；纯拼写剩余必须标为 spelling_fragment。
E. 必须为输入中的每个 word 返回且只返回一个 item；word 原样复制。
"""


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
        "prompt_version": PROMPT_VERSION,
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


def normalized_part_form(part: dict[str, Any]) -> str:
    return str(part.get("form", "")).strip("-").casefold()


def possible_productive_affix_split(word: str, reference_words: set[str]) -> bool:
    word = word.casefold()
    if len(word) < 6:
        return False
    for prefix in PRODUCTIVE_PREFIXES:
        if word.startswith(prefix) and len(word) - len(prefix) >= 4 and word[len(prefix):] in reference_words:
            return True
    for suffix in PRODUCTIVE_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 4 and word[:-len(suffix)] in reference_words:
            return True
    return False


def review_warnings(item: dict[str, Any], reference_words: set[str]) -> list[str]:
    warnings: list[str] = []
    word = str(item.get("word", "")).strip().casefold()
    parts = item.get("parts")
    if isinstance(parts, list):
        for part in parts:
            if part.get("type") == "root" and normalized_part_form(part) in reference_words:
                warnings.append("root_matches_reference_word")
    if item.get("status") == "not_decomposable" and item.get("confidence") == "high":
        if possible_productive_affix_split(word, reference_words):
            warnings.append("possible_productive_affix_split")
    note = str(item.get("spelling_note", ""))
    if (
        item.get("status") == "ok"
        and isinstance(parts, list)
        and note
        and normalized_spelling(parts) == word
        and SPELLING_CHANGE_CLAIM_RE.search(note)
        and not SPELLING_CHANGE_NEGATION_RE.search(note)
        and "同化" not in note
    ):
        warnings.append("spelling_change_claim_but_surface_unchanged")
    return sorted(set(warnings))


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
    normalized_components = [(normalized_part_form(part), part.get("type")) for part in parts]
    if len(normalized_components) != len(set(normalized_components)):
        issues.append("duplicate_component_form")
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
        if part_type in {"mnemonic_anchor", "spelling_fragment"} and (form.startswith("-") or form.endswith("-")):
            issues.append("learning_chunk_has_boundary")
        if part_type == "mnemonic_anchor" and "记忆锚点" not in meaning:
            issues.append("mnemonic_anchor_must_disclaim")
        if part_type == "spelling_fragment" and not ("拼写片段" in meaning and "无独立构词义" in meaning):
            issues.append("spelling_fragment_must_disclaim")
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
        elif part["type"] == "mnemonic_anchor":
            meaning += "（记忆锚点）"
        elif part["type"] == "spelling_fragment":
            meaning += "（拼写片段）"
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
    reference_words = set(known_words)
    if DEFAULT_INPUT.exists():
        try:
            reference_words.update(row["word"].casefold() for row in load_words(DEFAULT_INPUT))
        except (OSError, KeyError, ValueError):
            pass
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
                warnings = review_warnings(item, reference_words)
                if word_key in candidates:
                    issues.append("duplicate_word_output")
                candidate = {
                    **item,
                    "issues": sorted(set(issues)),
                    "warnings": warnings,
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
            if (
                candidate.get("status") == "needs_review"
                or candidate.get("confidence") != "high"
                or candidate.get("issues")
                or candidate.get("warnings")
            ):
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
        "valid_ok_high": sum(
            c.get("status") == "ok"
            and c.get("confidence") == "high"
            and not c.get("issues")
            and not c.get("warnings")
            for c in candidates.values()
        ),
        "warning_words": sum(bool(c.get("warnings")) for c in candidates.values()),
        "warning_counts": {
            warning: sum(warning in c.get("warnings", []) for c in candidates.values())
            for warning in sorted({warning for c in candidates.values() for warning in c.get("warnings", [])})
        },
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
