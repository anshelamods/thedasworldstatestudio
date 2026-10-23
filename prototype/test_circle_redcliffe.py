"""Broken Circle/Redcliffe export consistency and preservation."""
from pathlib import Path
import tempfile
import unittest

from export_worldstate import ROOT, EbxParser, read_mod
from world_profiles import Catalog, ProfileStore
from world_profiles.compiler import build_profile_mod, compile_profile


GROUPS = ('dao.broken_circle', 'dao.connor_fate', 'dao.isolde_fate')


class CircleRedcliffeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def test_all_combinations_serialize_consistent_flags_without_class_gates(self):
        for warden_class in ('warrior', 'rogue', 'mage'):
            for circle, circle_value in [('mages', 0), ('templars', 1)]:
                for connor, connor_value in [('dead', 0), ('freed', 1), ('possessed', 2)]:
                    for isolde, isolde_value in [('alive', 0), ('sacrificed', 1)]:
                        with self.subTest(warden_class=warden_class, circle=circle, connor=connor, isolde=isolde):
                            choices = dict(zip(GROUPS, (circle, connor, isolde)))
                            choices['dao.warden_class'] = warden_class
                            profile = self.catalog.create('Quest combination', mode='ordinary', choices=choices)
                            data, report = build_profile_mod(profile, catalog=self.catalog)
                            objects = EbxParser(read_mod(data)['ebx']).parse()['objects']
                            flags = {o['value']['VariableNameOnServer']: o['value']['DefaultValue']
                                     for o in objects if o['class'] == 'GameVaultVarInt'}
                            expected = dict(dao_broken_circle_choice=circle_value,
                                dao_broken_circle_mages=int(circle_value == 0),
                                dao_broken_circle_templars=int(circle_value == 1),
                                dao_connor_state=connor_value, dao_connor_dead=int(connor_value == 0),
                                dao_connor_alive_and_not_possessed=int(connor_value == 1),
                                dao_connor_alive_and_possessed=int(connor_value == 2), dao_isolde_state=isolde_value)
                            for name, value in expected.items():
                                self.assertEqual(flags[name], value, name)
                            self.assertEqual(sum(flags[name] for name in ('dao_connor_dead',
                                'dao_connor_alive_and_not_possessed', 'dao_connor_alive_and_possessed')), 1)
                            self.assertEqual(dict(profile.choices), choices)
                            self.assertEqual(report['profile']['story_conflicts'], [])

    def test_single_edits_preserve_every_unowned_flag_across_all_bases(self):
        for preset in self.catalog.presets:
            profile = self.catalog.create('Inherited quests', base_preset=preset, mode='experimental')
            before = compile_profile(profile, catalog=self.catalog)
            for group in GROUPS:
                for answer_id, answer in self.catalog.choices[group]['answers'].items():
                    with self.subTest(preset=preset, group=group, answer=answer_id):
                        compiled = compile_profile(profile.edited(choices={group: answer_id}), catalog=self.catalog)
                        for name, value in before.effective_values.items():
                            if name not in answer['export_values']:
                                self.assertEqual(compiled.effective_values[name], value, name)
                        self.assertEqual(compiled.report['resolved_choices'][group]['answer_id'], answer_id)

    def test_existing_released_quest_choices_reproduce_exact_payloads(self):
        for preset in self.catalog.presets:
            if not preset.startswith('template-'):
                continue
            profile = self.catalog.create('Released quests', base_preset=preset, mode='experimental')
            resolved = compile_profile(profile, catalog=self.catalog).report['resolved_choices']
            choices = {group: resolved[group]['answer_id'] for group in GROUPS}
            self.assertEqual(choices, dict(zip(GROUPS, ('mages', 'freed', 'alive'))))
            actual, _ = build_profile_mod(profile.edited(choices=choices), catalog=self.catalog)
            self.assertEqual(read_mod(actual)['ebx'], read_mod(self.catalog.template_path(preset).read_bytes())['ebx'])

    def test_catalog_seven_upgrade_preserves_all_base_payloads_and_existing_battle_ownership(self):
        old = Catalog(mapping_version=7)
        for preset in old.presets:
            for choices in ({}, {'dao.archdemon_killer': 'loghain', 'dao.loghain_fate': 'sacrificed',
                                 'dao.warden_fate': 'alive', 'dao.morrigan_child': 'none'}):
                with self.subTest(preset=preset, choices=choices):
                    original = old.create('Before quest controls', base_preset=preset, mode='experimental', choices=choices)
                    before, _ = build_profile_mod(original, catalog=self.catalog)
                    upgraded = self.catalog.upgrade(original)
                    after, _ = build_profile_mod(upgraded, catalog=self.catalog)
                    self.assertEqual(read_mod(before)['ebx'], read_mod(after)['ebx'])
                    self.assertEqual(upgraded.choices, original.choices)

    def test_upgrading_and_editing_keeps_the_prior_saved_revision(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'prototype', prefix='.quest-test-') as directory:
            legacy = ProfileStore(directory, catalog=Catalog(mapping_version=7))
            original = legacy.create('Existing history')
            path = legacy.profile_directory(original.profile_id) / 'History/00000001.json'
            before = path.read_bytes()
            upgraded = self.catalog.upgrade(original)
            self.assertEqual(path.read_bytes(), before)
            current = ProfileStore(directory, catalog=self.catalog)
            saved = current.save(upgraded.edited(choices={'dao.connor_fate': 'possessed'}))
            self.assertEqual(saved.revision, 2)
            self.assertEqual(saved.mapping_version, self.catalog.version)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(current.load(original.profile_id, revision=1), original)

    def test_unrecognized_inherited_connor_tuple_is_preserved_until_explicit_edit(self):
        catalog = Catalog()
        catalog._presets[catalog.default_preset]['export_values'].update(
            dao_connor_state=1, dao_connor_dead=1, dao_connor_alive_and_not_possessed=0,
            dao_connor_alive_and_possessed=0)
        profile = catalog.create('Inconsistent inherited flags')
        compiled = compile_profile(profile, catalog=catalog)
        self.assertIsNone(compiled.report['resolved_choices']['dao.connor_fate']['answer_id'])
        self.assertEqual(compiled.effective_values['dao_connor_dead'], 1)
        self.assertEqual(compiled.effective_values['dao_connor_state'], 1)
        selected = compile_profile(profile.edited(choices={'dao.connor_fate': 'freed'}), catalog=catalog)
        self.assertEqual(selected.effective_values['dao_connor_dead'], 0)
        self.assertEqual(selected.effective_values['dao_connor_alive_and_not_possessed'], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
