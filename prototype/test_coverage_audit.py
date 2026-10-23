"""Cross-source completeness and regressions found in the final coverage pass."""
from itertools import product
from pathlib import Path
import tempfile
import unittest

from audit_keep_coverage import audit
from export_worldstate import EbxParser, ROOT, read_mod
from gui import EditorApp
from world_profiles import Catalog, ProfileError, ProfileStore
from world_profiles.compiler import StoryConflict, build_profile_mod, compile_profile
from world_profiles.story_rules import propose


class CoverageAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def test_every_captured_question_answer_rule_truth_table_and_local_artwork_is_covered(self):
        report = audit()
        self.assertTrue(report['passed'], report['problems'])
        self.assertEqual(report['captured_questions'], 130)
        self.assertEqual(report['captured_answers'], 356)
        self.assertGreaterEqual(report['dependency_cases'], 8352)
        self.assertEqual(report['decision_layout_shape_differences'], [])

    def test_alistair_execution_and_duel_serialize_only_loghain_fields_in_all_presets(self):
        for preset, (answer, value) in product(self.catalog.presets,
                (('executed_by_alistair', 1), ('killed_in_duel', 2))):
            base = self.catalog.create('Execution review', base_preset=preset, mode='experimental')
            before = compile_profile(base, catalog=self.catalog)
            profile = base.edited(choices={'dao.loghain_fate': answer})
            expected = dict(dao_loghain_alive=0, dao_loghain_executed=2, dao_loghain_fate=value,
                            dao_loghain_killed_archdemon=0, dao_loghain_recruited=0)
            compiled = compile_profile(profile, catalog=self.catalog)
            self.assertEqual(dict(compiled.effective_values), {**before.effective_values, **expected})
            mod, _ = build_profile_mod(profile, catalog=self.catalog)
            objects = {obj['value']['VariableNameOnServer']: obj['value'] for obj in
                       EbxParser(read_mod(mod)['ebx']).parse()['objects'] if obj['class'] == 'GameVaultVarInt'}
            source = {obj['value']['VariableNameOnServer']: obj['value'] for obj in
                      EbxParser(read_mod(compiled.template_data)['ebx']).parse()['objects'] if obj['class'] == 'GameVaultVarInt'}
            self.assertEqual({name: obj['DefaultValue'] for name, obj in objects.items()}, dict(compiled.effective_values))
            self.assertEqual(compiled.report['resolved_choices']['dao.loghain_fate']['answer_id'], answer)
            for name, obj in objects.items():
                self.assertEqual((obj['MinValue'], obj['MaxValue'], obj['PlotFlag']),
                                 (source[name]['MinValue'], source[name]['MaxValue'], source[name]['PlotFlag']))
                if name not in expected:
                    self.assertEqual(obj, {**source[name], 'DefaultValue': before.effective_values[name]})

    def test_cullen_and_wynne_repair_each_other_and_locked_conflicts_remain_read_only(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'prototype') as directory:
            app = EditorApp(Path(directory) / 'profiles', Path(directory) / 'exports')
            base = self.catalog.create('Wynne review', mode='keep', choices={'dao.dagna_outcome': 'not_met'})
            agreed = propose(base, {'dao.cullen_request': 'agreed'}, mode='keep', catalog=self.catalog, editable=app.presentation)
            self.assertEqual(agreed.choices['dao.wynne_fate'], 'died_at_circle')
            original = agreed.to_dict()
            reverse = propose(agreed, {'dao.wynne_fate': 'not_recruited'}, mode='keep', catalog=self.catalog, editable=app.presentation)
            self.assertEqual(reverse.choices['dao.cullen_request'], 'disagreed')
            for cullen, fate in product(('agreed', 'disagreed'), ('not_recruited', 'died_at_circle')):
                candidate = agreed.edited(choices={**agreed.choices, 'dao.cullen_request': cullen, 'dao.wynne_fate': fate})
                if cullen == 'agreed' and fate == 'not_recruited':
                    with self.assertRaises(StoryConflict):
                        compile_profile(candidate, catalog=self.catalog)
                else:
                    compile_profile(candidate, catalog=self.catalog)
                compile_profile(candidate.edited(mode='experimental'), catalog=self.catalog)
            with self.assertRaises(ProfileError) as caught:
                propose(agreed, {'dao.cullen_request': 'agreed', 'dao.wynne_fate': 'not_recruited'},
                        mode='keep', catalog=self.catalog, editable=app.presentation)
            self.assertIn('No compatible set', str(caught.exception))
            self.assertEqual(agreed.to_dict(), original)

    def test_all_historical_catalogs_preserve_inherited_payload_when_opened_or_upgraded(self):
        for version, preset in product(range(1, 42), Catalog(41).presets):
            with self.subTest(version=version, preset=preset):
                old = Catalog(mapping_version=version)
                profile = old.create('Historical coverage', base_preset=preset, mode='experimental')
                before = compile_profile(profile, catalog=old)
                reopened = compile_profile(profile, catalog=self.catalog)
                upgraded = compile_profile(self.catalog.upgrade(profile), catalog=self.catalog)
                self.assertEqual(reopened.effective_values, before.effective_values)
                self.assertEqual(upgraded.effective_values, before.effective_values)
                self.assertEqual(upgraded.values, before.values)
                self.assertEqual(upgraded.max_overrides, before.max_overrides)
                # Every historical catalog ultimately references the same
                # immutable reviewed template for this inherited preset.
                self.assertEqual(upgraded.template_data, before.template_data)

    def test_catalog40_strict_history_is_preserved_and_new_conflict_requires_review(self):
        old = Catalog(mapping_version=40)
        with tempfile.TemporaryDirectory(dir=ROOT / 'prototype') as directory:
            store = ProfileStore(Path(directory) / 'profiles', catalog=old)
            app = EditorApp(Path(directory) / 'new-profiles', Path(directory) / 'exports')
            base = old.create('Old explicit Cullen', mode='keep', choices={'dao.dagna_outcome': 'not_met'})
            agreed = propose(base, {'dao.cullen_request': 'agreed'}, mode='keep', catalog=old, editable=app.presentation)
            choices = {**agreed.choices, 'dao.wynne_fate': 'not_recruited'}
            saved = store.create('Old explicit Cullen', mode='keep', choices=choices)
            snapshot = {str(path): path.read_bytes() for path in Path(directory).rglob('*') if path.is_file()}
            before = compile_profile(saved, catalog=self.catalog)
            upgraded = self.catalog.upgrade(saved)
            with self.assertRaises(StoryConflict):
                compile_profile(upgraded, catalog=self.catalog)
            after = compile_profile(upgraded.edited(mode='experimental'), catalog=self.catalog)
            self.assertEqual(after.effective_values, before.effective_values)
            repaired = propose(upgraded, {}, mode='keep', catalog=self.catalog, editable=app.presentation)
            compile_profile(repaired, catalog=self.catalog)
            self.assertEqual(snapshot, {str(path): path.read_bytes() for path in Path(directory).rglob('*') if path.is_file()})

    def test_every_profile_only_answer_stays_unknown_until_selected_and_never_exports(self):
        base = self.catalog.create('Local-only review', mode='experimental')
        before = compile_profile(base, catalog=self.catalog)
        for key, definition in self.catalog.choices.items():
            if definition.get('export_behavior') != 'profile-only':
                continue
            self.assertIsNone(before.report['resolved_choices'][key]['answer_id'])
            for answer in definition['answers']:
                after = compile_profile(base.edited(choices={key: answer}), catalog=self.catalog)
                self.assertEqual(after.values, before.values)
                self.assertEqual(after.effective_values, before.effective_values)
                self.assertEqual(after.max_overrides, before.max_overrides)
                self.assertEqual(after.report['resolved_choices'][key]['answer_id'], answer)


if __name__ == '__main__':
    unittest.main(verbosity=2)
