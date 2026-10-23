"""Political controls preserve unrelated flags and historical payloads."""
import json
from pathlib import Path
import tempfile
import unittest

from export_worldstate import ROOT, EbxParser, read_mod
from world_profiles import Catalog, ProfileStore, UnsupportedVersion
from world_profiles.compiler import StoryConflict, build_profile_mod, compile_profile


GROUPS = ('dao.ferelden_ruler', 'dao.alistair_fate', 'dao.alistair_relationship')


class PoliticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def test_each_political_answer_exports_and_preserves_all_unowned_flags_in_all_bases(self):
        for preset in self.catalog.presets:
            original = self.catalog.create('Base', base_preset=preset, mode='experimental')
            before = compile_profile(original, catalog=self.catalog)
            for group in GROUPS:
                for answer_id, answer in self.catalog.choices[group]['answers'].items():
                    with self.subTest(preset=preset, group=group, answer=answer_id):
                        profile = original.edited(choices={group: answer_id})
                        after = compile_profile(profile, catalog=self.catalog)
                        for flag, value in before.effective_values.items():
                            if flag not in answer['export_values']:
                                self.assertEqual(after.effective_values[flag], value, flag)
                        self.assertEqual(after.report['resolved_choices'][group]['answer_id'], answer_id)
                        self.assertFalse(after.report['gameplay_tested'])
        # Check every serialized answer as well as the in-memory compiler.
        for group in GROUPS:
            for answer_id, answer in self.catalog.choices[group]['answers'].items():
                profile = self.catalog.create('Serialized politics', mode='experimental', choices={group: answer_id})
                mod, report = build_profile_mod(profile, catalog=self.catalog)
                objects = EbxParser(read_mod(mod)['ebx']).parse()['objects']
                flags = {o['value']['VariableNameOnServer']: o['value'] for o in objects if o['class'] == 'GameVaultVarInt'}
                for name, value in answer['export_values'].items():
                    self.assertEqual(flags[name]['DefaultValue'], value)
                for name, maximum in answer.get('max_value_overrides', {}).items():
                    self.assertEqual(flags[name]['MaxValue'], maximum)

    def test_supported_ruling_arrangements_and_alistair_fates_can_be_selected_separately(self):
        for ruler in self.catalog.choices['dao.ferelden_ruler']['answers']:
            royal = ruler.startswith('alistair_')
            for fate in ('king',) if royal else ('sacrificed', 'executed', 'warden', 'drunk'):
                for relationship in self.catalog.choices['dao.alistair_relationship']['answers']:
                    with self.subTest(ruler=ruler, fate=fate, relationship=relationship):
                        choices = dict(zip(GROUPS, (ruler, fate, relationship)))
                        profile = self.catalog.create('Separate controls', choices=choices)
                        compiled = compile_profile(profile, catalog=self.catalog)
                        self.assertEqual(dict(profile.choices), choices)
                        self.assertEqual(compiled.report['story_conflicts'], [])
                        self.assertEqual(compiled.effective_values['dao_alistair_royal_status'], int(royal))

    def test_ordinary_mode_explains_crown_fate_conflicts_without_rewriting_choices(self):
        choices = {'dao.ferelden_ruler': 'anora_alone', 'dao.alistair_fate': 'king'}
        profile = self.catalog.create('Contradictory politics', choices=choices)
        with self.assertRaisesRegex(StoryConflict, 'disagree about whether Alistair is king'):
            compile_profile(profile, catalog=self.catalog)
        compiled = compile_profile(profile.edited(mode='experimental'), catalog=self.catalog)
        self.assertEqual(dict(profile.choices), choices)
        self.assertEqual(compiled.effective_values['dao_ruler_state'], 3)
        self.assertEqual(compiled.effective_values['dao_alistair_state'], 2)
        self.assertTrue(compiled.report['story_conflicts'])

    def test_legacy_leadership_splits_losslessly_across_all_bases_and_catalogs(self):
        for version in range(1, 6):
            old = Catalog(mapping_version=version)
            presets = old.presets if version == 5 else ['early-tests-v1']
            for preset in presets:
                for answer in old.choices['dao.ferelden_leadership']['answers']:
                    with self.subTest(version=version, preset=preset, answer=answer):
                        profile = old.create('Existing politics', base_preset=preset, mode='experimental',
                                             choices={'dao.ferelden_leadership': answer})
                        before, _ = build_profile_mod(profile, catalog=self.catalog)
                        upgraded = self.catalog.upgrade(profile)
                        after, _ = build_profile_mod(upgraded, catalog=self.catalog)
                        self.assertEqual(read_mod(before)['ebx'], read_mod(after)['ebx'])
                        self.assertNotIn('dao.ferelden_leadership', upgraded.choices)
                        self.assertEqual(set(upgraded.choices), set(GROUPS))

    def test_upgrade_keeps_saved_revision_immutable(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'prototype', prefix='.politics-test-') as directory:
            old_store = ProfileStore(directory, catalog=Catalog(mapping_version=5))
            original = old_store.create('Before politics expansion', choices={'dao.ferelden_leadership': 'alistair_king_alone'})
            path = old_store.profile_directory(original.profile_id) / 'History/00000001.json'
            original_bytes = path.read_bytes()
            upgraded = self.catalog.upgrade(original)
            self.assertEqual(path.read_bytes(), original_bytes)
            current = ProfileStore(directory, catalog=self.catalog)
            saved = current.save(upgraded)
            self.assertEqual(saved.revision, 2)
            self.assertEqual(saved.mapping_version, self.catalog.version)
            self.assertEqual(path.read_bytes(), original_bytes)
            self.assertEqual(current.load(original.profile_id, revision=1), original)

    def test_split_conversion_refuses_a_game_flag_change(self):
        old = Catalog(mapping_version=5).create('Old politics', choices={'dao.ferelden_leadership': 'alistair_king_alone'})
        changed = Catalog()
        changed._choices['dao.ferelden_ruler']['answers']['alistair_alone']['export_values']['dao_anora_queen_alone'] = 1
        with self.assertRaisesRegex(UnsupportedVersion, 'would change game flags'):
            changed.upgrade(old)


if __name__ == '__main__':
    unittest.main(verbosity=2)
