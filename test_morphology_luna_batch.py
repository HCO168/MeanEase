from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
            self.assertEqual(requests[0]["body"]["max_output_tokens"], 20000)
            self.assertEqual(requests[0]["body"]["text"]["format"]["type"], "json_schema")
            self.assertNotIn("etymology", output.read_text(encoding="utf-8").lower())

    def test_prepare_nano_uses_minimal_reasoning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "words.csv"
            output = root / "input.jsonl"
            self.write_csv(source, [{"word": "reform", "pos": "v./n.", "meaning": "改革；改正"}])
            result = batch.prepare(SimpleNamespace(
                input=source, output=output, batch_size=25, model="gpt-5-nano", reasoning_effort=None
            ))
            self.assertEqual(result, 0)
            request = json.loads(output.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(request["body"]["model"], "gpt-5-nano")
            self.assertEqual(request["body"]["reasoning"], {"effort": "minimal"})
            manifest = json.loads(output.with_suffix(".manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["reasoning_effort"], "minimal")

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

    def test_status_summary_counts_batches_and_requests(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "a-state.json").write_text(json.dumps({"batch_id": "batch-a", "model": "model-a"}), encoding="utf-8")
            (root / "b-state.json").write_text(json.dumps({"batch_id": "batch-b", "model": "model-b"}), encoding="utf-8")
            responses = {
                "/batches/batch-a": {"id": "batch-a", "status": "completed", "request_counts": {"total": 2, "completed": 2, "failed": 0}},
                "/batches/batch-b": {"id": "batch-b", "status": "in_progress", "request_counts": {"total": 3, "completed": 1, "failed": 0}},
            }
            output = io.StringIO()
            with patch.object(batch, "api_json", side_effect=lambda method, path: responses[path]), redirect_stdout(output):
                result = batch.status_summary(SimpleNamespace(state_dir=root, pattern="*-state.json"))
            self.assertEqual(result, 0)
            summary = json.loads(output.getvalue())
            self.assertEqual(summary["batch_count"], 2)
            self.assertEqual(summary["status_counts"], {"completed": 1, "in_progress": 1})
            self.assertEqual(summary["request_counts"], {"completed": 3, "failed": 0, "total": 5})
            self.assertEqual(summary["error_count"], 0)

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
