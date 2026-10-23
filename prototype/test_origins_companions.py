"""Origins companion outcomes, independent controls and historical preservation."""
from itertools import product
from pathlib import Path
import tempfile
import unittest

from export_worldstate import ROOT, EbxParser, read_mod
from world_profiles import Catalog, ProfileStore
from world_profiles.compiler import build_profile_mod, compile_profile


GROUPS = ('dao.leliana_fate', 'dao.wynne_fate', 'dao.zevran_recruited', 'dao.zevran_fate')
LELIANA = ('not_recruited', 'alive', 'killed_at_urn', 'left_after_urn')
WYNNE = ('not_recruited', 'alive', 'died_at_circle', 'killed_at_urn')


class OriginsCompanionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def test_all_sixty_four_combinations_serialize_related_fields(self):
        for leliana, wynne, recruited, alive in product(range(4), range(4), range(2), range(2)):
            choices = dict(zip(GROUPS, (LELIANA[leliana], WYNNE[wynne],
                ('not_recruited', 'recruited')[recruited], ('dead', 'alive')[alive])))
            with self.subTest(choices=choices):
                profile = self.catalog.create('Companion combination', mode='ordinary', choices=choices)
                mod, report = build_profile_mod(profile, catalog=self.catalog)
                flags = {o['value']['VariableNameOnServer']: o['value']['DefaultValue']
                    for o in EbxParser(read_mod(mod)['ebx']).parse()['objects'] if o['class'] == 'GameVaultVarInt'}
                expected = dict(dao_leliana_fate=leliana, dao_leliana_alive=int(leliana != 2),
                    dao_leliana_recruited=int(leliana != 0), dao_leliana_killed=0,
                    dao_leliana_killed_sacred_ashes=int(leliana == 2), dao_leliana_crisis=int(leliana == 3),
                    dao_wynne_fate=wynne, dao_wynne_recruited=int(wynne in (1, 3)),
                    dao_zevran_recruited=recruited, dao_zevran_alive=alive)
                self.assertEqual({name: flags[name] for name in expected}, expected)
                self.assertEqual(dict(profile.choices), choices)
                self.assertEqual(report['profile']['story_conflicts'], [])
                self.assertFalse(report['profile']['gameplay_tested'])

    def test_every_single_edit_preserves_unowned_flags_across_all_bases(self):
        for preset in self.catalog.presets:
            original = self.catalog.create('Inherited history', base_preset=preset, mode='experimental')
            before = compile_profile(original, catalog=self.catalog)
            for group in GROUPS:
                for answer_id, answer in self.catalog.choices[group]['answers'].items():
                    with self.subTest(preset=preset, group=group, answer=answer_id):
                        after = compile_profile(original.edited(choices={group: answer_id}), catalog=self.catalog)
                        for name, value in before.effective_values.items():
                            if name not in answer['export_values']:
                                self.assertEqual(after.effective_values[name], value, name)
                        self.assertEqual(after.report['resolved_choices'][group]['answer_id'], answer_id)
                        self.assertEqual(after.max_overrides, before.max_overrides)

    def test_explicit_released_outcomes_reproduce_all_original_payloads(self):
        for preset in self.catalog.presets:
            if not preset.startswith('template-'):
                continue
            original = self.catalog.create('Released history', base_preset=preset, mode='experimental')
            choices = dict(zip(GROUPS, ('alive', 'alive', 'recruited', 'alive')))
            resolved = compile_profile(original, catalog=self.catalog).report['resolved_choices']
            self.assertEqual({group: resolved[group]['answer_id'] for group in GROUPS}, choices)
            mod, _ = build_profile_mod(original.edited(choices=choices), catalog=self.catalog)
            self.assertEqual(read_mod(mod)['ebx'], read_mod(self.catalog.template_path(preset).read_bytes())['ebx'])

    def test_catalog_nine_upgrade_preserves_existing_choices_and_full_payload(self):
        old = Catalog(mapping_version=9)
        for preset in old.presets:
            for choices in ({}, {'dao.warden_romance': 'leliana', 'dao.nature_outcome': 'elves',
                                'dao.anvil_fate': 'branka_destroyed'}):
                with self.subTest(preset=preset, choices=choices):
                    original = old.create('Before companions', base_preset=preset, mode='experimental', choices=choices)
                    before, _ = build_profile_mod(original, catalog=self.catalog)
                    upgraded = self.catalog.upgrade(original)
                    after, _ = build_profile_mod(upgraded, catalog=self.catalog)
                    self.assertEqual(read_mod(before)['ebx'], read_mod(after)['ebx'])
                    self.assertEqual(upgraded.choices, original.choices)
                    self.assertEqual(original.mapping_version, 9)

    def test_new_saved_revision_keeps_historical_catalog_and_document(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'prototype', prefix='.companion-test-') as directory:
            old = ProfileStore(directory, catalog=Catalog(mapping_version=9))
            original = old.create('Existing history')
            path = old.profile_directory(original.profile_id) / 'History/00000001.json'
            raw = path.read_bytes()
            upgraded = self.catalog.upgrade(original)
            self.assertEqual(path.read_bytes(), raw)
            current = ProfileStore(directory, catalog=self.catalog)
            saved = current.save(upgraded.edited(choices={'dao.leliana_fate': 'left_after_urn'}))
            self.assertEqual(saved.revision, 2)
            self.assertEqual(saved.mapping_version, self.catalog.version)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(current.load(original.profile_id, revision=1), original)

    def test_inconsistent_inherited_combinations_are_not_silently_replaced(self):
        catalog = Catalog()
        catalog._presets[catalog.default_preset]['export_values'].update(dao_leliana_fate=3,
            dao_leliana_alive=0, dao_leliana_killed=1, dao_leliana_crisis=0,
            dao_wynne_fate=2, dao_wynne_recruited=1)
        profile = catalog.create('Unusual inherited history')
        before = compile_profile(profile, catalog=catalog)
        self.assertIsNone(before.report['resolved_choices']['dao.leliana_fate']['answer_id'])
        self.assertIsNone(before.report['resolved_choices']['dao.wynne_fate']['answer_id'])
        self.assertEqual(before.effective_values['dao_leliana_killed'], 1)
        self.assertEqual(before.effective_values['dao_wynne_recruited'], 1)
        after = compile_profile(profile.edited(choices={'dao.leliana_fate': 'left_after_urn',
            'dao.wynne_fate': 'died_at_circle'}), catalog=catalog)
        self.assertEqual(after.effective_values['dao_leliana_alive'], 1)
        self.assertEqual(after.effective_values['dao_leliana_crisis'], 1)
        self.assertEqual(after.effective_values['dao_leliana_killed'], 0)
        self.assertEqual(after.effective_values['dao_wynne_recruited'], 0)
        self.assertIn('original game enum', catalog.choices['dao.leliana_fate']['basis'])

    def test_romances_and_other_quest_choices_remain_independent_in_ordinary_mode(self):
        for romance in ('none', 'alistair', 'morrigan', 'leliana', 'zevran'):
            original = self.catalog.create('Independent romance', mode='ordinary',
                choices={'dao.warden_romance': romance, 'dao.broken_circle': 'mages'})
            before = compile_profile(original, catalog=self.catalog)
            for group in GROUPS:
                for answer in self.catalog.choices[group]['answers']:
                    choices = dict(original.choices, **{group: answer})
                    after = compile_profile(original.edited(choices=choices), catalog=self.catalog)
                    owned = self.catalog.choices[group]['answers'][answer]['export_values']
                    for flag, value in before.effective_values.items():
                        if flag not in owned:
                            self.assertEqual(after.effective_values[flag], value, (romance, group, flag))
                    self.assertEqual(after.report['story_conflicts'], [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
