"""DA2 main-story flags, independent companion history and lossless upgrades."""
from itertools import product
from pathlib import Path
import tempfile
import unittest

from export_worldstate import ROOT, EbxParser, read_mod
from world_profiles import Catalog, ProfileStore
from world_profiles.compiler import build_profile_mod, compile_profile


CASES = {
    'da2.final_allegiance': (('da2_hawke_chosen_side', 'da2_sided_with_mages', 'da2_sided_with_templars'),
        {'mages': (0, 1, 0), 'templars': (1, 0, 1)}),
    'da2.anders_approval': (('da2_hawke_approves_of_anders_action',), {'disapproved': (0,), 'approved': (1,)}),
    'da2.arishok_fate': (('da2_arishok_killed',), {'not_killed': (0,), 'killed': (1,)})}


def flags_from_mod(mod):
    return {obj['value']['VariableNameOnServer']: obj['value']
            for obj in EbxParser(read_mod(mod)['ebx']).parse()['objects'] if obj['class'] == 'GameVaultVarInt'}


class Da2MainStoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def test_all_eight_combinations_roundtrip_documented_tuples_across_nine_bases(self):
        for preset in self.catalog.presets:
            for answers in product(*(definition[1] for definition in CASES.values())):
                choices = dict(zip(CASES, answers))
                with self.subTest(preset=preset, choices=choices):
                    profile = self.catalog.create('Main story', base_preset=preset, mode='ordinary', choices=choices)
                    mod, report = build_profile_mod(profile, catalog=self.catalog)
                    flags = flags_from_mod(mod)
                    for group, (fields, expected) in CASES.items():
                        self.assertEqual(tuple(flags[field]['DefaultValue'] for field in fields), expected[choices[group]])
                    self.assertEqual(report['profile']['story_conflicts'], [])
                    self.assertFalse(report['profile']['gameplay_tested'])

    def test_single_edits_preserve_unowned_fields_ranges_and_bartrand(self):
        for preset in self.catalog.presets:
            original = self.catalog.create('Inherited history', base_preset=preset, mode='experimental')
            before = compile_profile(original, catalog=self.catalog)
            for group, (owned, answers) in CASES.items():
                for answer in answers:
                    after = compile_profile(original.edited(choices={group: answer}), catalog=self.catalog)
                    self.assertEqual({n: v for n, v in before.effective_values.items() if n not in owned},
                                     {n: v for n, v in after.effective_values.items() if n not in owned})
                    self.assertEqual(after.max_overrides, before.max_overrides)
                    self.assertEqual(after.effective_values['da2_varric_bartrand_killed'], before.effective_values['da2_varric_bartrand_killed'])
                    self.assertEqual(after.report['resolved_choices'][group]['answer_id'], answer)

    def test_all_eight_released_payloads_reproduce_including_both_approval_values(self):
        approvals = set()
        for preset in self.catalog.presets:
            if not preset.startswith('template-'):
                continue
            original = self.catalog.create('Released world', base_preset=preset, mode='experimental')
            resolved = compile_profile(original, catalog=self.catalog).report['resolved_choices']
            choices = {group: resolved[group]['answer_id'] for group in CASES}
            self.assertNotIn(None, choices.values())
            self.assertEqual(choices['da2.final_allegiance'], 'mages')
            self.assertEqual(choices['da2.arishok_fate'], 'killed')
            approvals.add(choices['da2.anders_approval'])
            mod, _ = build_profile_mod(original.edited(choices=choices), catalog=self.catalog)
            self.assertEqual(read_mod(mod)['ebx'], read_mod(self.catalog.template_path(preset).read_bytes())['ebx'])
        self.assertEqual(approvals, {'disapproved', 'approved'})

    def test_catalog_thirteen_upgrades_preserve_all_bases_and_prior_companions(self):
        old = Catalog(mapping_version=13)
        for preset in old.presets:
            for choices in ({}, {'da2.bartrand_fate': 'killed', 'da2.varric_relationship': 'rivals',
                                'da2.sebastian_recruited': 'recruited', 'da2.fenris_fate': 'pursued'}):
                original = old.create('Older history', base_preset=preset, mode='experimental', choices=choices)
                before, _ = build_profile_mod(original, catalog=self.catalog)
                upgraded = self.catalog.upgrade(original)
                after, _ = build_profile_mod(upgraded, catalog=self.catalog)
                self.assertEqual(read_mod(before)['ebx'], read_mod(after)['ebx'])
                self.assertEqual(original.choices, upgraded.choices)

    def test_saving_upgrade_preserves_old_revision_bytes_and_catalog(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'prototype', prefix='.da2-story-test-') as directory:
            old = ProfileStore(directory, catalog=Catalog(mapping_version=13))
            original = old.create('Existing history', choices={'da2.bartrand_fate': 'killed'})
            path = old.profile_directory(original.profile_id) / 'History/00000001.json'
            raw = path.read_bytes()
            upgraded = self.catalog.upgrade(original)
            self.assertEqual(path.read_bytes(), raw)
            store = ProfileStore(directory, catalog=self.catalog)
            saved = store.save(upgraded.edited(choices=dict(upgraded.choices, **{'da2.final_allegiance': 'templars'})))
            self.assertEqual(saved.revision, 2)
            self.assertEqual(saved.mapping_version, self.catalog.version)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(store.load(original.profile_id, revision=1), original)

    def test_main_story_preserves_execution_handover_companions_class_romance_and_both_siblings(self):
        for anders, handover, player_class in product(('alive', 'executed'), ('not_handed_over', 'handed_over'), ('warrior', 'rogue', 'mage')):
            choices = {'da2.anders_fate': anders, 'da2.isabela_handover': handover,
                'da2.hawke_identity': 'female_' + player_class, 'da2.hawke_romance': 'anders',
                'da2.bethany_fate': 'warden', 'da2.carver_fate': 'warden', 'da2.fenris_fate': 'alive',
                'da2.merrill_fate': 'alive', 'da2.aveline_remained': 'stayed', 'da2.bartrand_fate': 'killed'}
            original = self.catalog.create('Independent history', choices=choices)
            before = compile_profile(original, catalog=self.catalog)
            owned = {name for fields, _ in CASES.values() for name in fields}
            for answers in product(*(definition[1] for definition in CASES.values())):
                edits = dict(zip(CASES, answers))
                after = compile_profile(original.edited(choices=dict(choices, **edits)), catalog=self.catalog)
                self.assertEqual(after.report['story_conflicts'], [])
                self.assertEqual({n: v for n, v in before.effective_values.items() if n not in owned},
                                 {n: v for n, v in after.effective_values.items() if n not in owned})
                self.assertEqual(after.report['resolved_choices']['da2.final_allegiance']['answer_id'], edits['da2.final_allegiance'])

    def test_unmatched_inherited_allegiance_is_preserved_until_explicit_selection(self):
        catalog = Catalog()
        catalog._presets[catalog.default_preset]['export_values'].update(
            da2_hawke_chosen_side=0, da2_sided_with_mages=0, da2_sided_with_templars=1)
        original = catalog.create('Contradictory inherited allegiance')
        before = compile_profile(original, catalog=catalog)
        self.assertIsNone(before.report['resolved_choices']['da2.final_allegiance']['answer_id'])
        after = compile_profile(original.edited(choices={'da2.anders_approval': 'approved'}), catalog=catalog)
        self.assertEqual(tuple(after.effective_values[name] for name in CASES['da2.final_allegiance'][0]), (0, 0, 1))
        selected = compile_profile(original.edited(choices={'da2.final_allegiance': 'templars'}), catalog=catalog)
        self.assertEqual(tuple(selected.effective_values[name] for name in CASES['da2.final_allegiance'][0]), (1, 0, 1))


if __name__ == '__main__':
    unittest.main(verbosity=2)
