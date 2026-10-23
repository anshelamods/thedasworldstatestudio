"""Act I terminal/history evidence and DAO-in-DA2 isolation/regression checks."""
import json
from pathlib import Path
import unittest

from game_saves.da2 import ACT, Snapshot, import_save
from game_saves import da2_act1 as a
from game_saves.gff import SaveFormatError, SaveReader
from game_saves.worldvault import DIRECT, DaoHistory
from test_save_import import make_save
from world_profiles import Catalog
from world_profiles.compiler import compile_profile


class ImportBatch2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.catalog = Catalog()

    def result(self, plots=None, **kwargs):
        return import_save(make_save({ACT: [0, 2, 4], **(plots or {})}, **kwargs), self.catalog)

    def test_every_act1_answer_has_positive_source_evidence(self):
        cases = [
            ('feynriel_destination', {a.WAYWARD: [3]}, (), 'circle'),
            ('feynriel_destination', {a.WAYWARD: [4]}, (), 'dalish'),
            ('danzig_fate', {a.WAYWARD: [51]}, (), 'killed'),
            ('danzig_fate', {a.WAYWARD: [40]}, (), 'killed'),
            ('danzig_fate', {a.WAYWARD: [30]}, (), 'not_killed'),
            ('idunna_fate', {a.ENEMIES: [7]}, (), 'killed'),
            ('idunna_fate', {a.TOMES: [12]}, (), 'alive'),
            ('idunna_fate', {}, (6084875,), 'killed'),
            ('idunna_fate', {}, (6084881,), 'alive'),
            ('saemus_rescue', {a.SAEMUS: [0]}, (), 'returned'),
            ('saemus_rescue', {a.SAEMUS: [8]}, (), 'not_returned'),
            ('ginnis_fate', {a.SAEMUS: [4]}, (), 'dead'),
            ('ginnis_fate', {a.SAEMUS: [8]}, (), 'alive'),
            ('ghyslain_truth', {a.GHYSLAIN: [7]}, (6104804,), 'told'),
            ('ghyslain_truth', {a.GHYSLAIN: [7]}, (6104821,), 'concealed'),
            ('ghyslain_truth', {a.GHYSLAIN: [17]}, (), 'not_sought'),
            ('thrask_blackmail', {a.WAYWARD: [38]}, (), 'blackmailed'),
            ('thrask_blackmail', {a.WAYWARD: [37]}, (), 'not_blackmailed'),
            ('ketojan_fate', {a.KETOJAN: [17, 18]}, (), 'handed_over'),
            ('ketojan_fate', {a.KETOJAN: [18, 21]}, (), 'defended'),
            ('martin_cargo', {a.MARTIN: [1]}, (), 'returned'),
            ('martin_cargo', {a.MARTIN: [24]}, (), 'not_returned'),
            ('kelder_fate', {a.KELDER: [4, 5]}, (), 'killed'),
            ('kelder_fate', {a.KELDER: [5]}, (), 'not_killed'),
            ('bone_pit_miners', {a.MINERS: [7]}, (), 'solved'),
            ('bone_pit_miners', {a.MINERS: [11]}, (), 'not_solved'),
            ('keran_templars', {a.ENEMIES: [15]}, (), 'reinstated'),
            ('keran_templars', {a.ENEMIES: [16]}, (), 'expelled'),
            ('act1_templars', {a.MERCY: [13, 14, 25]}, (), 'fought'),
            ('act1_templars', {a.MERCY: [13, 19]}, (), 'persuaded'),
            ('act1_templars', {a.MERCY: [15]}, (), 'mages_handed_over'),
            ('karras_fate', {a.MERCY: [13, 14, 25]}, (), 'killed'),
            ('karras_fate', {a.MERCY: [15]}, (), 'not_killed'),
        ]
        self.assertEqual({'da2.' + case[0] for case in cases}, a.SUPPORTED)
        for key, plots, seen, expected in cases:
            with self.subTest(key=key, answer=expected):
                self.assertEqual(self.result(plots, seen=seen)['choices']['da2.' + key], expected)

    def test_objectives_and_battle_starts_never_become_completed_outcomes(self):
        result = self.result({a.MERCY: [7, 8, 9, 13, 14], a.WAYWARD: [29], a.SAEMUS: [9],
                              a.GHYSLAIN: [1, 3, 7, 17], a.MARTIN: [0, 8]})
        for key in ('act1_templars', 'karras_fate', 'danzig_fate', 'ginnis_fate', 'ghyslain_truth', 'martin_cargo'):
            self.assertNotIn('da2.' + key, result['choices'])

    def test_quest_completion_alone_does_not_identify_ghyslain_truth(self):
        r = self.result({a.GHYSLAIN: [7]})
        self.assertNotIn('da2.ghyslain_truth', r['choices'])
        self.assertIn('saved dialogue', next(e for e in r['unresolved'] if e['choice_id'] == 'da2.ghyslain_truth')['reason'])

    def test_contradictory_plot_or_dialogue_outcomes_stay_unresolved(self):
        r = self.result({a.KETOJAN: [17, 21], a.MERCY: [14, 25, 15], a.THRASK: [1, 2]}, seen=(6104804, 6104821))
        for key in ('ketojan_fate', 'act1_templars', 'thrask_blackmail', 'ghyslain_truth'):
            self.assertNotIn('da2.' + key, r['choices'])

    def test_unresolved_counts_cover_both_games_and_exclude_retired_controls(self):
        result = self.result()
        p = json.loads((Path(__file__).parent / 'gui/presentation.json').read_text())
        self.assertEqual({e['choice_id'] for e in result['recognized'] + result['unresolved']}, set(p))
        self.assertEqual(result['counts']['dao']['recovered'], 0)
        self.assertEqual(result['counts']['dao']['unresolved'], 74)
        states = {e['choice_id']: e['status'] for e in result['unresolved']}
        self.assertEqual(states['da2.saemus_rescue'], 'needs_review')
        self.assertEqual(states['da2.aveline_marriage'], 'needs_review')
        self.assertEqual(states['da2.legacy_side'], 'needs_review')

    def dao(self, flags=None, ints=None, plots=None):
        return self.result(dao_bools=flags, dao_ints=ints, dao_plots=plots)

    def complete(self, **overrides):
        flags = {key: 0 for key in DIRECT}
        flags.update({2089: 1, 2104: 0, **{int(k): v for k, v in overrides.items()}})
        return flags

    def test_direct_definitions_match_the_independent_worldvault_gda_audit(self):
        path = Path(__file__).parents[1] / 'assessment/output/save-import-survey/worldvault-audit.json'
        source = json.loads(path.read_text())
        self.assertEqual(DIRECT, {r['vault_id']: (source['plot_guids'][r['plot']], r['bit']) for r in source['direct_flags']})

    def test_spoken_line_references_match_the_original_conversation_resources(self):
        path = Path(__file__).parents[1] / 'assessment/output/save-import-survey/batch2/conversations.json'
        source = json.loads(path.read_text())
        for name, lines in [('ser120_ghyslain.cnv', {20: 6104804, 27: 6120630, 29: 6104821, 34: 6104832}),
                            ('mag121_idunna.cnv', {140: 6084245, 147: 6084875, 151: 6084881})]:
            for index, ref in lines.items():
                self.assertEqual(source[name]['lines'][index]['strref'], ref)

    def test_normalized_worldvault_values_override_raw_plots_without_crossing_games(self):
        bhelen_guid = DIRECT[2018][0]
        r = self.result({bhelen_guid: [7]}, dao_plots={bhelen_guid: [7]}, dao_bools={2018: 0, 2019: 1})
        self.assertEqual(r['choices']['dao.orzammar_ruler'], 'harrowmont')
        r = self.result({bhelen_guid: [7]})
        self.assertNotIn('dao.orzammar_ruler', r['choices'])
        r = self.dao(plots={bhelen_guid: [8]})
        self.assertEqual(r['choices']['dao.orzammar_ruler'], 'harrowmont')

    def test_missing_values_remain_unknown_and_do_not_create_negative_history(self):
        r = self.dao(flags={2000: 0})
        self.assertFalse(any(k.startswith('dao.') for k in r['choices']))
        v = DaoHistory(SaveReader(make_save(dao_bools={2037: 0})))
        self.assertIs(v.flag(2037), False)
        self.assertIsNone(v.flag(2039))
        self.assertNotIn('dao.dog_recruited', self.dao(flags={2037: 0})['choices'])

    def test_dao_hero_uses_dao_race_enum_not_da2_race_and_does_not_guess_class(self):
        r = self.dao(flags={2000: 1}, ints={1000: 2, 1001: 2, 1045: 2})
        self.assertEqual(r['choices']['dao.warden_identity'], 'female_elven_mage')
        self.assertEqual(r['choices']['dao.warden_class'], 'mage')
        r = self.dao(flags={2005: 1}, ints={1000: 1, 1001: 3})
        self.assertEqual(r['choices']['dao.warden_identity'], 'male_human_noble')
        self.assertNotIn('dao.warden_class', r['choices'])
        r = self.dao(flags={2000: 1}, ints={1000: 2, 1001: 6})
        self.assertNotIn('dao.warden_identity', r['choices'])

    def test_ritual_parent_killer_and_survival_are_inferred_together(self):
        for parent, key in [('warden', 2102), ('alistair', 2100), ('loghain', 2101)]:
            flags = self.complete(); flags.update({key: 1, 2104: 1, 2030: 1})
            r = self.dao(flags=flags)
            self.assertEqual(r['choices']['dao.morrigan_child'], 'old_god_' + parent)
            self.assertEqual(r['choices']['dao.warden_fate'], 'alive')
        flags = self.complete(); flags[2030] = 1
        r = self.dao(flags=flags)
        self.assertEqual(r['choices']['dao.warden_fate'], 'sacrificed')
        self.assertEqual(r['choices']['dao.morrigan_child'], 'none')
        flags[2047] = 1
        r = self.dao(flags=flags, ints={1000: 1})
        self.assertEqual(r['choices']['dao.morrigan_child'], 'human_warden')

    def test_inconsistent_ritual_and_missing_ritual_do_not_guess_survival(self):
        r = self.dao(flags={2030: 1})
        self.assertNotIn('dao.warden_fate', r['choices'])
        flags = self.complete(); flags.update({2100: 1, 2030: 1, 2104: 0})
        r = self.dao(flags=flags)
        self.assertNotIn('dao.morrigan_child', r['choices'])
        self.assertNotIn('dao.warden_fate', r['choices'])

    def test_all_five_ferelden_arrangements_and_loghain_execution_uncertainty(self):
        for key, answer in [(2020, 'alistair_anora'), (2026, 'alistair_warden'),
                             (2024, 'anora_warden'), (2021, 'alistair_alone'), (2027, 'anora_alone')]:
            flags = self.complete(); flags[key] = 1
            self.assertEqual(self.dao(flags=flags)['choices']['dao.ferelden_ruler'], answer)
        flags = self.complete(); flags[2025] = 1
        r = self.dao(flags=flags)
        self.assertNotIn('dao.loghain_fate', r['choices'])
        reason = next(e['reason'] for e in r['unresolved'] if e['choice_id'] == 'dao.loghain_fate')
        self.assertIn('executioner', reason)
        flags.update({2029: 1, 2097: 1})
        self.assertEqual(self.dao(flags=flags)['choices']['dao.loghain_fate'], 'sacrificed')

    def test_companion_history_and_dlc_need_their_own_positive_progress(self):
        flags = {2065: 1, 2084: 0}
        self.assertNotIn('dao.nathaniel_fate', self.dao(flags=flags)['choices'])
        flags[2091] = 1
        self.assertEqual(self.dao(flags=flags)['choices']['dao.nathaniel_fate'], 'alive')
        flags[2084] = 1
        self.assertEqual(self.dao(flags=flags)['choices']['dao.nathaniel_fate'], 'dead')
        r = self.dao(flags={2069: 1, 2067: 1, 2068: 0, 2071: 1, 2078: 1})
        self.assertEqual(r['choices']['dao.avernus_fate'], 'ethical_research')
        self.assertEqual(r['choices']['dao.witch_hunt'], 'did_not_follow')
        self.assertNotIn('dao.power_of_blood', r['choices'])

    def test_the_elves_alliance_flag_does_not_override_peace(self):
        r = self.dao(flags={2015: 1, 2017: 1})
        self.assertEqual(r['choices']['dao.nature_outcome'], 'peace')
        r = self.dao(flags={2015: 1, 2016: 1, 2017: 1})
        self.assertNotIn('dao.nature_outcome', r['choices'])

    def test_connor_bargain_requires_no_intimidation_and_isolde_ritual_is_separate(self):
        r = self.dao(flags={2007: 1, 2011: 1, 2010: 0, 2087: 1})
        self.assertEqual(r['choices']['dao.connor_fate'], 'possessed')
        self.assertEqual(r['choices']['dao.isolde_fate'], 'alive')
        r = self.dao(flags={2007: 1, 2011: 1, 2010: 1})
        self.assertEqual(r['choices']['dao.connor_fate'], 'freed')
        r = self.dao(flags={2007: 1, 2011: 1})
        self.assertNotIn('dao.connor_fate', r['choices'])
        r = self.dao(flags={2007: 1, 2006: 1})
        self.assertNotIn('dao.connor_fate', r['choices'])

    def test_landsmeet_role_without_final_survival_evidence_is_not_an_alive_fate(self):
        r = self.dao(flags={2089: 1, 2021: 1, 2097: 1})
        self.assertNotIn('dao.alistair_fate', r['choices'])
        self.assertNotIn('dao.loghain_fate', r['choices'])
        flags = self.complete(); flags.update({2023: 1, 2028: 1})
        self.assertNotIn('dao.alistair_fate', self.dao(flags=flags)['choices'])

    def test_invalid_duplicate_worldvault_records_and_boolean_values_are_rejected(self):
        with self.assertRaises(SaveFormatError):
            self.dao(flags={2037: 2})
        raw = bytearray(make_save(dao_bools={2037: 1, 2039: 1}))
        r = SaveReader(bytes(raw)); second = r.get((16024, 17607))[1]
        import struct
        struct.pack_into('<I', raw, second.offset, 2037)
        with self.assertRaises(SaveFormatError): DaoHistory(SaveReader(bytes(raw)))

    def test_imported_choices_compile_without_repair_and_unknown_history_stays_inherited(self):
        flags = self.complete(); flags.update({2005: 1, 2018: 1, 2012: 1})
        r = self.dao(flags=flags, ints={1000: 2, 1001: 3})
        profile = self.catalog.create('Mixed imported history', choices=r['choices'], mode='experimental')
        result = compile_profile(profile, catalog=self.catalog)
        self.assertEqual(result.effective_values['dao_orzammar_ruler'], 1)
        self.assertEqual(result.effective_values['dao_warden_mf'], 1)
        self.assertNotIn('dao_warden_class', {name for key in r['choices'] for name in self.catalog.choices[key]['answers'][r['choices'][key]]['export_values']})


if __name__ == '__main__': unittest.main()
