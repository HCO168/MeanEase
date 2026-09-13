from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import apply_morphology_candidates as apply


FIELDS = ['word', 'morphology', 'morphology_source', 'morphology_license']


class ApplyMorphologyCandidatesTests(unittest.TestCase):
    def write_csv(self, path: Path) -> None:
        with path.open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerow({'word': 'poster', 'morphology': '', 'morphology_source': '', 'morphology_license': ''})
            writer.writerow({'word': 'window', 'morphology': '', 'morphology_source': '', 'morphology_license': ''})

    def test_accepted_requires_clean_high_ok_note(self) -> None:
        base = {'status': 'ok', 'confidence': 'high', 'issues': [], 'warnings': [], 'note': 'poster / post-er'}
        self.assertTrue(apply.accepted(base))
        self.assertFalse(apply.accepted({**base, 'warnings': ['possible_productive_affix_split']}))
        self.assertFalse(apply.accepted({**base, 'confidence': 'medium'}))
        self.assertFalse(apply.accepted({**base, 'status': 'not_decomposable', 'note': ''}))

    def test_main_applies_only_accepted_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.csv'
            candidates = root / 'candidates.jsonl'
            output = root / 'output.csv'
            self.write_csv(source)
            items = [
                {'word': 'poster', 'status': 'ok', 'confidence': 'high', 'issues': [], 'warnings': [], 'note': 'poster / post-er'},
                {'word': 'window', 'status': 'not_decomposable', 'confidence': 'high', 'issues': [], 'warnings': [], 'note': ''},
            ]
            candidates.write_text('\n'.join(json.dumps(item) for item in items) + '\n', encoding='utf-8')
            argv = ['apply', '--input', str(source), '--candidates', str(candidates), '--output', str(output), '--expected-accepted', '1']
            with patch.object(sys, 'argv', argv):
                self.assertEqual(apply.main(), 0)
            with output.open(encoding='utf-8-sig', newline='') as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]['morphology'], 'poster / post-er')
            self.assertTrue(rows[0]['morphology_source'])
            self.assertTrue(rows[0]['morphology_license'])
            self.assertEqual(rows[1]['morphology'], '')


if __name__ == '__main__':
    unittest.main()
