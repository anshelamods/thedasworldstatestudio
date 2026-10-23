"""Direct DAO twelve-control expansion and source ambiguity regression tests."""
import json
from pathlib import Path
import tempfile
import unittest

from game_saves.dao import import_save, ALL_SUPPORTED
from game_saves.dao_quests import FLAGS, SUPPORTED
from game_saves.worldvault import DIRECT
from gui import EditorApp
from test_save_import import make_save
from world_profiles import Catalog

ROOT = Path(__file__).resolve().parents[1]


def quest_save(*names, completed=True, missing=(), extra=None):
    plots = {guid: [] for guid, _ in FLAGS.values() if guid not in missing}
    for name in names:
        guid, bit = FLAGS[name]
        plots.setdefault(guid, []).append(bit)
    if completed:
        guid, bit = DIRECT[2030]
        plots.setdefault(guid, []).append(bit)
    for guid, bits in (extra or {}).items(): plots.setdefault(guid, []).extend(bits)
    return make_save(plots, game='dao')


class DaoQuestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.catalog = Catalog()

    def result(self, *names, **kwargs): return import_save(quest_save(*names, **kwargs), self.catalog)

    def choices(self, *names, **kwargs):
        return {k: v for k, v in self.result(*names, **kwargs)['choices'].items() if k in SUPPORTED}

    def test_scope_empty_progress_and_missing_are_distinct(self):
        self.assertEqual(len(SUPPORTED), 12)
        self.assertEqual(len(ALL_SUPPORTED), 74)
        self.assertEqual(self.choices(completed=False), {})
        self.assertEqual(self.choices(missing={guid for guid, _ in FLAGS.values()}), {})
        result = self.result(completed=False)
        self.assertEqual(result['counts']['dao']['recovered'] + result['counts']['dao']['unresolved'], 74)
        self.assertTrue(all(e['status'] == 'needs_review' for e in result['unresolved'] if e['choice_id'] in SUPPORTED))

    def test_goldanna_meeting_request_and_no_encounter(self):
        for name in ('goldanna_calmed', 'goldanna_hardened', 'goldanna_money', 'goldanna_house_left'):
            self.assertEqual(self.choices(name, completed=False)['dao.alistair_family'], 'helped')
        self.assertNotIn('dao.alistair_family', self.choices('goldanna_wanted', completed=False))
        self.assertEqual(self.choices('goldanna_wanted')['dao.alistair_family'], 'not_helped')
        self.assertEqual(self.choices()['dao.alistair_family'], 'not_encountered')

    def test_marjolaine_both_outcomes_and_conflict(self):
        self.assertEqual(self.choices('marjolaine_killed', completed=False)['dao.leliana_past'], 'killed')
        self.assertEqual(self.choices('marjolaine_spared', completed=False)['dao.leliana_past'], 'sent_away')
        self.assertEqual(self.choices()['dao.leliana_past'], 'not_encountered')
        self.assertNotIn('dao.leliana_past', self.choices('marjolaine_killed', 'marjolaine_spared'))
        self.assertNotIn('dao.leliana_past', self.choices('marjolaine_confronted'))

    def test_oghren_current_recruitment_is_not_ever_recruited_after_removal(self):
        self.assertEqual(self.choices('oghren_recruited', completed=False)['dao.oghren_recruited'], 'recruited')
        self.assertEqual(self.choices()['dao.oghren_recruited'], 'not_recruited')
        for marker in ('oghren_left', 'oghren_killed'):
            self.assertNotIn('dao.oghren_recruited', self.choices(marker))
            self.assertNotIn('dao.oghren_recruited', self.choices(marker, 'oghren_recruited'))

    def test_felsi_awakening_resolution_is_separate_from_origins_tavern(self):
        self.assertEqual(self.choices('awakening_felsi_encouraged', completed=False)['dao.oghren_felsi'], 'reunited')
        for earlier in ('felsi_reunited', 'felsi_parted', 'felsi_failed'):
            self.assertEqual(self.choices(earlier, 'awakening_felsi_encouraged')['dao.oghren_felsi'], 'reunited')
            self.assertNotIn('dao.oghren_felsi', self.choices(earlier))
        self.assertNotIn('dao.oghren_felsi', self.choices())
        for marker in ('awakening_felsi_visited', 'awakening_felsi_resolution', 'awakening_felsi_refused'):
            self.assertNotIn('dao.oghren_felsi', self.choices(marker))

    def test_felsi_no_help_requires_explicit_awakening_records_and_completion(self):
        architect = {DIRECT[2063][0]: [DIRECT[2063][1]]}
        self.assertEqual(self.choices(extra=architect)['dao.oghren_felsi'], 'not_helped')
        self.assertNotIn('dao.oghren_felsi', self.choices(extra=architect,
            missing={FLAGS['awakening_felsi_encouraged'][0]}))
        self.assertNotIn('dao.oghren_felsi', self.choices('awakening_felsi_resolution', extra=architect))

    def test_real_grimoire_possession_and_method_need_separate_evidence(self):
        self.assertEqual(self.choices('real_grimoire_given', 'flemeth_spared')['dao.flemeth_grimoire'], 'peaceful')
        self.assertEqual(self.choices('real_grimoire_kept', 'flemeth_slain')['dao.flemeth_grimoire'], 'defeated_flemeth')
        tower_book = {FLAGS['real_grimoire_given'][0]: [0]}
        self.assertEqual(self.choices(extra=tower_book)['dao.flemeth_grimoire'], 'not_acquired')
        for names in (('flemeth_fight_started',), ('flemeth_slain',), ('flemeth_spared',),
                      ('real_grimoire_given',), ('real_grimoire_given', 'flemeth_spared', 'flemeth_slain')):
            self.assertNotIn('dao.flemeth_grimoire', self.choices(*names))

    def test_prisoner_killing_also_sets_fed_and_shared_food_is_not_a_method(self):
        self.assertEqual(self.choices('prisoner_killed', 'prisoner_key_given', 'prisoner_fed')['dao.ostagar_deserter'], 'killed')
        self.assertEqual(self.choices('prisoner_guard_bribed', 'prisoner_food_obtained', 'prisoner_fed')['dao.ostagar_deserter'], 'bought_food')
        for names in ((), ('prisoner_key_used',), ('prisoner_guard_bribed',),
                      ('prisoner_guard_bribed', 'prisoner_food_obtained'),
                      ('prisoner_fed', 'prisoner_food_obtained')):
            self.assertNotIn('dao.ostagar_deserter', self.choices(*names))
        reason = next(e['reason'] for e in self.result('prisoner_fed', 'prisoner_food_obtained')['unresolved']
                      if e['choice_id'] == 'dao.ostagar_deserter')
        self.assertIn('same food-acquisition flag', reason)

    def test_hound_actual_heal_death_and_generic_flower_delivery(self):
        self.assertEqual(self.choices('mabari_healed', completed=False)['dao.ostagar_mabari'], 'cured')
        self.assertEqual(self.choices('mabari_killed', completed=False)['dao.ostagar_mabari'], 'killed')
        self.assertEqual(self.choices()['dao.ostagar_mabari'], 'not_helped')
        self.assertNotIn('dao.ostagar_mabari', self.choices('mabari_healed', 'mabari_killed'))
        non_noble = {DIRECT[2005][0]: []}
        self.assertEqual(self.choices('mabari_flower_without_quest', extra=non_noble)['dao.ostagar_mabari'], 'cured')
        self.assertEqual(self.choices('mabari_flower_without_quest')['dao.ostagar_mabari'], 'cured')
        self.assertEqual(self.choices('mabari_flower_without_quest', completed=False)['dao.ostagar_mabari'], 'cured')
        self.assertEqual(self.choices('mabari_flower_without_quest', 'mabari_healed')['dao.ostagar_mabari'], 'cured')
        self.assertEqual(self.choices('mabari_flower_without_quest', 'mabari_killed')['dao.ostagar_mabari'], 'killed')
        self.assertNotIn('dao.ostagar_mabari', self.choices(missing={FLAGS['mabari_healed'][0]}))

    def test_flower_hand_in_is_equivalent_cure_without_requiring_origin(self):
        noble = {DIRECT[2005][0]: [DIRECT[2005][1]]}
        for origin in (noble, {DIRECT[2003][0]: [DIRECT[2003][1]]}, {}):
            for completed in (False, True):
                self.assertEqual(self.choices('mabari_flower_without_quest', completed=completed,
                                             extra=origin)['dao.ostagar_mabari'], 'cured')
        self.assertEqual(self.choices('mabari_flower_without_quest', 'mabari_killed', extra=noble)['dao.ostagar_mabari'], 'killed')
        self.assertEqual(self.choices('mabari_flower_without_quest', 'mabari_healed', extra=noble)['dao.ostagar_mabari'], 'cured')
        self.assertNotIn('dao.ostagar_mabari', self.choices('mabari_flower_without_quest', 'mabari_healed',
                                                       'mabari_killed', extra=noble))
        # Background alone, knowing about the flower, or owning Dog is not a hand-in.
        self.assertNotIn('dao.ostagar_mabari', self.choices(completed=False, extra=noble))
        self.assertNotIn('dao.ostagar_mabari', self.choices(completed=False,
            extra={DIRECT[2005][0]: [DIRECT[2005][1]], FLAGS['mabari_healed'][0]: [7, 8]}))

    def test_irving_cullen_are_separate_from_army_allegiance(self):
        self.assertEqual(self.choices('irving_alive')['dao.irving_fate'], 'alive')
        self.assertEqual(self.choices('irving_dead')['dao.irving_fate'], 'dead')
        self.assertNotIn('dao.irving_fate', self.choices('irving_alive', 'irving_dead'))
        templars = {'C232DA078A044178AA9FCBC6E537FA75': [4]}
        self.assertNotIn('dao.irving_fate', self.choices('circle_complete', extra=templars))
        self.assertEqual(self.choices('cullen_agreed', completed=False)['dao.cullen_request'], 'agreed')
        self.assertEqual(self.choices('circle_complete', extra=templars)['dao.cullen_request'], 'disagreed')
        self.assertNotIn('dao.cullen_request', self.choices(completed=False))

    def test_poison_positive_and_preserved_final_progress(self):
        self.assertEqual(self.choices('urn_poisoned', completed=False)['dao.urn_poisoned'], 'poisoned')
        self.assertEqual(self.choices('urn_complete')['dao.urn_poisoned'], 'preserved')
        self.assertNotIn('dao.urn_poisoned', self.choices('urn_complete', completed=False))
        self.assertNotIn('dao.urn_poisoned', self.choices())

    def test_dagna_distinct_outcomes_shared_completion_and_unused_failure(self):
        self.assertEqual(self.choices('dagna_left', completed=False)['dao.dagna_outcome'], 'studied')
        self.assertEqual(self.choices('dagna_left', 'dagna_refused')['dao.dagna_outcome'], 'studied')
        self.assertEqual(self.choices('dagna_refused', completed=False)['dao.dagna_outcome'], 'refused')
        self.assertEqual(self.choices()['dao.dagna_outcome'], 'not_met')
        self.assertEqual(self.choices('dagna_complete', 'circle_all_mages_dead')['dao.dagna_outcome'], 'circle_destroyed')
        for names in (('dagna_failed',), ('dagna_talked',), ('dagna_complete',),
                      ('dagna_complete', 'dagna_irving_accepted'), ('dagna_left', 'dagna_failed'),
                      ('dagna_complete', 'circle_all_mages_dead', 'dagna_irving_accepted')):
            self.assertNotIn('dao.dagna_outcome', self.choices(*names))

    def test_dagna_permission_tracks_requests_even_when_refused(self):
        for marker in ('dagna_irving_accepted', 'dagna_greagoir_refused'):
            self.assertEqual(self.choices(marker, completed=False)['dao.dagna_permission'], 'requested')
        self.assertEqual(self.choices()['dao.dagna_permission'], 'not_requested')
        self.assertNotIn('dao.dagna_permission', self.choices(completed=False))
        self.assertNotIn('dao.dagna_permission', self.choices(missing={FLAGS['dagna_irving_accepted'][0]}))

    def test_existing_dagna_is_protected_or_replaced_only_after_review(self):
        with tempfile.TemporaryDirectory() as temp:
            app = EditorApp(Path(temp) / 'profiles', Path(temp) / 'exports')
            target = app.store.create('Existing', mode='experimental', choices={
                'dao.dagna_outcome': 'stayed', 'da2.hawke_romance': 'anders'})
            raw = quest_save('dagna_left', 'dagna_irving_accepted', 'oghren_recruited')
            for policy, expected in (('missing', 'stayed'), ('replace', 'studied')):
                review = app.save_imports.preview(raw, game='dao')
                plan = app.save_imports.plan(dict(import_id=review['import_id'], target_profile_id=target.profile_id,
                    target_revision=target.revision, policy=policy))
                self.assertEqual(app.store.load(target.profile_id), target)
                saved = app.save_imports.commit(dict(import_id=plan['import_id'], name=target.name))
                self.assertEqual(saved.choices['dao.dagna_outcome'], expected)
                self.assertEqual(saved.choices['da2.hawke_romance'], 'anders')
                target = saved

    def test_literal_source_anchors_for_ambiguous_flags(self):
        source = ROOT / 'assessment/output/dao-import/batch2'
        plots = {p['guid']: {f['id']: f['name'] for f in p['flags']} for p in json.loads((source / 'plots.json').read_text())}
        family = ROOT / 'assessment/output/dao-import/felsi'
        plots.update({p['guid']: {f['id']: f['name'] for f in p['flags']}
                      for p in json.loads((family / 'plots.json').read_text())})
        for name,(guid,bit) in FLAGS.items():
            with self.subTest(name=name): self.assertIn(bit, plots[guid])
        self.assertEqual(plots[FLAGS['flemeth_slain'][0]][1], 'COD_CHA_FLEMETH_SLAIN')
        convos = json.loads((source / 'conversations.json').read_text(encoding='utf8'))
        self.assertEqual(convos['pre100_guard.dlg'][13]['action']['flag'], 7)
        self.assertEqual(convos['pre100_guard.dlg'][15]['action']['flag'], 7)
        acquisition = (source / 'preev_item_acquired.nss').read_text()
        self.assertIn('tag == "pre100im_food"', acquisition)
        self.assertIn('"F0CCF894E7F844A99BDF263D6DBB618A", 7, 1, 0', acquisition)
        self.assertEqual(convos['orz200_dagna.dlg'][97]['condition']['flag'], 12)
        self.assertEqual(convos['orz200_dagna.dlg'][97]['action']['flag'], 2)
        self.assertEqual(convos['cir240_irving.dlg'][16]['action']['flag'], 7)
        self.assertEqual(convos['cir200_greagoir.dlg'][262]['action']['flag'], 14)
        awakening = json.loads((family / 'conversations.json').read_text(encoding='utf-8'))
        action = awakening['gxa000_oghren.dlg'][42]['action']
        self.assertEqual((action['guid'], action['flag']), FLAGS['awakening_felsi_encouraged'])
        self.assertEqual(plots[action['guid']][action['flag']], 'COD_CHA_OGHREN_ENCOURAGED_TO_BE_A_FATHER')


if __name__ == '__main__': unittest.main()
