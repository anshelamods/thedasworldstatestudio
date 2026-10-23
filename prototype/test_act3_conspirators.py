"""Act III conspirators, Emile and Keran mapping tuples, independent history and immutable older profiles."""
from itertools import product
from pathlib import Path
import tempfile
import unittest

from export_worldstate import ROOT, read_mod
from world_profiles import Catalog, ProfileStore
from world_profiles.compiler import build_profile_mod, compile_profile
from test_da2_main_story import flags_from_mod


CASES = {
    'da2.conspirators': (('da2_act3_conspirators_end',), {'orsino': (0,), 'meredith': (1,)}),
    'da2.emile_fate': (('da2_act3_emile_end',), {'circle': (0,), 'freed': (1,)}),
    'da2.keran_fate': (('da2_act3_keran_end',), {'released': (0,), 'killed': (1,), 'templars': (2,)})}


class ActThreeConspiratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def test_twelve_combinations_roundtrip_across_nine_bases(self):
        for preset in self.catalog.presets:
            for answers in product(*(definition[1] for definition in CASES.values())):
                choices = dict(zip(CASES, answers))
                with self.subTest(preset=preset, choices=choices):
                    profile = self.catalog.create('Act III history', base_preset=preset,
                                                  mode='ordinary', choices=choices)
                    mod, report = build_profile_mod(profile, catalog=self.catalog)
                    flags = flags_from_mod(mod)
                    for group, (fields, expected) in CASES.items():
                        self.assertEqual(tuple(flags[n]['DefaultValue'] for n in fields), expected[choices[group]])
                    self.assertEqual(report['profile']['story_conflicts'], [])
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

    def test_all_released_act_three_selections_reproduce_exact_payloads(self):
        for preset in self.catalog.presets:
            if not preset.startswith('template-'):
                continue
            profile = self.catalog.create('Released history', base_preset=preset, mode='experimental')
            resolved = compile_profile(profile, catalog=self.catalog).report['resolved_choices']
            choices = {group: resolved[group]['answer_id'] for group in CASES}
            self.assertEqual(choices, {'da2.conspirators': 'orsino', 'da2.emile_fate': 'freed', 'da2.keran_fate': 'released'})
            mod, _ = build_profile_mod(profile.edited(choices=choices), catalog=self.catalog)
            self.assertEqual(read_mod(mod)['ebx'], read_mod(self.catalog.template_path(preset).read_bytes())['ebx'])

    def test_v18_upgrade_preserves_payloads_and_immutable_revision_bytes(self):
        old = Catalog(mapping_version=18)
        for preset in old.presets:
            original = old.create('Older history', base_preset=preset, mode='experimental',
                choices={'da2.final_allegiance': 'templars', 'da2.fenris_fate': 'pursued'})
            upgraded = self.catalog.upgrade(original)
            before, _ = build_profile_mod(original, catalog=self.catalog)
            after, _ = build_profile_mod(upgraded, catalog=self.catalog)
            self.assertEqual(read_mod(before)['ebx'], read_mod(after)['ebx'])
            self.assertEqual(original.choices, upgraded.choices)
        with tempfile.TemporaryDirectory(dir=ROOT / 'prototype', prefix='.act3-conspirators-test-') as directory:
            store = ProfileStore(directory, catalog=old)
            original = store.create('Old revision', choices={'da2.anders_approval': 'approved'})
            path = store.profile_directory(original.profile_id) / 'History/00000001.json'
            raw = path.read_bytes()
            upgraded = self.catalog.upgrade(original)
            current = ProfileStore(directory, catalog=self.catalog)
            saved = current.save(upgraded.edited(choices=dict(upgraded.choices, **{'da2.conspirators': 'meredith'})))
            self.assertEqual(saved.mapping_version, self.catalog.version)
            self.assertEqual(saved.revision, 2)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(current.load(original.profile_id, revision=1), original)

    def test_act_three_preserves_both_siblings_for_all_classes_and_other_story_choices(self):
        owned = {name for fields, _ in CASES.values() for name in fields}
        for player_class in ('warrior', 'rogue', 'mage'):
            profile = self.catalog.create('Independent history', choices={
                'da2.hawke_identity': 'female_' + player_class, 'da2.bethany_fate': 'warden',
                'da2.carver_fate': 'warden', 'da2.final_allegiance': 'templars',
                'da2.anders_fate': 'alive', 'da2.hawke_romance': 'anders',
                'da2.anders_approval': 'approved', 'da2.fenris_fate': 'pursued'})
            before = compile_profile(profile, catalog=self.catalog)
            for answers in product(*(definition[1] for definition in CASES.values())):
                choices = dict(profile.choices, **dict(zip(CASES, answers)))
                after = compile_profile(profile.edited(choices=choices), catalog=self.catalog)
                self.assertEqual(after.report['story_conflicts'], [])
                self.assertEqual({n: v for n, v in before.effective_values.items() if n not in owned},
                                 {n: v for n, v in after.effective_values.items() if n not in owned})

    def test_each_outcome_is_independent_of_final_allegiance_and_other_act_three_history(self):
        for side in ('mages', 'templars'):
            profile = self.catalog.create('Independent Act III history', choices={
                'da2.final_allegiance': side, 'da2.murder_of_crows': 'not_sought',
                'da2.zevran_freed': 'not_freed', 'da2.finding_nathaniel': 'not_encountered',
                'da2.gamlen_treasure': 'returned_gem', 'da2.legacy_played': 'not_played',
                'da2.malcolm_will': 'not_found', 'da2.conspirators': 'orsino',
                'da2.emile_fate': 'freed', 'da2.keran_fate': 'released'})
            before = compile_profile(profile, catalog=self.catalog)
            for group, (fields, answers) in CASES.items():
                for answer in answers:
                    edited = profile.edited(choices=dict(profile.choices, **{group: answer}))
                    mod, report = build_profile_mod(edited, catalog=self.catalog)
                    flags = flags_from_mod(mod)
                    self.assertEqual(report['profile']['story_conflicts'], [])
                    self.assertEqual({n: v for n, v in before.effective_values.items() if n not in fields},
                                     {n: v['DefaultValue'] for n, v in flags.items() if n not in fields})


if __name__ == '__main__':
    unittest.main(verbosity=2)
