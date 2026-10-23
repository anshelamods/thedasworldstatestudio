"""Distinguish actual execution from offers, duel starts and conflicts."""
import json
from pathlib import Path
import unittest

from game_saves.dao import import_save
from game_saves.dao_landsmeet import PLOT
from game_saves.worldvault import DIRECT
from test_save_import import make_save
from world_profiles import Catalog


class LandsmeetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.catalog = Catalog()

    def result(self, bits=(), extra=None):
        plots = {PLOT: list(bits)}
        for guid, flags in (extra or {}).items(): plots.setdefault(guid, []).extend(flags)
        return import_save(make_save(plots, game='dao'), self.catalog)

    def test_execution_actor_and_alistair_duel(self):
        for bits, answer in (((6, 20), 'executed_by_warden'),
                             ((6, 22), 'executed_by_alistair'),
                             ((6, 22, 24), 'killed_in_duel')):
            result = self.result(bits)
            self.assertEqual(result['choices']['dao.loghain_fate'], answer)
            self.assertFalse(any(r['choice_id'] == 'dao.loghain_fate' for r in result['unresolved']))

    def test_generic_death_offers_and_duel_start_remain_unknown(self):
        for bits in ((), (6,), (14,), (19,), (24,), (6, 24), (6, 13, 19)):
            self.assertNotIn('dao.loghain_fate', self.result(bits)['choices'])

    def test_execution_conflicts_remove_earlier_inferred_survival(self):
        for bits in ((20,), (22,), (6, 20, 22), (6, 20, 8), (6, 22, 8)):
            self.assertNotIn('dao.loghain_fate', self.result(bits)['choices'])
        guid, flag = DIRECT[2029]
        self.assertNotIn('dao.loghain_fate', self.result((6, 22), {guid: [flag]})['choices'])

    def test_recruited_and_sacrificed_rules_are_preserved(self):
        guid, bit = DIRECT[2030]
        self.assertEqual(self.result((8,), {guid: [bit]})['choices']['dao.loghain_fate'], 'alive_recruited')
        plots = {}
        for key in (2029, 2104):
            if key in DIRECT:
                guid, bit = DIRECT[key]; plots.setdefault(guid, []).append(bit)
        # An explicit no-ritual record plus Loghain's killing blow.
        ritual_guid, _ = DIRECT[2034]
        plots.setdefault(ritual_guid, [])
        second_guid, _ = DIRECT[2100]
        plots.setdefault(second_guid, [])
        self.assertEqual(self.result((8,), plots)['choices']['dao.loghain_fate'], 'sacrificed')

    def test_original_dialogue_and_plot_script_confirm_actor_flags(self):
        root = Path(__file__).resolve().parents[1] / 'assessment/output/dao-import/ambiguities'
        convo = json.loads((root / 'conversations.json').read_text(encoding='utf-8'))['den600_landsmeet.dlg']
        for line, flag in ((87, 20), (212, 22), (693, 24)):
            self.assertEqual((convo[line]['action']['guid'], convo[line]['action']['flag']), (PLOT, flag))
        self.assertEqual(convo[218]['condition']['flag'], 24)
        self.assertEqual(convo[219]['links'], [588])
        self.assertEqual(convo[588]['links'], [212])
        script = (root / 'denpt_main.nss').read_text()
        self.assertIn('case 20: goto block_000042ED;', script)
        self.assertIn('case 22: goto block_0000436B;', script)
        self.assertIn(f'("{PLOT}", 6, 1, 1)', script)


if __name__ == '__main__': unittest.main()
