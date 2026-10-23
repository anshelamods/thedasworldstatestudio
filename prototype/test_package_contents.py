"""Packaged reachability must preserve every UI answer and category variation."""
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

import gui
from export_worldstate import ROOT, read_mod
from frostbite_reader import decode_cas
sys.path.insert(0, str(ROOT / 'assessment'))
from inspect_worldstates import decode_cas as inspection_decode_cas
from package_contents import asset_manifests, runtime_evidence
from world_profiles import Catalog
from world_profiles.catalog import CURRENT_MAPPING_VERSION
from world_profiles.model import read_json


class PackageContentsTests(unittest.TestCase):
    def test_runtime_evidence_subset_preserves_all_catalog_fingerprints(self):
        compact = runtime_evidence(ROOT)
        self.assertTrue(all(set(entry) == {'name', 'plot_guid', 'keep'} for entry in compact))
        def runtime_read(path):
            return compact if Path(path).name == 'worldstate-evidence.json' else read_json(path)
        for version in range(1, CURRENT_MAPPING_VERSION + 1):
            before = Catalog(version)
            with patch('world_profiles.catalog.read_json', side_effect=runtime_read):
                after = Catalog(version)
            self.assertEqual(before.sha256, after.sha256)
            self.assertEqual(before.flag_evidence, after.flag_evidence)

    def test_trimmed_manifests_preserve_all_runtime_choices_and_category_art_mappings(self):
        manifests, removed = asset_manifests(ROOT)
        self.assertEqual({entry['path'] for entry in removed}, {
            'assets/keep/da2_hawke_appearance/no_detail.jpg',
            'assets/keep/da2_hawke_appearance/yes_detail.jpg',
            'assets/keep/temp/daisoon2x2.jpg', 'assets/keep-interface/keep-tower.ico'})
        with tempfile.TemporaryDirectory(dir=ROOT / 'prototype') as temporary:
            directory = Path(temporary)
            original = gui.EditorApp(directory / 'original/profiles', directory / 'original/exports')
            for folder, manifest in manifests.items():
                target = directory / 'assets' / folder / 'manifest.json'
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(manifest), encoding='utf-8')
            with patch.object(gui, 'ROOT', directory):
                trimmed = gui.EditorApp(directory / 'trimmed/profiles', directory / 'trimmed/exports')
            self.assertEqual(trimmed.choices(), original.choices())
            self.assertEqual(trimmed.categories, original.categories)
            flags = {original.presentation[category['art_choice']].get('art_flag') for category in original.categories}
            for lookup in ('_category_media', '_media'):
                expected = {key: value for key, value in getattr(original, lookup).items() if key[0] in flags}
                self.assertEqual(expected, {key: value for key, value in getattr(trimmed, lookup).items() if key[0] in flags})

    def test_runtime_cas_reader_matches_all_reviewed_original_payloads(self):
        templates = json.loads((ROOT / 'prototype/supported-templates.json').read_text())
        for entry in templates:
            mod = read_mod((ROOT / entry['path']).read_bytes())
            packed = mod['payloads'][mod['target']['index']]
            self.assertEqual(decode_cas(packed), inspection_decode_cas(packed))


if __name__ == '__main__':
    unittest.main()
