"""Complementary Varric flags, correct Bartrand field and preserved profile history."""
from itertools import product
from pathlib import Path
import tempfile
import unittest

from export_worldstate import ROOT, EbxParser, read_mod
from world_profiles import Catalog, ProfileStore
from world_profiles.compiler import build_profile_mod, compile_profile


CASES = {
    'da2.aveline_marriage': (('da2_aveline_married',), {'not_married': (0,), 'married': (1,)}),
    'da2.aveline_remained': (('da2_aveline_remained',), {'left': (0,), 'stayed': (1,)}),
    'da2.varric_relationship': (('da2_hawke_varric_relationship', 'da2_varric_friendship'), {
        'friends': (0, 1), 'rivals': (1, 0)}),
    'da2.bartrand_fate': (('da2_varric_bartrand_killed', 'da2_bartrand_alive'), {
        'alive': (0, 1), 'killed': (1, 0)}),
    'da2.varric_idol': (('da2_varric_has_idol_piece',), {'not_kept': (0,), 'kept': (1,)}),
    'da2.varric_quest': (('da2_varric_plot_complete',), {'not_completed': (0,), 'completed': (1,)}),
    'da2.sebastian_recruited': (('da2_sebastian_joined',), {'not_recruited': (0,), 'recruited': (1,)})}


def flags_from_mod(mod):
    return {obj['value']['VariableNameOnServer']: obj['value']
            for obj in EbxParser(read_mod(mod)['ebx']).parse()['objects'] if obj['class'] == 'GameVaultVarInt'}


class AvelineVarricSebastianTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def test_all_128_combinations_roundtrip_complementary_flags(self):
        for answers in product(*(definition[1] for definition in CASES.values())):
            choices = dict(zip(CASES, answers))
            with self.subTest(choices=choices):
                profile = self.catalog.create('Companion history', choices=choices)
                mod, report = build_profile_mod(profile, catalog=self.catalog)
                flags = flags_from_mod(mod)
                for group, (fields, expected) in CASES.items():
                    self.assertEqual(tuple(flags[field]['DefaultValue'] for field in fields), expected[choices[group]])
                self.assertEqual(report['profile']['story_conflicts'], [])
                self.assertFalse(report['profile']['gameplay_tested'])

    def test_single_edits_preserve_every_unowned_field_and_range_across_all_bases(self):
        for preset in self.catalog.presets:
            original = self.catalog.create('Inherited history', base_preset=preset, mode='experimental')
            before = compile_profile(original, catalog=self.catalog)
            for group, (owned, answers) in CASES.items():
                for answer in answers:
                    with self.subTest(preset=preset, group=group, answer=answer):
                        after = compile_profile(original.edited(choices={group: answer}), catalog=self.catalog)
                        self.assertEqual({n: v for n, v in before.effective_values.items() if n not in owned},
                                         {n: v for n, v in after.effective_values.items() if n not in owned})
                        self.assertEqual(after.max_overrides, before.max_overrides)
                        self.assertEqual(after.effective_values['da2_sided_with_templars'], before.effective_values['da2_sided_with_templars'])
                        self.assertEqual(after.report['resolved_choices'][group]['answer_id'], answer)

    def test_both_released_relationships_and_sebastian_variants_reproduce_all_eight_payloads(self):
        relationships, recruitments = set(), set()
        for preset in self.catalog.presets:
            if not preset.startswith('template-'):
                continue
            original = self.catalog.create('Released world', base_preset=preset, mode='experimental')
            compiled = compile_profile(original, catalog=self.catalog)
            choices = {group: compiled.report['resolved_choices'][group]['answer_id'] for group in CASES}
            self.assertNotIn(None, choices.values())
            relationships.add(choices['da2.varric_relationship'])
            recruitments.add(choices['da2.sebastian_recruited'])
            mod, _ = build_profile_mod(original.edited(choices=choices), catalog=self.catalog)
            self.assertEqual(read_mod(mod)['ebx'], read_mod(self.catalog.template_path(preset).read_bytes())['ebx'])
        self.assertEqual(relationships, {'friends', 'rivals'})
        self.assertEqual(recruitments, {'not_recruited', 'recruited'})

    def test_catalog_twelve_upgrades_preserve_all_bases_and_previous_companion_edits(self):
        old = Catalog(mapping_version=12)
        for preset in old.presets:
            for choices in ({}, {'da2.fenris_fate': 'pursued', 'da2.isabela_handover': 'handed_over',
                                'da2.merrill_clan': 'killed', 'da2.hawke_romance': 'sebastian'}):
                original = old.create('Older history', base_preset=preset, mode='experimental', choices=choices)
                before, _ = build_profile_mod(original, catalog=self.catalog)
                upgraded = self.catalog.upgrade(original)
                after, _ = build_profile_mod(upgraded, catalog=self.catalog)
                self.assertEqual(read_mod(before)['ebx'], read_mod(after)['ebx'])
                self.assertEqual(original.choices, upgraded.choices)

    def test_saving_upgrade_preserves_old_revision_bytes_and_interpretation(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'prototype', prefix='.aveline-varric-test-') as directory:
            old = ProfileStore(directory, catalog=Catalog(mapping_version=12))
            original = old.create('Existing history', choices={'da2.fenris_fate': 'pursued'})
            path = old.profile_directory(original.profile_id) / 'History/00000001.json'
            raw = path.read_bytes()
            upgraded = self.catalog.upgrade(original)
            self.assertEqual(path.read_bytes(), raw)
            store = ProfileStore(directory, catalog=self.catalog)
            saved = store.save(upgraded.edited(choices=dict(upgraded.choices, **{'da2.varric_relationship': 'rivals'})))
            self.assertEqual(saved.revision, 2)
            self.assertEqual(saved.mapping_version, self.catalog.version)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(store.load(original.profile_id, revision=1), original)

    def test_unmatched_inherited_pairs_remain_until_explicit_edit(self):
        # Model an older authored preset with contradictory duplicate values.
        catalog = Catalog()
        catalog._presets[catalog.default_preset]['export_values'].update(
            da2_hawke_varric_relationship=0, da2_varric_friendship=0,
            da2_bartrand_alive=1, da2_varric_bartrand_killed=1)
        original = catalog.create('Unmatched history')
        before = compile_profile(original, catalog=catalog)
        for group in ('da2.varric_relationship', 'da2.bartrand_fate'):
            self.assertIsNone(before.report['resolved_choices'][group]['answer_id'])
        unrelated = compile_profile(original.edited(choices={'da2.aveline_marriage': 'not_married'}), catalog=catalog)
        self.assertEqual(unrelated.effective_values['da2_varric_friendship'], 0)
        self.assertEqual(unrelated.effective_values['da2_bartrand_alive'], 1)
        fixed = compile_profile(original.edited(choices={'da2.varric_relationship': 'rivals', 'da2.bartrand_fate': 'alive'}), catalog=catalog)
        self.assertEqual(fixed.report['resolved_choices']['da2.varric_relationship']['answer_id'], 'rivals')
        self.assertEqual(fixed.report['resolved_choices']['da2.bartrand_fate']['answer_id'], 'alive')
        self.assertEqual(fixed.effective_values['da2_varric_bartrand_killed'], 0)

    def test_sebastian_and_other_companions_do_not_rewrite_anders_romance_class_or_siblings(self):
        for romance, player_class, anders in product(('none', 'anders', 'sebastian'), ('warrior', 'rogue', 'mage'), ('alive', 'executed')):
            choices = {'da2.hawke_romance': romance, 'da2.hawke_identity': 'female_' + player_class,
                       'da2.anders_fate': anders, 'da2.bethany_fate': 'warden', 'da2.carver_fate': 'warden'}
            original = self.catalog.create('Independent history', choices=choices)
            before = compile_profile(original, catalog=self.catalog)
            for group, (owned, answers) in CASES.items():
                for answer in answers:
                    after = compile_profile(original.edited(choices=dict(choices, **{group: answer})), catalog=self.catalog)
                    self.assertEqual(after.report['story_conflicts'], [])
                    self.assertEqual({n: v for n, v in before.effective_values.items() if n not in owned},
                                     {n: v for n, v in after.effective_values.items() if n not in owned})


if __name__ == '__main__':
    unittest.main(verbosity=2)
