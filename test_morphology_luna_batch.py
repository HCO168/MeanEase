from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import morphology_luna_batch as batch


FIELDS = [
    "word", "base_word", "phonetic", "pos", "meaning", "level", "level_source",
    "placement_eligible", "collocation", "morphology", "morphology_source",
    "morphology_license", "example_en", "example_zh", "example_source", "example_license",
]


class MorphologyLunaBatchTests(unittest.TestCase):
    def write_csv(self, path: Path, rows: list[dict[str, str]]) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field, "") for field in FIELDS})

    def test_prepare_groups_words_for_responses_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "words.csv"
            output = root / "input.jsonl"
            self.write_csv(source, [
                {"word": "interrogation", "pos": "n.", "meaning": "审问；询问"},
                {"word": "the", "pos": "art.", "meaning": "这；那"},
                {"word": "reform", "pos": "v./n.", "meaning": "改革；改正"},
            ])
            result = batch.prepare(SimpleNamespace(input=source, output=output, batch_size=2))
            self.assertEqual(result, 0)
            requests = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(requests), 2)
            self.assertEqual(requests[0]["url"], "/v1/responses")
            self.assertEqual(requests[0]["body"]["model"], "gpt-5.6-luna")
            self.assertEqual(requests[0]["body"]["reasoning"], {"effort": "none"})
            self.assertEqual(requests[0]["body"]["text"]["format"]["type"], "json_schema")
            self.assertNotIn("etymology", output.read_text(encoding="utf-8").lower())

    def test_parse_renders_morphology_and_leaves_core_word_blank(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "words.csv"
            results = root / "output.jsonl"
            candidates = root / "candidates.jsonl"
            self.write_csv(source, [
                {"word": "interrogation", "pos": "n.", "meaning": "审问；询问"},
                {"word": "the", "pos": "art.", "meaning": "这；那"},
            ])
            model_output = {
                "items": [
                    {
                        "word": "interrogation", "status": "ok", "confidence": "high",
                        "spelling_note": "interrogate 加 -ion 时末尾 e 脱落",
                        "parts": [
                            {"form": "inter-", "type": "prefix", "meaning_zh": "在……之间、相互"},
                            {"form": "rog", "type": "root", "meaning_zh": "问、请求"},
                            {"form": "-ate", "type": "suffix", "meaning_zh": "构成动词"},
                            {"form": "-ion", "type": "suffix", "meaning_zh": "表示行为、过程或结果"},
                        ],
                    },
                    {"word": "the", "status": "not_decomposable", "confidence": "high", "spelling_note": "", "parts": []},
                ]
            }
            response_body = {
                "model": "gpt-5.6-luna",
                "usage": {"input_tokens": 100, "output_tokens": 80, "total_tokens": 180},
                "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(model_output, ensure_ascii=False)}]}],
            }
            batch_line = {"custom_id": "morph-00000-00001", "response": {"status_code": 200, "body": response_body}, "error": None}
            results.write_text(json.dumps(batch_line, ensure_ascii=False) + "\n", encoding="utf-8")
            result = batch.parse_results(SimpleNamespace(results=results, input_csv=source, output=candidates))
            self.assertEqual(result, 0)
            parsed = [json.loads(line) for line in candidates.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(parsed[0]["issues"], [])
            self.assertIn("interrogation / inter-rog-ate-ion", parsed[0]["note"])
            self.assertIn("rog：问、请求（词根）", parsed[0]["note"])
            self.assertEqual(parsed[1]["note"], "")

    def test_historical_origin_text_is_rejected(self) -> None:
        item = {
            "word": "reform", "status": "ok", "confidence": "high", "spelling_note": "",
            "parts": [
                {"form": "re-", "type": "prefix", "meaning_zh": "源自拉丁语，重新"},
                {"form": "form", "type": "base", "meaning_zh": "形式"},
            ],
        }
        issues = batch.validate_item(item, {"reform"})
        self.assertIn("historical_etymology_in_meaning", issues)


if __name__ == "__main__":
    unittest.main()
