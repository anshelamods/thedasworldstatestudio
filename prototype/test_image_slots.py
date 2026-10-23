"""Frosty's mod constructor interprets the first five resources as images."""
import json
from pathlib import Path
import unittest

from export_worldstate import ROOT, read_mod, build_mod_values
from world_profiles import Catalog
from world_profiles.compiler import build_profile_mod
from test_fbmod_metadata import test_icon


class ImageSlotTests(unittest.TestCase):
    def test_all_presets_reserve_icon_and_four_screenshot_slots_before_game_data(self):
        catalog = Catalog()
        for preset in catalog.presets:
            for icon in (None, test_icon()):
                with self.subTest(preset=preset, custom_icon=icon is not None):
                    profile = catalog.create('Image layout', base_preset=preset, mode='experimental')
                    data, _ = build_profile_mod(profile, catalog=catalog, metadata={'icon': icon})
                    mod = read_mod(data)
                    self.assertEqual([record['name'] for record in mod['records'][:5]],
                                     ['Icon', 'Screenshot0', 'Screenshot1', 'Screenshot2', 'Screenshot3'])
                    self.assertTrue(all(record['kind'] == 0 for record in mod['records'][:5]))
                    self.assertEqual(mod['records'][5]['kind'], 1)
                    for record in mod['records'][:5]:
                        if record['index'] >= 0:
                            payload = mod['payloads'][record['index']]
                            self.assertTrue(payload.startswith((b'\x89PNG\r\n\x1a\n', b'\xff\xd8')))

    def test_sparse_original_template_is_unchanged_and_output_keeps_identical_game_asset(self):
        catalog = Catalog()
        profile = catalog.create('Default layout', mode='keep')
        template = catalog.template_path(profile.base_preset)
        before = template.read_bytes()
        self.assertEqual(len(read_mod(before)['records']), 2)
        output, _ = build_mod_values(before, {}, title='Layout-only check', explanation='No flag edits')
        self.assertEqual(template.read_bytes(), before)
        self.assertEqual(read_mod(output)['ebx'], read_mod(before)['ebx'])


if __name__ == '__main__':
    unittest.main()
