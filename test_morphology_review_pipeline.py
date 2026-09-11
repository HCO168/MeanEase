#!/usr/bin/env python3
"""Regression tests for the manual morphology-review guardrails."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from morphology_review_pipeline import (
    ENGRA_LICENSE,
    ENGRA_SOURCE,
    WIKTIONARY_LICENSE,
    canonical_wiktionary_source,
    is_allowed_manual_source,
    merge_reviews,
    prepare_batches,
    validate_etymology,
)


FIELDS = ["word", "base_word", "meaning", "etymology", "etymology_source", "etymology_license"]


def write_fixture(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


class MorphologyReviewPipelineTests(unittest.TestCase):
    def test_rejects_inflection_and_duplicate_origin_nodes(self) -> None:
        detailed = "detailed / de-tail-ed；de-：向下；tail：切割；-ed：过去式；detailed：详细的。"
        errors = validate_etymology("detailed", detailed, ENGRA_SOURCE, ENGRA_LICENSE)
        self.assertTrue(any("屈折" in error for error in errors))
        social = "social：源自中古法语 social，可追溯至法语 social；今义：社会的。"
        errors = validate_etymology("social", social, canonical_wiktionary_source("social"), WIKTIONARY_LICENSE)
        self.assertTrue(any("重复" in error for error in errors))

    def test_accepts_manually_verified_wiktionary_formation_and_borrowing(self) -> None:
        within = "within / with-in；with：和、与；in：在……内；within：在……之内。"
        self.assertEqual(
            validate_etymology("within", within, canonical_wiktionary_source("within"), WIKTIONARY_LICENSE), []
        )
        they = "they：借自中古英语 þei，源自古诺斯语 þeir；今义：他们、它们。"
        self.assertEqual(
            validate_etymology("they", they, canonical_wiktionary_source("they"), WIKTIONARY_LICENSE), []
        )
        pm = "pm：缩写自 post meridiem；今义：下午、傍晚。"
        self.assertEqual(
            validate_etymology("pm", pm, canonical_wiktionary_source("pm"), WIKTIONARY_LICENSE), []
        )
        ok = "OK：英语缩写 O.K.（oll korrect）；今义：好、可以。"
        self.assertEqual(
            validate_etymology("ok", ok, canonical_wiktionary_source("ok"), WIKTIONARY_LICENSE), []
        )
        motel = "motel：由 motor 和 hotel 混合而来；今义：汽车旅馆。"
        self.assertEqual(
            validate_etymology("motel", motel, canonical_wiktionary_source("motel"), WIKTIONARY_LICENSE), []
        )

    def test_allows_only_case_variant_of_verified_wiktionary_title(self) -> None:
        self.assertTrue(
            is_allowed_manual_source(
                "brazilian", "https://en.wiktionary.org/wiki/Brazilian", WIKTIONARY_LICENSE
            )
        )
        self.assertFalse(
            is_allowed_manual_source(
                "brazilian", "https://en.wiktionary.org/wiki/Brazil", WIKTIONARY_LICENSE
            )
        )
        self.assertFalse(
            is_allowed_manual_source(
                "brazilian", "https://en.wiktionary.org/wiki/brazilians", WIKTIONARY_LICENSE
            )
        )

    def test_merges_only_complete_manual_review_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = temporary / "source.csv"
            write_fixture(source, [
                {
                    "word": "reform", "base_word": "reform", "meaning": "v. 改革",
                    "etymology": "旧说明", "etymology_source": ENGRA_SOURCE, "etymology_license": ENGRA_LICENSE,
                },
                {
                    "word": "social", "base_word": "social", "meaning": "adj. 社会的",
                    "etymology": "旧的错误拆分", "etymology_source": ENGRA_SOURCE, "etymology_license": ENGRA_LICENSE,
                },
            ])
            review_dir = temporary / "review"
            manifest = prepare_batches(source, review_dir, batch_size=2)
            batch_id = manifest["batches"][0]["id"]
            response_records = [
                {
                    "batch_id": batch_id, "word_key": "reform", "word": "reform", "status": "accepted",
                    "note": "reform / re-form；re-：重新、再次；form：形式、组成；reform：改革。",
                    "source_basis": ENGRA_SOURCE, "source_license": ENGRA_LICENSE,
                    "evidence_summary": "人工核对 form 词族中 reform 的派生关系。", "review_flags": [],
                },
                {
                    "batch_id": batch_id, "word_key": "social", "word": "social", "status": "accepted",
                    "note": "social：源自拉丁语 socialis；今义：社会的。",
                    "source_basis": canonical_wiktionary_source("social"), "source_license": WIKTIONARY_LICENSE,
                    "evidence_summary": "人工核对 social 的 Wiktionary 词源条目，替换不支持该说明的旧自动来源。", "review_flags": [],
                },
            ]
            response_path = review_dir / "responses" / f"{batch_id}.jsonl"
            response_path.write_text(
                "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in response_records), encoding="utf-8"
            )
            output = temporary / "output.csv"
            report = merge_reviews(source, review_dir / "manifest.json", review_dir / "responses", output, None)
            self.assertEqual(report["review_status_counts"], {"accepted": 2})
            with output.open(encoding="utf-8-sig", newline="") as handle:
                output_rows = {row["word"]: row for row in csv.DictReader(handle)}
            self.assertEqual(output_rows["reform"]["etymology_source"], ENGRA_SOURCE)
            self.assertEqual(output_rows["social"]["etymology_source"], canonical_wiktionary_source("social"))
            self.assertIn("拉丁语 socialis", output_rows["social"]["etymology"])

    def test_selected_batch_merge_ignores_other_pending_batches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = temporary / "source.csv"
            write_fixture(source, [
                {
                    "word": "reform", "base_word": "reform", "meaning": "v. 改革",
                    "etymology": "旧说明", "etymology_source": ENGRA_SOURCE, "etymology_license": ENGRA_LICENSE,
                },
                {
                    "word": "social", "base_word": "social", "meaning": "adj. 社会的",
                    "etymology": "", "etymology_source": "", "etymology_license": "",
                },
            ])
            review_dir = temporary / "review"
            manifest = prepare_batches(source, review_dir, batch_size=1)
            selected_batch = manifest["batches"][0]["id"]
            response = {
                "batch_id": selected_batch, "word_key": "reform", "word": "reform", "status": "accepted",
                "note": "reform / re-form；re-：重新、再次；form：形式、组成；reform：改革。",
                "source_basis": ENGRA_SOURCE, "source_license": ENGRA_LICENSE,
                "evidence_summary": "人工核对 form 词族。", "review_flags": [],
            }
            (review_dir / "responses" / "selected.jsonl").write_text(
                json.dumps(response, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            pending_batch = manifest["batches"][1]["id"]
            (review_dir / "responses" / "pending.jsonl").write_text(
                json.dumps({"batch_id": pending_batch}, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            output = temporary / "output.csv"
            report = merge_reviews(
                source, review_dir / "manifest.json", review_dir / "responses", output, None, {selected_batch}
            )
            self.assertEqual(report["completed_batches"], [selected_batch])


if __name__ == "__main__":
    unittest.main()
