"""Source-backed direct DAO companion imports and ambiguous-history guards."""
import json
from pathlib import Path
import tempfile
import unittest

from game_saves.dao import import_save
from game_saves.dao_companions import FLAGS, SUPPORTED
from game_saves.worldvault import DIRECT
from gui import EditorApp
from test_save_import import make_save
from world_profiles import Catalog

ROOT = Path(__file__).resolve().parents[1]


def save_flags(*names, completed=True, missing=(), extra=None):
    plots = {guid: [] for guid, _ in FLAGS.values() if guid not in missing}
    for name in names:
        guid, bit = FLAGS[name]
        plots.setdefault(guid, []).append(bit)
    if completed:
        guid, bit = DIRECT[2030]
        plots.setdefault(guid, []).append(bit)
    for guid, bits in (extra or {}).items(): plots.setdefault(guid, []).extend(bits)
    return plots


class DaoCompanionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.catalog = Catalog()

    def result(self, *names, **kwargs):
        return import_save(make_save(save_flags(*names, **kwargs), game='dao'), self.catalog)

    def choices(self, *names, **kwargs):
        return {k: v for k, v in self.result(*names, **kwargs)['choices'].items() if k in SUPPORTED}

    def test_empty_early_records_are_not_negative_or_final_outcomes(self):
        self.assertEqual(self.choices(completed=False), {})
        self.assertEqual(self.choices('sten_recruited', 'wynne_recruited', 'leliana_recruited', completed=False),
            {'dao.sten_recruited': 'recruited', 'dao.wynne_recruited': 'recruited'})

    def test_completed_negative_outcomes_require_present_evidence(self):
        self.assertEqual(self.choices('circle_complete'), dict(
            **{'dao.sten_recruited': 'not_recruited', 'dao.sten_release': 'not_freed',
               'dao.sten_sword': 'not_recruited', 'dao.leliana_fate': 'not_recruited',
               'dao.wynne_recruited': 'not_recruited', 'dao.wynne_fate': 'not_recruited'}))
        all_missing = {g for g, _ in FLAGS.values()}
        self.assertEqual(self.choices(missing=all_missing), {})

    def test_sten_release_methods_require_actual_release_and_preserve_uncertainty(self):
        for names, expected in ((('sten_released', 'sten_lock_picked'), 'picked_lock'),
                                (('sten_released', 'sten_key_permission'), 'persuaded'),
                                (('sten_released', 'sten_lock_picked', 'mother_threatened'), 'picked_lock')):
            with self.subTest(names=names):
                self.assertEqual(self.choices(*names, completed=False)['dao.sten_release'], expected)
        for names in (('sten_key_permission',), ('sten_lock_picked',),
                      ('sten_released', 'sten_key_permission', 'mother_threatened'),
                      ('sten_released', 'mother_attacked')):
            with self.subTest(names=names): self.assertNotIn('dao.sten_release', self.choices(*names, completed=False))
        review = self.result('sten_released', 'mother_threatened', completed=False)
        unresolved = next(e for e in review['unresolved'] if e['choice_id'] == 'dao.sten_release')
        self.assertEqual(unresolved['status'], 'needs_review')
        self.assertIn('uniquely', unresolved['reason'])

    def test_sten_sword_retrieved_is_not_returned_and_departure_is_not_nonrecruitment(self):
        guid = FLAGS['sten_sword_returned'][0]
        self.assertEqual(self.choices('sten_recruited', extra={guid: [15]})['dao.sten_sword'], 'not_returned')
        self.assertNotIn('dao.sten_sword', self.choices('sten_recruited', completed=False, extra={guid: [15]}))
        self.assertEqual(self.choices('sten_sword_returned', completed=False)['dao.sten_sword'], 'returned')
        for names in (('sten_left',), ('sten_left', 'sten_recruited')):
            self.assertNotIn('dao.sten_recruited', self.choices(*names))
            self.assertNotIn('dao.sten_sword', self.choices(*names))

    def test_leliana_alive_and_both_urn_outcomes(self):
        self.assertEqual(self.choices('leliana_recruited')['dao.leliana_fate'], 'alive')
        self.assertEqual(self.choices('leliana_attacked', 'urn_tainted')['dao.leliana_fate'], 'killed_at_urn')
        self.assertEqual(self.choices('leliana_left', 'urn_tainted', 'leliana_urn_reaction', completed=False)['dao.leliana_fate'], 'left_after_urn')

    def test_leliana_generic_crisis_or_incomplete_combat_is_not_a_specific_fate(self):
        for names, completed in ((('leliana_left',), True),
                (('leliana_left', 'urn_tainted'), True),
                (('leliana_left', 'urn_tainted', 'leliana_urn_reaction', 'leliana_second_crisis'), True),
                (('leliana_attacked', 'urn_tainted'), False), (('leliana_attacked',), True),
                (('leliana_attacked', 'leliana_left', 'urn_tainted'), True),
                (('leliana_recruited', 'leliana_attacked', 'urn_tainted'), True),
                (('leliana_recruited', 'leliana_left', 'urn_tainted'), True)):
            with self.subTest(names=names): self.assertNotIn('dao.leliana_fate', self.choices(*names, completed=completed))
        self.assertNotIn('dao.leliana_fate', self.choices('leliana_joined_initially'))
        self.assertNotIn('dao.leliana_fate', self.choices('leliana_fired'))

    def test_wynne_death_sources_override_live_party_assumptions(self):
        for marker in ('wynne_killed_circle', 'wynne_killed_at_cullen', 'wynne_codex_killed'):
            with self.subTest(marker=marker):
                choices = self.choices(marker, completed=False)
                self.assertEqual(choices['dao.wynne_fate'], 'died_at_circle')
                self.assertEqual(choices['dao.wynne_recruited'], 'not_recruited')
        choices = self.choices('wynne_killed_urn', completed=False)
        self.assertEqual(choices['dao.wynne_fate'], 'killed_at_urn')
        self.assertEqual(choices['dao.wynne_recruited'], 'recruited', 'Urn combat clears the current recruited flag')
        choices = self.choices('wynne_killed_circle', 'wynne_recruited', completed=False)
        self.assertEqual(choices['dao.wynne_fate'], 'died_at_circle')
        self.assertEqual(choices['dao.wynne_recruited'], 'recruited', 'modded source combination is preserved')

    def test_wynne_spirit_story_and_temporary_help_are_not_deaths_or_final_fates(self):
        spirit_story = {'0F78D9FC6FBD4183A1243DDC1BBE5D01': [0]}
        self.assertEqual(self.choices('wynne_recruited', extra=spirit_story)['dao.wynne_fate'], 'alive')
        self.assertNotIn('dao.wynne_fate', self.choices('wynne_recruited', completed=False, extra=spirit_story))
        for marker in ('wynne_helped', 'wynne_left_circle', 'wynne_codex_joined'):
            self.assertNotIn('dao.wynne_fate', self.choices(marker, 'circle_complete'))
        self.assertNotIn('dao.wynne_fate', self.choices('wynne_recruited', 'wynne_did_not_join'))
        self.assertNotIn('dao.wynne_fate', self.choices('wynne_killed_circle', 'wynne_killed_urn'))

    def test_missing_secondary_plots_cannot_be_assumed_clear(self):
        for marker, key, missing_marker in (
                ('sten_released', 'dao.sten_release', 'mother_threatened'),
                ('leliana_recruited', 'dao.leliana_fate', 'leliana_left'),
                ('leliana_left', 'dao.leliana_fate', 'leliana_second_crisis'),
                ('wynne_recruited', 'dao.wynne_fate', 'wynne_codex_killed')):
            with self.subTest(key=key):
                self.assertNotIn(key, self.choices(marker, missing={FLAGS[missing_marker][0]}))

    def test_new_companion_results_follow_reviewed_merge_and_conflict_policy(self):
        with tempfile.TemporaryDirectory() as temp:
            app = EditorApp(Path(temp) / 'profiles', Path(temp) / 'exports')
            original = app.store.create('Existing', mode='experimental', choices={
                'dao.sten_sword': 'not_returned', 'da2.hawke_romance': 'anders'})
            raw = make_save(save_flags('sten_recruited', 'sten_sword_returned', 'wynne_recruited', 'leliana_recruited'), game='dao')
            review = app.save_imports.preview(raw, game='dao')
            plan = app.save_imports.plan(dict(import_id=review['import_id'], target_profile_id=original.profile_id,
                target_revision=original.revision, policy='missing'))
            saved = app.save_imports.commit(dict(import_id=plan['import_id'], name=original.name))
            self.assertEqual(saved.choices['dao.sten_sword'], 'not_returned')
            self.assertEqual(saved.choices['dao.leliana_fate'], 'alive')
            self.assertEqual(saved.choices['da2.hawke_romance'], 'anders')
            conflict_raw = make_save(save_flags('wynne_recruited', 'wynne_killed_circle'), game='dao')
            review = app.save_imports.preview(conflict_raw, game='dao')
            self.assertEqual(review['mode'], 'experimental')
            self.assertTrue(review['restriction_reasons'])
            self.assertEqual(app.store.load(saved.profile_id), saved)

    def test_literal_flags_and_critical_source_paths_match_original_extraction(self):
        source = ROOT / 'assessment/output/dao-import/companions'
        plots = {p['guid']: {f['id']: f['name'] for f in p['flags']} for p in json.loads((source / 'plots.json').read_text())}
        for name,(guid,bit) in FLAGS.items():
            with self.subTest(name=name): self.assertIn(bit, plots[guid])
        self.assertEqual(plots[FLAGS['sten_sword_returned'][0]][13], 'STEN_MAIN_HAS_SWORD_BACK')
        self.assertEqual(plots[FLAGS['wynne_killed_urn'][0]][6], 'COD_CHA_WYNNE_DIES_AT_THE_URN')
        convos = json.loads((source / 'conversations.json').read_text(encoding='utf8'))
        camp = convos['party_camp.dlg']
        self.assertEqual(camp[853]['action']['flag'], 42)
        self.assertEqual(camp[297]['action']['flag'], 84)
        self.assertEqual(camp[740]['action']['flag'], 85)
        self.assertEqual(camp[746]['action']['flag'], 85)
        self.assertIn(853, camp[206]['links'])
        self.assertIn(853, camp[297]['links'])
        mother = convos['lot110_grand_cleric.dlg']
        self.assertEqual(mother[3]['action']['flag'], mother[28]['action']['flag'])
        self.assertIn('intolerable', mother[3]['text'])
        self.assertIn('dislike being threatened', mother[28]['text'])


if __name__ == '__main__': unittest.main()
