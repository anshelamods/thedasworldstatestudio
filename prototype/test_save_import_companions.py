"""Companion import outcomes, terminal gates and misleading historical markers."""
import json
from pathlib import Path
import unittest

from game_saves.da2 import ACT, FINALE, import_save
from game_saves.da2_companions import (
    MERRILL, NEW_PATH, LONG_ROAD, ANDERS_APPROVED, ANDERS_DISAPPROVED,
    MIRROR_KEPT, MIRROR_DESTROYED, SUPPORTED)
from test_save_import import make_save
from world_profiles import Catalog
from world_profiles.compiler import compile_profile


class CompanionImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def result(self, plots=None, **kwargs):
        return import_save(make_save({ACT: [], **(plots or {})}, **kwargs), self.catalog)

    def choices(self, plots=None, **kwargs):
        return self.result(plots, **kwargs)['choices']

    def test_mirror_destruction_uses_shattered_prop_not_shared_cleanup(self):
        for plots in ({MERRILL: [26]}, {NEW_PATH: [4]}):
            self.assertEqual(self.choices(plots)['da2.merrill_eluvian'], 'destroyed')
        self.assertNotIn('da2.merrill_eluvian', self.choices({MERRILL: [27]}))
        # Both endings hide the whole prop. Jenna records kept dialogue and 27.
        self.assertEqual(self.choices({MERRILL: [27]}, seen=list(MIRROR_KEPT))['da2.merrill_eluvian'], 'preserved')
        self.assertEqual(self.choices(seen=list(MIRROR_DESTROYED))['da2.merrill_eluvian'], 'destroyed')

    def test_mirror_unchanged_requires_completed_story_and_known_follower(self):
        plots = {ACT: [4], MERRILL: [], NEW_PATH: []}
        party = [('gen00fl_merrill', 123, 2)]
        self.assertNotIn('da2.merrill_eluvian', self.choices(plots, party=party))
        plots[ACT] = [4, 5]
        self.assertEqual(self.choices(plots, party=party)['da2.merrill_eluvian'], 'preserved')
        self.assertNotIn('da2.merrill_eluvian', self.choices(plots))
        self.assertNotIn('da2.merrill_eluvian', self.choices({ACT: [5]}, party=party))

    def test_conflicting_mirror_evidence_stays_unresolved(self):
        result = self.result({MERRILL: [26]}, seen=list(MIRROR_KEPT))
        self.assertNotIn('da2.merrill_eluvian', result['choices'])
        entry = next(e for e in result['unresolved'] if e['choice_id'] == 'da2.merrill_eluvian')
        self.assertEqual(entry['status'], 'needs_review')
        self.assertIn('conflicting', entry['reason'])

    def test_clan_combat_start_does_not_mean_clan_killed(self):
        self.assertNotIn('da2.merrill_clan', self.choices({NEW_PATH: [15]}))
        self.assertEqual(self.choices({NEW_PATH: [16]})['da2.merrill_clan'], 'killed')
        self.assertEqual(self.choices({NEW_PATH: [14]})['da2.merrill_clan'], 'survived')
        self.assertEqual(self.choices({NEW_PATH: [14, 16]})['da2.merrill_clan'], 'killed')
        self.assertEqual(self.choices({ACT: [5], NEW_PATH: []})['da2.merrill_clan'], 'survived')
        self.assertNotIn('da2.merrill_clan', self.choices({ACT: [5], NEW_PATH: [15]}))
        self.assertNotIn('da2.merrill_clan', self.choices({ACT: [5]}))

    def test_marriage_waits_until_act_three(self):
        self.assertNotIn('da2.aveline_marriage', self.choices({ACT: [2], LONG_ROAD: [20]}))
        self.assertEqual(self.choices({ACT: [4], LONG_ROAD: [20]})['da2.aveline_marriage'], 'married')
        for marker in (1, 26):
            self.assertEqual(self.choices({ACT: [4], LONG_ROAD: [marker]})['da2.aveline_marriage'], 'not_married')
        self.assertNotIn('da2.aveline_marriage', self.choices({ACT: [4], LONG_ROAD: []}))
        # Initially declining can be followed by accepting and succeeding.
        self.assertEqual(self.choices({ACT: [4], LONG_ROAD: [1, 20]})['da2.aveline_marriage'], 'married')

    def test_loyalty_uses_completed_allegiance_not_temporary_availability(self):
        party = [('gen00fl_aveline', 100, 2), ('gen00fl_merrill', 101, 2)]
        for flags in ([], [0], [17], [0, 1, 17]):
            result = self.choices({FINALE: flags}, party=party)
            self.assertNotIn('da2.aveline_remained', result)
            self.assertNotIn('da2.merrill_remained', result)
        result = self.choices({FINALE: [0, 17]}, party=party)
        self.assertEqual(result['da2.aveline_remained'], 'stayed')
        self.assertEqual(result['da2.merrill_remained'], 'stayed')
        for flag, key in ((12, 'aveline'), (54, 'aveline'), (14, 'merrill'), (55, 'merrill')):
            result = self.choices({FINALE: [0, 17, flag]}, party=party)
            self.assertEqual(result['da2.' + key + '_remained'], 'left')
        self.assertNotIn('da2.aveline_remained', self.choices({FINALE: [0, 17]}))

    def test_approval_is_separate_from_forgiveness_romance_and_execution(self):
        self.assertEqual(self.choices(seen=list(ANDERS_APPROVED))['da2.anders_approval'], 'approved')
        for ref in ANDERS_DISAPPROVED:
            self.assertEqual(self.choices(seen=[ref])['da2.anders_approval'], 'disapproved')
        # Sympathetic line 50 and forgiving line 75 do not explicitly approve.
        result = self.result({FINALE: [0, 17, 97]}, seen=[6075121, 6127577, 6182443])
        self.assertNotIn('da2.anders_approval', result['choices'])
        self.assertEqual(self.choices({FINALE: [18]}, seen=list(ANDERS_APPROVED))['da2.anders_approval'], 'approved')
        self.assertNotIn('da2.anders_approval', self.choices(seen=list(ANDERS_APPROVED | ANDERS_DISAPPROVED)))

    def test_bethany_final_survival_does_not_predict_future_events(self):
        self.assertEqual(self.choices({ACT: [11]})['da2.bethany_final_battle'], 'before_war')
        self.assertEqual(self.choices({ACT: [13]})['da2.bethany_final_battle'], 'before_war')
        self.assertEqual(self.choices({ACT: [4, 9], FINALE: [84]})['da2.bethany_final_battle'], 'died')
        self.assertNotIn('da2.bethany_final_battle', self.choices({ACT: [4, 9], FINALE: []}))
        for final in ({ACT: [4, 5, 9], FINALE: []}, {ACT: [4, 7], FINALE: [76]}):
            self.assertEqual(self.choices(final)['da2.bethany_final_battle'], 'survived')
        self.assertNotIn('da2.bethany_final_battle', self.choices({ACT: [4, 5, 9]}))
        self.assertNotIn('da2.bethany_final_battle', self.choices({ACT: [11], FINALE: [84]}))

    def test_modded_living_bethany_does_not_gain_a_vanilla_career(self):
        party = [('gen00fl_bethany', 123, 2)]
        plots = {ACT: [2, 4, 5], FINALE: []}
        result = self.result(plots, party=party)
        self.assertEqual(result['choices']['da2.bethany_fate'], 'alive_unspecified')
        self.assertEqual(result['choices']['da2.bethany_final_battle'], 'survived')
        profile = self.catalog.create('Modded siblings', choices=result['choices'], mode='experimental')
        self.assertIn('da2_bethany_alive', compile_profile(profile, catalog=self.catalog).values)
        plots[ACT].append(11)
        self.assertNotIn('da2.bethany_final_battle', self.choices(plots, party=party))

    def test_unresolved_living_bethany_defaults_to_surviving_without_claiming_recovery(self):
        cases = [({ACT: [2, 4, 9]}, (), 'circle'),
                 ({ACT: [2, 4, 7]}, (), 'warden'),
                 ({ACT: [2, 4]}, [('gen00fl_bethany', 123, 2)], 'alive_unspecified')]
        for plots, party, career in cases:
            with self.subTest(career=career):
                result = self.result(plots, party=party)
                self.assertEqual(result['choices']['da2.bethany_fate'], career)
                self.assertNotIn('da2.bethany_final_battle', result['choices'])
                self.assertTrue(any(e['choice_id'] == 'da2.bethany_final_battle' for e in result['unresolved']))
                profile = self.catalog.create('Unresolved Bethany', choices=result['choices'], mode='experimental')
                compiled = compile_profile(profile, catalog=self.catalog)
                self.assertEqual(compiled.effective_values['da2_bethany_final_battle_death'], 1)
                self.assertEqual(compiled.report['resolved_choices']['da2.bethany_final_battle']['answer_id'], 'survived')

    def test_bethany_survival_default_cannot_override_recorded_deaths(self):
        for plots, party, expected in [({ACT: [2, 4, 9], FINALE: [84]}, (), 2),
                 ({ACT: [2, 4], FINALE: [84]}, [('gen00fl_bethany', 123, 2)], 2),
                 ({ACT: [11]}, (), 0), ({ACT: [13]}, (), 0)]:
            result = self.result(plots, party=party)
            profile = self.catalog.create('Recorded fate', choices=result['choices'], mode='experimental')
            self.assertEqual(compile_profile(profile, catalog=self.catalog).effective_values['da2_bethany_final_battle_death'], expected)

    def test_v43_upgrade_changes_only_unspecified_living_bethany_fallback(self):
        old = Catalog(mapping_version=43)
        for explicit in (None, 'before_war', 'survived', 'died'):
            with self.subTest(explicit=explicit):
                choices = {'da2.bethany_fate': 'alive_unspecified'}
                if explicit:
                    choices['da2.bethany_final_battle'] = explicit
                original = old.create('Old modded Bethany', choices=choices, mode='experimental')
                before = compile_profile(original, catalog=old).effective_values
                upgraded = self.catalog.upgrade(original)
                after = compile_profile(upgraded, catalog=self.catalog).effective_values
                changed = {key for key in before if before[key] != after[key]}
                self.assertEqual(changed, {'da2_bethany_final_battle_death'} if explicit is None else set())
                self.assertEqual(dict(upgraded.choices), choices)
                self.assertEqual(original.mapping_version, 43)

    def test_source_dialogue_ids_and_conditions_are_checked_against_vanilla(self):
        path = Path(__file__).parents[1] / 'assessment/output/save-import-survey/batch3/conversations.json'
        if not path.is_file(): self.skipTest('Development source extraction is unavailable')
        cnv = json.loads(path.read_text(encoding='utf8'))
        checks = [('mcr310_argument.cnv', 85, next(iter(ANDERS_APPROVED))),
                  ('gen00fl_merrill.cnv', 189, next(iter(MIRROR_KEPT))),
                  ('gen00fl_merrill.cnv', 187, next(iter(MIRROR_DESTROYED)))]
        checks += [('mcr310_argument.cnv', line, ref) for line, ref in ((35, 6075100), (43, 6075110), (64, 6127563))]
        for name, line, ref in checks:
            self.assertEqual(cnv[name]['lines'][line]['strref'], ref)
        for name, line, flag in [('mcr310_argument.cnv', 316, 14), ('mcr310_argument.cnv', 364, 12),
                                  ('mcr370_meredith.cnv', 217, 84), ('mcr371_hostile_aveline.cnv', 49, 54),
                                  ('mcr371_hostile_merrill.cnv', 35, 55)]:
            action = cnv[name]['lines'][line]['action']
            self.assertEqual(action['guid'].rstrip('\0'), FINALE)
            self.assertEqual((action['flag'], action['value']), (flag, 255))
        self.assertEqual(len(SUPPORTED), 7)


if __name__ == '__main__': unittest.main()
