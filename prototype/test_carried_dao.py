"""Copied DAO history in DA2: isolation, scalar precedence and extra outcomes."""
import hashlib
import json
from pathlib import Path
import unittest
import zipfile

from game_saves.da2 import ACT, import_save
from game_saves.gff import SaveReader
from game_saves.worldvault import DaoHistory, infer_dao, DIRECT
from game_saves.dao_carried import CarriedPlots
from game_saves.dao_companions import FLAGS as COMPANIONS
from game_saves.dao_sidequests import FLAGS as SIDEQUESTS
from game_saves.dao_landsmeet import PLOT as LANDSMEET
from game_saves.da2_nathaniel import PLOT as NATHANIEL
from test_save_import import make_save
from world_profiles import Catalog


def plots_for(flags, names):
    plots = {}
    for name, value in names.items():
        guid, bit = flags[name]
        plots.setdefault(guid, [])
        if value:
            plots[guid].append(bit)
    return plots


class CarriedDaoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def result(self, plots=None, booleans=None, active=None, **kwargs):
        raw = make_save({ACT: [0, 2, 4, 5], **(active or {})}, dao_plots=plots or {},
                        dao_bools=booleans or {}, **kwargs)
        return import_save(raw, self.catalog)

    def test_requested_companions_are_recovered_from_separate_copied_plots(self):
        plots = plots_for(COMPANIONS, {'sten_recruited': True, 'sten_left': False,
            'wynne_recruited': True, 'leliana_recruited': True,
            'leliana_attacked': False, 'leliana_left': False})
        r = self.result(plots, {2089: 1})
        for key, answer in {'sten_recruited': 'recruited', 'wynne_recruited': 'recruited', 'leliana_fate': 'alive'}.items():
            self.assertEqual(r['choices']['dao.' + key], answer)
            entry = next(e for e in r['recognized'] if e['choice_id'] == 'dao.' + key)
            self.assertIn('copied into DA2', entry['evidence'])

    def test_active_hawke_plots_cannot_supply_dao_history(self):
        active = plots_for(COMPANIONS, {'sten_recruited': True, 'wynne_recruited': True,
                                      'leliana_recruited': True, 'leliana_attacked': False})
        result = self.result(active=active)
        self.assertEqual(result['counts']['dao']['recovered'], 0)

    def test_missing_and_zeroed_records_without_completion_stay_unknown(self):
        plots = {guid: [] for guid, _ in COMPANIONS.values()}
        for r in (self.result(), self.result(plots)):
            for key in ('sten_recruited', 'wynne_recruited', 'leliana_fate', 'wynne_fate'):
                self.assertNotIn('dao.' + key, r['choices'])

    def test_leliana_alive_needs_retained_departure_and_hostility_record(self):
        plots = plots_for(COMPANIONS, {'leliana_recruited': True})
        self.assertNotIn('dao.leliana_fate', self.result(plots)['choices'])
        plots.update(plots_for(COMPANIONS, {'leliana_attacked': False, 'leliana_left': False}))
        self.assertEqual(self.result(plots, {2089: 1})['choices']['dao.leliana_fate'], 'alive')

    def test_contradictory_companion_outcomes_are_not_guessed(self):
        plots = plots_for(COMPANIONS, {'leliana_recruited': True, 'leliana_attacked': True,
            'wynne_recruited': True, 'wynne_killed_circle': True, 'wynne_killed_urn': True})
        r = self.result(plots, {2089: 1})
        for key in ('leliana_fate', 'wynne_fate', 'wynne_recruited'):
            self.assertNotIn('dao.' + key, r['choices'])

    def test_saved_scalar_overrides_copied_recruitment_in_extra_rules(self):
        plots = plots_for(COMPANIONS, {'leliana_recruited': True, 'leliana_attacked': False, 'leliana_left': False})
        r = self.result(plots, {2038: 0, 2089: 1})
        self.assertNotEqual(r['choices'].get('dao.leliana_fate'), 'alive')
        self.assertEqual(self.result(plots, {2038: 1, 2089: 1})['choices']['dao.leliana_fate'], 'alive')

    def test_scalars_do_not_synthesize_missing_raw_records(self):
        r = self.result(booleans={2089: 1, 2038: 1, 2045: 0})
        for key in ('leliana_fate', 'sten_recruited', 'wynne_recruited', 'dagna_outcome'):
            self.assertNotIn('dao.' + key, r['choices'])

    def test_awakening_felsi_marker_overrides_earlier_origins_tavern_failure(self):
        plots = {'530C45E15B4548A5A41DEC739E1F2B2D': [3, 43],
                 'D4920BFFC3E24C2FAC5A513AFD87C6DE': [2, 3],
                 '6F08DC1CF4984FF699D7DC3CAD18B753': [3, 6]}
        self.assertEqual(self.result(plots)['choices']['dao.oghren_felsi'], 'reunited')
        plots.pop('D4920BFFC3E24C2FAC5A513AFD87C6DE')
        self.assertNotIn('dao.oghren_felsi', self.result(plots)['choices'])

    def test_projection_keeps_original_history_immutable_and_scalar_zero_authoritative(self):
        guid, bit = DIRECT[2038]
        history = DaoHistory(SaveReader(make_save(dao_plots={guid: [bit, 8, 13]}, dao_bools={2038: 0})))
        before = dict(history.plots)
        projected = CarriedPlots(history)
        self.assertFalse(projected.plots[guid][0] & (1 << bit))
        self.assertTrue(projected.plots[guid][0] & (1 << 8))
        self.assertEqual(history.plots, before)

    def test_completion_is_derived_only_when_saved_completion_is_absent(self):
        guid, bit = DIRECT[2030]
        plots = {guid: [bit]}
        plots.update(plots_for(COMPANIONS, {'sten_recruited': True, 'sten_left': False, 'sten_sword_returned': False}))
        self.assertEqual(self.result(plots)['choices']['dao.sten_sword'], 'not_returned')
        self.assertNotIn('dao.sten_sword', self.result(plots, {2089: 0})['choices'])

    def test_execution_actor_refines_missing_fate_but_keeps_primary_survival(self):
        self.assertEqual(self.result({LANDSMEET: [6, 20]})['choices']['dao.loghain_fate'], 'executed_by_warden')
        plots = {LANDSMEET: [6, 20]}
        r = self.result(plots, {2025: 0, 2097: 1, 2030: 1})
        self.assertEqual(r['choices']['dao.loghain_fate'], 'alive_recruited')

    def test_extra_side_quests_and_release_sword_outcomes(self):
        plots = plots_for(COMPANIONS, {'sten_recruited': True, 'sten_left': False,
            'sten_released': True, 'sten_lock_picked': True, 'sten_sword_returned': True})
        plots.update(plots_for(SIDEQUESTS, {'ironbark_complete': True}))
        r = self.result(plots)
        self.assertEqual(r['choices']['dao.sten_release'], 'picked_lock')
        self.assertEqual(r['choices']['dao.sten_sword'], 'returned')
        self.assertEqual(r['choices']['dao.varathorn_ironbark'], 'brought')

    def test_later_da2_nathaniel_rescue_still_has_final_authority(self):
        r = self.result(booleans={2065: 1, 2084: 1, 2091: 1}, active={NATHANIEL: [6]})
        self.assertEqual(r['choices']['dao.nathaniel_fate'], 'alive')
        self.assertEqual(r['choices']['da2.finding_nathaniel'], 'rescued')
        self.assertTrue(any('overrides' in e['evidence'] for e in r['recognized'] if e['choice_id'] == 'dao.nathaniel_fate'))

    def test_supplied_saves_preserve_prior_answers_and_recover_fuller_dao_history(self):
        root = Path(__file__).resolve().parents[1]
        fixture = root / 'assessment/output/save-import-survey/comparison-cases.json'
        if not fixture.is_file():
            self.skipTest('Local research fixtures are unavailable')
        cases = json.loads(fixture.read_text())['cases']
        for case in cases:
            path = Path(case['source'])
            if not path.exists():
                self.skipTest('Local research saves are unavailable')
            if path.suffix == '.zip':
                with zipfile.ZipFile(path) as archive:
                    raw = archive.read(next(n for n in archive.namelist() if n.endswith('.das')))
            else:
                raw = path.read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), case['save_sha256'])
            result = import_save(raw, self.catalog)
            prior, _, _ = infer_dao(DaoHistory(SaveReader(raw)))
            for key, answer in prior.items():
                self.assertEqual(result['choices'][key], answer)
            expected = 70 if case['label'] == 'Marian4_AndersRomance' else 72
            self.assertEqual(result['counts']['dao'], {'recovered': expected, 'unresolved': 74 - expected})
            for key, answer in {'wynne_recruited': 'recruited', 'sten_recruited': 'recruited',
                                'leliana_fate': 'alive', 'sten_sword': 'returned', 'dagna_outcome': 'studied'}.items():
                self.assertEqual(result['choices']['dao.' + key], answer)
            self.assertNotIn('dao.bevin_fate', result['choices'])
            self.assertNotIn('dao.ostagar_deserter', result['choices'])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), case['save_sha256'])


if __name__ == '__main__':
    unittest.main()
