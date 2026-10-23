"""Remaining Act II quests and source conflicts, independent history and immutable older profiles."""
from itertools import product
from pathlib import Path
import tempfile
import unittest

from export_worldstate import ROOT, read_mod
from world_profiles import Catalog, ProfileStore
from world_profiles.compiler import build_profile_mod, compile_profile
from test_da2_main_story import flags_from_mod


CASES = {
    'da2.hubert_caravans': (('da2_act2_merchants_inside_job',), {'not_discovered': (0,), 'discovered': (1,)}),
    'da2.fools_gold': (('da2_act2_fools_gold',), {'not_encountered': (0,), 'iwan': (1,), 'merin': (2,)}),
    'da2.cliff_raiders': (('da2_act2_raiders_on_cliffs',),
        {'not_encountered': (0,), 'abandoned': (1,), 'with_guards': (2,), 'alone': (3,)}),
    'da2.varnell_side': (('da2_act2_varnell_side',), {'not_sided': (0,), 'sided': (1,)}),
    'da2.petrice_side': (('da2_act2_petrice_side',), {'not_sided': (0,), 'sided': (1,)})}


class ActTwoRemainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def test_96_combinations_compile_across_nine_bases_and_roundtrip_baseline(self):
        for preset in self.catalog.presets:
            for answers in product(*(definition[1] for definition in CASES.values())):
                choices = dict(zip(CASES, answers))
                with self.subTest(preset=preset, choices=choices):
                    profile = self.catalog.create('Act II history', base_preset=preset,
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

    def test_all_released_remaining_act_two_selections_reproduce_exact_payloads(self):
        for preset in self.catalog.presets:
            if not preset.startswith('template-'):
                continue
            profile = self.catalog.create('Released history', base_preset=preset, mode='experimental')
            resolved = compile_profile(profile, catalog=self.catalog).report['resolved_choices']
            choices = {group: resolved[group]['answer_id'] for group in CASES}
            self.assertEqual(choices, {'da2.hubert_caravans': 'not_discovered', 'da2.fools_gold': 'not_encountered', 'da2.cliff_raiders': 'not_encountered', 'da2.varnell_side': 'not_sided', 'da2.petrice_side': 'not_sided'})
            mod, _ = build_profile_mod(profile.edited(choices=choices), catalog=self.catalog)
            self.assertEqual(read_mod(mod)['ebx'], read_mod(self.catalog.template_path(preset).read_bytes())['ebx'])

    def test_v21_upgrade_preserves_payloads_and_immutable_revision_bytes(self):
        old = Catalog(mapping_version=21)
        for preset in old.presets:
            original = old.create('Older history', base_preset=preset, mode='experimental',
                choices={'da2.final_allegiance': 'templars', 'da2.fenris_fate': 'pursued', 'da2.bone_pit_dragon': 'killed'})
            upgraded = self.catalog.upgrade(original)
            before, _ = build_profile_mod(original, catalog=self.catalog)
            after, _ = build_profile_mod(upgraded, catalog=self.catalog)
            self.assertEqual(read_mod(before)['ebx'], read_mod(after)['ebx'])
            self.assertEqual(original.choices, upgraded.choices)
        with tempfile.TemporaryDirectory(dir=ROOT / 'prototype', prefix='.act2-remaining-test-') as directory:
            store = ProfileStore(directory, catalog=old)
            original = store.create('Old revision', choices={'da2.anders_approval': 'approved'})
            path = store.profile_directory(original.profile_id) / 'History/00000001.json'
            raw = path.read_bytes()
            upgraded = self.catalog.upgrade(original)
            current = ProfileStore(directory, catalog=self.catalog)
            saved = current.save(upgraded.edited(choices=dict(upgraded.choices, **{'da2.fools_gold': 'merin'})))
            self.assertEqual(saved.mapping_version, self.catalog.version)
            self.assertEqual(saved.revision, 2)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(current.load(original.profile_id, revision=1), original)

    def test_act_two_preserves_both_siblings_for_all_classes_and_other_story_choices(self):
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

    def test_keep_dependencies_do_not_rewrite_miners_nathaniel_or_other_act_two_choices(self):
        for miners, nathaniel in product((0, 1), repeat=2):
            catalog = Catalog()
            catalog._presets[catalog.default_preset]['export_values'].update(
                da2_act1_bonepit_completed=miners, dao_awakenings_nathaniel_live=nathaniel)
            choices = {'da2.feynriel_fate': 'possessed', 'da2.gascard_fate': 'not_killed',
                'da2.javaris_fate': 'alive', 'da2.arishok_fate': 'not_killed',
                'da2.bone_pit_dragon': 'killed', 'da2.hubert_caravans': 'not_discovered',
                'da2.fools_gold': 'not_encountered', 'da2.cliff_raiders': 'not_encountered',
                'da2.varnell_side': 'not_sided', 'da2.petrice_side': 'not_sided'}
            original = catalog.create('Independent quest history', choices=choices)
            before = compile_profile(original, catalog=catalog)
            for group, (fields, answers) in CASES.items():
                for answer in answers:
                    profile = original.edited(choices=dict(choices, **{group: answer}))
                    mod, report = build_profile_mod(profile, catalog=catalog)
                    flags = flags_from_mod(mod)
                    self.assertEqual(report['profile']['story_conflicts'], [])
                    self.assertEqual({n: v for n, v in before.effective_values.items() if n not in fields},
                                     {n: v['DefaultValue'] for n, v in flags.items() if n not in fields})
                    self.assertEqual(report['profile']['resolved_choices']['da2.bone_pit_dragon']['export_behavior'], 'profile-only')

    def test_fools_gold_uses_editor_keep_order_and_reports_the_unresolved_reversal(self):
        definition = self.catalog.choices['da2.fools_gold']
        self.assertEqual(definition['evidence_status'], 'disputed')
        self.assertIn('Original game descriptions reverse Iwan/Merin', definition['basis'])
        for answer, value in [('iwan', 1), ('merin', 2)]:
            profile = self.catalog.create('Provisional brother mapping', choices={'da2.fools_gold': answer})
            compiled = compile_profile(profile, catalog=self.catalog)
            self.assertEqual(compiled.effective_values['da2_act2_fools_gold'], value)
            self.assertEqual(compiled.report['selections'][0]['evidence_status'], 'disputed')
            self.assertIn('needs verification', compiled.report['selections'][0]['basis'])
            self.assertTrue(any('conflicting source evidence' in w for w in compiled.report['warnings']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
