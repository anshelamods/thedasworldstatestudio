"""Nature/Orzammar/Anvil flag consistency and historical preservation."""
from pathlib import Path
import tempfile
import unittest

from export_worldstate import ROOT, EbxParser, read_mod
from world_profiles import Catalog, ProfileStore
from world_profiles.compiler import build_profile_mod, compile_profile


GROUPS = ('dao.nature_outcome', 'dao.orzammar_ruler', 'dao.anvil_fate')


class NatureOrzammarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def test_all_eighteen_combinations_serialize_consistent_related_flags(self):
        for nature, nature_value in [('peace', 0), ('werewolves', 1), ('elves', 2)]:
            for ruler, ruler_value in [('harrowmont', 0), ('bhelen', 1)]:
                for anvil, anvil_value in [('warden_destroyed', 0), ('branka_destroyed', 1), ('preserved', 2)]:
                    with self.subTest(nature=nature, ruler=ruler, anvil=anvil):
                        choices = dict(zip(GROUPS, (nature, ruler, anvil)))
                        profile = self.catalog.create('Quest combination', mode='ordinary', choices=choices)
                        mod, report = build_profile_mod(profile, catalog=self.catalog)
                        flags = {o['value']['VariableNameOnServer']: o['value']['DefaultValue']
                            for o in EbxParser(read_mod(mod)['ebx']).parse()['objects'] if o['class'] == 'GameVaultVarInt'}
                        expected = dict(dao_nb_werewolf_elf_choice=nature_value,
                            dao_ntb_brokered_peace=int(nature_value == 0), dao_ntb_side_werewolves=int(nature_value == 1),
                            dao_ntb_side_elves=int(nature_value == 2), dao_orzammar_ruler=ruler_value,
                            dao_harrowmont_is_king=int(ruler_value == 0), dao_bhelen_is_king=int(ruler_value == 1),
                            dao_paragon_anvil_fate=anvil_value, dao_paragon_chosen=int(anvil_value != 0),
                            dao_par_chose_caridin=int(anvil_value == 0), dao_par_chose_branka=int(anvil_value != 0),
                            dao_par_caridin_destroyed_anvil=int(anvil_value == 0),
                            dao_par_branka_destroyed_anvil=int(anvil_value == 1), dao_par_branka_kept_anvil=int(anvil_value == 2))
                        for name, value in expected.items():
                            self.assertEqual(flags[name], value, name)
                        self.assertEqual(sum(flags[n] for n in ('dao_ntb_brokered_peace', 'dao_ntb_side_werewolves', 'dao_ntb_side_elves')), 1)
                        self.assertEqual(flags['dao_harrowmont_is_king'] + flags['dao_bhelen_is_king'], 1)
                        self.assertEqual(sum(flags[n] for n in ('dao_par_caridin_destroyed_anvil', 'dao_par_branka_destroyed_anvil', 'dao_par_branka_kept_anvil')), 1)
                        self.assertEqual(dict(profile.choices), choices)
                        self.assertEqual(report['profile']['story_conflicts'], [])
                        self.assertFalse(report['profile']['gameplay_tested'])

    def test_single_edits_preserve_every_unowned_flag_in_all_bases(self):
        for preset in self.catalog.presets:
            profile = self.catalog.create('Inherited world', base_preset=preset, mode='experimental')
            before = compile_profile(profile, catalog=self.catalog)
            for group in GROUPS:
                for answer_id, answer in self.catalog.choices[group]['answers'].items():
                    with self.subTest(preset=preset, group=group, answer=answer_id):
                        compiled = compile_profile(profile.edited(choices={group: answer_id}), catalog=self.catalog)
                        for name, value in before.effective_values.items():
                            if name not in answer['export_values']:
                                self.assertEqual(compiled.effective_values[name], value, name)
                        self.assertEqual(compiled.report['resolved_choices'][group]['answer_id'], answer_id)

    def test_released_outcomes_reproduce_exact_original_payloads(self):
        for preset in self.catalog.presets:
            if not preset.startswith('template-'):
                continue
            original = self.catalog.create('Released world', base_preset=preset, mode='experimental')
            resolved = compile_profile(original, catalog=self.catalog).report['resolved_choices']
            choices = {group: resolved[group]['answer_id'] for group in GROUPS}
            self.assertEqual(choices, dict(zip(GROUPS, ('peace', 'bhelen', 'warden_destroyed'))))
            actual, _ = build_profile_mod(original.edited(choices=choices), catalog=self.catalog)
            self.assertEqual(read_mod(actual)['ebx'], read_mod(self.catalog.template_path(preset).read_bytes())['ebx'])

    def test_catalog_eight_upgrade_preserves_all_bases_and_existing_quest_selections(self):
        old = Catalog(mapping_version=8)
        for preset in old.presets:
            for choices in ({}, {'dao.broken_circle': 'templars', 'dao.connor_fate': 'possessed', 'dao.isolde_fate': 'sacrificed'}):
                with self.subTest(preset=preset, choices=choices):
                    original = old.create('Before new quests', base_preset=preset, mode='experimental', choices=choices)
                    before, _ = build_profile_mod(original, catalog=self.catalog)
                    upgraded = self.catalog.upgrade(original)
                    after, _ = build_profile_mod(upgraded, catalog=self.catalog)
                    self.assertEqual(read_mod(before)['ebx'], read_mod(after)['ebx'])
                    self.assertEqual(upgraded.choices, original.choices)

    def test_saved_upgrade_keeps_the_prior_revision_intact(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'prototype', prefix='.orzammar-test-') as directory:
            old = ProfileStore(directory, catalog=Catalog(mapping_version=8))
            original = old.create('Existing world')
            path = old.profile_directory(original.profile_id) / 'History/00000001.json'
            before = path.read_bytes()
            upgraded = self.catalog.upgrade(original)
            self.assertEqual(path.read_bytes(), before)
            current = ProfileStore(directory, catalog=self.catalog)
            saved = current.save(upgraded.edited(choices={'dao.orzammar_ruler': 'harrowmont'}))
            self.assertEqual(saved.revision, 2)
            self.assertEqual(saved.mapping_version, self.catalog.version)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(current.load(original.profile_id, revision=1), original)

    def test_inconsistent_inherited_flags_are_preserved_until_explicitly_edited(self):
        catalog = Catalog()
        catalog._presets[catalog.default_preset]['export_values'].update(dao_orzammar_ruler=1,
            dao_bhelen_is_king=0, dao_harrowmont_is_king=0, dao_paragon_anvil_fate=0, dao_par_chose_caridin=0)
        profile = catalog.create('Inherited inconsistency')
        before = compile_profile(profile, catalog=catalog)
        for group in ('dao.orzammar_ruler', 'dao.anvil_fate'):
            self.assertIsNone(before.report['resolved_choices'][group]['answer_id'])
        self.assertEqual(before.effective_values['dao_par_chose_caridin'], 0)
        after = compile_profile(profile.edited(choices={'dao.orzammar_ruler': 'bhelen',
            'dao.anvil_fate': 'warden_destroyed'}), catalog=catalog)
        self.assertEqual(after.effective_values['dao_bhelen_is_king'], 1)
        self.assertEqual(after.effective_values['dao_par_chose_caridin'], 1)
        basis = next(item['basis'] for item in after.report['selections'] if item['choice_id'] == 'dao.anvil_fate')
        self.assertIn('dao_par_chose_caridin', basis)
        self.assertIn('verification', basis)


if __name__ == '__main__':
    unittest.main(verbosity=2)
