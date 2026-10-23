"""Malcolm's will and preservation of the hidden Legacy played flag."""
from itertools import product
from pathlib import Path
import tempfile
import unittest

from export_worldstate import ROOT, read_mod
from world_profiles import Catalog, ProfileStore
from world_profiles.compiler import build_profile_mod, compile_profile
from test_da2_main_story import flags_from_mod


class MalcolmWillTests(unittest.TestCase):
    def test_all_eight_legacy_combinations_roundtrip_without_changing_other_fields(self):
        catalog = Catalog()
        for preset in catalog.presets:
            for played, side, found in product(('not_played', 'played'), ('larius', 'janeka'), ('not_found', 'found')):
                choices = {'da2.legacy_played': played, 'da2.legacy_side': side,
                    'da2.hawke_identity': 'female_mage', 'da2.bethany_fate': 'warden',
                    'da2.carver_fate': 'warden'}
                original = catalog.create('Independent Legacy', base_preset=preset, mode='ordinary', choices=choices)
                before = compile_profile(original, catalog=catalog)
                mod, report = build_profile_mod(original.edited(choices=dict(choices, **{'da2.malcolm_will': found})), catalog=catalog)
                flags = flags_from_mod(mod)
                self.assertEqual(flags['da2_legacy_malcolm_will']['DefaultValue'], int(found == 'found'))
                self.assertEqual(flags['da2_legacy_malcolm_will']['MaxValue'], 1)
                self.assertEqual({n: v['DefaultValue'] for n, v in flags.items() if n != 'da2_legacy_malcolm_will'},
                                 {n: v for n, v in before.effective_values.items() if n != 'da2_legacy_malcolm_will'})
                self.assertEqual(report['profile']['story_conflicts'], [])
                self.assertFalse(report['profile']['gameplay_tested'])

    def test_all_eight_released_will_values_reproduce_exact_payloads(self):
        catalog = Catalog()
        for preset in catalog.presets:
            if not preset.startswith('template-'):
                continue
            profile = catalog.create('Released Legacy', base_preset=preset, mode='experimental')
            resolved = compile_profile(profile, catalog=catalog).report['resolved_choices']
            self.assertEqual(resolved['da2.malcolm_will']['answer_id'], 'found')
            mod, _ = build_profile_mod(profile.edited(choices={'da2.malcolm_will': 'found'}), catalog=catalog)
            self.assertEqual(read_mod(mod)['ebx'], read_mod(catalog.template_path(preset).read_bytes())['ebx'])

    def test_catalog_seventeen_upgrade_preserves_played_false_and_revision_bytes(self):
        old, current = Catalog(mapping_version=17), Catalog()
        for preset in old.presets:
            profile = old.create('Old Legacy', base_preset=preset, mode='experimental',
                choices={'da2.legacy_played': 'not_played', 'da2.legacy_side': 'janeka'})
            before, _ = build_profile_mod(profile, catalog=current)
            upgraded = current.upgrade(profile)
            after, _ = build_profile_mod(upgraded, catalog=current)
            self.assertEqual(read_mod(before)['ebx'], read_mod(after)['ebx'])
            self.assertEqual(dict(upgraded.choices), dict(profile.choices))
        with tempfile.TemporaryDirectory(dir=ROOT / 'prototype', prefix='.malcolm-test-') as directory:
            store = ProfileStore(directory, catalog=old)
            profile = store.create('Old played flag', choices={'da2.legacy_played': 'not_played'})
            path = store.profile_directory(profile.profile_id) / 'History/00000001.json'
            raw = path.read_bytes()
            upgraded = current.upgrade(profile)
            self.assertEqual(path.read_bytes(), raw)
            saved = ProfileStore(directory, catalog=current).save(upgraded.edited(
                choices=dict(upgraded.choices, **{'da2.malcolm_will': 'not_found'})))
            self.assertEqual(saved.revision, 2)
            self.assertEqual(saved.choices['da2.legacy_played'], 'not_played')
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(store.load(profile.profile_id, revision=1), profile)

    def test_inherited_will_is_preserved_by_other_legacy_edits(self):
        for found in (0, 1):
            catalog = Catalog()
            catalog._presets[catalog.default_preset]['export_values']['da2_legacy_malcolm_will'] = found
            for choices in ({'da2.legacy_played': 'not_played'}, {'da2.legacy_side': 'janeka'}):
                profile = catalog.create('Inherited will', choices=choices)
                result = compile_profile(profile, catalog=catalog)
                self.assertEqual(result.effective_values['da2_legacy_malcolm_will'], found)
                self.assertEqual(result.report['resolved_choices']['da2.malcolm_will']['answer_id'],
                                 'found' if found else 'not_found')


if __name__ == '__main__':
    unittest.main(verbosity=2)
