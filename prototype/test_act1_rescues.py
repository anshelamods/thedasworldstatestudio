"""Saemus, Ginnis, Ghyslain, Thrask and Ketojan, independent history and immutable older profiles."""
from itertools import product
from pathlib import Path
import tempfile
import unittest

from export_worldstate import ROOT, read_mod
from world_profiles import Catalog, ProfileStore
from world_profiles.compiler import build_profile_mod, compile_profile
from test_da2_main_story import flags_from_mod


CASES = {
    'da2.saemus_rescue': (('da2_act1_seamus',), {'not_returned': (0,), 'returned': (1,)}),
    'da2.ginnis_fate': (('da2_act1_ginnis_alive',), {'dead': (0,), 'alive': (1,)}),
    'da2.ghyslain_truth': (('da2_act1_ghyslain_truth',), {'not_sought': (0,), 'concealed': (1,), 'told': (2,)}),
    'da2.thrask_blackmail': (('da2_act1_thrask_blackmailed',), {'not_blackmailed': (0,), 'blackmailed': (1,)}),
    'da2.ketojan_fate': (('da2_act1_saarebas_defended',), {'defended': (0,), 'handed_over': (1,)})}


class ActOneRescueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def test_48_combinations_compile_across_nine_bases_and_roundtrip_baseline(self):
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

    def test_all_released_act_one_rescue_selections_reproduce_exact_payloads(self):
        for preset in self.catalog.presets:
            if not preset.startswith('template-'):
                continue
            profile = self.catalog.create('Released history', base_preset=preset, mode='experimental')
            resolved = compile_profile(profile, catalog=self.catalog).report['resolved_choices']
            choices = {group: resolved[group]['answer_id'] for group in CASES}
            self.assertEqual(choices, {'da2.saemus_rescue': 'returned', 'da2.ginnis_fate': 'dead', 'da2.ghyslain_truth': 'not_sought', 'da2.thrask_blackmail': 'not_blackmailed', 'da2.ketojan_fate': 'handed_over'})
            mod, _ = build_profile_mod(profile.edited(choices=choices), catalog=self.catalog)
            self.assertEqual(read_mod(mod)['ebx'], read_mod(self.catalog.template_path(preset).read_bytes())['ebx'])

    def test_v23_upgrade_preserves_payloads_and_immutable_revision_bytes(self):
        old = Catalog(mapping_version=23)
        for preset in old.presets:
            original = old.create('Older history', base_preset=preset, mode='experimental',
                choices={'da2.final_allegiance': 'templars', 'da2.fenris_fate': 'pursued', 'da2.bone_pit_dragon': 'killed'})
            upgraded = self.catalog.upgrade(original)
            before, _ = build_profile_mod(original, catalog=self.catalog)
            after, _ = build_profile_mod(upgraded, catalog=self.catalog)
            self.assertEqual(read_mod(before)['ebx'], read_mod(after)['ebx'])
            self.assertEqual(original.choices, upgraded.choices)
        with tempfile.TemporaryDirectory(dir=ROOT / 'prototype', prefix='.act1-rescues-test-') as directory:
            store = ProfileStore(directory, catalog=old)
            original = store.create('Old revision', choices={'da2.anders_approval': 'approved'})
            path = store.profile_directory(original.profile_id) / 'History/00000001.json'
            raw = path.read_bytes()
            upgraded = self.catalog.upgrade(original)
            current = ProfileStore(directory, catalog=self.catalog)
            saved = current.save(upgraded.edited(choices=dict(upgraded.choices, **{'da2.ghyslain_truth': 'told'})))
            self.assertEqual(saved.mapping_version, self.catalog.version)
            self.assertEqual(saved.revision, 2)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(current.load(original.profile_id, revision=1), original)

    def test_act_one_rescues_preserve_both_siblings_for_all_classes_and_other_story_choices(self):
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

    def test_saemus_and_ginnis_remain_independent_from_each_other_and_other_history(self):
        # Keep has dependency rules for these two flags; the offline editor deliberately does not enforce them.
        for saemus, ginnis in product(('not_returned', 'returned'), ('dead', 'alive')):
            choices = {'da2.saemus_rescue': saemus, 'da2.ginnis_fate': ginnis,
                'da2.feynriel_destination': 'dalish', 'da2.act1_templars': 'persuaded',
                'da2.danzig_fate': 'not_killed', 'da2.idunna_fate': 'killed',
                'da2.feynriel_fate': 'possessed', 'da2.final_allegiance': 'templars',
                'da2.bone_pit_dragon': 'killed'}
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

    def test_ketojan_positive_field_value_is_handed_over_despite_field_name(self):
        for answer, value in [('defended', 0), ('handed_over', 1)]:
            profile = self.catalog.create('Explicit Ketojan mapping', choices={'da2.ketojan_fate': answer})
            mod, report = build_profile_mod(profile, catalog=self.catalog)
            self.assertEqual(flags_from_mod(mod)['da2_act1_saarebas_defended']['DefaultValue'], value)
            resolved = report['profile']['resolved_choices']['da2.ketojan_fate']
            self.assertEqual(resolved['answer_id'], answer)
            self.assertIn('0 defended and 1 handed over', self.catalog.choices['da2.ketojan_fate']['basis'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
