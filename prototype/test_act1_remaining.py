"""Remaining Act I choices, independent history and immutable older profiles."""
from itertools import product
from pathlib import Path
import tempfile
import unittest

from export_worldstate import ROOT, read_mod
from world_profiles import Catalog, ProfileStore
from world_profiles.compiler import build_profile_mod, compile_profile
from test_da2_main_story import flags_from_mod


CASES = {
    'da2.martin_cargo': (('da2_act1_martin_cargo_returned',), {'not_returned': (0,), 'returned': (1,)}),
    'da2.kelder_fate': (('da2_act1_kelder_killed',), {'not_killed': (0,), 'killed': (1,)}),
    'da2.bone_pit_miners': (('da2_act1_bonepit_completed',), {'not_solved': (0,), 'solved': (1,)}),
    'da2.keran_templars': (('da2_act1_keran_templars',), {'reinstated': (0,), 'expelled': (1,)}),
    'da2.karras_fate': (('da2_act1_karras_killed',), {'not_killed': (0,), 'killed': (1,)})}


class ActOneRemainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def test_32_combinations_compile_across_nine_bases_and_roundtrip_baseline(self):
        for preset in self.catalog.presets:
            for answers in product(*(definition[1] for definition in CASES.values())):
                choices = dict(zip(CASES, answers))
                with self.subTest(preset=preset, choices=choices):
                    profile = self.catalog.create('Act I history', base_preset=preset,
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

    def test_all_released_remaining_act_one_selections_reproduce_exact_payloads(self):
        for preset in self.catalog.presets:
            if not preset.startswith('template-'):
                continue
            profile = self.catalog.create('Released history', base_preset=preset, mode='experimental')
            resolved = compile_profile(profile, catalog=self.catalog).report['resolved_choices']
            choices = {group: resolved[group]['answer_id'] for group in CASES}
            self.assertEqual(choices, {'da2.martin_cargo': 'not_returned', 'da2.kelder_fate': 'killed', 'da2.bone_pit_miners': 'solved', 'da2.keran_templars': 'expelled', 'da2.karras_fate': 'killed'})
            mod, _ = build_profile_mod(profile.edited(choices=choices), catalog=self.catalog)
            self.assertEqual(read_mod(mod)['ebx'], read_mod(self.catalog.template_path(preset).read_bytes())['ebx'])

    def test_v24_upgrade_preserves_payloads_and_immutable_revision_bytes(self):
        old = Catalog(mapping_version=24)
        for preset in old.presets:
            original = old.create('Older history', base_preset=preset, mode='experimental',
                choices={'da2.final_allegiance': 'templars', 'da2.fenris_fate': 'pursued', 'da2.bone_pit_dragon': 'killed',
                         'da2.saemus_rescue': 'not_returned', 'da2.ginnis_fate': 'alive', 'da2.ketojan_fate': 'defended'})
            upgraded = self.catalog.upgrade(original)
            before, _ = build_profile_mod(original, catalog=self.catalog)
            after, _ = build_profile_mod(upgraded, catalog=self.catalog)
            self.assertEqual(read_mod(before)['ebx'], read_mod(after)['ebx'])
            self.assertEqual(original.choices, upgraded.choices)
        with tempfile.TemporaryDirectory(dir=ROOT / 'prototype', prefix='.act1-remaining-test-') as directory:
            store = ProfileStore(directory, catalog=old)
            original = store.create('Old revision', choices={'da2.anders_approval': 'approved'})
            path = store.profile_directory(original.profile_id) / 'History/00000001.json'
            raw = path.read_bytes()
            upgraded = self.catalog.upgrade(original)
            current = ProfileStore(directory, catalog=self.catalog)
            saved = current.save(upgraded.edited(choices=dict(upgraded.choices, **{'da2.keran_templars': 'reinstated'})))
            self.assertEqual(saved.mapping_version, self.catalog.version)
            self.assertEqual(saved.revision, 2)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(current.load(original.profile_id, revision=1), original)

    def test_remaining_act_one_preserves_both_siblings_for_all_classes_and_other_story_choices(self):
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

    def test_new_choices_preserve_templar_encounter_hubert_and_cosmetic_dragon(self):
        for templars, hubert in product(('fought', 'persuaded', 'mages_handed_over'), ('not_discovered', 'discovered')):
            choices = {'da2.act1_templars': templars, 'da2.hubert_caravans': hubert,
                'da2.feynriel_destination': 'dalish', 'da2.danzig_fate': 'not_killed',
                'da2.idunna_fate': 'killed', 'da2.feynriel_fate': 'possessed',
                'da2.final_allegiance': 'templars', 'da2.bone_pit_dragon': 'killed'}
            original = self.catalog.create('Independent quest history', choices=choices)
            before = compile_profile(original, catalog=self.catalog)
            for group, (fields, answers) in CASES.items():
                for answer in answers:
                    profile = original.edited(choices=dict(choices, **{group: answer}))
                    mod, report = build_profile_mod(profile, catalog=self.catalog)
                    flags = flags_from_mod(mod)
                    self.assertEqual(report['profile']['story_conflicts'], [])
                    self.assertEqual({n: v for n, v in before.effective_values.items() if n not in fields},
                                     {n: v['DefaultValue'] for n, v in flags.items() if n not in fields})
                    self.assertEqual(report['profile']['resolved_choices']['da2.bone_pit_dragon']['export_behavior'], 'profile-only')

    def test_early_keran_status_and_later_fate_are_six_independent_combinations(self):
        for early, late in product(('reinstated', 'expelled'), ('released', 'killed', 'templars')):
            profile = self.catalog.create('Two Keran decisions', choices={
                'da2.keran_templars': early, 'da2.keran_fate': late})
            mod, report = build_profile_mod(profile, catalog=self.catalog)
            flags = flags_from_mod(mod)
            self.assertEqual(flags['da2_act1_keran_templars']['DefaultValue'], {'reinstated': 0, 'expelled': 1}[early])
            self.assertEqual(flags['da2_act3_keran_end']['DefaultValue'], {'released': 0, 'killed': 1, 'templars': 2}[late])
            self.assertEqual(report['profile']['story_conflicts'], [])
            self.assertEqual(report['profile']['resolved_choices']['da2.keran_templars']['answer_id'], early)
            self.assertEqual(report['profile']['resolved_choices']['da2.keran_fate']['answer_id'], late)


if __name__ == '__main__':
    unittest.main(verbosity=2)
