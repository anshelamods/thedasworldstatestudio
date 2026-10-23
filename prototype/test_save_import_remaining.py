"""DA2 final twenty controls: source distinctions, stage gates and conflicts."""
import json
from pathlib import Path
import unittest

from game_saves.da2 import import_save, SUPPORTED as ALL_SUPPORTED
from game_saves.da2_remaining import *
from test_save_import import make_save
from world_profiles import Catalog

ROOT = Path(__file__).resolve().parents[1]


def synthetic_remaining_cases():
    """Generated source-only branches; no personal save bytes or gameplay claim."""
    first = {ACT: [4, 5, 6, 7], FINALE: [1], PROLOGUE: [59],
        CROWS: [1, 6], GAMLEN: [18, 19], COLD: [43], EMILE: [3],
        SUSPECT: [3], REMAINS: [22], JAVARIS: [5, 16], CARGO: [46],
        DRAGON: [28], GOLD: [8, 12, 19], CLIFF: [2], VARNELL: [11], PETRICE: [14],
        LEGACY: [26, 42], MALCOLM: [2], ASSASSIN: [43], TALLIS: [5, 6]}
    second = {ACT: [4, 5, 6, 7], FINALE: [0], PROLOGUE: [69],
        CROWS: [2], GAMLEN: [], COLD: [42, 15], EMILE: [2],
        SUSPECT: [3], REMAINS: [23], JAVARIS: [5], CARGO: [12],
        DRAGON: [26], GOLD: [7, 13, 19], CLIFF: [1], VARNELL: [5, 6], PETRICE: [5, 7],
        LEGACY: [25, 26], MALCOLM: [14], ASSASSIN: [], TALLIS: []}
    return [('Synthetic remaining A', make_save(first, seen=[6041704]), {
        'legacy_played': 'played', 'legacy_side': 'janeka', 'murder_of_crows': 'offered_help',
        'zevran_freed': 'not_freed', 'gamlen_treasure': 'returned_gem', 'malcolm_will': 'found',
        'conspirators': 'meredith', 'emile_fate': 'circle', 'keran_fate': 'templars',
        'bone_pit_dragon': 'not_killed', 'gascard_fate': 'killed', 'javaris_fate': 'dead',
        'hubert_caravans': 'not_discovered', 'fools_gold': 'iwan', 'cliff_raiders': 'with_guards',
        'varnell_side': 'sided', 'petrice_side': 'sided', 'tallis_kiss': 'kissed',
        'prologue_allegiance': 'mercenaries'}),
        ('Synthetic remaining B', make_save(second), {
        'legacy_played': 'played', 'legacy_side': 'larius', 'murder_of_crows': 'not_helped',
        'zevran_freed': 'not_encountered', 'gamlen_treasure': 'not_helped', 'malcolm_will': 'not_found',
        'conspirators': 'orsino', 'emile_fate': 'freed', 'keran_fate': 'killed',
        'bone_pit_dragon': 'killed', 'gascard_fate': 'not_killed', 'javaris_fate': 'alive',
        'hubert_caravans': 'discovered', 'fools_gold': 'merin', 'cliff_raiders': 'alone',
        'varnell_side': 'not_sided', 'petrice_side': 'not_sided', 'tallis_kiss': 'not_kissed',
        'tallis_reaction': 'never_met', 'prologue_allegiance': 'smugglers'})]


class RemainingImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.catalog = Catalog()
    def result(self, plots=None, **kwargs): return import_save(make_save({ACT: [], **(plots or {})}, **kwargs), self.catalog)
    def choices(self, plots=None, **kwargs):
        return {k: v for k, v in self.result(plots, **kwargs)['choices'].items() if k in SUPPORTED}

    def test_scope_missing_and_empty_early_histories(self):
        self.assertEqual(len(SUPPORTED), 20)
        self.assertEqual(len(ALL_SUPPORTED), 63)
        self.assertFalse(self.choices())
        self.assertFalse(self.choices({ACT: [5]}))
        self.assertTrue(all(r['status'] == 'needs_review' for r in self.result()['unresolved'] if r['choice_id'].startswith('da2.')))

    def test_prologue_requires_joining_not_initial_agreement(self):
        for f, a in ((69, 'smugglers'), (59, 'mercenaries')):
            self.assertEqual(self.choices({PROLOGUE: [f]})['da2.prologue_allegiance'], a)
        self.assertNotIn('da2.prologue_allegiance', self.choices({PROLOGUE: [35, 38, 54]}))
        self.assertNotIn('da2.prologue_allegiance', self.choices({PROLOGUE: [59, 69]}))

    def test_crows_declined_empty_and_offered_are_distinct(self):
        self.assertEqual(self.choices({CROWS: [2]})['da2.murder_of_crows'], 'not_helped')
        self.assertEqual(self.choices({CROWS: [1]})['da2.murder_of_crows'], 'offered_help')
        self.assertNotIn('da2.murder_of_crows', self.choices({ACT: [5], CROWS: []}))
        self.assertEqual(self.choices({ACT: [5], CROWS: []}, dao_bools={2106: 1})['da2.murder_of_crows'], 'not_sought')
        alive = {2089: 1, 2039: 1, 2050: 0, 2105: 0, 2106: 0}
        self.assertEqual(self.choices({ACT: [5], CROWS: []}, dao_bools=alive)['da2.murder_of_crows'], 'not_helped')
        self.assertNotIn('da2.murder_of_crows', self.choices({CROWS: []}))
        self.assertNotIn('da2.murder_of_crows', self.choices({CROWS: [1, 2]}))

    def test_zevran_initial_disposition_not_later_battle_or_reward(self):
        self.assertEqual(self.choices({CROWS: [7, 8, 10, 11]})['da2.zevran_freed'], 'freed')
        self.assertEqual(self.choices({CROWS: [6, 8, 9, 11]})['da2.zevran_freed'], 'not_freed')
        self.assertNotIn('da2.zevran_freed', self.choices({CROWS: [1, 3]}))
        self.assertNotIn('da2.zevran_freed', self.choices({CROWS: [6, 7]}))
        self.assertEqual(self.choices({CROWS: [2]})['da2.zevran_freed'], 'not_encountered')
        self.assertEqual(self.choices({ACT: [5], CROWS: [1, 23]})['da2.zevran_freed'], 'not_encountered')

    def test_gamlen_completion_and_route_not_gem_possession_or_quest_start(self):
        for f, a in ((17, 'reunited'), (18, 'returned_gem')):
            self.assertEqual(self.choices({GAMLEN: [f, 19]})['da2.gamlen_treasure'], a)
            self.assertNotIn('da2.gamlen_treasure', self.choices({GAMLEN: [f]}))
        self.assertEqual(self.choices({ACT: [5], GAMLEN: [0, 2]})['da2.gamlen_treasure'], 'not_helped')
        self.assertNotIn('da2.gamlen_treasure', self.choices({GAMLEN: [17, 18, 19]}))

    def test_conspirators_final_report_not_initial_quest_giver(self):
        for f, a in ((42, 'orsino'), (43, 'meredith')):
            self.assertEqual(self.choices({COLD: [f]})['da2.conspirators'], a)
        self.assertNotIn('da2.conspirators', self.choices({COLD: [5, 40]}))
        self.assertNotIn('da2.conspirators', self.choices({COLD: [42, 43]}))

    def test_emile_explicit_outcomes_not_a_night_in_the_tavern(self):
        self.assertEqual(self.choices({EMILE: [2]})['da2.emile_fate'], 'freed')
        self.assertEqual(self.choices({EMILE: [3]})['da2.emile_fate'], 'circle')
        self.assertNotIn('da2.emile_fate', self.choices({EMILE: [0, 1, 5]}))
        self.assertNotIn('da2.emile_fate', self.choices({EMILE: [2, 3]}))

    def test_keran_shared_release_flag_and_kill_threat_do_not_invent_fate(self):
        self.assertNotIn('da2.keran_fate', self.choices({COLD: [12, 13, 14]}))
        self.assertNotIn('da2.keran_fate', self.choices(seen=[6041685]))
        self.assertEqual(self.choices({COLD: [14]}, seen=[6041588])['da2.keran_fate'], 'released')
        self.assertEqual(self.choices({COLD: [14]}, seen=[6041704])['da2.keran_fate'], 'templars')
        self.assertEqual(self.choices({COLD: [15]})['da2.keran_fate'], 'killed')
        self.assertNotIn('da2.keran_fate', self.choices({COLD: [15]}, seen=[6041588]))

    def test_later_act2_gascard_execution_supersedes_earlier_mercy(self):
        self.assertEqual(self.choices({SUSPECT: [3], REMAINS: [22]})['da2.gascard_fate'], 'killed')
        self.assertEqual(self.choices({SUSPECT: [6]})['da2.gascard_fate'], 'killed')
        self.assertEqual(self.choices({REMAINS: [23]})['da2.gascard_fate'], 'not_killed')
        self.assertNotIn('da2.gascard_fate', self.choices({SUSPECT: [3], REMAINS: []}))
        self.assertNotIn('da2.gascard_fate', self.choices({REMAINS: [6, 20]}))
        self.assertEqual(self.choices({ACT: [4], SUSPECT: [], REMAINS: [6, 29]})['da2.gascard_fate'], 'killed')
        self.assertEqual(self.choices({ACT: [4], SUSPECT: [], REMAINS: [7, 29]})['da2.gascard_fate'], 'not_killed')

    def test_javaris_and_looter_require_resolved_encounter_or_identity(self):
        self.assertEqual(self.choices({JAVARIS: [5]})['da2.javaris_fate'], 'alive')
        self.assertEqual(self.choices({JAVARIS: [5, 16]})['da2.javaris_fate'], 'dead')
        self.assertNotIn('da2.javaris_fate', self.choices({JAVARIS: [4]}))
        self.assertEqual(self.choices({CARGO: [11]})['da2.hubert_caravans'], 'discovered')
        self.assertNotIn('da2.hubert_caravans', self.choices({CARGO: [4, 5, 8]}))
        self.assertEqual(self.choices({CARGO: [46]})['da2.hubert_caravans'], 'not_discovered')
        self.assertNotIn('da2.hubert_caravans', self.choices({ACT: [5]}))

    def test_dragon_profile_only_not_initial_reveal_or_old_labor_return(self):
        self.assertEqual(self.choices({DRAGON: [26]})['da2.bone_pit_dragon'], 'killed')
        self.assertEqual(self.choices({DRAGON: [28]})['da2.bone_pit_dragon'], 'not_killed')
        for f in (3, 20, 24, 25, 27, 29): self.assertNotIn('da2.bone_pit_dragon', self.choices({DRAGON: [f]}))
        self.assertNotIn('da2.bone_pit_dragon', self.choices({DRAGON: [28, 26]}))
        self.assertFalse(self.catalog.choices['da2.bone_pit_dragon']['answers']['killed'].get('export_values'))

    def test_fools_gold_both_saved_brothers_and_incomplete_or_unrepresentable(self):
        self.assertEqual(self.choices({GOLD: [8, 12, 19]})['da2.fools_gold'], 'iwan')
        self.assertEqual(self.choices({GOLD: [7, 13, 19]})['da2.fools_gold'], 'merin')
        self.assertEqual(self.choices({ACT: [4], GOLD: []})['da2.fools_gold'], 'not_encountered')
        for fs in ([0], [1], [8], [7], [23], [7, 8, 12, 13, 19]):
            self.assertNotIn('da2.fools_gold', self.choices({ACT: [4], GOLD: fs}))

    def test_cliff_alone_can_follow_together_proposal_and_retreat_is_not_invented(self):
        self.assertEqual(self.choices({CLIFF: [1, 2, 4, 5, 6]})['da2.cliff_raiders'], 'alone')
        self.assertEqual(self.choices({CLIFF: [2]})['da2.cliff_raiders'], 'with_guards')
        self.assertEqual(self.choices({CLIFF: [12]})['da2.cliff_raiders'], 'abandoned')
        self.assertEqual(self.choices({ACT: [4], CLIFF: [15]})['da2.cliff_raiders'], 'abandoned')
        self.assertNotIn('da2.cliff_raiders', self.choices({CLIFF: [3]}))
        self.assertNotIn('da2.cliff_raiders', self.choices({CLIFF: [15]}))
        self.assertNotIn('da2.cliff_raiders', self.choices({CLIFF: [0, 9]}))

    def test_varnell_betrayal_does_not_erase_endorsing_him(self):
        self.assertEqual(self.choices({VARNELL: [11]})['da2.varnell_side'], 'sided')
        self.assertEqual(self.choices({VARNELL: [5, 6]})['da2.varnell_side'], 'not_sided')
        self.assertEqual(self.choices({VARNELL: [5, 6, 11]})['da2.varnell_side'], 'sided')
        self.assertNotIn('da2.varnell_side', self.choices({VARNELL: [5]}))

    def test_petrice_final_alignment_not_earlier_offer(self):
        self.assertEqual(self.choices({PETRICE: [14]})['da2.petrice_side'], 'sided')
        self.assertEqual(self.choices({PETRICE: [5, 7]})['da2.petrice_side'], 'not_sided')
        self.assertNotIn('da2.petrice_side', self.choices({PETRICE: [14, 7]}))
        self.assertNotIn('da2.petrice_side', self.choices({PETRICE: [9]}))

    def test_legacy_availability_is_not_played_and_initial_side_can_change(self):
        self.assertEqual(self.choices({LEGACY: [1]})['da2.legacy_played'], 'played')
        self.assertNotIn('da2.legacy_side', self.choices({LEGACY: [15, 18]}))
        self.assertEqual(self.choices({LEGACY: [15, 18, 42]})['da2.legacy_side'], 'janeka')
        self.assertEqual(self.choices({LEGACY: [25]})['da2.legacy_side'], 'larius')
        self.assertNotIn('da2.legacy_side', self.choices({LEGACY: [25, 42]}))
        self.assertEqual(self.choices({ACT: [5], LEGACY: []})['da2.legacy_played'], 'not_played')
        self.assertNotIn('da2.legacy_played', self.choices({LEGACY: []}))

    def test_malcolm_will_needs_completion_not_echoes_or_killed_demons(self):
        self.assertEqual(self.choices({MALCOLM: [2]})['da2.malcolm_will'], 'found')
        self.assertNotIn('da2.malcolm_will', self.choices({MALCOLM: [0, 1, 4, 5, 6]}))
        self.assertEqual(self.choices({MALCOLM: [14]})['da2.malcolm_will'], 'not_found')
        self.assertNotIn('da2.malcolm_will', self.choices({LEGACY: [26]}))
        self.assertEqual(self.choices({LEGACY: [26], MALCOLM: []})['da2.malcolm_will'], 'not_found')

    def test_tallis_kiss_is_not_flirt_and_unknown_reaction_is_not_guessed(self):
        self.assertNotIn('da2.tallis_kiss', self.choices({TALLIS: [0]}))
        self.assertEqual(self.choices({TALLIS: [5]})['da2.tallis_kiss'], 'kissed')
        self.assertEqual(self.choices({TALLIS: [6]})['da2.tallis_kiss'], 'not_kissed')
        self.assertNotIn('da2.tallis_reaction', self.choices({TALLIS: [0, 5, 6], ASSASSIN: [43]}))
        self.assertEqual(self.choices({ACT: [5], TALLIS: [], ASSASSIN: []})['da2.tallis_reaction'], 'never_met')
        self.assertNotIn('da2.tallis_reaction', self.choices({ACT: [5], ASSASSIN: []}))
        self.assertNotIn('da2.tallis_reaction', self.choices({ACT: [5], ASSASSIN: [], TALLIS: []}, party=[('eye00fl_tallis', 122, 2)]))

    def test_tallis_completed_routes_do_not_require_specific_final_dialogue(self):
        done = {ASSASSIN: [43], TALLIS: [6]}
        for flags in ([10], [13], [10, 6, 7, 9]):
            self.assertEqual(self.choices({**done, DUNGEON: flags})['da2.tallis_reaction'], 'not_angry')
        for flags in ([11, 12], [10, 11, 12], [11, 12, 6, 7]):
            self.assertEqual(self.choices({**done, DUNGEON: flags})['da2.tallis_reaction'], 'angry')
        # Reused personality/Qun flags and incomplete route data prove neither.
        for flags in ([], [6], [7], [9], [11], [12], [10, 11], [10, 12]):
            self.assertNotIn('da2.tallis_reaction', self.choices({**done, DUNGEON: flags}))
        self.assertNotIn('da2.tallis_reaction', self.choices(done))

    def test_tallis_route_before_farewell_is_not_a_final_outcome(self):
        for flags in ([10], [11, 12]):
            for earlier in ({ASSASSIN: [1], TALLIS: [1]},
                            {ASSASSIN: [43], TALLIS: [1]},
                            {ASSASSIN: [1], TALLIS: [6]}):
                self.assertNotIn('da2.tallis_reaction', self.choices({**earlier, DUNGEON: flags}))

    def test_original_dialogue_and_export_script_anchors(self):
        root = ROOT / 'assessment/output/save-import-survey/remaining'
        c = json.loads((root / 'conversations.json').read_text('utf8'))
        keran = c['mag311_keran.cnv']['lines']
        self.assertIn(keran[95]['strref'], KERAN_RELEASED)
        self.assertIn(keran[127]['strref'], KERAN_TEMPLARS)
        self.assertEqual(keran[146]['action']['flag'], 14)
        self.assertEqual(keran[147]['action']['flag'], 13)
        for node in (703, 709): self.assertEqual(c['eye400_tallis_dungeon.cnv']['lines'][node]['action'], dict(guid=TALLIS, flag=5, value=255))
        script = (root / 'drk000_world_state.nss').read_text()
        for guid, bit in ((LEGACY, 25), (LEGACY, 42), (MALCOLM, 2)):
            self.assertIn(f'"{guid}", {bit}', script)
        unavailable = [r for r in self.catalog.story_rules['rules']
            if r['target'] == 'da2_act3_murder_of_crows' and r['value'] == 0]
        self.assertTrue(unavailable)
        self.assertTrue(all(any(d['question'] == 'dao_zevran_alive' and d['min'] == d['max'] == 0
            for d in r['dependencies']) for r in unavailable))

    def test_combined_alternate_outcomes_with_modded_siblings(self):
        for name, payload, expected in synthetic_remaining_cases():
            result = import_save(payload, self.catalog)
            self.assertEqual({k: v for k, v in result['choices'].items() if k in SUPPORTED},
                {'da2.' + k: v for k, v in expected.items()}, name)
            self.assertEqual(result['choices']['da2.bethany_fate'], 'warden')
            self.assertEqual(result['choices']['da2.carver_fate'], 'warden')


if __name__ == '__main__': unittest.main()
