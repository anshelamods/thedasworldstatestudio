"""Survival, ritual and battle serialization, ownership and historical compatibility."""
from pathlib import Path
import tempfile
import unittest

from export_worldstate import ROOT, EbxParser, read_mod
from world_profiles import Catalog, ProfileStore
from world_profiles.compiler import StoryConflict, build_profile_mod, compile_profile


GROUPS = ('dao.warden_fate', 'dao.archdemon_killer', 'dao.morrigan_child')


class FinalBattleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def test_new_answers_preserve_all_unowned_fields_in_every_base(self):
        for preset in self.catalog.presets:
            original = self.catalog.create('Reference', base_preset=preset, mode='experimental')
            before = compile_profile(original, catalog=self.catalog)
            for group in GROUPS:
                for answer_id, answer in self.catalog.choices[group]['answers'].items():
                    with self.subTest(preset=preset, group=group, answer=answer_id):
                        after = compile_profile(original.edited(choices={group: answer_id}), catalog=self.catalog)
                        for name, value in before.effective_values.items():
                            if name not in answer['export_values']:
                                self.assertEqual(after.effective_values[name], value, name)
                        self.assertEqual(after.report['resolved_choices'][group]['answer_id'], answer_id)

    def test_all_ritual_answers_update_both_parent_occurrences_and_the_reviewed_range(self):
        fields = ('dao_morrigan_baby', 'dao_morrigan_baby_warden', 'dao_morrigan_baby_alistair',
                  'dao_morrigan_baby_loghain', 'dao_morrigan_dark_ritual',
                  'dao_morrigan_dark_ritual_warden', 'dao_morrigan_has_child')
        expected = {
            'none': (0, 0, 0, 0, 0, 0, 0),
            'old_god_warden': (1, 1, 0, 0, 1, 1, 1),
            'old_god_alistair': (2, 0, 1, 0, 1, 0, 1),
            'old_god_loghain': (3, 0, 0, 1, 1, 0, 1),
            'human_warden': (4, 1, 0, 0, 0, 0, 1),
        }
        for answer, values in expected.items():
            with self.subTest(answer=answer):
                profile = self.catalog.create('Ritual', choices={'dao.morrigan_child': answer})
                mod, report = build_profile_mod(profile, catalog=self.catalog)
                objects = [o['value'] for o in EbxParser(read_mod(mod)['ebx']).parse()['objects'] if o['class'] == 'GameVaultVarInt']
                parents = [o for o in objects if o['VariableNameOnServer'] == 'dao_morrigan_baby_warden']
                self.assertEqual(len(parents), 2)
                for name, value in zip(fields, values):
                    matches = [o for o in objects if o['VariableNameOnServer'] == name]
                    self.assertTrue(matches)
                    for obj in matches:
                        self.assertEqual(obj['DefaultValue'], value)
                if answer == 'human_warden':
                    self.assertEqual(next(o for o in objects if o['VariableNameOnServer'] == 'dao_morrigan_baby')['MaxValue'], 4)
                self.assertTrue(any('dao_morrigan_has_child needs verification' in warning for warning in report['profile']['warnings']))
                self.assertFalse(report['profile']['gameplay_tested'])

    def test_explicit_matching_controls_reproduce_released_payloads(self):
        for preset in self.catalog.presets:
            if not preset.startswith('template-'):
                continue
            original = self.catalog.create('Released', base_preset=preset, mode='experimental')
            resolved = compile_profile(original, catalog=self.catalog).report['resolved_choices']
            choices = {g: resolved[g]['answer_id'] for g in GROUPS if resolved[g]['answer_id'] is not None}
            exported, _ = build_profile_mod(original.edited(choices=choices), catalog=self.catalog)
            self.assertEqual(read_mod(exported)['ebx'], read_mod(self.catalog.template_path(preset).read_bytes())['ebx'])

    def test_survival_battle_and_loghain_sacrifice_serialize_the_reviewed_fields(self):
        cases = [({'dao.warden_fate': answer}, {'dao_warden_state': value, 'dao_warden_alive': value})
                 for answer, value in [('sacrificed', 0), ('alive', 1)]]
        cases += [({'dao.archdemon_killer': answer}, {'dao_archdemon_killer': value,
            'dao_alistair_killed_archdemon': int(value == 1), 'dao_loghain_killed_archdemon': int(value == 2)})
            for answer, value in [('warden', 0), ('alistair', 1), ('loghain', 2)]]
        cases.append(({'dao.loghain_fate': 'sacrificed'}, {'dao_loghain_fate': 3, 'dao_loghain_alive': 0,
            'dao_loghain_executed': 0, 'dao_loghain_killed_archdemon': 1, 'dao_loghain_recruited': 1}))
        for choices, expected in cases:
            with self.subTest(choices=choices):
                mod, _ = build_profile_mod(self.catalog.create('Serialized finale', mode='experimental', choices=choices), catalog=self.catalog)
                objects = EbxParser(read_mod(mod)['ebx']).parse()['objects']
                flags = {o['value']['VariableNameOnServer']: o['value']['DefaultValue'] for o in objects if o['class'] == 'GameVaultVarInt'}
                for name, value in expected.items():
                    self.assertEqual(flags[name], value)

    def test_complete_finale_matrix_validates_without_automatic_fate_edits(self):
        for killer_index, killer in enumerate(('warden', 'alistair', 'loghain')):
            for child_index, child in enumerate(('none', 'old_god_warden', 'old_god_alistair', 'old_god_loghain', 'human_warden')):
                ritual = child_index in (1, 2, 3)
                for warden in ('sacrificed', 'alive'):
                    with self.subTest(killer=killer, child=child, warden=warden):
                        alistair = 'sacrificed' if killer == 'alistair' and not ritual else 'king'
                        loghain = ('alive_recruited' if ritual else 'sacrificed') if killer == 'loghain' else 'executed_by_warden'
                        choices = dict(zip(GROUPS, (warden, killer, child)))
                        choices.update({'dao.alistair_fate': alistair, 'dao.loghain_fate': loghain,
                            'dao.ferelden_ruler': 'anora_alone' if alistair == 'sacrificed' else 'alistair_alone'})
                        profile = self.catalog.create('Finale', choices=choices)
                        expected_survival = killer != 'warden' or ritual
                        if (warden == 'alive') != expected_survival:
                            with self.assertRaisesRegex(StoryConflict, 'Warden’s survival disagrees'):
                                compile_profile(profile, catalog=self.catalog)
                            continue
                        compiled = compile_profile(profile, catalog=self.catalog)
                        self.assertEqual(dict(profile.choices), choices)
                        self.assertEqual(compiled.effective_values['dao_archdemon_killer'], killer_index)
                        self.assertEqual(compiled.effective_values['dao_alistair_killed_archdemon'], int(killer == 'alistair'))
                        self.assertEqual(compiled.effective_values['dao_loghain_killed_archdemon'], int(killer == 'loghain'))
                        for group, answer in choices.items():
                            self.assertEqual(compiled.report['resolved_choices'][group]['answer_id'], answer)

    def test_battle_owns_kill_flags_while_surviving_alistair_keeps_his_career(self):
        profile = self.catalog.create('Alistair kills and survives', choices={
            'dao.archdemon_killer': 'alistair', 'dao.morrigan_child': 'old_god_alistair',
            'dao.warden_fate': 'alive', 'dao.alistair_fate': 'king'})
        compiled = compile_profile(profile, catalog=self.catalog)
        self.assertEqual(compiled.effective_values['dao_alistair_state'], 2)
        self.assertEqual(compiled.effective_values['dao_alistair_alive'], 1)
        self.assertEqual(compiled.effective_values['dao_alistair_killed_archdemon'], 1)
        self.assertEqual(compiled.report['resolved_choices']['dao.alistair_fate']['answer_id'], 'king')
        self.assertEqual(compiled.report['battle_flag_ownership']['owner'], 'dao.archdemon_killer')
        before = compile_profile(profile.edited(choices={'dao.alistair_fate': 'king'}), catalog=self.catalog)
        self.assertEqual(before.effective_values['dao_alistair_killed_archdemon'], 0)

    def test_conflicting_finale_is_retained_only_in_experimental_mode(self):
        profile = self.catalog.create('Contradictory sacrifice', choices={'dao.archdemon_killer': 'alistair',
            'dao.morrigan_child': 'none', 'dao.alistair_fate': 'executed', 'dao.ferelden_ruler': 'anora_alone'})
        with self.assertRaisesRegex(StoryConflict, 'Alistair’s fate disagrees'):
            compile_profile(profile, catalog=self.catalog)
        compiled = compile_profile(profile.edited(mode='experimental'), catalog=self.catalog)
        self.assertTrue(compiled.report['story_conflicts'])
        self.assertEqual(compiled.effective_values['dao_alistair_executed'], 1)
        self.assertEqual(compiled.effective_values['dao_alistair_killed_archdemon'], 1)

    def test_catalog_six_upgrade_keeps_every_base_payload_and_immutable_history(self):
        old = Catalog(mapping_version=6)
        for preset in old.presets:
            for choices in ({}, {'dao.alistair_fate': 'king', 'dao.loghain_fate': 'alive_recruited'}):
                original = old.create('Before finale controls', base_preset=preset, mode='experimental', choices=choices)
                before, _ = build_profile_mod(original, catalog=self.catalog)
                upgraded = self.catalog.upgrade(original)
                after, _ = build_profile_mod(upgraded, catalog=self.catalog)
                self.assertEqual(read_mod(before)['ebx'], read_mod(after)['ebx'])
        with tempfile.TemporaryDirectory(dir=ROOT / 'prototype', prefix='.finale-test-') as directory:
            legacy = ProfileStore(directory, catalog=old)
            original = legacy.create('Existing history')
            path = legacy.profile_directory(original.profile_id) / 'History/00000001.json'
            before = path.read_bytes()
            upgraded = self.catalog.upgrade(original)
            current = ProfileStore(directory, catalog=self.catalog)
            saved = current.save(upgraded)
            self.assertEqual(saved.revision, 2)
            self.assertEqual(saved.mapping_version, self.catalog.version)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(current.load(original.profile_id, revision=1), original)

    def test_missing_warden_state_is_preserved_without_guessing_survival(self):
        catalog = Catalog()
        catalog._presets[catalog.default_preset]['export_values'].update(dao_warden_state=2, dao_warden_alive=0)
        profile = catalog.create('Missing Warden')
        compiled = compile_profile(profile, catalog=catalog)
        self.assertIsNone(compiled.report['resolved_choices']['dao.warden_fate']['answer_id'])
        self.assertEqual(compiled.effective_values['dao_warden_state'], 2)
        self.assertEqual(compiled.effective_values['dao_warden_alive'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
