"""Selectable Keep history with no corresponding export assignment."""
from pathlib import Path
import tempfile
import unittest

from export_worldstate import ROOT, read_mod
from world_profiles import Catalog, ProfileStore
from world_profiles.compiler import build_profile_mod, compile_profile
from world_profiles.model import ProfileError, UnsupportedVersion

CHOICE = 'da2.bone_pit_dragon'


class ProfileOnlyDragonTests(unittest.TestCase):
    def test_both_answers_leave_entire_fbmod_and_every_game_value_unchanged_across_nine_bases(self):
        catalog = Catalog()
        for preset in catalog.presets:
            original = catalog.create('Profile only proof', base_preset=preset, mode='experimental')
            baseline, _ = build_profile_mod(original, catalog=catalog)
            before = compile_profile(original, catalog=catalog)
            for answer in ('not_killed', 'killed'):
                profile = original.edited(choices={CHOICE: answer})
                mod, report = build_profile_mod(profile, catalog=catalog)
                compiled = compile_profile(profile, catalog=catalog)
                self.assertEqual(mod, baseline)
                self.assertEqual(compiled.values, before.values)
                self.assertEqual(compiled.effective_values, before.effective_values)
                self.assertEqual(compiled.max_overrides, before.max_overrides)
                self.assertEqual(report['profile']['compiled_values_sha256'], before.report['compiled_values_sha256'])
                self.assertEqual(report['profile']['inherited_flag_count'], before.report['inherited_flag_count'])

    def test_unselected_has_no_inherited_answer_and_explicit_answers_are_reported_as_profile_only(self):
        catalog = Catalog()
        original = catalog.create('Unselected dragon')
        before = compile_profile(original, catalog=catalog)
        resolved = before.report['resolved_choices'][CHOICE]
        self.assertIsNone(resolved['answer_id'])
        self.assertEqual(resolved['source'], 'not_selected')
        self.assertFalse(any(CHOICE in warning for warning in before.report['warnings']))
        for answer in ('not_killed', 'killed'):
            after = compile_profile(original.edited(choices={CHOICE: answer}), catalog=catalog)
            selection, = after.report['selections']
            self.assertEqual(selection['export_behavior'], 'profile-only')
            self.assertEqual(selection['evidence_status'], 'profile-only')
            self.assertEqual(after.report['resolved_choices'][CHOICE]['answer_id'], answer)
            self.assertEqual(after.report['resolved_choices'][CHOICE]['source'], 'explicit_selection')
            self.assertIn(CHOICE + ': saved in the profile only; not exported to DAI.', after.report['warnings'])

    def test_json_duplicate_import_save_clear_and_history_preserve_the_local_choice(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'prototype', prefix='.dragon-profile-test-') as directory:
            store = ProfileStore(Path(directory) / 'profiles')
            original = store.create('Dragon history', choices={CHOICE: 'killed', 'da2.bethany_fate': 'warden'})
            document = Path(directory) / 'portable.json'
            store.export_json(original.profile_id, document)
            imported = store.import_profile(document)
            copied = store.duplicate(original.profile_id, 'Copied dragon')
            self.assertEqual(dict(imported.choices), dict(original.choices))
            self.assertEqual(dict(copied.choices), dict(original.choices))
            raw = document.read_bytes()
            cleared = store.save(original.edited(choices={'da2.bethany_fate': 'warden'}))
            self.assertNotIn(CHOICE, cleared.choices)
            self.assertEqual(store.load(original.profile_id, revision=1), original)
            self.assertEqual(document.read_bytes(), raw)
            self.assertEqual(read_mod(build_profile_mod(cleared)[0])['ebx'], read_mod(build_profile_mod(original)[0])['ebx'])

    def test_catalog_nineteen_upgrades_preserve_payloads_and_old_revision_bytes(self):
        old, current = Catalog(mapping_version=19), Catalog()
        for preset in old.presets:
            original = old.create('Older history', base_preset=preset, mode='experimental',
                choices={'da2.keran_fate': 'templars', 'da2.legacy_played': 'not_played'})
            upgraded = current.upgrade(original)
            self.assertEqual(dict(original.choices), dict(upgraded.choices))
            self.assertEqual(read_mod(build_profile_mod(original, catalog=current)[0])['ebx'],
                             read_mod(build_profile_mod(upgraded, catalog=current)[0])['ebx'])
        with tempfile.TemporaryDirectory(dir=ROOT / 'prototype', prefix='.dragon-upgrade-test-') as directory:
            store = ProfileStore(directory, catalog=old)
            original = store.create('Old revision', choices={'da2.keran_fate': 'killed'})
            path = store.profile_directory(original.profile_id) / 'History/00000001.json'
            raw = path.read_bytes()
            upgraded = current.upgrade(original)
            saved = ProfileStore(directory, catalog=current).save(upgraded.edited(
                choices=dict(upgraded.choices, **{CHOICE: 'killed'})))
            self.assertEqual(saved.revision, 2)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(store.load(original.profile_id, revision=1), original)

    def test_profile_only_cannot_accidentally_assign_values_ranges_or_requirements(self):
        for poison in ('values', 'range', 'answer_requirement', 'choice_requirement'):
            catalog = Catalog()
            definition = catalog._choices[CHOICE]
            answer = definition['answers']['killed']
            if poison == 'values':
                answer['export_values'] = {'da2_hawke_class': 2}
            elif poison == 'range':
                answer['max_value_overrides'] = {'da2_fenris_alive': 4}
            elif poison == 'answer_requirement':
                answer['requires'] = {'da2_hawke_class': 2}
            else:
                definition['requires'] = {'da2_hawke_class': 2}
            with self.assertRaisesRegex(ProfileError, 'Profile-only choices cannot assign'):
                compile_profile(catalog.create('Invalid local mapping', choices={CHOICE: 'killed'}), catalog=catalog)

    def test_upgrade_cannot_silently_reclassify_existing_export_behavior(self):
        old, current = Catalog(mapping_version=19), Catalog()
        original = old.create('Existing game choice', choices={'da2.keran_fate': 'killed'})
        current._choices['da2.keran_fate']['export_behavior'] = 'profile-only'
        with self.assertRaisesRegex(UnsupportedVersion, 'Changed export behavior'):
            current.upgrade(original)


if __name__ == '__main__':
    unittest.main(verbosity=2)
