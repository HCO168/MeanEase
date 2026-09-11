#!/usr/bin/env python3
"""Historical automatic word-formation generator; disabled for MeanEase.

MeanEase now requires every Chinese morphology or origin note to be written by
a human reviewer. The implementation remains here for historical inspection,
but its command-line entry point intentionally refuses to write data. Use
``morphology_review_pipeline.py prepare`` and ``morphology_review_guide.md``
instead; that pipeline only transports and validates human-authored notes.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import urllib.request
import zipfile
from collections import Counter, defaultdict
from pathlib import Path


ENGRA_ARCHIVE = "https://github.com/eslsoft/engra/archive/refs/heads/master.zip"
ENGRA_SOURCE = "https://github.com/eslsoft/engra"
WIKTIONARY_LICENSE = "CC BY-SA 4.0"
ENGRA_LICENSE = "MIT"

PREFIXES = {
    "anti": "反对、抵抗", "auto": "自己、自动", "bi": "二、双", "co": "共同、一起",
    "com": "共同、一起", "con": "共同、一起", "contra": "反对、相反", "counter": "反对、相反",
    "de": "向下、去除", "dis": "分开、否定", "en": "使成为", "em": "使成为",
    "ex": "向外、以前的", "extra": "在外、超出", "fore": "在前、预先", "hyper": "超过、过度",
    "il": "不、无", "im": "不、无", "in": "进入；也可表示不、无", "inter": "在……之间、相互",
    "intra": "在内部", "ir": "不、无", "macro": "大", "mal": "坏、不良", "micro": "小、微小",
    "mid": "中间", "mis": "错误、不当", "mono": "单一", "multi": "多", "non": "不、非",
    "over": "过度、在上方", "post": "在后、之后", "pre": "在前、预先", "pro": "向前、支持",
    "pseudo": "假的、伪", "re": "重新、再次", "semi": "半、部分", "sub": "在下、次级",
    "super": "在上、超过", "tele": "远", "trans": "穿过、转变", "tri": "三", "ultra": "超越",
    "un": "不；相反动作", "under": "在下、不足",
}

SUFFIXES = {
    "ability": "表示能力或性质的名词后缀", "ibility": "表示能力或性质的名词后缀",
    "ation": "表示行为或结果的名词后缀", "ition": "表示行为或结果的名词后缀",
    "sion": "名词后缀", "tion": "名词后缀", "ion": "名词后缀", "ment": "表示行为或结果的名词后缀",
    "ness": "表示性质或状态的名词后缀", "ity": "表示性质或状态的名词后缀",
    "logy": "表示学科或研究", "graphy": "表示书写、记录或学科", "scope": "表示观察工具",
    "ship": "表示身份或状态的名词后缀", "ism": "表示主义或体系的名词后缀",
    "ist": "表示人或从业者的后缀", "er": "表示人、物或比较级的后缀", "or": "表示人或物的名词后缀",
    "ian": "表示人或相关事物的后缀", "al": "构成形容词或名词", "ial": "形容词后缀",
    "ional": "形容词后缀", "ic": "形容词后缀", "ical": "形容词后缀", "ive": "形容词后缀",
    "ous": "表示性质的形容词后缀", "ful": "充满……的", "less": "没有……的",
    "able": "能够……的", "ible": "能够……的", "ly": "副词后缀", "ize": "使……化",
    "ise": "使……化", "ify": "使成为", "fy": "使成为", "ate": "构成动词或形容词",
    "en": "使成为", "ing": "表示进行或动名词", "ed": "表示过去或完成", "es": "复数或第三人称单数",
    "s": "复数或第三人称单数",
}

ROOT_GLOSSES = {
    "act": "做、行动", "bio": "生命", "cap": "拿、抓", "cept": "拿、取", "clud": "关闭",
    "corp": "身体", "corpor": "身体", "cred": "相信", "dict": "说", "duc": "引导",
    "fac": "做、制造", "fect": "做、完成", "fer": "携带", "fin": "结束、界限", "form": "形式、组成",
    "ject": "投、掷", "leg": "选择；也可表示法律", "lect": "选择、读", "miss": "送出",
    "mit": "送出", "mod": "方式、尺度", "nat": "出生", "part": "部分", "pend": "悬挂",
    "phon": "声音", "port": "携带、运送", "pos": "放置", "press": "压", "rupt": "破裂",
    "scrib": "写", "script": "写", "sent": "感觉、意见", "sist": "站立", "spect": "看",
    "stat": "站立", "tain": "握住、保持", "tend": "伸展、趋向", "tract": "拉、牵引",
    "vert": "转", "vers": "转", "vis": "看",
}

LANGUAGES = {
    "Proto-Indo-European": "原始印欧语", "Proto-West Germanic": "原始西日耳曼语",
    "Proto-Germanic": "原始日耳曼语", "Middle English": "中古英语", "Old English": "古英语",
    "Late Latin": "晚期拉丁语", "Medieval Latin": "中世纪拉丁语", "Vulgar Latin": "通俗拉丁语",
    "Latin": "拉丁语", "Ancient Greek": "古希腊语", "Greek": "希腊语", "Old French": "古法语",
    "Middle French": "中古法语", "French": "法语", "Old Norse": "古诺斯语", "Italian": "意大利语",
    "Spanish": "西班牙语", "German": "德语", "Dutch": "荷兰语", "Arabic": "阿拉伯语",
    "Sanskrit": "梵语", "Japanese": "日语", "Chinese": "汉语",
}


def concise_meaning(text: str) -> str:
    first = re.split(r"[；\n]", text, maxsplit=1)[0]
    first = re.sub(r"^(?:vt\.|vi\.|v\.|n\.|a\.|adj\.|ad\.|adv\.|prep\.|conj\.|pron\.|art\.|num\.)\s*", "", first, flags=re.I)
    first = re.sub(r"\[[^]]+\]", "", first).strip(" ；,，。")
    parts = [part.strip() for part in re.split(r"[,，]", first) if part.strip()]
    return "、".join(parts[:2])[:28]


def clean_root_name(value: str) -> str:
    match = re.search(r"[A-Za-z]+", value or "")
    return match.group(0).casefold() if match else ""


def extract_root_glosses(files: dict[str, bytes]) -> dict[str, str]:
    candidates: dict[str, Counter[str]] = defaultdict(Counter)
    for path, content in files.items():
        if "/dict/roots/" not in path or not path.endswith(".yml"):
            continue
        text = content.decode("utf-8", errors="replace")
        root_match = re.search(r"^name:\s*([^\n]+)", text, re.MULTILINE)
        root = clean_root_name(root_match.group(1) if root_match else Path(path).stem)
        if not root:
            continue
        for mnemonic in re.findall(r"mnemonic:\s*[^【\n]*【([^】]+)", text):
            for variant in {root, root.rstrip("e"), root + "e"}:
                match = re.search(rf"(?<![A-Za-z]){re.escape(variant)}-?\s*(?:=\s*[A-Za-z-]+\s*)?([\u4e00-\u9fff][\u4e00-\u9fff、，…至表示]*)", mnemonic, re.I)
                if not match:
                    continue
                gloss = re.split(r"[，,；;→]", match.group(1))[0].strip()
                gloss = re.sub(r"(?:表示|构成)$", "", gloss).strip()
                if 1 <= len(gloss) <= 12 and gloss not in {"见上", "的"}:
                    candidates[root][gloss] += 1
    result = {root: counts.most_common(1)[0][0] for root, counts in candidates.items() if counts}
    result.update(ROOT_GLOSSES)
    return result


def download_engra(url: str) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    request = urllib.request.Request(url, headers={"User-Agent": "MeanEase-builder/1.0"})
    with urllib.request.urlopen(request, timeout=90) as response:
        archive = response.read()
    with zipfile.ZipFile(io.BytesIO(archive)) as package:
        files = {name: package.read(name) for name in package.namelist() if name.endswith(("dict/words.csv", ".yml"))}
    words_path = next(name for name in files if name.endswith("dict/words.csv"))
    roots_by_word: dict[str, str] = {}
    meanings_by_word: dict[str, str] = {}
    for row in csv.DictReader(io.StringIO(files[words_path].decode("utf-8-sig"))):
        word = (row.get("name") or "").strip().casefold()
        root = clean_root_name(row.get("roots") or "")
        if word and root and word not in roots_by_word:
            roots_by_word[word] = root
        if word and row.get("meaning") and word not in meanings_by_word:
            meanings_by_word[word] = concise_meaning(row["meaning"].replace("\\n", "；"))
    return roots_by_word, meanings_by_word, extract_root_glosses(files)


def formation_note(word: str, meaning: str, root: str, root_gloss: str) -> str:
    key = word.casefold()
    variants = [root, root.rstrip("e"), root + "e"]
    located = next(((variant, key.find(variant)) for variant in variants if variant and key.find(variant) >= 0), None)
    if not located:
        return f"{word} / {root}；{root}：{root_gloss}；{word}：{meaning}。"
    variant, index = located
    before, after = key[:index], key[index + len(variant):]
    pieces, explanations = [], []
    if before in PREFIXES:
        pieces.append(before); explanations.append(f"{before}-：{PREFIXES[before]}")
    pieces.append(variant); explanations.append(f"{variant}：{root_gloss}")
    if after in SUFFIXES:
        pieces.append(after); explanations.append(f"-{after}：{SUFFIXES[after]}")
    decomposition = "-".join(pieces)
    return f"{word} / {decomposition}；" + "；".join(explanations) + f"；{word}：{meaning}。"


def wiktionary_note(word: str, meaning: str, english: str) -> str:
    lowered = english.casefold()
    for label, action in (("contraction of", "缩写自"), ("clipping of", "截短自"), ("abbreviation of", "缩写自")):
        if label in lowered:
            tail = english[lowered.index(label) + len(label):].strip()
            source = re.match(r"[A-Za-z][A-Za-z' -]{0,40}", tail)
            if source:
                return f"{word}：{action} {source.group(0).strip()}；今义：{meaning}。"
    origins = []
    for language in sorted(LANGUAGES, key=len, reverse=True):
        for match in re.finditer(re.escape(language) + r"\s+([^\s,.;()]+)", english, re.I):
            item = (match.start(), LANGUAGES[language], match.group(1).strip("“”\"*"))
            if item[2] and item not in origins:
                origins.append(item)
    origins.sort()
    deduped = []
    for _, language, term in origins:
        pair = (language, term)
        if pair not in deduped:
            deduped.append(pair)
        if len(deduped) == 2:
            break
    if deduped:
        chain = "，可追溯至".join(f"{language} {term}" for language, term in deduped)
        return f"{word}：源自{chain}；今义：{meaning}。"
    return ""


def enrich(input_path: Path, output_path: Path, engra_url: str) -> tuple[int, int, int]:
    with input_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle); rows = list(reader); fields = list(reader.fieldnames or [])
    roots_by_word, source_meanings, root_glosses = download_engra(engra_url)
    formation_count = origin_count = 0
    for row in rows:
        word = row.get("word", "").strip(); key = word.casefold(); meaning = concise_meaning(row.get("meaning", ""))
        root = roots_by_word.get(key, ""); root_gloss = root_glosses.get(root) or source_meanings.get(root, "")
        if root and root != key and root_gloss and meaning:
            row["etymology"] = formation_note(word, meaning, root, root_gloss)
            row["etymology_source"] = ENGRA_SOURCE; row["etymology_license"] = ENGRA_LICENSE; formation_count += 1
        else:
            note = wiktionary_note(word, meaning, row.get("etymology", "")) if meaning else ""
            row["etymology"] = note
            if note:
                row["etymology_license"] = WIKTIONARY_LICENSE; origin_count += 1
            else:
                row["etymology_source"] = ""; row["etymology_license"] = ""
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    temporary.replace(output_path)
    return len(rows), formation_count, origin_count


def main() -> int:
    print(
        "Automatic Chinese morphology generation is disabled. "
        "Use morphology_review_pipeline.py to validate and merge human-authored review batches.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
