"""Literal Sten/Dagna mappings and preservation of independently editable history."""
from itertools import product
from pathlib import Path
import tempfile
import unittest

from export_worldstate import ROOT, EbxParser, read_mod
from world_profiles import Catalog, ProfileStore
from world_profiles.compiler import build_profile_mod, compile_profile


GROUPS = ('dao.sten_recruited', 'dao.sten_release', 'dao.sten_sword', 'dao.dagna_outcome', 'dao.dagna_permission')
ANSWERS = (('not_recruited', 'recruited'), ('not_freed', 'picked_lock', 'persuaded', 'intimidated'),
           ('not_recruited', 'not_returned', 'returned'), ('not_met', 'refused', 'stayed', 'studied', 'circle_destroyed'),
           ('not_requested', 'requested'))
FIELDS = ('dao_sten_recruited', 'dao_lot_qunari_prisoner', 'dao_sten_sword',
          'dao_par_unlikely_scholar', 'dao_par_dagna_circle')


class StenDagnaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def test_all_240_combinations_serialize_exact_documented_values(self):
        for values in product(range(2), range(4), range(3), range(5), range(2)):
            choices = {group: answers[value] for group, answers, value in zip(GROUPS, ANSWERS, values)}
            with self.subTest(choices=choices):
                profile = self.catalog.create('Sten and Dagna', mode='ordinary', choices=choices)
                mod, report = build_profile_mod(profile, catalog=self.catalog)
                flags = {obj['value']['VariableNameOnServer']: obj['value']['DefaultValue']
                         for obj in EbxParser(read_mod(mod)['ebx']).parse()['objects'] if obj['class'] == 'GameVaultVarInt'}
                self.assertEqual({field: flags[field] for field in FIELDS}, dict(zip(FIELDS, values)))
                self.assertEqual(dict(profile.choices), choices)
                self.assertEqual(report['profile']['story_conflicts'], [])
                self.assertFalse(report['profile']['gameplay_tested'])

    def test_all_single_edits_preserve_every_other_flag_and_range_in_nine_bases(self):
        for preset in self.catalog.presets:
            original = self.catalog.create('Inherited history', base_preset=preset, mode='experimental')
            before = compile_profile(original, catalog=self.catalog)
            for group, field in zip(GROUPS, FIELDS):
                for answer in self.catalog.choices[group]['answers']:
                    with self.subTest(preset=preset, group=group, answer=answer):
                        after = compile_profile(original.edited(choices={group: answer}), catalog=self.catalog)
                        self.assertEqual({name: value for name, value in after.effective_values.items() if name != field},
                                         {name: value for name, value in before.effective_values.items() if name != field})
                        self.assertEqual(after.max_overrides, before.max_overrides)
                        self.assertEqual(after.report['resolved_choices'][group]['answer_id'], answer)

    def test_all_eight_released_payloads_reproduce_including_dagna_four_permission_one(self):
        choices = dict(zip(GROUPS, ('recruited', 'persuaded', 'returned', 'circle_destroyed', 'requested')))
        for preset in self.catalog.presets:
            if not preset.startswith('template-'):
                continue
            original = self.catalog.create('Released world', base_preset=preset, mode='experimental')
            resolved = compile_profile(original, catalog=self.catalog).report['resolved_choices']
            self.assertEqual({group: resolved[group]['answer_id'] for group in GROUPS}, choices)
            mod, _ = build_profile_mod(original.edited(choices=choices), catalog=self.catalog)
            self.assertEqual(read_mod(mod)['ebx'], read_mod(self.catalog.template_path(preset).read_bytes())['ebx'])

    def test_catalog_ten_upgrade_preserves_all_bases_existing_companions_and_full_payload(self):
        old = Catalog(mapping_version=10)
        for preset in old.presets:
            for choices in ({}, {'dao.leliana_fate': 'left_after_urn', 'dao.wynne_fate': 'died_at_circle',
                                'dao.zevran_fate': 'dead', 'dao.warden_romance': 'zevran'}):
                with self.subTest(preset=preset, choices=choices):
                    original = old.create('Before Sten and Dagna', base_preset=preset, mode='experimental', choices=choices)
                    before, _ = build_profile_mod(original, catalog=self.catalog)
                    upgraded = self.catalog.upgrade(original)
                    after, _ = build_profile_mod(upgraded, catalog=self.catalog)
                    self.assertEqual(read_mod(before)['ebx'], read_mod(after)['ebx'])
                    self.assertEqual(original.choices, upgraded.choices)

    def test_saving_an_upgrade_retains_historical_revision_bytes_and_catalog(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'prototype', prefix='.sten-dagna-test-') as directory:
            old = ProfileStore(directory, catalog=Catalog(mapping_version=10))
            original = old.create('Existing history')
            path = old.profile_directory(original.profile_id) / 'History/00000001.json'
            raw = path.read_bytes()
            upgraded = self.catalog.upgrade(original)
            self.assertEqual(path.read_bytes(), raw)
            store = ProfileStore(directory, catalog=self.catalog)
            saved = store.save(upgraded.edited(choices={'dao.sten_release': 'picked_lock'}))
            self.assertEqual(saved.revision, 2)
            self.assertEqual(saved.mapping_version, self.catalog.version)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(store.load(original.profile_id, revision=1), original)

    def test_dagna_outcome_and_permission_never_change_circle_class_or_other_history(self):
        for player_class, circle in product(('warrior', 'rogue', 'mage'), ('mages', 'templars')):
            original = self.catalog.create('Independent Circle history', mode='ordinary',
                choices={'dao.warden_class': player_class, 'dao.broken_circle': circle})
            before = compile_profile(original, catalog=self.catalog)
            for outcome, permission in product(ANSWERS[3], ANSWERS[4]):
                choices = dict(original.choices, **{'dao.dagna_outcome': outcome, 'dao.dagna_permission': permission})
                after = compile_profile(original.edited(choices=choices), catalog=self.catalog)
                self.assertEqual(after.report['story_conflicts'], [])
                for field, value in before.effective_values.items():
                    if field not in FIELDS[3:]:
                        self.assertEqual(after.effective_values[field], value)
                self.assertEqual(after.report['resolved_choices']['dao.dagna_outcome']['answer_id'], outcome)
                self.assertEqual(after.report['resolved_choices']['dao.dagna_permission']['answer_id'], permission)


if __name__ == '__main__':
    unittest.main(verbosity=2)
