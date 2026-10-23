"""Platonic Alistair and ambiguous Avernus research use retained evidence."""
import unittest

from game_saves.dao import import_save as import_dao
from game_saves.da2 import import_save as import_da2
from game_saves.worldvault import DIRECT
from test_save_import import make_save
from world_profiles import Catalog

APP = DIRECT[2040][0]
LANDSMEET = DIRECT[2026][0]
CLIMAX = DIRECT[2030][0]
KEEP = DIRECT[2069][0]
AVERNUS = DIRECT[2071][0]


class UnresolvedOutcomeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def dao(self, plots, **kwargs):
        return import_dao(make_save(plots, game='dao', **kwargs), self.catalog)

    def test_platonic_relationship_does_not_require_origins_completion_or_gender(self):
        for completed in (False, True):
            for gender in (1, 2):
                with self.subTest(completed=completed, gender=gender):
                    result = self.dao({APP: [], LANDSMEET: [], CLIMAX: [4] if completed else []}, gender=gender)
                    self.assertEqual(result['choices']['dao.alistair_relationship'], 'never_lovers')
                    self.assertNotIn('dao.alistair_relationship', {e['choice_id'] for e in result['unresolved']})

    def test_missing_relationship_record_is_not_recovered_as_platonic(self):
        result = self.dao({LANDSMEET: [], CLIMAX: [4]})
        self.assertNotIn('dao.alistair_relationship', result['choices'])

    def test_no_landsmeet_record_does_not_block_current_platonic_relationship(self):
        self.assertEqual(self.dao({APP: []})['choices']['dao.alistair_relationship'], 'never_lovers')

    def test_persistent_romance_and_breakup_history_prevent_platonic_answer(self):
        for bit in (21, 27, 28, 29, 30, 32, 34):
            for completed in (False, True):
                with self.subTest(bit=bit, completed=completed):
                    result = self.dao({APP: [bit], LANDSMEET: [], CLIMAX: [4] if completed else []})
                    self.assertNotEqual(result['choices'].get('dao.alistair_relationship'), 'never_lovers')

    def test_marriage_and_ended_sexual_relationship_keep_existing_priority(self):
        queen = self.dao({APP: [], LANDSMEET: [56], CLIMAX: [4]})
        self.assertEqual(queen['choices']['dao.alistair_relationship'], 'queen')
        ended = self.dao({APP: [29], LANDSMEET: [], CLIMAX: [4]})
        self.assertEqual(ended['choices']['dao.alistair_relationship'], 'ended')

    def test_carried_dao_uses_retained_history_and_respects_saved_scalar_priority(self):
        for complete in (0, 1):
            result = import_da2(make_save(dao_plots={APP: [], LANDSMEET: []}, dao_bools={2089: complete}), self.catalog)
            self.assertEqual(result['choices']['dao.alistair_relationship'], 'never_lovers')
        missing = import_da2(make_save(dao_bools={2040: 0, 2041: 0, 2089: 1}), self.catalog)
        self.assertNotIn('dao.alistair_relationship', missing['choices'])
        active = import_da2(make_save(dao_plots={APP: [], LANDSMEET: []}, dao_bools={2040: 1, 2041: 0}), self.catalog)
        self.assertNotEqual(active['choices'].get('dao.alistair_relationship'), 'never_lovers')
        married = import_da2(make_save(dao_plots={APP: [], LANDSMEET: []}, dao_bools={2026: 1, 2089: 1}), self.catalog)
        self.assertEqual(married['choices']['dao.alistair_relationship'], 'queen')

    def test_departure_does_not_establish_exile_or_a_research_outcome(self):
        result = self.dao({KEEP: [2, 13], AVERNUS: [4]})
        self.assertNotIn('dao.avernus_fate', result['choices'])
        reason = next(e['reason'] for e in result['unresolved'] if e['choice_id'] == 'dao.avernus_fate')
        self.assertIn('neither ethical nor unrestricted research is recorded', reason)
        self.assertIn('marker alone does not establish', reason)
        self.assertNotIn('exile', reason)

    def test_existing_four_keep_outcomes_and_unfinished_quest_are_preserved(self):
        cases = (([2, 13, 17], [], 'both_perished'), ([13, 17], [], 'sided_sophia'),
                 ([2, 13], [5], 'unrestricted_research'), ([2, 13], [3], 'ethical_research'))
        for main, experiments, expected in cases:
            self.assertEqual(self.dao({KEEP: main, AVERNUS: experiments})['choices']['dao.avernus_fate'], expected)
        unfinished = self.dao({KEEP: [2], AVERNUS: [4]})
        reason = next(e['reason'] for e in unfinished['unresolved'] if e['choice_id'] == 'dao.avernus_fate')
        self.assertNotIn('GWB_AVERNUS_LEAVES', reason)


if __name__ == '__main__':
    unittest.main()
