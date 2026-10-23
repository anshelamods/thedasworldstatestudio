"""DA2 merges preserve explicit choices, carried DAO history and saved revisions."""
import unittest

import test_dao_import as dao_tests
from test_save_import import ACT, make_save
from world_profiles import ProfileError, RevisionConflict
from world_profiles.compiler import compile_profile


class Da2MergeTests(unittest.TestCase):
    setUp = dao_tests.DaoMergeTests.setUp
    plan = dao_tests.DaoMergeTests.plan
    commit = dao_tests.DaoMergeTests.commit

    def preview(self):
        return self.imports.preview(make_save({ACT: [0, 2, 4, 8]}, primary=2,
                                              dao_bools={2018: 1, 2019: 0}))

    def test_fill_missing_protects_explicit_answers_in_both_games(self):
        target = self.store.create('Existing', mode='experimental', choices={
            'da2.hawke_identity': 'female_mage', 'dao.orzammar_ruler': 'harrowmont',
            'dao.dagna_outcome': 'stayed'})
        other = self.store.create('Unrelated')
        result = self.plan(self.preview(), target)
        self.assertEqual(self.store.load(target.profile_id), target)
        statuses = {e['choice_id']: e['status'] for e in result['changes']}
        self.assertEqual(statuses['da2.hawke_identity'], 'kept')
        self.assertEqual(statuses['dao.orzammar_ruler'], 'kept')
        saved = self.commit(result)
        for key, value in target.choices.items():
            self.assertEqual(saved.choices[key], value)
        self.assertIn('da2.carver_fate', saved.choices)
        self.assertEqual(saved.profile_id, target.profile_id)
        self.assertEqual(saved.revision, target.revision + 1)
        self.assertEqual(self.store.history(target.profile_id), [saved, target])
        self.assertEqual(self.store.load(other.profile_id), other)

    def test_replace_updates_only_recovered_choices_including_carried_dao(self):
        target = self.store.create('Existing', mode='experimental', choices={
            'da2.hawke_identity': 'female_mage', 'dao.orzammar_ruler': 'harrowmont',
            'dao.dagna_outcome': 'stayed'})
        source = self.preview()
        result = self.plan(source, target, 'replace')
        saved = self.commit(result)
        for key, value in source['choices'].items():
            self.assertEqual(saved.choices[key], value)
        self.assertEqual(saved.choices['da2.hawke_identity'], 'female_rogue')
        self.assertEqual(saved.choices['dao.orzammar_ruler'], 'bhelen')
        self.assertEqual(saved.choices['dao.dagna_outcome'], 'stayed')

    def test_explicit_inherited_default_stays_protected_and_noop_adds_no_revision(self):
        source = self.preview()
        choices = dict(source['choices'])
        target = self.store.create('Already imported', mode=source['mode'], choices=choices)
        result = self.plan(self.preview(), target)
        self.assertFalse(result['has_changes'])
        self.assertEqual(self.commit(result), target)
        self.assertEqual(len(self.store.history(target.profile_id)), 1)

    def test_plan_rotation_cancel_and_stale_destination_guards(self):
        target = self.store.create('Existing')
        original = self.preview()
        planned = self.plan(original, target)
        with self.assertRaisesRegex(ProfileError, 'expired'):
            self.commit(original)
        back = self.plan(planned)
        self.assertIsNone(back['target_profile_id'])
        self.imports.cancel({'import_id': back['import_id']})
        with self.assertRaisesRegex(ProfileError, 'expired'):
            self.commit(back)
        review = self.preview()
        newest = self.store.save(target.edited(name='Newer'))
        with self.assertRaises(RevisionConflict):
            self.plan(review, target)
        planned = self.plan(review, newest)
        latest = self.store.save(newest.edited(name='Changed after review'))
        with self.assertRaises(RevisionConflict):
            self.commit(planned)
        self.assertEqual(self.store.load(target.profile_id), latest)

    def test_dao_cannot_inject_da2_choices(self):
        target = self.store.create('Existing')
        result = self.imports.preview(dao_tests.dao_save(), game='dao')
        item = self.imports.pending[result['import_id']][1]
        item.source['choices']['da2.hawke_identity'] = 'female_mage'
        with self.assertRaisesRegex(ProfileError, 'source game history'):
            self.plan(result, target, 'replace')
        self.assertEqual(self.store.load(target.profile_id), target)

    def test_unresolved_bethany_fallback_stays_fillable_by_a_later_save(self):
        raw = make_save({ACT: [2, 4]}, party=[('gen00fl_bethany', 123, 2)])
        result = self.imports.preview(raw)
        saved = self.commit(result)
        self.assertNotIn('da2.bethany_final_battle', saved.choices)
        self.assertEqual(compile_profile(saved, catalog=self.app.catalog).effective_values['da2_bethany_final_battle_death'], 1)
        from game_saves.da2 import FINALE
        later = self.imports.preview(make_save({ACT: [2, 4], FINALE: [84]}, party=[('gen00fl_bethany', 123, 2)]))
        updated = self.commit(self.plan(later, saved))
        self.assertEqual(updated.choices['da2.bethany_final_battle'], 'died')
        self.assertEqual(compile_profile(updated, catalog=self.app.catalog).effective_values['da2_bethany_final_battle_death'], 2)

    def test_unresolved_bethany_never_replaces_a_manual_final_fate(self):
        for policy in ('missing', 'replace'):
            target = self.store.create('Explicit death ' + policy, mode='experimental', choices={
                'da2.bethany_final_battle': 'died'})
            source = self.imports.preview(make_save({ACT: [2, 4]}, party=[('gen00fl_bethany', 123, 2)]))
            saved = self.commit(self.plan(source, target, policy))
            self.assertEqual(saved.choices['da2.bethany_final_battle'], 'died')
            self.assertEqual(compile_profile(saved, catalog=self.app.catalog).effective_values['da2_bethany_final_battle_death'], 2)


if __name__ == '__main__':
    unittest.main()
