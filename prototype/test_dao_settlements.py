"""Settlement outcomes, shared flags and DA2 later-survival precedence."""
import hashlib
import json
from pathlib import Path
import unittest

from game_saves.dao import import_save, ALL_SUPPORTED
from game_saves.dao_settlements import FLAGS, SUPPORTED
from game_saves.da2 import ACT, import_save as import_da2
from game_saves.da2_nathaniel import PLOT
from game_saves.worldvault import DIRECT
from test_save_import import make_save
from world_profiles import Catalog

ROOT = Path(__file__).resolve().parents[1]


def settlement_save(*names, completed=True, missing=(), extra=None):
    plots = {g: [] for g, _ in FLAGS.values() if g not in missing}
    for n in names:
        g, b = FLAGS[n]
        plots.setdefault(g, []).append(b)
    if completed:
        g, b = DIRECT[2030]
        plots.setdefault(g, []).append(b)
    for g, bits in (extra or {}).items(): plots.setdefault(g, []).extend(bits)
    return make_save(plots, game='dao')


class SettlementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.catalog = Catalog()
    def result(self, *names, **kwargs): return import_save(settlement_save(*names, **kwargs), self.catalog)
    def choices(self, *names, **kwargs):
        return {k: v for k, v in self.result(*names, **kwargs)['choices'].items() if k in SUPPORTED}

    def test_scope_missing_and_progress(self):
        self.assertEqual(len(SUPPORTED), 12)
        self.assertEqual(len(ALL_SUPPORTED), 74)
        self.assertEqual(self.choices(completed=False), {})
        self.assertEqual(self.choices(missing={g for g, _ in FLAGS.values()}), {})
        self.assertEqual(sum(self.result()['counts']['dao'].values()), 74)
        self.assertNotIn('dao.bella_fate', self.choices())

    def test_preparation_actual_delivery_or_honored_agreement_not_just_promise(self):
        for n in ('red_weapons', 'red_stash_given', 'red_oil', 'red_amulets', 'red_dwyn'):
            self.assertEqual(self.choices(n, completed=False)['dao.redcliffe_preparation'], 'helped')
        self.assertNotIn('dao.redcliffe_preparation', self.choices('red_agreed', completed=False))
        self.assertEqual(self.choices('red_agreed', 'red_siege_begins')['dao.redcliffe_preparation'], 'helped')
        self.assertEqual(self.choices('red_agreed', 'red_oil', 'red_abandoned')['dao.redcliffe_preparation'], 'not_helped')

    def test_bevin_actual_return_not_promise_key_or_shared_money(self):
        self.assertEqual(self.choices('bevin_returned', completed=False)['dao.bevin_fate'], 'returned_sword')
        self.assertEqual(self.choices('bevin_sword')['dao.bevin_fate'], 'took_sword')
        for names in (('bevin_found',), ('bevin_found', 'bevin_key'), ('bevin_found', 'bevin_sword', 'bevin_med_money')):
            self.assertNotIn('dao.bevin_fate', self.choices(*names))
        self.assertNotIn('dao.bevin_fate', self.choices('bevin_found', extra={FLAGS['bevin_found'][0]: [14]}))

    def test_bevin_sword_purchase_acknowledgments_are_not_travel_payments(self):
        for marker in ('bevin_sword_paid_medium', 'bevin_sword_paid_huge'):
            self.assertEqual(self.choices(marker, completed=False)['dao.bevin_fate'], 'paid_for_sword')
            self.assertEqual(self.choices(marker, 'bevin_returned')['dao.bevin_fate'], 'returned_sword')
        for marker in ('bevin_med_money', 'bevin_huge_money', 'bevin_small_money', 'bevin_tiny_money'):
            self.assertNotIn('dao.bevin_fate', self.choices('bevin_found', marker))

    def test_valena_must_escape_not_just_be_greeted(self):
        for n in ('valena_rescued', 'valena_left'):
            self.assertEqual(self.choices(n, completed=False)['dao.valena_fate'], 'rescued')
        self.assertNotIn('dao.valena_fate', self.choices(completed=False, extra={FLAGS['valena_rescued'][0]: [2]}))

    def test_bella_destination_funding_and_real_ownership(self):
        self.assertEqual(self.choices('bella_teagan')['dao.bella_fate'], 'left')
        self.assertEqual(self.choices('bella_denerim', 'bella_money')['dao.bella_fate'], 'brewery')
        self.assertEqual(self.choices('bella_in_charge', 'lloyd_siege_death')['dao.bella_fate'], 'tavern_owner')
        for names in (('bella_in_charge',), ('bella_in_charge', 'bella_player_owns', 'lloyd_killed'),
                      ('bella_denerim',), ('bella_teagan', 'bella_denerim'), ('red_abandoned', 'bella_teagan')):
            self.assertNotIn('dao.bella_fate', self.choices(*names))
        self.assertEqual(self.choices('red_abandoned')['dao.bella_fate'], 'died')

    def test_filda_shared_heroic_death_news_and_distinct_truth(self):
        for names, answer in ((('filda_said_dead',), 'said_dead'),
                              (('filda_condition_truth',), 'condition_truth'),
                              (('ruck_killed', 'filda_killed_truth'), 'killed_truth'),
                              (('ruck_killed', 'filda_not_found'), 'killed_lied')):
            self.assertEqual(self.choices(*names, completed=False)['dao.filda_ruck'], answer)
        self.assertEqual(self.choices()['dao.filda_ruck'], 'not_met')
        self.assertEqual(self.choices('ruck_killed', 'filda_said_dead')['dao.filda_ruck'], 'killed_heroic')
        for names in (('ruck_killed', 'filda_said_dead', 'ruck_promised_dead_story'), ('filda_accepted',),
                      ('filda_talked',), ('filda_said_dead', 'filda_condition_truth')):
            self.assertNotIn('dao.filda_ruck', self.choices(*names))

    def test_zerlinda_all_destinations_and_conflict(self):
        for n, a in (('zerlinda_deep_roads', 'deep_roads'), ('zerlinda_chantry', 'chantry'),
                     ('zerlinda_family', 'reconciled'), ('zerlinda_surface', 'surface')):
            self.assertEqual(self.choices(n, completed=False)['dao.zerlinda_fate'], a)
        self.assertEqual(self.choices()['dao.zerlinda_fate'], 'dust_town')
        self.assertNotIn('dao.zerlinda_fate', self.choices('zerlinda_family', 'zerlinda_chantry'))

    def test_mardy_origin_choices_follow_original_child_eligibility(self):
        self.assertNotIn('dao.mardy_relationship', self.choices('mardy_chosen', completed=False))
        for n in ('mardy_chosen', 'mardy_both_chosen'):
            self.assertEqual(self.choices(n)['dao.mardy_relationship'], 'had_relations')
            self.assertEqual(self.choices(n)['dao.mardy_son'], 'not_encountered')
        self.assertEqual(self.choices('mardy_met_origin')['dao.mardy_relationship'], 'no_relations')
        self.assertEqual(self.choices()['dao.mardy_relationship'], 'not_met')
        self.assertEqual(self.choices()['dao.mardy_son'], 'no_son')
        self.assertEqual(self.choices(extra={FLAGS['mardy_son_restored'][0]: [1]})['dao.mardy_son'], 'no_son')
        self.assertNotIn('dao.mardy_son', self.choices('mardy_chosen', extra={FLAGS['mardy_son_restored'][0]: [1]}))
        self.assertEqual(self.choices('mardy_son_restored')['dao.mardy_son'], 'restored')
        self.assertEqual(self.choices('mardy_chosen', extra={FLAGS['mardy_son_restored'][0]: [4]})['dao.mardy_son'], 'not_restored')
        self.assertNotIn('dao.mardy_son', self.choices(extra={FLAGS['mardy_son_restored'][0]: [4]}))

    def test_tome_stolen_item_is_not_a_final_disposition(self):
        self.assertEqual(self.choices('tome_returned', completed=False)['dao.shaperate_tome'], 'returned')
        self.assertEqual(self.choices('tome_sold', completed=False)['dao.shaperate_tome'], 'sold')
        self.assertNotIn('dao.shaperate_tome', self.choices('tome_sold', 'tome_returned'))
        self.assertNotIn('dao.shaperate_tome', self.choices(extra={FLAGS['tome_returned'][0]: [0, 1, 2]}))

    def test_landry_finished_duel_not_start_but_explicit_death_wins(self):
        self.assertEqual(self.choices('landry_killed', completed=False)['dao.landry_fate'], 'killed')
        self.assertEqual(self.choices('landry_peace', completed=False)['dao.landry_fate'], 'alive')
        self.assertEqual(self.choices('landry_left', completed=False)['dao.landry_fate'], 'alive')
        self.assertNotIn('dao.landry_fate', self.choices(completed=False, extra={FLAGS['landry_killed'][0]: [0, 4]}))

    def test_beggar_found_amulet_is_not_returned(self):
        self.assertEqual(self.choices('beggar_returned', completed=False)['dao.beggar_amulet'], 'returned')
        self.assertEqual(self.choices(extra={FLAGS['beggar_returned'][0]: [0]})['dao.beggar_amulet'], 'not_returned')

    def test_ignacio_attack_and_last_mission_not_chain_completion(self):
        self.assertEqual(self.choices('ignacio_killed', completed=False)['dao.ignacio_fate'], 'killed')
        self.assertEqual(self.choices('ignacio_done', completed=False)['dao.ignacio_fate'], 'completed')
        self.assertNotIn('dao.ignacio_fate', self.choices('ignacio_attacked'))
        self.assertNotIn('dao.ignacio_fate', self.choices('ignacio_killed', 'ignacio_done'))

    def test_source_flag_ids_and_shared_dialogue_ambiguity(self):
        p = ROOT / 'assessment/output/dao-import/batch4'
        plots = {x['guid']: x for x in json.loads((p / 'plots.json').read_text())}
        for guid, bit in FLAGS.values(): self.assertIn(bit, {f['id'] for f in plots[guid]['flags']})
        c = json.loads((p / 'conversations.json').read_text())
        for name, line, marker in (('arl110cr_kaitlyn.dlg', 13, 'bevin_returned'),
            ('arl220cr_valena.dlg', 47, 'valena_rescued'), ('arl150cr_bella.dlg', 24, 'bella_money'),
            ('orz200_filda.dlg', 102, 'filda_said_dead'), ('orz400_zerlinda.dlg', 198, 'zerlinda_deep_roads'),
            ('orz300_mardy.dlg', 69, 'mardy_son_restored')):
            a = c[name][line]['action']; self.assertEqual((a['guid'], a['flag']), FLAGS[marker])
        # Sword payment and travel money deliberately share these same bits.
        for line in (152, 174): self.assertEqual(c['arl110cr_kaitlyn.dlg'][line]['action']['flag'], 18)
        # “Heroically” and plain death-news both flow into the same terminal flag.
        self.assertEqual(c['orz200_filda.dlg'][90]['links'], [25, 26])
        self.assertEqual(c['orz200_filda.dlg'][98]['links'], [25, 26])
        self.assertEqual(c['orz200_filda.dlg'][90]['condition']['flag'], 7)
        self.assertEqual(c['orz200_filda.dlg'][98]['condition']['flag'], 6)
        self.assertEqual(c['arl110cr_kaitlyn.dlg'][34]['action']['flag'], 16)
        self.assertEqual(c['arl110cr_kaitlyn.dlg'][40]['action']['flag'], 15)


class DA2NathanielTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.catalog = Catalog()
    def result(self, bits=(), dead=True, stage=(4, 5), missing=False, vault=True):
        plots = {ACT: list(stage)}
        if not missing: plots[PLOT] = list(bits)
        return import_da2(make_save(plots, dao_bools={2084: int(dead)} if vault else {}), self.catalog)

    def test_success_corrects_scalar_death_and_sets_both_tapestry_answers(self):
        raw = make_save({ACT: [4], PLOT: [6]}, dao_bools={2084: 1})
        before = hashlib.sha256(raw).hexdigest()
        r = import_da2(raw, self.catalog)
        self.assertEqual(r['choices']['dao.nathaniel_fate'], 'alive')
        self.assertEqual(r['choices']['da2.finding_nathaniel'], 'rescued')
        self.assertTrue(any('overrides the inherited' in w for w in r['warnings']))
        self.assertEqual(hashlib.sha256(raw).hexdigest(), before)

    def test_success_also_confirms_missing_history_without_warning_of_override(self):
        r = self.result([6], vault=False)
        self.assertEqual(r['choices']['dao.nathaniel_fate'], 'alive')
        self.assertFalse(any('overrides the inherited' in w for w in r['warnings']))

    def test_abandonment_or_conflicting_success_is_not_successful_rescue(self):
        for bits in ((15,), (21,), (6, 15), (6, 21)):
            r = self.result(bits)
            self.assertEqual(r['choices']['dao.nathaniel_fate'], 'dead')
            self.assertNotIn('da2.finding_nathaniel', r['choices'])

    def test_meeting_start_or_fight_not_enough_to_override(self):
        for bit in (0, 1, 5, 8, 12):
            r = self.result([bit])
            self.assertEqual(r['choices']['dao.nathaniel_fate'], 'dead')
            self.assertNotIn('da2.finding_nathaniel', r['choices'])

    def test_absence_is_not_death_and_final_empty_plot_is_not_missing(self):
        self.assertNotIn('da2.finding_nathaniel', self.result(missing=True)['choices'])
        self.assertNotIn('da2.finding_nathaniel', self.result(stage=(4,))['choices'])
        self.assertEqual(self.result()['choices']['da2.finding_nathaniel'], 'not_survived')
        # Existing direct-history inference can establish alive using completed Awakening.
        raw = make_save({ACT: [5], PLOT: []}, dao_bools={2084: 0, 2065: 1, 2091: 1})
        self.assertEqual(import_da2(raw, self.catalog)['choices']['da2.finding_nathaniel'], 'not_encountered')
        self.assertNotIn('da2.finding_nathaniel', self.result(vault=False)['choices'])

    def test_original_success_dialogue_is_after_live_reward_speech(self):
        p = ROOT / 'assessment/output/save-import-survey/nathaniel'
        c = json.loads((p / 'conversations.json').read_text())['nat380_nathaniel.cnv']['lines']
        self.assertIn('see my sister and nephew again', c[10]['text'])
        self.assertEqual(c[31]['action']['guid'].rstrip('\0'), PLOT)
        self.assertEqual(c[31]['action']['flag'], 6)
        script = (p / 'nat300pt_find_nathaniel.nss').read_text()
        self.assertIn('case 6:', script)
        self.assertIn('RemoveNonPartyFollower(local_oFollower_4)', script)


if __name__ == '__main__': unittest.main()
