"""Final DAO import outcomes, unsafe shortcuts and original source anchors."""
import json
from pathlib import Path
import unittest

from game_saves.dao import import_save, ALL_SUPPORTED
from game_saves.dao_finalquests import FLAGS, SUPPORTED
from game_saves.worldvault import DIRECT
from test_save_import import make_save
from world_profiles import Catalog

ROOT = Path(__file__).resolve().parents[1]


def final_save(*names, completed=False, missing=(), extra=None):
    plots = {g: [] for g, _ in FLAGS.values() if g not in missing}
    for n in names:
        g, b = FLAGS[n]
        plots.setdefault(g, []).append(b)
    if completed:
        g, b = DIRECT[2030]
        plots.setdefault(g, []).append(b)
    for g, bits in (extra or {}).items(): plots.setdefault(g, []).extend(bits)
    return make_save(plots, game='dao')


class FinalQuestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.catalog = Catalog()
    def result(self, *names, **kwargs): return import_save(final_save(*names, **kwargs), self.catalog)
    def choices(self, *names, **kwargs):
        return {k: v for k, v in self.result(*names, **kwargs)['choices'].items() if k in SUPPORTED}

    def test_scope_and_missing_plots_are_not_negative_answers(self):
        self.assertEqual(len(SUPPORTED), 6)
        self.assertEqual(len(ALL_SUPPORTED), 74)
        self.assertFalse(self.choices())
        self.assertFalse(self.choices(completed=True, missing={g for g, _ in FLAGS.values()}))
        self.assertTrue(all(r['status'] == 'needs_review' for r in self.result()['unresolved']))

    def test_couldry_uses_final_completion_not_skills_last_assignment_or_acknowledgment(self):
        self.assertEqual(self.choices('couldry_done')['dao.slim_couldry'], 'completed')
        for bit in (0, 1, 2, 11, 14, 17, 18):
            self.assertNotIn('dao.slim_couldry', self.choices(extra={FLAGS['couldry_done'][0]: [bit]}))
        self.assertEqual(self.choices(completed=True)['dao.slim_couldry'], 'not_completed')

    def test_falcons_peaceful_and_violent_clearance_count_even_without_turn_in(self):
        for n in ('falcons_quelled', 'falcons_killed', 'falcons_left'):
            self.assertEqual(self.choices(n)['dao.kylon_falcons'], 'helped')
        # Quest failure can mean Kylon disliked killing them, not that they stayed.
        self.assertEqual(self.choices('falcons_killed', extra={FLAGS['falcons_killed'][0]: [8]})['dao.kylon_falcons'], 'helped')
        self.assertNotIn('dao.kylon_falcons', self.choices(extra={FLAGS['falcons_left'][0]: [0, 9]}))
        self.assertEqual(self.choices(completed=True)['dao.kylon_falcons'], 'not_helped')

    def test_oars_clearance_siding_and_conflict(self):
        for n in ('oars_killed', 'oars_left'):
            self.assertEqual(self.choices(n)['dao.kylon_crimson_oars'], 'handled')
            result = self.result(n, 'oars_sided_with')
            self.assertNotIn('dao.kylon_crimson_oars', result['choices'])
            self.assertIn('both clearing and siding', next(r['reason'] for r in result['unresolved'] if r['choice_id'] == 'dao.kylon_crimson_oars'))
        self.assertEqual(self.choices('oars_sided_with')['dao.kylon_crimson_oars'], 'not_handled')
        self.assertNotIn('dao.kylon_crimson_oars', self.choices(extra={FLAGS['oars_killed'][0]: [0, 2]}))

    def test_both_protected_matches_exact_original_granite_expression(self):
        for granite in ('granite_complete', 'granite_without_men'):
            self.assertEqual(self.choices('amaranthine_saved', granite, 'walls_funded')['dao.awakening_protection'], 'both')
            self.assertEqual(self.choices('amaranthine_saved', granite)['dao.awakening_protection'], 'amaranthine')
        self.assertEqual(self.choices('amaranthine_saved', 'walls_funded')['dao.awakening_protection'], 'amaranthine')
        self.assertNotIn('dao.awakening_protection', self.choices('granite_complete', 'walls_funded', completed=True))

    def test_missing_upgrade_data_does_not_guess_keep_survival(self):
        for missing in (('walls_funded',), ('granite_complete',), ('walls_funded', 'granite_complete')):
            missing_guids = {FLAGS[n][0] for n in missing}
            names = ['amaranthine_saved'] + [n for n in ('granite_complete', 'walls_funded') if FLAGS[n][0] not in missing_guids]
            self.assertNotIn('dao.awakening_protection', self.choices(*names, missing=missing_guids))
        # A known unmet AND operand is sufficient to establish no strong walls.
        self.assertEqual(self.choices('amaranthine_saved', missing={FLAGS['walls_funded'][0]})['dao.awakening_protection'], 'amaranthine')

    def test_keep_requires_actual_defense_not_just_abandonment_or_siege_start(self):
        self.assertEqual(self.choices('keep_defended', 'amaranthine_abandoned')['dao.awakening_protection'], 'keep')
        for names in (('amaranthine_abandoned',), ('keep_defended',), ('keep_defended', 'keep_failed', 'amaranthine_abandoned'), ('amaranthine_saved', 'amaranthine_abandoned')):
            self.assertNotIn('dao.awakening_protection', self.choices(*names))

    def test_blood_consumed_destroyed_absent_and_conflicting(self):
        self.assertEqual(self.choices('blood_accepted')['dao.power_of_blood'], 'drank')
        self.assertEqual(self.choices('blood_destroyed')['dao.power_of_blood'], 'did_not_drink')
        self.assertEqual(self.choices(completed=True)['dao.power_of_blood'], 'did_not_drink')
        self.assertNotIn('dao.power_of_blood', self.choices('blood_accepted', 'blood_destroyed'))

    def test_kitty_all_five_outcomes(self):
        cases = [('both_unpossessed', ('amalia_escaped',)),
                 ('amalia_possessed', ('amalia_possessed',)),
                 ('matthias_possessed', ('matthias_possessed',)),
                 ('matthias_dead', ('matthias_possessed', 'matthias_dead')),
                 ('amalia_dead', ('amalia_dead',))]
        for answer, names in cases:
            with self.subTest(answer=answer): self.assertEqual(self.choices(*names)['dao.kitty_amalia'], answer)

    def test_kitty_departure_markers_and_historical_possession(self):
        for n, answer in [('left_amalia_free', 'both_unpossessed'), ('left_amalia_possessed', 'amalia_possessed'), ('left_matthias_possessed', 'matthias_possessed')]:
            self.assertEqual(self.choices(n)['dao.kitty_amalia'], answer)
        self.assertEqual(self.choices('matthias_possessed', 'matthias_dead')['dao.kitty_amalia'], 'matthias_dead')

    def test_kitty_unfinished_and_contradictory_outcomes_need_review(self):
        cases = [(), ('matthias_dead',), ('left_without_amalia',), ('amalia_escaped', 'amalia_possessed'),
                 ('amalia_dead', 'matthias_dead'), ('amalia_dead', 'amalia_possessed'),
                 ('amalia_escaped', 'left_amalia_possessed'), ('amalia_dead', 'left_amalia_free')]
        for names in cases:
            with self.subTest(names=names): self.assertNotIn('dao.kitty_amalia', self.choices(*names, completed=True))
        self.assertNotIn('dao.kitty_amalia', self.choices(completed=True, extra={FLAGS['matthias_dead'][0]: [1, 2, 13, 15]}))

    def test_original_source_anchors(self):
        root = ROOT / 'assessment/output/dao-import/batch5'
        plots = {p['guid']: p for p in json.loads((root / 'plots.json').read_text())}
        for guid, bit in FLAGS.values():
            self.assertIn(bit, {f['id'] for f in plots[guid]['flags']})
        convo = json.loads((root / 'conversations.json').read_text('utf8'))
        father = convo['shale200_matthias.dlg']
        self.assertEqual(father[8]['action']['flag'], 23)
        self.assertEqual(father[121]['action']['flag'], 0)
        self.assertEqual(convo['ep1_epilogue.dlg'][28]['condition']['guid'], FLAGS['granite_complete'][0])
        self.assertEqual(convo['ep1_epilogue.dlg'][28]['condition']['flag'], 257)
        script = (root / 'gwb120pt_abilities.nss').read_text()
        self.assertIn('AddAbility(hero, 310000', script)
        self.assertIn('case 0:', script)


if __name__ == '__main__': unittest.main()
