"""DAO side-quest evidence and the original Nathaniel siege-bug correction."""
import json
from pathlib import Path
import unittest

from game_saves.dao import import_save, ALL_SUPPORTED
from game_saves.dao_sidequests import FLAGS, SUPPORTED
from game_saves.dao_nathaniel import FLAGS as NATHANIEL
from game_saves.da2 import import_save as import_da2
from game_saves.worldvault import DIRECT
from test_save_import import make_save
from world_profiles import Catalog

ROOT = Path(__file__).resolve().parents[1]


def side_save(*names, completed=True, missing=(), extra=None, game='dao'):
    all_flags = dict(FLAGS, **NATHANIEL)
    plots = {guid: [] for guid, _ in all_flags.values() if guid not in missing}
    for n in names:
        guid, bit = all_flags[n]
        plots.setdefault(guid, []).append(bit)
    if completed:
        guid, bit = DIRECT[2030]
        plots.setdefault(guid, []).append(bit)
    for guid, bits in (extra or {}).items(): plots.setdefault(guid, []).extend(bits)
    return make_save(plots, game=game)


class DaoSideQuestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.catalog = Catalog()

    def result(self, *names, **kwargs): return import_save(side_save(*names, **kwargs), self.catalog)
    def choices(self, *names, **kwargs):
        return {k: v for k, v in self.result(*names, **kwargs)['choices'].items() if k in SUPPORTED}

    def test_scope_missing_progress_and_negative_endings(self):
        self.assertEqual(len(SUPPORTED), 12)
        self.assertEqual(len(ALL_SUPPORTED), 74)
        self.assertEqual(self.choices(completed=False), {})
        self.assertEqual(self.choices(missing={g for g, _ in FLAGS.values()}), {})
        choices = self.choices()
        self.assertEqual(len(choices), 12)
        self.assertTrue(all(v.startswith('not_') for v in choices.values()))
        result = self.result()
        self.assertEqual(sum(result['counts']['dao'].values()), 74)
        self.assertTrue(all(e['status'] == 'needs_review' for e in self.result(completed=False)['unresolved'] if e['choice_id'] in SUPPORTED))

    def test_cammen_terminal_answers_and_encounter_without_final_answer(self):
        self.assertEqual(self.choices('cammen_together', completed=False)['dao.cammen_relationship'], 'together')
        self.assertEqual(self.choices('cammen_separated', completed=False)['dao.cammen_relationship'], 'broke_up')
        for names in (('cammen_met',), ('gheyna_met',), ('cammen_separated', 'cammen_together')):
            self.assertNotIn('dao.cammen_relationship', self.choices(*names))
        guid = FLAGS['cammen_together'][0]
        self.assertNotIn('dao.cammen_relationship', self.choices(extra={guid: [6]}))  # pelt promise
        self.assertNotIn('dao.cammen_relationship', self.choices(extra={guid: [17]}))  # persuasion before couple scene

    def test_halla_saved_death_and_failed_attempt(self):
        self.assertEqual(self.choices('halla_saved', completed=False)['dao.elora_halla'], 'saved')
        for death in ('halla_killing', 'halla_killed'):
            self.assertEqual(self.choices(death, completed=False)['dao.elora_halla'], 'killed')
            self.assertNotIn('dao.elora_halla', self.choices(death, 'halla_saved'))
        self.assertEqual(self.choices(extra={FLAGS['halla_saved'][0]: [2, 4, 7]})['dao.elora_halla'], 'not_helped')

    def test_athras_news_not_scarf_or_reward_alone(self):
        self.assertEqual(self.choices('athras_told', completed=False)['dao.athras_danyla'], 'told')
        for n in ('athras_scarf', 'athras_reward', 'athras_angry'):
            self.assertNotIn('dao.athras_danyla', self.choices(n))

    def test_ironbark_handover_not_possession_or_halla_amulet(self):
        for n in (n for n in FLAGS if n.startswith('ironbark_')):
            self.assertEqual(self.choices(n, completed=False)['dao.varathorn_ironbark'], 'brought')
        self.assertEqual(self.choices(extra={FLAGS['ironbark_complete'][0]: [4, 13, 16]})['dao.varathorn_ironbark'], 'not_brought')

    def test_deygan_killed_body_return_and_live_return_are_distinct(self):
        self.assertEqual(self.choices('deygan_killed', 'deygan_returned_body')['dao.deygan_fate'], 'killed')
        for n in ('deygan_returned_body', 'deygan_returned_alive', 'deygan_healed'):
            self.assertEqual(self.choices(n, completed=False)['dao.deygan_fate'], 'returned')
        self.assertNotIn('dao.deygan_fate', self.choices('deygan_killed', 'deygan_returned_alive'))
        for bit in (4, 18, 20, 28):  # found, died, abandoned, left in forest
            self.assertNotIn('dao.deygan_fate', self.choices(extra={FLAGS['deygan_killed'][0]: [bit]}))

    def test_burkel_permission_is_not_opened_chantry(self):
        self.assertEqual(self.choices('burkel_complete', completed=False)['dao.burkel_chantry'], 'helped')
        self.assertNotIn('dao.burkel_chantry', self.choices('burkel_permission'))
        self.assertNotIn('dao.burkel_chantry', self.choices('burkel_complete', 'burkel_failed'))
        self.assertEqual(self.choices('burkel_failed')['dao.burkel_chantry'], 'not_helped')

    def test_orta_records_must_be_delivered_not_merely_found(self):
        for n in ('orta_complete', 'orta_assembly'):
            self.assertEqual(self.choices(n, completed=False)['dao.orta_ancestry'], 'helped')
            self.assertNotIn('dao.orta_ancestry', self.choices(n, 'orta_failed'))
        self.assertEqual(self.choices(extra={FLAGS['orta_complete'][0]: [3, 12]})['dao.orta_ancestry'], 'not_helped')

    def test_legion_must_be_filed_not_just_found(self):
        for n in ('legion_filed', 'legion_codex_filed'):
            self.assertEqual(self.choices(n, completed=False)['dao.legion_noble_house'], 'proven')
        self.assertEqual(self.choices(extra={FLAGS['legion_filed'][0]: [0, 1]})['dao.legion_noble_house'], 'not_proven')

    def test_rogek_delivery_is_not_returned_order(self):
        self.assertEqual(self.choices('rogek_complete', completed=False)['dao.rogek_lyrium'], 'completed')
        self.assertNotIn('dao.rogek_lyrium', self.choices('rogek_complete', 'rogek_failed'))
        self.assertEqual(self.choices(extra={FLAGS['rogek_complete'][0]: [0, 8]})['dao.rogek_lyrium'], 'not_completed')

    def test_noble_deliveries_and_justine_not_item_acquisition(self):
        for key, name, answer, early_bit in (
            ('oswyn_sighard', 'oswyn_spoke_sighard', 'told', 92),
            ('irminric_ring', 'irminric_proof_given', 'given', 46),
            ('justine_scroll', 'justine_scroll_given', 'brought', 4)):
            self.assertEqual(self.choices(name, completed=False)['dao.' + key], answer)
            self.assertTrue(self.choices(extra={FLAGS[name][0]: [early_bit]})['dao.' + key].startswith('not_'))

    def test_source_plot_anchors_and_key_dialogue_actions(self):
        p = ROOT / 'assessment/output/dao-import/batch3'
        plots = {x['guid']: x for x in json.loads((p / 'plots.json').read_text())}
        for guid, bit in FLAGS.values():
            self.assertIn(bit, {f['id'] for f in plots[guid]['flags']})
        c = json.loads((p / 'conversations.json').read_text())
        for name, line, marker in (
            ('ntb100cr_cammen.dlg', 169, 'cammen_together'),
            ('ntb100cr_gheyna.dlg', 3, 'cammen_separated'),
            ('ntb100cr_elora.dlg', 93, 'halla_saved'),
            ('ntb100cr_athras.dlg', 11, 'athras_told'),
            ('orz200_burkel.dlg', 99, 'burkel_complete'),
            ('orz310_orta.dlg', 84, 'orta_assembly'),
            ('orz400_rogek.dlg', 80, 'rogek_complete'),
            ('den220_sighard.dlg', 1, 'oswyn_spoke_sighard'),
            ('den220_alfstanna.dlg', 20, 'irminric_proof_given'),
            ('den_justine.dlg', 39, 'justine_scroll_given')):
            action = c[name][line]['action']
            self.assertEqual((action['guid'], action['flag']), FLAGS[marker])
            self.assertEqual(action['value'], 255)
        memories = (p / 'orz310ip_memories.nss').read_text()
        self.assertIn('"FF482830F073470CACEA04B640C2560F", 2, 1, 1', memories)
        self.assertIn('"EDA07192072C4B7D96ACB432DBDDE790", 4, 1, 0', memories)


class NathanielSiegeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.catalog = Catalog()

    markers = ('siege_death', 'amaranthine_saved', 'joining_complete', 'granite_complete', 'walls_funded')

    def result(self, *markers, missing=(), recruited=True, **kwargs):
        guid, bit = DIRECT[2065]
        return import_save(side_save(*markers, missing=missing, extra={guid: [bit] if recruited else []}, **kwargs), self.catalog)

    def test_exact_survival_epilogue_corrects_bug_with_both_wall_routes(self):
        for wall in ('granite_complete', 'granite_without_men'):
            markers = tuple(n for n in self.markers if n != 'granite_complete') + (wall,)
            r = self.result(*markers)
            self.assertEqual(r['choices']['dao.nathaniel_fate'], 'alive')
            e = next(x['evidence'] for x in r['recognized'] if x['choice_id'] == 'dao.nathaniel_fate')
            self.assertIn('corrected Awakening siege/codex bug', e)

    def test_genuine_siege_death_or_absent_upgrade_evidence_is_not_erased(self):
        for omitted in ('amaranthine_saved', 'joining_complete', 'granite_complete', 'walls_funded'):
            markers = tuple(n for n in self.markers if n != omitted)
            self.assertEqual(self.result(*markers)['choices']['dao.nathaniel_fate'], 'dead')
        for guid in {g for g, _ in NATHANIEL.values()}:
            # Missing source plot must never satisfy an epilogue condition.
            from game_saves.dao import DaoSaveHistory
            from game_saves.gff import SaveReader
            raw = side_save(*self.markers, extra={DIRECT[2065][0]: [DIRECT[2065][1]]})
            h = DaoSaveHistory(SaveReader(raw, game='dao'))
            h.plots.pop(guid, None)
            from game_saves.dao_nathaniel import reconcile
            choices, evidence, notes = {'dao.nathaniel_fate': 'dead'}, {}, {}
            reconcile(h, choices, evidence, notes)
            self.assertNotEqual(choices.get('dao.nathaniel_fate'), 'alive')
            if guid in {NATHANIEL[n][0] for n in ('granite_complete', 'walls_funded')}:
                self.assertNotIn('dao.nathaniel_fate', choices)
                self.assertIn('wall-upgrade evidence', notes['dao.nathaniel_fate'])

    def test_separate_killing_departure_party_or_no_recruitment_prevents_repair(self):
        for marker in ('executed', 'killed_after_return', 'left_crisis', 'hanged',
                       'killed_by_player', 'left_for_good', 'left_after_release', 'amaranthine_party'):
            self.assertEqual(self.result(*self.markers, marker)['choices']['dao.nathaniel_fate'], 'dead')
        self.assertEqual(self.result(*self.markers, recruited=False)['choices']['dao.nathaniel_fate'], 'dead')

    def test_da2_copied_history_and_vault_death_are_not_silently_repaired(self):
        plots = {g: [] for g, _ in NATHANIEL.values()}
        for name in self.markers:
            guid, bit = NATHANIEL[name]
            plots[guid].append(bit)
        plots[DIRECT[2065][0]] = [DIRECT[2065][1]]
        for bools in ({}, {2084: 1, 2065: 1}):
            raw = make_save(dao_plots=plots, dao_bools=bools)
            self.assertEqual(import_da2(raw, self.catalog)['choices']['dao.nathaniel_fate'], 'dead')

    def test_original_bug_setter_and_epilogue_conditions_are_separate(self):
        p = ROOT / 'assessment/output/dao-import/nathaniel'
        text = (p / 'aoa100pt_siege.nss').read_text()
        self.assertIn('"5BEE8FEFF2AC44788A13AD590C96E67A", 10, 0', text)
        self.assertIn('"F29B4323C13049BABE1D2E3007C6AD1D", 12, 1, 1', text)
        conditions = (p / 'gxapt_nathaniel_defined.nss').read_text().split('case 264:', 1)[1].split('break;', 1)[0]
        self.assertIn('"1C7395DEAAC14F889A5D41F86854F48B", 7, 0', conditions)
        self.assertIn('"542D51BDE496410FAE275169B06ABF3E", 257, 1', conditions)
        wall = (p / 'vgk100pt_voldrik.nss').read_text().split('case 257:', 1)[1].split('break;', 1)[0]
        for g, bit in (NATHANIEL[n] for n in ('granite_complete', 'granite_without_men', 'walls_funded')):
            self.assertIn(f'"{g}", {bit}, 0', wall)
        lines = json.loads((p / 'conversations.json').read_text())['ep1_epilogue.dlg']
        self.assertIn('Nathaniel managed to survive', lines[76]['text'])
        self.assertEqual(lines[76]['condition']['flag'], 264)


if __name__ == '__main__': unittest.main()
