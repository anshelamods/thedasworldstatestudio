"""Origins Prologue and Dog choices, independent history and immutable older profiles."""
from itertools import product
from pathlib import Path
import tempfile
import unittest

from export_worldstate import ROOT, read_mod
from world_profiles import Catalog, ProfileStore
from world_profiles.compiler import build_profile_mod, compile_profile
from test_da2_main_story import flags_from_mod


CASES = {
    'dao.ostagar_deserter': (('dao_pre_hungry_deserter',), {'left_alone': (0,), 'killed': (1,), 'stolen_food': (2,), 'guards_lunch': (3,), 'bought_food': (4,), 'stolen_key': (5,)}),
    'dao.ostagar_mabari': (('dao_pre_mabari_hound',), {'not_helped': (0,), 'cured': (1,), 'killed': (2,)}),
    'dao.dog_recruited': (('dao_dog_recruited',), {'not_recruited': (0,), 'recruited': (1,)})}


class OriginsPrologueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def test_36_combinations_compile_across_nine_bases_and_roundtrip_baseline(self):
        for preset in self.catalog.presets:
            for answers in product(*(definition[1] for definition in CASES.values())):
                choices = dict(zip(CASES, answers))
                with self.subTest(preset=preset, choices=choices):
                    profile = self.catalog.create('Ostagar history', base_preset=preset,
                                                  mode='ordinary', choices=choices)
                    compiled = compile_profile(profile, catalog=self.catalog)
                    for group, (fields, expected) in CASES.items():
                        self.assertEqual(tuple(compiled.effective_values[n] for n in fields), expected[choices[group]])
                    self.assertEqual(compiled.report['story_conflicts'], [])
                    if not preset.startswith('template-'):
                        mod, report = build_profile_mod(profile, catalog=self.catalog)
                        flags = flags_from_mod(mod)
                        for group, (fields, expected) in CASES.items():
                            self.assertEqual(tuple(flags[n]['DefaultValue'] for n in fields), expected[choices[group]])
                        self.assertFalse(report['profile']['gameplay_tested'])

    def test_single_edits_preserve_every_unowned_value_and_range(self):
        for preset in self.catalog.presets:
            original = self.catalog.create('Inherited history', base_preset=preset, mode='experimental')
            before = compile_profile(original, catalog=self.catalog)
            for group, (owned, answers) in CASES.items():
                for answer in answers:
                    after = compile_profile(original.edited(choices={group: answer}), catalog=self.catalog)
                    self.assertEqual({n: v for n, v in before.effective_values.items() if n not in owned},
                                     {n: v for n, v in after.effective_values.items() if n not in owned})
                    self.assertEqual(after.max_overrides, before.max_overrides)
                    self.assertEqual(after.report['resolved_choices'][group]['answer_id'], answer)

    def test_all_released_ostagar_dog_selections_reproduce_exact_payloads(self):
        for preset in self.catalog.presets:
            if not preset.startswith('template-'):
                continue
            profile = self.catalog.create('Released history', base_preset=preset, mode='experimental')
            resolved = compile_profile(profile, catalog=self.catalog).report['resolved_choices']
            choices = {group: resolved[group]['answer_id'] for group in CASES}
            self.assertEqual(choices, {'dao.ostagar_deserter': 'left_alone', 'dao.ostagar_mabari': 'cured', 'dao.dog_recruited': 'recruited'})
            mod, _ = build_profile_mod(profile.edited(choices=choices), catalog=self.catalog)
            self.assertEqual(read_mod(mod)['ebx'], read_mod(self.catalog.template_path(preset).read_bytes())['ebx'])

    def test_v26_upgrade_preserves_payloads_and_immutable_revision_bytes(self):
        old = Catalog(mapping_version=26)
        for preset in old.presets:
            original = old.create('Older history', base_preset=preset, mode='experimental',
                choices={'da2.final_allegiance': 'templars', 'da2.fenris_fate': 'pursued', 'da2.bone_pit_dragon': 'killed',
                         'da2.bethany_fate': 'warden', 'da2.bethany_final_battle': 'died', 'da2.tallis_reaction': 'never_met'})
            upgraded = self.catalog.upgrade(original)
            before, _ = build_profile_mod(original, catalog=self.catalog)
            after, _ = build_profile_mod(upgraded, catalog=self.catalog)
            self.assertEqual(read_mod(before)['ebx'], read_mod(after)['ebx'])
            self.assertEqual(original.choices, upgraded.choices)
        with tempfile.TemporaryDirectory(dir=ROOT / 'prototype', prefix='.dao-prologue-test-') as directory:
            store = ProfileStore(directory, catalog=old)
            original = store.create('Old revision', choices={'da2.anders_approval': 'approved'})
            path = store.profile_directory(original.profile_id) / 'History/00000001.json'
            raw = path.read_bytes()
            upgraded = self.catalog.upgrade(original)
            current = ProfileStore(directory, catalog=self.catalog)
            saved = current.save(upgraded.edited(choices=dict(upgraded.choices, **{'dao.ostagar_deserter': 'stolen_key'})))
            self.assertEqual(saved.mapping_version, self.catalog.version)
            self.assertEqual(saved.revision, 2)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(current.load(original.profile_id, revision=1), original)

    def test_dog_and_hound_are_independent_for_every_warden_identity_and_class(self):
        owned = {'dao_dog_recruited', 'dao_pre_mabari_hound'}
        for identity, player_class in product(self.catalog.choices['dao.warden_identity']['answers'], ('warrior', 'rogue', 'mage')):
            original = self.catalog.create('Independent origin and recruitment', choices={
                'dao.warden_identity': identity, 'dao.warden_class': player_class,
                'dao.warden_romance': 'leliana', 'da2.hawke_identity': 'female_mage',
                'da2.bethany_fate': 'warden', 'da2.carver_fate': 'warden',
                'da2.bethany_final_battle': 'died', 'da2.tallis_reaction': 'never_met',
                'da2.bone_pit_dragon': 'killed'})
            before = compile_profile(original, catalog=self.catalog)
            for dog, hound in product(('not_recruited', 'recruited'), ('not_helped', 'cured', 'killed')):
                profile = original.edited(choices=dict(original.choices, **{'dao.dog_recruited': dog, 'dao.ostagar_mabari': hound}))
                after = compile_profile(profile, catalog=self.catalog)
                self.assertEqual(after.report['story_conflicts'], [])
                self.assertEqual({n: v for n, v in before.effective_values.items() if n not in owned},
                                 {n: v for n, v in after.effective_values.items() if n not in owned})
                self.assertEqual(after.max_overrides, before.max_overrides)
                self.assertEqual(after.effective_values['dao_dog_recruited'], int(dog == 'recruited'))
                self.assertEqual(after.effective_values['dao_pre_mabari_hound'], {'not_helped': 0, 'cured': 1, 'killed': 2}[hound])

    def test_inherited_mabari_values_three_and_four_are_preserved_without_guessing(self):
        for legacy in (3, 4):
            catalog = Catalog()
            catalog._presets[catalog.default_preset]['export_values']['dao_pre_mabari_hound'] = legacy
            profile = catalog.create('Legacy hound value')
            before = compile_profile(profile, catalog=catalog)
            self.assertIsNone(before.report['resolved_choices']['dao.ostagar_mabari']['answer_id'])
            for dog in ('not_recruited', 'recruited'):
                mod, _ = build_profile_mod(profile.edited(choices={'dao.dog_recruited': dog}), catalog=catalog)
                flag = flags_from_mod(mod)['dao_pre_mabari_hound']
                self.assertEqual((flag['DefaultValue'], flag['MinValue'], flag['MaxValue']), (legacy, 0, 4))
            for hound, expected in [('not_helped', 0), ('cured', 1), ('killed', 2)]:
                mod, _ = build_profile_mod(profile.edited(choices={'dao.ostagar_mabari': hound}), catalog=catalog)
                flag = flags_from_mod(mod)['dao_pre_mabari_hound']
                self.assertEqual((flag['DefaultValue'], flag['MaxValue']), (expected, 4))


if __name__ == '__main__':
    unittest.main(verbosity=2)
