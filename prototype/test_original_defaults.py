"""Original-asset baseline, optional presets, and immutable historical exports."""
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from export_worldstate import LocatedEbxParser, ROOT, read_mod
from gui import EditorApp
from world_profiles import Catalog, ProfileStore
from world_profiles.compiler import StoryConflict, build_profile_mod, compile_profile
from world_profiles.story_rules import propose


class OriginalDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog()

    def test_default_export_changes_only_three_played_fields_in_original_binary(self):
        source = (ROOT / 'BWWorldStateConfigAsset.bin').read_bytes()
        expected = bytearray(source)
        parser = LocatedEbxParser(source)
        parser.parse()
        played = {'dao_played', 'da2_played', 'dao_or_da2_played'}
        for entry in parser.variables:
            if entry['value']['VariableNameOnServer'] in played:
                struct.pack_into('<i', expected, entry['fields']['DefaultValue'], 1)
        profile = self.catalog.create('Original defaults', mode='keep')
        self.assertEqual(profile.base_preset, 'original-game-v1')
        self.assertEqual(dict(profile.choices), {})
        compiled = compile_profile(profile, catalog=self.catalog)
        self.assertEqual(dict(compiled.values), {field: 1 for field in played})
        data, _ = build_profile_mod(profile, catalog=self.catalog)
        mod = read_mod(data)
        self.assertEqual(mod['ebx'], bytes(expected))
        self.assertEqual(len(mod['records']), 6)
        self.assertNotIn('Cousland', '\n'.join(mod['details']))
        xml = ET.fromstring('<Export>' + (ROOT / 'BWWorldStateConfigAsset.xml').read_text(encoding='utf-8-sig') + '</Export>')
        xml_values = {entry.findtext('VariableNameOnServer'): int(entry.findtext('DefaultValue'), 0)
                      for entry in xml.findall('GameVaultVarInt')}
        self.assertEqual(dict(compiled.effective_values), {**xml_values, **{field: 1 for field in played}})

    def test_new_history_lists_default_and_two_optional_presets_and_works_without_original_mod_folder(self):
        original_read = Path.read_bytes
        def isolated_read(path):
            self.assertNotIn('Customized Worldstates', path.parts)
            return original_read(path)
        with tempfile.TemporaryDirectory(dir=ROOT / 'prototype') as directory, patch.object(Path, 'read_bytes', isolated_read):
            app = EditorApp(Path(directory) / 'profiles', Path(directory) / 'exports')
            boot = app.bootstrap()
            self.assertEqual(boot['default_preset'], 'original-game-v1')
            self.assertEqual(len(boot['presets']), 3)
            for entry in boot['presets']:
                profile = self.catalog.create('Starting history', base_preset=entry['id'], mode='experimental')
                data, _ = build_profile_mod(profile, catalog=self.catalog)
                self.assertEqual(len(read_mod(data)['ebx']), 84848)
            settings = app.export_settings()
            self.assertEqual(settings['category'], 'World States')
            self.assertIsNone(settings['preset_icon_data_url'])
            store = ProfileStore(Path(directory) / 'saved', catalog=self.catalog)
            self.assertEqual(store.create('New default').base_preset, 'original-game-v1')

    def test_catalog41_profiles_reopen_and_upgrade_without_changed_flags_or_payload(self):
        previous = Catalog(41)
        for preset in previous.presets:
            with self.subTest(preset=preset):
                old = previous.create('Saved history', base_preset=preset, mode='experimental', choices={'da2.anders_fate': 'executed'})
                old_data, _ = build_profile_mod(old, catalog=previous)
                for profile in (old, self.catalog.upgrade(old)):
                    data, _ = build_profile_mod(profile, catalog=self.catalog)
                    self.assertEqual(read_mod(data)['ebx'], read_mod(old_data)['ebx'])
                    self.assertEqual(profile.base_preset, preset)

    def test_untouched_original_isabela_is_preserved_and_explicit_edit_requires_repair(self):
        profile = self.catalog.create('Default history', mode='keep')
        before = compile_profile(profile, catalog=self.catalog)
        self.assertEqual(before.effective_values['da2_isabela_joined'], 1)
        self.assertEqual(before.effective_values['da2_isabela_returned_with_book'], 0)
        with tempfile.TemporaryDirectory(dir=ROOT / 'prototype') as directory:
            app = EditorApp(Path(directory) / 'profiles', Path(directory) / 'exports')
            unrelated = propose(profile, {'da2.hawke_personality': 'humourous'}, mode='keep', catalog=self.catalog, editable=app.presentation)
            self.assertEqual(dict(unrelated.choices), {'da2.hawke_personality': 'humourous'})
            repaired = propose(profile, {'da2.isabela_recruited': 'recruited'}, mode='keep', catalog=self.catalog, editable=app.presentation)
            self.assertIn('da2.isabela_book', repaired.choices)
            compile_profile(repaired, catalog=self.catalog)
            with self.assertRaises(StoryConflict):
                compile_profile(profile.edited(choices={'da2.isabela_recruited': 'recruited'}), catalog=self.catalog)


if __name__ == '__main__':
    unittest.main()
