"""Final DA2 tapestry coverage, explicit Bethany ownership and Keep-only Tallis value."""
from itertools import product
from pathlib import Path
import tempfile
import unittest

from export_worldstate import ROOT, read_mod
from world_profiles import Catalog, ProfileStore
from world_profiles.model import ProfileError
from world_profiles.compiler import build_profile_mod, compile_profile
from test_da2_main_story import flags_from_mod

CASES = {
    'da2.bethany_final_battle': (('da2_bethany_final_battle_death',), {'before_war': (0,), 'survived': (1,), 'died': (2,)}),
    'da2.tallis_kiss': (('da2_mark_tallis_kiss',), {'not_kissed': (0,), 'kissed': (1,)}),
    'da2.tallis_reaction': (('da2_mark_tallis_angry',), {'not_angry': (0,), 'angry': (1,), 'never_met': (2,)}),
    'da2.prologue_allegiance': (('da2_pro_choice',), {'smugglers': (0,), 'mercenaries': (1,)})}

class FinalDa2ChoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def test_36_combinations_across_nine_bases_and_serialized_baseline(self):
        for preset in self.catalog.presets:
            for answers in product(*(definition[1] for definition in CASES.values())):
                choices = dict(zip(CASES, answers))
                profile = self.catalog.create('Last DA2 choices', base_preset=preset, mode='ordinary', choices=choices)
                compiled = compile_profile(profile, catalog=self.catalog)
                for group, (fields, expected) in CASES.items():
                    self.assertEqual(tuple(compiled.effective_values[field] for field in fields), expected[choices[group]])
                self.assertEqual(compiled.report['story_conflicts'], [])
                if not preset.startswith('template-'):
                    mod, report = build_profile_mod(profile, catalog=self.catalog)
                    flags = flags_from_mod(mod)
                    for group, (fields, expected) in CASES.items():
                        self.assertEqual(tuple(flags[field]['DefaultValue'] for field in fields), expected[choices[group]])
                    self.assertFalse(report['profile']['gameplay_tested'])

    def test_single_edits_preserve_all_unowned_fields_and_only_extend_never_met_range(self):
        for preset in self.catalog.presets:
            original = self.catalog.create('Inherited history', base_preset=preset, mode='experimental')
            before = compile_profile(original, catalog=self.catalog)
            for group, (owned, answers) in CASES.items():
                for answer in answers:
                    after = compile_profile(original.edited(choices={group: answer}), catalog=self.catalog)
                    self.assertEqual({n: v for n, v in before.effective_values.items() if n not in owned},
                                     {n: v for n, v in after.effective_values.items() if n not in owned})
                    self.assertEqual(dict(after.max_overrides), {'da2_mark_tallis_angry': 2} if answer == 'never_met' else {})
                    self.assertEqual(after.report['resolved_choices'][group]['answer_id'], answer)

    def test_all_eight_released_payloads_reproduce_exactly(self):
        for preset in self.catalog.presets:
            if not preset.startswith('template-'):
                continue
            profile = self.catalog.create('Released history', base_preset=preset, mode='experimental')
            resolved = compile_profile(profile, catalog=self.catalog).report['resolved_choices']
            choices = {group: resolved[group]['answer_id'] for group in CASES}
            self.assertEqual(choices, {'da2.bethany_final_battle': 'survived', 'da2.tallis_kiss': 'not_kissed',
                'da2.tallis_reaction': 'not_angry', 'da2.prologue_allegiance': 'smugglers'})
            mod, _ = build_profile_mod(profile.edited(choices=choices), catalog=self.catalog)
            self.assertEqual(read_mod(mod)['ebx'], read_mod(self.catalog.template_path(preset).read_bytes())['ebx'])

    def test_v25_upgrade_preserves_payloads_and_immutable_revision_bytes(self):
        old = Catalog(mapping_version=25)
        for preset in old.presets:
            original = old.create('Old history', base_preset=preset, mode='experimental', choices={
                'da2.bethany_fate': 'warden', 'da2.carver_fate': 'warden', 'da2.bone_pit_dragon': 'killed'})
            upgraded = self.catalog.upgrade(original)
            self.assertEqual(original.choices, upgraded.choices)
            self.assertEqual(read_mod(build_profile_mod(original)[0])['ebx'], read_mod(build_profile_mod(upgraded)[0])['ebx'])
        with tempfile.TemporaryDirectory(dir=ROOT / 'prototype', prefix='.da2-final-test-') as directory:
            store = ProfileStore(directory, catalog=old)
            original = store.create('Older revision', choices={'da2.bethany_fate': 'warden'})
            path = store.profile_directory(original.profile_id) / 'History/00000001.json'
            raw = path.read_bytes()
            current = ProfileStore(directory, catalog=self.catalog)
            saved = current.save(self.catalog.upgrade(original).edited(choices=dict(original.choices, **{'da2.bethany_final_battle': 'died'})))
            self.assertEqual(saved.revision, 2)
            self.assertEqual(saved.mapping_version, self.catalog.version)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(current.load(original.profile_id, revision=1), original)

    def test_explicit_bethany_finale_owns_enum_for_every_earlier_fate_and_hawke_class(self):
        for early, late, player_class in product(self.catalog.choices['da2.bethany_fate']['answers'],
                CASES['da2.bethany_final_battle'][1], ('warrior', 'rogue', 'mage')):
            choices = {'da2.bethany_fate': early, 'da2.carver_fate': 'warden', 'da2.hawke_identity': 'female_' + player_class,
                'da2.final_allegiance': 'mages'}
            partial = self.catalog.choices['da2.bethany_fate']['answers'][early].get('requires_unrestricted')
            mode = 'experimental' if partial else 'ordinary'
            before = compile_profile(self.catalog.create('Earlier Bethany', choices=choices, mode=mode))
            profile = self.catalog.create('Explicit finale', mode=mode, choices=dict(choices, **{'da2.bethany_final_battle': late}))
            mod, report = build_profile_mod(profile)
            flags = flags_from_mod(mod)
            self.assertEqual(flags['da2_bethany_final_battle_death']['DefaultValue'], {'before_war': 0, 'survived': 1, 'died': 2}[late])
            self.assertEqual({n: v for n, v in before.effective_values.items() if n != 'da2_bethany_final_battle_death'},
                             {n: v['DefaultValue'] for n, v in flags.items() if n != 'da2_bethany_final_battle_death'})
            self.assertEqual(report['profile']['resolved_choices']['da2.bethany_fate']['answer_id'], early)
            self.assertEqual(report['profile']['resolved_choices']['da2.bethany_final_battle']['answer_id'], late)
            owner = report['profile']['bethany_final_battle_ownership']
            self.assertEqual(owner['owner'], 'da2.bethany_final_battle')
            # The later alive-unspecified career also supplies a survival
            # fallback. Unrestricted mode no longer implies no finale copy.
            legacy_values = self.catalog.choices['da2.bethany_fate']['answers'][early]['export_values']
            if owner['flag'] not in legacy_values:
                self.assertEqual(owner['superseded_copies'], [])
            else:
                self.assertEqual(owner['superseded_copies'][0]['legacy_value'], before.effective_values[owner['flag']])
            self.assertEqual(report['profile']['story_conflicts'], [])

    def test_clearing_finale_restores_historical_fate_fallback_without_changing_other_choices(self):
        for early in self.catalog.choices['da2.bethany_fate']['answers']:
            mode = 'experimental' if self.catalog.choices['da2.bethany_fate']['answers'][early].get('requires_unrestricted') else 'ordinary'
            original = self.catalog.create('Fallback', mode=mode, choices={'da2.bethany_fate': early, 'da2.carver_fate': 'warden'})
            changed = original.edited(choices=dict(original.choices, **{'da2.bethany_final_battle': 'died'}))
            restored = changed.edited(choices={k: v for k, v in changed.choices.items() if k != 'da2.bethany_final_battle'})
            mod, report = build_profile_mod(restored)
            self.assertEqual(read_mod(mod)['ebx'], read_mod(build_profile_mod(original)[0])['ebx'])
            self.assertNotIn('bethany_final_battle_ownership', report['profile'])

    def test_tallis_never_met_is_scoped_to_its_field_and_restores_original_range_when_changed(self):
        for kiss in ('not_kissed', 'kissed'):
            profile = self.catalog.create('Keep-only Tallis', choices={'da2.tallis_reaction': 'never_met',
                'da2.tallis_kiss': kiss, 'da2.hawke_romance': 'anders', 'da2.bethany_fate': 'warden', 'da2.carver_fate': 'warden'})
            mod, report = build_profile_mod(profile)
            flag = flags_from_mod(mod)['da2_mark_tallis_angry']
            self.assertEqual((flag['DefaultValue'], flag['MinValue'], flag['MaxValue']), (2, 0, 2))
            self.assertTrue(any('conflicting source evidence' in w for w in report['profile']['warnings']))
            for reaction, value in [('not_angry', 0), ('angry', 1)]:
                changed, _ = build_profile_mod(profile.edited(choices=dict(profile.choices, **{'da2.tallis_reaction': reaction})))
                changed_flags = flags_from_mod(changed)
                self.assertEqual((changed_flags['da2_mark_tallis_angry']['DefaultValue'], changed_flags['da2_mark_tallis_angry']['MaxValue']), (value, 1))
                self.assertEqual(changed_flags['da2_mark_tallis_kiss']['DefaultValue'], int(kiss == 'kissed'))
                self.assertEqual(flags_from_mod(mod)['da2_mark_tallis_angry']['MaxValue'], 2)

    def test_unsupported_tallis_range_extension_is_rejected(self):
        catalog = Catalog()
        catalog._choices['da2.tallis_reaction']['answers']['never_met']['max_value_overrides']['da2_mark_tallis_angry'] = 3
        profile = catalog.create('Invalid range', choices={'da2.tallis_reaction': 'never_met'})
        with self.assertRaisesRegex(ProfileError, 'Unsupported range override'):
            compile_profile(profile, catalog=catalog)

    def test_historical_catalogs_retain_the_original_bethany_copy_assignments(self):
        for version in (1, 2, 14, 25):
            catalog = Catalog(mapping_version=version)
            for answer, definition in catalog.choices['da2.bethany_fate']['answers'].items():
                profile = catalog.create('Historical semantics', mode='experimental', choices={'da2.bethany_fate': answer})
                compiled = compile_profile(profile)
                self.assertEqual(compiled.effective_values['da2_bethany_final_battle_death'], definition['export_values']['da2_bethany_final_battle_death'])
                self.assertNotIn('bethany_final_battle_ownership', compiled.report)
                self.assertEqual(compiled.effective_values, compile_profile(self.catalog.upgrade(profile)).effective_values)

if __name__ == '__main__':
    unittest.main(verbosity=2)
