"""Act I Feynriel, templars, Danzig and Idunna mapping tuples, independent history and immutable older profiles."""
from itertools import product
from pathlib import Path
import tempfile
import unittest

from export_worldstate import ROOT, read_mod
from world_profiles import Catalog, ProfileStore
from world_profiles.compiler import build_profile_mod, compile_profile
from test_da2_main_story import flags_from_mod


CASES = {
    'da2.feynriel_destination': (('da2_act1_feynriel_complete',), {'dalish': (0,), 'circle': (1,)}),
    'da2.act1_templars': (('da2_act1_templars',), {'fought': (0,), 'persuaded': (1,), 'mages_handed_over': (2,)}),
    'da2.danzig_fate': (('da2_act1_danzig_killed',), {'not_killed': (0,), 'killed': (1,)}),
    'da2.idunna_fate': (('da2_act1_idunna_killed',), {'alive': (0,), 'killed': (1,)})}


class ActOneHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def test_twenty_four_combinations_roundtrip_across_nine_bases(self):
        for preset in self.catalog.presets:
            for answers in product(*(definition[1] for definition in CASES.values())):
                choices = dict(zip(CASES, answers))
                with self.subTest(preset=preset, choices=choices):
                    profile = self.catalog.create('Act I history', base_preset=preset,
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

    def test_all_released_act_one_selections_reproduce_exact_payloads(self):
        for preset in self.catalog.presets:
            if not preset.startswith('template-'):
                continue
            profile = self.catalog.create('Released history', base_preset=preset, mode='experimental')
            resolved = compile_profile(profile, catalog=self.catalog).report['resolved_choices']
            choices = {group: resolved[group]['answer_id'] for group in CASES}
            self.assertEqual(choices, {'da2.feynriel_destination': 'circle', 'da2.act1_templars': 'fought', 'da2.danzig_fate': 'killed', 'da2.idunna_fate': 'alive'})
            mod, _ = build_profile_mod(profile.edited(choices=choices), catalog=self.catalog)
            self.assertEqual(read_mod(mod)['ebx'], read_mod(self.catalog.template_path(preset).read_bytes())['ebx'])

    def test_v22_upgrade_preserves_payloads_and_immutable_revision_bytes(self):
        old = Catalog(mapping_version=22)
        for preset in old.presets:
            original = old.create('Older history', base_preset=preset, mode='experimental',
                choices={'da2.final_allegiance': 'templars', 'da2.fenris_fate': 'pursued', 'da2.bone_pit_dragon': 'killed'})
            upgraded = self.catalog.upgrade(original)
            before, _ = build_profile_mod(original, catalog=self.catalog)
            after, _ = build_profile_mod(upgraded, catalog=self.catalog)
            self.assertEqual(read_mod(before)['ebx'], read_mod(after)['ebx'])
            self.assertEqual(original.choices, upgraded.choices)
        with tempfile.TemporaryDirectory(dir=ROOT / 'prototype', prefix='.act1-history-test-') as directory:
            store = ProfileStore(directory, catalog=old)
            original = store.create('Old revision', choices={'da2.anders_approval': 'approved'})
            path = store.profile_directory(original.profile_id) / 'History/00000001.json'
            raw = path.read_bytes()
            upgraded = self.catalog.upgrade(original)
            current = ProfileStore(directory, catalog=self.catalog)
            saved = current.save(upgraded.edited(choices=dict(upgraded.choices, **{'da2.feynriel_destination': 'dalish'})))
            self.assertEqual(saved.mapping_version, self.catalog.version)
            self.assertEqual(saved.revision, 2)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(current.load(original.profile_id, revision=1), original)

    def test_act_one_preserves_both_siblings_for_all_classes_and_other_story_choices(self):
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

    def test_early_choices_preserve_all_later_feynriel_fates_and_final_sides(self):
        owned = {field for fields, _ in CASES.values() for field in fields}
        for later_fate, final_side in product(('tevinter', 'tranquil', 'possessed'), ('mages', 'templars')):
            profile = self.catalog.create('Independent Acts I to III', choices={
                'da2.feynriel_fate': later_fate, 'da2.final_allegiance': final_side,
                'da2.bone_pit_dragon': 'killed'})
            before = compile_profile(profile, catalog=self.catalog)
            for answers in product(*(definition[1] for definition in CASES.values())):
                choices = dict(profile.choices, **dict(zip(CASES, answers)))
                after = compile_profile(profile.edited(choices=choices), catalog=self.catalog)
                self.assertEqual(after.report['story_conflicts'], [])
                self.assertEqual({n: v for n, v in before.effective_values.items() if n not in owned},
                                 {n: v for n, v in after.effective_values.items() if n not in owned})
                self.assertEqual(after.report['resolved_choices']['da2.bone_pit_dragon']['answer_id'], 'killed')
                self.assertEqual(after.report['resolved_choices']['da2.bone_pit_dragon']['export_behavior'], 'profile-only')


if __name__ == '__main__':
    unittest.main(verbosity=2)
