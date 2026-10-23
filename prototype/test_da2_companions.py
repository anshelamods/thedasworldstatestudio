"""Documented DA2 companion fields, range extension and independent history."""
from itertools import product
from pathlib import Path
import tempfile
import unittest

from export_worldstate import ROOT, EbxParser, read_mod
from world_profiles import Catalog, ProfileStore
from world_profiles.compiler import build_profile_mod, compile_profile


# Independent expected tuples: status, survival; Danarius enum, boolean.
CASES = {
    'da2.fenris_recruited': (('da2_fenris_joined',), {'not_recruited': (0,), 'recruited': (1,)}),
    'da2.fenris_fate': (('da2_fenris_alive', 'da2_fenris_still_alive'), {
        'not_recruited': (0, 1), 'dead': (1, 0), 'alive': (2, 1), 'returned': (3, 1), 'pursued': (4, 1)}),
    'da2.fenris_danarius': (('da2_fenris_enslaved', 'da2_fenris_returned_to_master'), {
        'not_recruited': (0, 0), 'not_returned': (1, 0), 'returned': (2, 1)}),
    'da2.isabela_recruited': (('da2_isabela_joined',), {'not_recruited': (0,), 'recruited': (1,)}),
    'da2.isabela_book': (('da2_isabela_returned_with_book',), {
        'not_recruited': (0,), 'not_returned': (1,), 'returned': (2,)}),
    'da2.isabela_handover': (('da2_isabela_turned_over',), {'not_handed_over': (0,), 'handed_over': (1,)}),
    'da2.merrill_fate': (('da2_merrill_alive',), {'dead': (0,), 'alive': (1,)}),
    'da2.merrill_eluvian': (('da2_merrill_eluvian_destroy',), {'preserved': (0,), 'destroyed': (1,)}),
    'da2.merrill_remained': (('da2_merrill_remained',), {'left': (0,), 'stayed': (1,)}),
    'da2.merrill_clan': (('da2_merrils_clan',), {'survived': (0,), 'killed': (1,)})}
RELEASED = dict(zip(CASES, ('recruited', 'alive', 'not_returned', 'recruited', 'returned',
                           'not_handed_over', 'alive', 'destroyed', 'stayed', 'survived')))


def flags_from_mod(mod):
    return {obj['value']['VariableNameOnServer']: obj['value']
            for obj in EbxParser(read_mod(mod)['ebx']).parse()['objects'] if obj['class'] == 'GameVaultVarInt'}


class Da2CompanionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def test_each_companions_full_combination_space_roundtrips_documented_tuples(self):
        count = 0
        for person in ('fenris', 'isabela', 'merrill'):
            groups = [group for group in CASES if group.startswith('da2.' + person)]
            for answers in product(*(CASES[group][1] for group in groups)):
                choices = dict(zip(groups, answers))
                with self.subTest(choices=choices):
                    profile = self.catalog.create('Companion history', choices=choices)
                    mod, report = build_profile_mod(profile, catalog=self.catalog)
                    flags = flags_from_mod(mod)
                    for group, answer in choices.items():
                        names, expected = CASES[group]
                        self.assertEqual(tuple(flags[name]['DefaultValue'] for name in names), expected[answer])
                    self.assertEqual(report['profile']['story_conflicts'], [])
                    self.assertFalse(report['profile']['gameplay_tested'])
                    count += 1
        self.assertEqual(count, 58)

    def test_each_single_edit_preserves_unowned_fields_and_ranges_across_nine_bases(self):
        for preset in self.catalog.presets:
            original = self.catalog.create('Inherited history', base_preset=preset, mode='experimental')
            before = compile_profile(original, catalog=self.catalog)
            for group, (owned, answers) in CASES.items():
                for answer in answers:
                    with self.subTest(preset=preset, group=group, answer=answer):
                        after = compile_profile(original.edited(choices={group: answer}), catalog=self.catalog)
                        self.assertEqual({n: v for n, v in before.effective_values.items() if n not in owned},
                                         {n: v for n, v in after.effective_values.items() if n not in owned})
                        self.assertEqual(after.max_overrides,
                            {'da2_fenris_alive': 4} if group == 'da2.fenris_fate' and answer == 'pursued' else {})
                        self.assertEqual(after.report['resolved_choices'][group]['answer_id'], answer)

    def test_all_eight_released_payloads_are_exactly_reproduced(self):
        for preset in self.catalog.presets:
            if not preset.startswith('template-'):
                continue
            original = self.catalog.create('Released world', base_preset=preset, mode='experimental')
            resolved = compile_profile(original, catalog=self.catalog).report['resolved_choices']
            self.assertEqual({group: resolved[group]['answer_id'] for group in CASES}, RELEASED)
            mod, _ = build_profile_mod(original.edited(choices=RELEASED), catalog=self.catalog)
            self.assertEqual(read_mod(mod)['ebx'], read_mod(self.catalog.template_path(preset).read_bytes())['ebx'])

    def test_catalog_eleven_upgrades_preserve_all_bases_and_existing_selections(self):
        old = Catalog(mapping_version=11)
        for preset in old.presets:
            for choices in ({}, {'dao.sten_release': 'picked_lock', 'dao.dagna_outcome': 'circle_destroyed',
                                'dao.dagna_permission': 'requested', 'da2.hawke_romance': 'fenris'}):
                with self.subTest(preset=preset, choices=choices):
                    profile = old.create('Before DA2 companions', base_preset=preset, mode='experimental', choices=choices)
                    before, _ = build_profile_mod(profile, catalog=self.catalog)
                    upgraded = self.catalog.upgrade(profile)
                    after, _ = build_profile_mod(upgraded, catalog=self.catalog)
                    self.assertEqual(read_mod(before)['ebx'], read_mod(after)['ebx'])
                    self.assertEqual(profile.choices, upgraded.choices)

    def test_saving_upgrade_retains_old_revision_bytes_and_catalog(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'prototype', prefix='.da2-companion-test-') as directory:
            old = ProfileStore(directory, catalog=Catalog(mapping_version=11))
            original = old.create('Existing history')
            path = old.profile_directory(original.profile_id) / 'History/00000001.json'
            before = path.read_bytes()
            upgraded = self.catalog.upgrade(original)
            self.assertEqual(path.read_bytes(), before)
            store = ProfileStore(directory, catalog=self.catalog)
            saved = store.save(upgraded.edited(choices={'da2.fenris_fate': 'pursued'}))
            self.assertEqual(saved.revision, 2)
            self.assertEqual(saved.mapping_version, self.catalog.version)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(store.load(original.profile_id, revision=1), original)

    def test_companion_edits_never_change_romance_class_or_either_sibling(self):
        for romance, player_class in product(('none', 'fenris', 'isabela', 'merrill'), ('warrior', 'rogue', 'mage')):
            choices = {'da2.hawke_romance': romance, 'da2.hawke_identity': 'female_' + player_class,
                       'da2.bethany_fate': 'warden', 'da2.carver_fate': 'warden'}
            original = self.catalog.create('Independent companions', choices=choices)
            before = compile_profile(original, catalog=self.catalog)
            for group, (owned, answers) in CASES.items():
                for answer in answers:
                    after = compile_profile(original.edited(choices=dict(choices, **{group: answer})), catalog=self.catalog)
                    self.assertEqual(after.report['story_conflicts'], [])
                    self.assertEqual({n: v for n, v in before.effective_values.items() if n not in owned},
                                     {n: v for n, v in after.effective_values.items() if n not in owned})

    def test_pursued_only_extends_one_range_and_handover_dispute_stays_visible(self):
        for answer in CASES['da2.fenris_fate'][1]:
            profile = self.catalog.create('Fenris range', choices={'da2.fenris_fate': answer})
            flags = flags_from_mod(build_profile_mod(profile, catalog=self.catalog)[0])
            self.assertEqual(flags['da2_fenris_alive']['MaxValue'], 4 if answer == 'pursued' else 3)
        for answer, value in [('not_handed_over', 0), ('handed_over', 1)]:
            profile = self.catalog.create('Isabela interpretation', choices={'da2.isabela_handover': answer})
            mod, report = build_profile_mod(profile, catalog=self.catalog)
            field = flags_from_mod(mod)['da2_isabela_turned_over']
            self.assertEqual((field['DefaultValue'], field['MaxValue']), (value, 1))
            self.assertEqual(report['profile']['selections'][0]['evidence_status'], 'disputed')
            self.assertIn('0 absent / 1 no / 2 yes', report['profile']['selections'][0]['basis'])
            self.assertTrue(any('conflicting source evidence' in warning for warning in report['profile']['warnings']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
