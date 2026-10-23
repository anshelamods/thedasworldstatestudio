"""Profile persistence, conflict protection, and parity with reviewed export examples."""
from contextlib import redirect_stdout
from dataclasses import replace
import hashlib
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from export_worldstate import DEFAULT_TEMPLATE, ROOT, EbxParser, build_mod, load_early_cases, read_mod
from profile_cli import main as cli
from world_profiles import Catalog, Profile, ProfileError, ProfileStore, RevisionConflict, UnsupportedVersion
from world_profiles.compiler import StoryConflict, build_profile_mod, compile_profile, export_profile_mod
from world_profiles.model import canonical_json


class ProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / 'prototype', prefix='.profile-test-')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.store = ProfileStore(self.directory / 'profiles', catalog=self.catalog)

    def create(self, **kwargs):
        return self.store.create('Test history', **{'base_preset': 'early-tests-v1', **kwargs})

    def test_unicode_roundtrip_and_choice_immutability(self):
        choices = {'da2.bethany_fate': 'warden'}
        profile = self.store.create('Éléonore — Grey Wardens', choices=choices)
        choices['da2.bethany_fate'] = 'circle'
        self.assertEqual(profile.choices['da2.bethany_fate'], 'warden')
        with self.assertRaises(TypeError):
            profile.choices['da2.bethany_fate'] = 'circle'
        output = self.directory / 'portable.profile.json'
        self.store.export_json(profile.profile_id, output)
        self.assertEqual(Profile.load(output), profile)
        self.assertEqual(Profile.from_dict(json.loads(canonical_json(profile.to_dict()))), profile)

    def test_revision_history_and_noop_save(self):
        first = self.create()
        saved = self.store.save(first.edited(name='Changed name', choices={'da2.bethany_fate': 'warden'}))
        self.assertEqual(saved.revision, 2)
        self.assertEqual(self.store.load(first.profile_id, revision=1), first)
        self.assertEqual(self.store.load(first.profile_id), saved)
        self.assertEqual([p.revision for p in self.store.history(first.profile_id)], [2, 1])
        self.assertEqual(self.store.save(saved), saved)
        self.assertEqual(len(self.store.history(first.profile_id)), 2)

    def test_stale_edit_cannot_overwrite_a_newer_revision(self):
        first = self.create()
        saved = self.store.save(first.edited(name='Other editor'))
        with self.assertRaises(RevisionConflict):
            self.store.save(first.edited(name='Stale edit'))
        self.assertEqual(self.store.load(first.profile_id), saved)

    def test_exclusive_lock_preserves_history(self):
        profile = self.create()
        lock = self.store.profile_directory(profile.profile_id) / '.write.lock'
        lock.write_text('other writer')
        with self.assertRaisesRegex(RevisionConflict, 'locked'):
            self.store.save(profile.edited(name='Attempt'))
        self.assertEqual(lock.read_text(), 'other writer')
        self.assertEqual(self.store.load(profile.profile_id), profile)

    def test_failed_head_commit_keeps_old_revision_and_next_save_recovers(self):
        first = self.create()
        with patch('world_profiles.storage._replace_json', side_effect=OSError('simulated interrupted commit')):
            with self.assertRaises(OSError):
                self.store.save(first.edited(name='Uncommitted'))
        self.assertEqual(self.store.load(first.profile_id), first)
        self.assertEqual([p.revision for p in self.store.history(first.profile_id)], [1])
        with self.assertRaisesRegex(ProfileError, 'committed'):
            self.store.load(first.profile_id, revision=2)
        saved = self.store.save(first.edited(name='Recovered'))
        self.assertEqual(saved.revision, 3)
        self.assertEqual([p.revision for p in self.store.history(first.profile_id)], [3, 1])

    def test_duplicate_and_import_never_overwrite_original_identity(self):
        first = self.create(choices={'dao.loghain_fate': 'alive_recruited'})
        duplicate = self.store.duplicate(first.profile_id, 'Copy')
        portable = self.directory / 'history.json'
        self.store.export_json(first.profile_id, portable)
        imported = self.store.import_profile(portable)
        self.assertEqual(len({first.profile_id, duplicate.profile_id, imported.profile_id}), 3)
        self.assertEqual(duplicate.revision, 1)
        self.assertEqual(imported.choices, first.choices)
        self.assertEqual(self.store.load(first.profile_id), first)
        self.assertEqual(len(self.store.list()), 3)

    def test_unknown_schema_fields_and_duplicate_json_keys_are_rejected(self):
        document = self.create().to_dict()
        for mutation in ({'schema_version': 2}, {'schema_version': True}, {'unexpected': 1}, {'revision': True}):
            with self.subTest(mutation=mutation), self.assertRaises(ProfileError):
                Profile.from_dict(dict(document, **mutation))
        broken = self.directory / 'duplicate.json'
        broken.write_text('{"schema_version":1,"schema_version":2}')
        with self.assertRaisesRegex(ProfileError, 'Duplicate'):
            Profile.load(broken)

    def test_malformed_documents_and_path_ids_fail_cleanly(self):
        for value in ('../elsewhere', '..', 'C:/another-directory'):
            with self.subTest(value=value), self.assertRaises(ProfileError):
                self.store.load(value)
        for mutation in ({'choices': {'da2.bethany_fate': 1}}, {'name': 'bad\0name'},
                         {'created_at': 'not a date'}, {'name': '  '}, {'mode': 'unknown'}):
            with self.subTest(mutation=mutation), self.assertRaises(ProfileError):
                Profile.from_dict(dict(self.create().to_dict(), **mutation))
        oversized = self.directory / 'oversized.json'
        oversized.write_bytes(b' ' * 1_048_577)
        with self.assertRaisesRegex(ProfileError, '1 MiB'):
            Profile.load(oversized)

    def test_mapping_drift_rejected_without_rewriting_profile(self):
        profile = self.create()
        changed = replace(profile, mapping_sha256='0' * 64)
        with self.assertRaises(UnsupportedVersion):
            compile_profile(changed, catalog=self.catalog)
        with self.assertRaises(UnsupportedVersion):
            self.store.save(changed)
        self.assertEqual(self.store.load(profile.profile_id), profile)

    def test_all_sibling_fates_are_independent_of_hawke_class_in_ordinary_mode(self):
        bethany = {'circle': 1, 'warden': 2, 'deep_roads_death': 3, 'lothering_death': 0}
        carver = {'templar': 1, 'warden': 2, 'deep_roads_death': 3, 'lothering_death': 0}
        for hawke in ('warrior', 'rogue', 'mage'):
            for b_answer, b_career in bethany.items():
                for c_answer, c_career in carver.items():
                    with self.subTest(hawke=hawke, bethany=b_answer, carver=c_answer):
                        profile = self.catalog.create('Sibling combination', mode='ordinary', choices={
                            'da2.hawke_class': hawke, 'da2.bethany_fate': b_answer, 'da2.carver_fate': c_answer})
                        compiled = compile_profile(profile, catalog=self.catalog)
                        self.assertEqual(compiled.report['story_conflicts'], [])
                        for sibling, career in (('bethany', b_career), ('carver', c_career)):
                            self.assertEqual(compiled.values['da2_' + sibling + '_career'], career)
                            self.assertEqual(compiled.values['da2_' + sibling + '_alive'], int(career in (1, 2)))
                            self.assertEqual(compiled.values['da2_' + sibling + '_is_warden'], int(career == 2))
                            self.assertEqual(compiled.values['da2_' + sibling + '_died_deep_roads'], int(career == 3))

    def test_changing_hawke_class_leaves_both_sibling_histories_untouched(self):
        before = compile_profile(self.catalog.create('Before'), catalog=self.catalog)
        for hawke, value in (('warrior', 0), ('rogue', 1), ('mage', 2)):
            after = compile_profile(self.catalog.create('After', choices={'da2.hawke_class': hawke}), catalog=self.catalog)
            self.assertEqual(after.values['da2_hawke_class'], value)
            self.assertEqual(sum(after.values['da2_hawke_class_' + item] for item in ('warrior', 'rogue', 'mage')), 1)
            for key in before.values:
                if key.startswith(('da2_bethany_', 'da2_carver_')):
                    self.assertEqual(after.values[key], before.values[key])

    def test_version_one_upgrade_preserves_payload_and_committed_history(self):
        legacy = Catalog(mapping_version=1)
        self.assertEqual(legacy.sha256, '7d50b7d87defcbecc8981244801b5afd4e27a9f1e8bc0043700df1083db2da80')
        legacy_store = ProfileStore(self.directory / 'legacy', catalog=legacy)
        original = legacy_store.create('Existing history', choices={'da2.bethany_fate': 'warden'})
        original_file = legacy_store.profile_directory(original.profile_id) / 'History/00000001.json'
        original_bytes = original_file.read_bytes()
        old_mod, _ = build_profile_mod(original, catalog=self.catalog)
        upgraded = self.catalog.upgrade(original)
        new_mod, _ = build_profile_mod(upgraded, catalog=self.catalog)
        self.assertEqual(read_mod(old_mod)['ebx'], read_mod(new_mod)['ebx'])
        self.assertEqual(upgraded.choices, original.choices)
        current_store = ProfileStore(legacy_store.directory, catalog=self.catalog)
        saved = current_store.save(upgraded.edited(choices={**upgraded.choices, 'da2.carver_fate': 'warden'}))
        self.assertEqual(saved.mapping_version, self.catalog.version)
        self.assertEqual(saved.revision, 2)
        self.assertEqual(original_file.read_bytes(), original_bytes)
        self.assertEqual(current_store.load(original.profile_id, revision=1), original)
        historical_mod, _ = build_profile_mod(current_store.load(original.profile_id, revision=1), catalog=self.catalog)
        self.assertEqual(read_mod(historical_mod)['ebx'], read_mod(old_mod)['ebx'])

    def test_additive_upgrade_rejects_changed_old_flag_assignments(self):
        legacy = Catalog(mapping_version=1).create('Legacy')
        changed = Catalog()
        changed._choices['da2.bethany_fate']['answers']['warden']['export_values']['da2_bethany_alive'] = 0
        with self.assertRaisesRegex(UnsupportedVersion, 'Changed answer mappings'):
            changed.upgrade(legacy)

    def test_hero_classes_and_personalities_set_redundant_flags_without_changing_siblings(self):
        for hero in ('da2.hawke', 'dao.warden'):
            for index, career in enumerate(('warrior', 'rogue', 'mage')):
                for personality, value in (('diplomatic', 0), ('humourous', 1), ('aggressive', 2)):
                    profile = self.catalog.create('Heroes', choices={hero + '_class': career,
                        'da2.hawke_personality': personality, 'da2.bethany_fate': 'warden',
                        'da2.carver_fate': 'templar'})
                    compiled = compile_profile(profile, catalog=self.catalog)
                    prefix = hero.replace('.', '_')
                    self.assertEqual(compiled.values[prefix + '_class'], index)
                    for other in ('warrior', 'rogue', 'mage'):
                        self.assertEqual(compiled.values[prefix + '_class_' + other], int(other == career))
                    self.assertEqual(compiled.values['da2_hawke_personality_type'], value)
                    for other in ('diplomatic', 'humourous', 'aggressive'):
                        self.assertEqual(compiled.values['da2_hawke_personality_' + other], int(other == personality))
                    self.assertEqual(compiled.values['da2_bethany_alive'], 1)
                    self.assertEqual(compiled.values['da2_carver_alive'], 1)

    def test_warden_origins_set_background_and_race_and_preserve_zero_range_field(self):
        origins = [('human_noble', 0), ('human_mage', 0), ('dalish_elf', 1),
                   ('city_elf', 1), ('elven_mage', 1), ('dwarf_noble', 2), ('dwarf_commoner', 2)]
        for index, (origin, race) in enumerate(origins):
            with self.subTest(origin=origin):
                profile = self.catalog.create('Origin', choices={'dao.warden_origin': origin})
                data, _ = build_profile_mod(profile, catalog=self.catalog)
                objects = EbxParser(read_mod(data)['ebx']).parse()['objects']
                flags = {obj['value']['VariableNameOnServer']: obj['value']
                         for obj in objects if obj['class'] == 'GameVaultVarInt'}
                self.assertEqual(flags['dao_warden_background']['DefaultValue'], index)
                self.assertEqual(flags['dao_warden_race']['DefaultValue'], race)
                for other, _ in origins:
                    field = flags['dao_warden_background_' + other]
                    self.assertEqual(field['DefaultValue'], int(other == origin and other != 'human_mage'))
                self.assertEqual(flags['dao_warden_background_human_mage']['MaxValue'], 0)
                self.assertEqual([flags['dao_warden_race_' + r]['DefaultValue']
                                  for r in ('human', 'elf', 'dwarf')], [int(i == race) for i in range(3)])

    def test_version_two_upgrade_preserves_payload_and_revisions(self):
        legacy = Catalog(mapping_version=2)
        store = ProfileStore(self.directory / 'v2', catalog=legacy)
        original = store.create('Both siblings', choices={'da2.hawke_class': 'mage',
            'da2.bethany_fate': 'circle', 'da2.carver_fate': 'templar'})
        path = store.profile_directory(original.profile_id) / 'History/00000001.json'
        before = path.read_bytes()
        old_mod, _ = build_profile_mod(original, catalog=self.catalog)
        upgraded = self.catalog.upgrade(original)
        new_mod, _ = build_profile_mod(upgraded, catalog=self.catalog)
        self.assertEqual(read_mod(old_mod)['ebx'], read_mod(new_mod)['ebx'])
        current = ProfileStore(store.directory, catalog=self.catalog)
        saved = current.save(upgraded.edited(choices={**upgraded.choices, 'da2.hawke_personality': 'humourous'}))
        self.assertEqual(saved.mapping_version, self.catalog.version)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(current.load(original.profile_id, revision=1), original)

    def test_six_hawke_identities_preserve_every_sibling_combination(self):
        for gender, mf in (('male', 0), ('female', 1)):
            for career, class_value in (('warrior', 0), ('rogue', 1), ('mage', 2)):
                for bethany in ('circle', 'warden', 'deep_roads_death', 'lothering_death'):
                    for carver in ('templar', 'warden', 'deep_roads_death', 'lothering_death'):
                        identity = gender + '_' + career
                        compiled = compile_profile(self.catalog.create('Identity', choices={
                            'da2.hawke_identity': identity, 'da2.bethany_fate': bethany,
                            'da2.carver_fate': carver}), catalog=self.catalog)
                        self.assertEqual(compiled.values['da2_hawke_mf'], mf)
                        self.assertEqual(compiled.values['da2_hawke_class'], class_value)
                        self.assertEqual(compiled.report['resolved_choices']['da2.hawke_identity']['answer_id'], identity)
                        self.assertEqual(compiled.report['story_conflicts'], [])
                        self.assertEqual(compiled.report['resolved_choices']['da2.bethany_fate']['answer_id'], bethany)
                        self.assertEqual(compiled.report['resolved_choices']['da2.carver_fate']['answer_id'], carver)

    def test_fourteen_warden_identities_export_gender_race_and_origin_independently_of_class(self):
        origins = [('human_noble', 0), ('human_mage', 0), ('dalish_elf', 1),
                   ('city_elf', 1), ('elven_mage', 1), ('dwarf_noble', 2), ('dwarf_commoner', 2)]
        for index, (origin, race) in enumerate(origins):
            for gender, mf in (('male', 0), ('female', 1)):
                for career, class_value in (('warrior', 0), ('rogue', 1), ('mage', 2)):
                    identity = gender + '_' + origin
                    compiled = compile_profile(self.catalog.create('Warden', choices={
                        'dao.warden_identity': identity, 'dao.warden_class': career}), catalog=self.catalog)
                    self.assertEqual(compiled.values['dao_warden_mf'], mf)
                    self.assertEqual(compiled.values['dao_warden_background'], index)
                    self.assertEqual(compiled.values['dao_warden_race'], race)
                    self.assertEqual(compiled.values['dao_warden_class'], class_value)
                    self.assertNotIn('dao_warden_background_human_mage', compiled.values)
                    self.assertEqual(compiled.report['resolved_choices']['dao.warden_identity']['answer_id'], identity)
                    self.assertEqual([compiled.values['dao_warden_race_' + r]
                        for r in ('human', 'elf', 'dwarf')], [int(i == race) for i in range(3)])

    def test_v3_hero_conversion_preserves_exact_payload_across_presets_and_origins(self):
        legacy = Catalog(mapping_version=3)
        for preset in legacy.presets:
            for index, origin in enumerate(('human_noble', 'human_mage', 'dalish_elf', 'city_elf',
                                           'elven_mage', 'dwarf_noble', 'dwarf_commoner')):
                with self.subTest(preset=preset, origin=origin):
                    original = legacy.create('Existing heroes', base_preset=preset, mode='experimental', choices={
                        'da2.hawke_class': ('warrior', 'rogue', 'mage')[index % 3],
                        'dao.warden_origin': origin, 'da2.bethany_fate': 'circle', 'da2.carver_fate': 'templar'})
                    before, _ = build_profile_mod(original, catalog=self.catalog)
                    upgraded = self.catalog.upgrade(original)
                    after, _ = build_profile_mod(upgraded, catalog=self.catalog)
                    self.assertEqual(read_mod(before)['ebx'], read_mod(after)['ebx'])
                    self.assertNotIn('da2.hawke_class', upgraded.choices)
                    self.assertNotIn('dao.warden_origin', upgraded.choices)
                    self.assertIn('da2.hawke_identity', upgraded.choices)
                    self.assertTrue(upgraded.choices['dao.warden_identity'].endswith('_' + origin))

    def test_hero_conversion_rejects_a_change_to_effective_gender(self):
        original = Catalog(mapping_version=3).create('Old hero', choices={'da2.hawke_class': 'rogue'})
        changed = Catalog()
        gender = compile_profile(original).report['hero_appearance']['da2']['gender']
        changed._choices['da2.hawke_identity']['answers'][gender + '_rogue']['export_values']['da2_hawke_mf'] ^= 1
        with self.assertRaisesRegex(UnsupportedVersion, 'conversion would change game flags'):
            changed.upgrade(original)

    def test_baseline_and_identity_cannot_change_in_place(self):
        profile = self.create()
        template_id = next(key for key in self.catalog.presets if key.startswith('template-'))
        with self.assertRaisesRegex(ProfileError, 'baseline'):
            self.store.save(replace(profile, base_preset=template_id))

    def test_all_thirty_romance_pairs_export_consistent_flags(self):
        wardens = ('none', 'alistair', 'morrigan', 'leliana', 'zevran')
        hawkes = ('none', 'anders', 'fenris', 'isabela', 'merrill', 'sebastian')
        for warden_index, warden in enumerate(wardens):
            for hawke_index, hawke in enumerate(hawkes):
                with self.subTest(warden=warden, hawke=hawke):
                    profile = self.create(choices={'dao.warden_romance': warden, 'da2.hawke_romance': hawke})
                    data, _ = build_profile_mod(profile, catalog=self.catalog)
                    flags = {o['value']['VariableNameOnServer']: o['value']['DefaultValue']
                             for o in EbxParser(read_mod(data)['ebx']).parse()['objects']
                             if o['class'] == 'GameVaultVarInt'}
                    self.assertEqual(flags['dao_warden_romance'], warden_index)
                    self.assertEqual(flags['da2_hawke_romance'], hawke_index)
                    for answer in wardens[1:]:
                        self.assertEqual(flags['dao_warden_romance_' + answer], int(answer == warden))
                    for answer in hawkes:
                        self.assertEqual(flags['da2_hawke_romance_' + answer], int(answer == hawke))

    def test_romance_changes_preserve_every_other_flag_in_every_preset(self):
        groups = [('dao.warden_romance', 'dao_warden_romance', ('none', 'alistair', 'morrigan', 'leliana', 'zevran')),
                  ('da2.hawke_romance', 'da2_hawke_romance', ('none', 'anders', 'fenris', 'isabela', 'merrill', 'sebastian'))]
        for preset in self.catalog.presets:
            original = self.catalog.create('Before', base_preset=preset, mode='experimental')
            before = compile_profile(original, catalog=self.catalog)
            for choice, prefix, answers in groups:
                for answer in answers:
                    after = compile_profile(original.edited(choices={choice: answer}), catalog=self.catalog)
                    self.assertEqual({k: v for k, v in before.effective_values.items() if not k.startswith(prefix)},
                                     {k: v for k, v in after.effective_values.items() if not k.startswith(prefix)})
                    self.assertEqual(after.report['resolved_choices'][choice]['answer_id'], answer)

    def test_explicit_romances_reproduce_all_released_preset_payloads(self):
        for preset in self.catalog.presets:
            if not preset.startswith('template-'):
                continue
            original = self.catalog.create('Released', base_preset=preset)
            resolved = compile_profile(original, catalog=self.catalog).report['resolved_choices']
            selections = {key: resolved[key]['answer_id'] for key in ('dao.warden_romance', 'da2.hawke_romance')}
            self.assertTrue(all(selections.values()))
            data, _ = build_profile_mod(original.edited(choices=selections), catalog=self.catalog)
            self.assertEqual(read_mod(data)['ebx'], read_mod(self.catalog.template_path(preset).read_bytes())['ebx'])

    def test_romance_selection_does_not_rewrite_gender_siblings_or_anders_fate(self):
        for identity in ('male_warrior', 'male_rogue', 'male_mage', 'female_warrior', 'female_rogue', 'female_mage'):
            for romance in ('none', 'anders', 'fenris', 'isabela', 'merrill', 'sebastian'):
                for anders in ('alive', 'executed'):
                    selections = {'da2.hawke_identity': identity, 'da2.hawke_romance': romance,
                        'da2.bethany_fate': 'warden', 'da2.carver_fate': 'templar', 'da2.anders_fate': anders}
                    compiled = compile_profile(self.catalog.create('Independent', choices=selections), catalog=self.catalog)
                    resolved = compiled.report['resolved_choices']
                    for key, answer in selections.items():
                        self.assertEqual(resolved[key]['answer_id'], answer)
                    self.assertEqual(compiled.report['story_conflicts'], [])

    def test_version_four_upgrade_preserves_payload_and_immutable_revision(self):
        legacy = ProfileStore(self.directory / 'v4', catalog=Catalog(mapping_version=4))
        original = legacy.create('Before romance controls', choices={'da2.hawke_identity': 'female_mage',
            'dao.warden_identity': 'female_human_noble', 'da2.bethany_fate': 'warden', 'da2.carver_fate': 'templar'})
        path = legacy.profile_directory(original.profile_id) / 'History/00000001.json'
        before = path.read_bytes()
        upgraded = self.catalog.upgrade(original)
        old_mod, _ = build_profile_mod(original, catalog=self.catalog)
        new_mod, _ = build_profile_mod(upgraded, catalog=self.catalog)
        self.assertEqual(read_mod(old_mod)['ebx'], read_mod(new_mod)['ebx'])
        self.assertEqual(upgraded.choices, original.choices)
        current = ProfileStore(legacy.directory, catalog=self.catalog)
        saved = current.save(upgraded.edited(choices={**upgraded.choices, 'dao.warden_romance': 'leliana',
                                                     'da2.hawke_romance': 'merrill'}))
        self.assertEqual(saved.mapping_version, self.catalog.version)
        self.assertEqual(saved.revision, 2)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(current.load(original.profile_id, revision=1), original)

    def test_romance_pack_covers_all_answers_and_refuses_existing_directory(self):
        from build_romance_test_pack import build_pack
        output = self.directory / 'romances'
        records = build_pack(output)
        self.assertEqual(len(records), 6)
        self.assertEqual({r['choices']['dao.warden_romance'] for r in records},
                         {'none', 'alistair', 'morrigan', 'leliana', 'zevran'})
        self.assertEqual({r['choices']['da2.hawke_romance'] for r in records},
                         {'none', 'anders', 'fenris', 'isabela', 'merrill', 'sebastian'})
        for record in records:
            self.assertEqual(hashlib.sha256((output / record['mod']).read_bytes()).hexdigest(), record['mod_sha256'])
            portable = Profile.load(output / record['profile'])
            self.assertEqual(dict(portable.choices), record['choices'])
            self.assertFalse(record['gameplay_tested'])
        self.assertEqual(records[1]['expected_flags']['dao_warden_married_alistair'], 1)
        self.assertEqual(records[2]['expected_flags']['dao_warden_mf'], 0)
        self.assertEqual(records[-1]['expected_flags']['da2_anders_executed'], 1)
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir()}
        with self.assertRaises(FileExistsError):
            build_pack(output)
        self.assertEqual(before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir()})

    def test_tampered_stored_revision_and_head_are_detected(self):
        profile = self.create()
        head = self.store.profile_directory(profile.profile_id) / 'head.json'
        original_head = head.read_bytes()
        head.write_text(json.dumps(dict(revision=1, sha256='0' * 64)))
        with self.assertRaisesRegex(ProfileError, 'checksum'):
            self.store.load(profile.profile_id)
        head.write_bytes(original_head)
        revision = self.store.profile_directory(profile.profile_id) / 'History/00000001.json'
        document = json.loads(revision.read_text())
        document['profile']['name'] = 'Tampered'
        revision.write_text(json.dumps(document))
        with self.assertRaisesRegex(ProfileError, 'integrity'):
            self.store.load(profile.profile_id)

    def test_unknown_story_choices_and_answers_rejected_even_experimental(self):
        for choices in ({'missing': 'answer'}, {'da2.bethany_fate': 'missing'}):
            with self.subTest(choices=choices), self.assertRaises(ProfileError):
                self.create(choices=choices, mode='experimental')

    def test_empty_invalid_inputs_are_not_silently_replaced_with_defaults(self):
        with self.assertRaises(ProfileError):
            self.create(choices=[])
        with self.assertRaises(ProfileError):
            self.create(mode='')

    def test_effective_answers_distinguish_inheritance_from_explicit_choices(self):
        profile = self.create(choices={'da2.bethany_fate': 'warden'})
        compiled = compile_profile(profile, catalog=self.catalog)
        resolved = compiled.report['resolved_choices']
        self.assertEqual(resolved['da2.bethany_fate']['answer_id'], 'warden')
        self.assertEqual(resolved['da2.bethany_fate']['source'], 'explicit_selection')
        self.assertEqual(resolved['dao.ferelden_leadership']['answer_id'], 'alistair_king_alone')
        self.assertEqual(resolved['dao.ferelden_leadership']['source'], 'base_preset')
        self.assertEqual(resolved['da2.anders_fate']['source'], 'inherited_template')

    def test_unrepresentable_inherited_flags_are_preserved_without_guessing(self):
        # The authored Queen Cousland preset has a ruler combination outside
        # the two initial GUI answers, and must remain unchanged.
        digest = hashlib.sha256(DEFAULT_TEMPLATE.read_bytes()).hexdigest()
        profile = self.create(base_preset='template-' + digest[:16])
        compiled = compile_profile(profile, catalog=self.catalog)
        self.assertIsNone(compiled.report['resolved_choices']['dao.ferelden_leadership']['answer_id'])
        self.assertTrue(any('without guessing' in text for text in compiled.report['warnings']))

    def test_profiles_reproduce_all_five_existing_early_test_payloads(self):
        choices = {
            '00-baseline': {},
            '01-bethany-warden': {'da2.bethany_fate': 'warden'},
            '02-bethany-dead': {'da2.bethany_fate': 'deep_roads_death'},
            '03-anora-rules': {'dao.ferelden_leadership': 'anora_queen_alistair_warden'},
            '04-loghain-alive': {'dao.loghain_fate': 'alive_recruited'}
        }
        self.assertEqual(set(choices), set(load_early_cases()['cases']))
        for case, selections in choices.items():
            with self.subTest(case=case):
                profile = self.create(choices=selections)
                actual, report = build_profile_mod(profile, catalog=self.catalog)
                expected = (ROOT / 'prototype/output/early-tests' / (case + '.fbmod')).read_bytes()
                self.assertEqual(read_mod(actual)['ebx'], read_mod(expected)['ebx'])
                self.assertEqual(report['profile']['profile_sha256'], profile.sha256)
                self.assertFalse(report['profile']['gameplay_tested'])

    def test_anders_semantic_mapping_matches_both_released_variants(self):
        digest = hashlib.sha256(DEFAULT_TEMPLATE.read_bytes()).hexdigest()
        for answer in ('alive', 'executed'):
            with self.subTest(answer=answer):
                profile = self.create(base_preset='template-' + digest[:16], choices={'da2.anders_fate': answer})
                actual, report = build_profile_mod(profile, catalog=self.catalog)
                expected, _ = build_mod(DEFAULT_TEMPLATE.read_bytes(), answer)
                self.assertEqual(read_mod(actual)['ebx'], read_mod(expected)['ebx'])
                self.assertEqual(report['profile']['selections'][0]['evidence_status'], 'disputed')

    def test_unedited_reviewed_presets_preserve_entire_ebx(self):
        for preset_id, preset in self.catalog.presets.items():
            if not preset_id.startswith('template-'):
                continue
            with self.subTest(preset=preset['label']):
                profile = self.create(base_preset=preset_id)
                actual, _ = build_profile_mod(profile, catalog=self.catalog)
                expected = self.catalog.template_path(preset_id).read_bytes()
                self.assertEqual(read_mod(actual)['ebx'], read_mod(expected)['ebx'])

    def test_ordinary_conflict_blocks_export_experimental_retains_warning(self):
        selections = {'dao.loghain_fate': 'alive_recruited',
                      'dao.ferelden_leadership': 'anora_queen_alistair_warden'}
        ordinary = self.create(choices=selections)
        with self.assertRaises(StoryConflict):
            build_profile_mod(ordinary, catalog=self.catalog)
        experimental = ordinary.edited(mode='experimental')
        actual, report = build_profile_mod(experimental, catalog=self.catalog)
        self.assertTrue(read_mod(actual)['ebx'])
        self.assertTrue(report['profile']['story_conflicts'])
        self.assertEqual(dict(ordinary.choices), dict(experimental.choices))

    def test_experimental_mode_cannot_bypass_technical_range_validation(self):
        catalog = Catalog()
        catalog._choices['dao.loghain_fate']['answers']['alive_recruited']['export_values']['dao_loghain_fate'] = 999
        profile = catalog.create('Invalid mapping', choices={'dao.loghain_fate': 'alive_recruited'}, mode='experimental')
        with self.assertRaisesRegex(ProfileError, 'technical value'):
            compile_profile(profile, catalog=catalog)

    def test_profile_export_is_deterministic_and_does_not_overwrite_files(self):
        profile = self.create(choices={'da2.bethany_fate': 'warden'})
        first, _ = build_profile_mod(profile, catalog=self.catalog)
        second, _ = build_profile_mod(profile, catalog=self.catalog)
        self.assertEqual(first, second)
        output = self.directory / 'history.fbmod'
        report = export_profile_mod(profile, output, catalog=self.catalog)
        self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), report['output_sha256'])
        before = output.read_bytes()
        with self.assertRaises(ProfileError):
            export_profile_mod(profile, output, catalog=self.catalog)
        self.assertEqual(output.read_bytes(), before)
        portable = self.directory / 'portable.json'
        portable.write_text('keep existing')
        with self.assertRaises(FileExistsError):
            self.store.export_json(profile.profile_id, portable)
        self.assertEqual(portable.read_text(), 'keep existing')

    def test_changed_template_is_rejected_before_compilation(self):
        catalog = Catalog()
        modified = self.directory / 'altered.fbmod'
        modified.write_bytes(DEFAULT_TEMPLATE.read_bytes() + b'changed')
        profile = catalog.create('Changed template')
        with patch.object(catalog, 'template_path', return_value=modified):
            with self.assertRaisesRegex(ProfileError, 'template has changed'):
                compile_profile(profile, catalog=catalog)

    def test_cli_create_edit_export_and_stale_revision_error(self):
        def run(arguments):
            with redirect_stdout(StringIO()) as captured:
                self.assertEqual(cli(['--store', str(self.store.directory), *arguments]), 0)
                return json.loads(captured.getvalue())
        created = run(['create', '--name', 'CLI history'])
        edited = run(['edit', created['profile_id'], '--expected-revision', '1',
                      '--choice', 'da2.bethany_fate=warden'])
        self.assertEqual(edited['revision'], 2)
        checked = run(['check', created['profile_id']])
        self.assertEqual(checked['values']['da2_bethany_is_warden'], 1)
        output = self.directory / 'cli.fbmod'
        exported = run(['export-fbmod', created['profile_id'], '--output', str(output)])
        self.assertEqual(exported['profile']['revision'], 2)
        with patch('sys.stderr', new=StringIO()), self.assertRaises(SystemExit) as error:
            cli(['--store', str(self.store.directory), 'edit', created['profile_id'],
                 '--expected-revision', '1', '--name', 'Stale'])
        self.assertEqual(error.exception.code, 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
