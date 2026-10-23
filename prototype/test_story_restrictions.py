"""Behavioral tests for Keep dependencies, proposals and legacy profile preservation."""
import copy
from itertools import product
import json
from pathlib import Path
import tempfile
import unittest

from gui import EditorApp
from world_profiles import Catalog, ProfileError, ProfileStore, RevisionConflict
from world_profiles.compiler import StoryConflict, compile_profile, build_profile_mod
from world_profiles.story_rules import RuleSet, propose


class StoryRestrictionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            app = EditorApp(Path(directory)/'profiles', Path(directory)/'exports')
            cls.editable = app.presentation
        cls.base = propose(cls.catalog.create('Consistent world state', mode='keep'), {},
                           mode='keep', catalog=cls.catalog, editable=cls.editable)

    def edit(self, profile=None, **updates):
        return propose(profile or self.base, updates, mode='keep', catalog=self.catalog, editable=self.editable)

    def test_all_388_current_answers_have_compilable_locked_proposals(self):
        total = 0
        for key in self.editable:
            for answer, definition in self.catalog.choices[key]['answers'].items():
                if definition.get('requires_unrestricted'):
                    continue
                with self.subTest(choice=key, answer=answer):
                    total += 1
                    result = self.edit(**{key: answer})
                    self.assertEqual(result.choices[key], answer)
                    self.assertFalse(compile_profile(result, catalog=self.catalog).report['story_conflicts'])
        self.assertEqual(total, 388)

    def test_sibling_class_restrictions_and_free_combinations(self):
        for gender, job, bethany, carver in product(('male','female'), ('warrior','rogue','mage'),
                    ('circle','warden','deep_roads_death','lothering_death'),
                    ('templar','warden','deep_roads_death','lothering_death')):
            choices = dict(self.base.choices, **{'da2.hawke_identity':gender+'_'+job,
                           'da2.bethany_fate':bethany,'da2.carver_fate':carver})
            candidate = self.base.edited(choices=choices)
            valid = ((bethany == 'lothering_death') == (job == 'mage') and
                     (carver == 'lothering_death') == (job != 'mage'))
            with self.subTest(gender=gender, job=job, bethany=bethany, carver=carver):
                if valid:
                    compile_profile(candidate, catalog=self.catalog)
                else:
                    with self.assertRaises(StoryConflict):compile_profile(candidate, catalog=self.catalog)
                free = compile_profile(candidate.edited(mode='experimental'), catalog=self.catalog)
                self.assertEqual(free.effective_values['da2_bethany_alive'],int(bethany in ('circle','warden')))
                self.assertEqual(free.effective_values['da2_carver_alive'],int(carver in ('templar','warden')))

    def test_choosing_bethany_preserves_gender_and_changes_mage_class(self):
        mage = self.edit(**{'da2.hawke_identity':'female_mage'})
        result = self.edit(mage, **{'da2.bethany_fate':'warden'})
        flags = compile_profile(result, catalog=self.catalog).effective_values
        self.assertEqual(flags['da2_hawke_mf'],1)
        self.assertIn(flags['da2_hawke_class'],(0,1))
        self.assertEqual(flags['da2_bethany_career'],2)
        self.assertEqual(flags['da2_carver_career'],0)
        self.assertEqual(mage.choices['da2.hawke_identity'],'female_mage')

    def test_origin_and_class_restrict_each_other_in_both_directions(self):
        mage = self.edit(**{'dao.warden_class':'mage'})
        flags = compile_profile(mage, catalog=self.catalog).effective_values
        self.assertIn(flags['dao_warden_background'],(1,4))
        dwarf = self.edit(mage, **{'dao.warden_identity':'female_dwarf_noble'})
        flags = compile_profile(dwarf, catalog=self.catalog).effective_values
        self.assertIn(flags['dao_warden_class'],(0,1))
        self.assertEqual(flags['dao_warden_race'],2)
        self.assertEqual(flags['dao_warden_mf'],1)

    def test_sebastian_uses_semantic_anders_value_without_changing_export_policy(self):
        alive = self.edit(**{'da2.anders_fate':'alive'})
        result = self.edit(alive, **{'da2.hawke_romance':'sebastian'})
        flags = compile_profile(result, catalog=self.catalog).effective_values
        self.assertEqual(flags['da2_hawke_mf'],1)
        self.assertEqual(flags['da2_anders_fate'],1) # Author's tested/documented executed encoding.
        self.assertEqual(result.choices['da2.anders_fate'],'executed')
        self.assertEqual(RuleSet(self.catalog).semantic(flags)['da2_anders_fate'],0)

    def test_cross_game_nathaniel_and_zevran_prerequisites_are_proposed(self):
        for choice, answer, flag in [('da2.finding_nathaniel','rescued','dao_awakenings_nathaniel_live'),
                                     ('da2.murder_of_crows','helped','dao_zevran_alive')]:
            definition = self.catalog.choices[choice]
            # Select the last outcome, the successful quest branch in the captured mapping.
            answer = list(definition['answers'])[-1]
            result = self.edit(**{choice:answer})
            self.assertEqual(compile_profile(result, catalog=self.catalog).effective_values[flag],1)

    def test_multi_step_quest_dependencies_and_or_branches(self):
        result = self.edit(**{'da2.zevran_freed':list(self.catalog.choices['da2.zevran_freed']['answers'])[-1]})
        flags = compile_profile(result, catalog=self.catalog).effective_values
        self.assertEqual(flags['da2_act3_murder_of_crows'],2)
        self.assertEqual(flags['dao_zevran_alive'],1)
        result = self.edit(**{'da2.bethany_final_battle':'died'})
        flags = compile_profile(result, catalog=self.catalog).effective_values
        self.assertEqual(flags['da2_bethany_career'],1)
        self.assertEqual(flags['da2_hawke_chosen_side'],1)

    def test_quick_fenris_controls_follow_the_same_composed_answer_as_tapestry(self):
        result = self.edit(**{'da2.fenris_danarius':'returned'})
        flags = compile_profile(result,catalog=self.catalog).effective_values
        self.assertEqual(flags['da2_fenris_alive'],3)
        self.assertEqual(flags['da2_fenris_joined'],1)
        result = self.edit(result,**{'da2.fenris_recruited':'not_recruited'})
        flags = compile_profile(result,catalog=self.catalog).effective_values
        self.assertEqual(flags['da2_fenris_alive'],0)
        self.assertEqual(flags['da2_fenris_enslaved'],0)

    def test_impossible_locked_sibling_answers_are_rejected_without_mutation(self):
        before = self.base.to_dict()
        with self.assertRaises(ProfileError):
            self.edit(**{'da2.hawke_identity':'male_mage','da2.bethany_fate':'warden'})
        self.assertEqual(self.base.to_dict(),before)

    def test_free_mode_still_rejects_unknown_and_overlapping_assignments(self):
        with self.assertRaises(ProfileError):
            propose(self.base, {'da2.hawke_identity':'unknown'}, mode='experimental',catalog=self.catalog,editable=self.editable)
        candidate = self.base.edited(mode='experimental',choices={'da2.hawke_class':'mage',
                               'da2.hawke_identity':'female_warrior'})
        with self.assertRaises(ProfileError):compile_profile(candidate,catalog=self.catalog)

    def test_proposal_is_read_only_and_only_save_commits_one_revision(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path=Path(directory);app=EditorApp(path/'profiles',path/'exports')
            saved=app.store.create('Custom history',mode='experimental',choices={
                'da2.hawke_identity':'female_mage','da2.bethany_fate':'warden','da2.carver_fate':'warden'})
            draft={key:saved.to_dict()[key] for key in ('profile_id','revision','name','base_preset','mode','choices')}
            original=copy.deepcopy(draft)
            snapshot={str(p):p.read_bytes() for p in path.rglob('*') if p.is_file()}
            proposal=app.propose(dict(draft=draft,updates={},mode='keep'))
            self.assertTrue(proposal['changes'])
            self.assertEqual(draft,original)
            self.assertEqual(snapshot,{str(p):p.read_bytes() for p in path.rglob('*') if p.is_file()})
            self.assertEqual(app.store.load(saved.profile_id),saved)
            accepted=app.save(proposal['draft'])
            self.assertEqual(accepted.revision,2)
            self.assertEqual(accepted.mode,'keep')
            self.assertEqual(app.store.load(saved.profile_id,revision=1),saved)
            with self.assertRaises(RevisionConflict):app.propose(dict(draft=draft,updates={},mode='keep'))
            self.assertFalse((path/'exports').exists())

    def test_keep_save_and_export_cannot_bypass_rules(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            app=EditorApp(Path(directory)/'profiles',Path(directory)/'exports')
            draft=dict(profile_id=None,revision=0,name='Invalid strict state',base_preset='early-tests-v1',mode='keep',choices={})
            self.assertFalse(app.preview(draft)['can_export'])
            with self.assertRaises(StoryConflict):app.save(draft)
            with self.assertRaises(StoryConflict):build_profile_mod(self.catalog.create('Invalid',base_preset='early-tests-v1',mode='keep'),catalog=self.catalog)

    def test_v27_profiles_keep_exact_game_payload_and_original_revision(self):
        old=Catalog(mapping_version=27)
        profile=old.create('Both siblings survive',mode='ordinary',choices={
            'da2.hawke_identity':'male_mage','da2.bethany_fate':'warden','da2.carver_fate':'warden'})
        before=compile_profile(profile,catalog=old)
        upgraded=self.catalog.upgrade(profile)
        after=compile_profile(upgraded,catalog=self.catalog)
        self.assertEqual(before.effective_values,after.effective_values)
        self.assertEqual(before.values,after.values)
        self.assertEqual(before.max_overrides,after.max_overrides)
        self.assertEqual(compile_profile(profile,catalog=self.catalog).effective_values,before.effective_values)
        self.assertEqual(profile.mapping_version,27)


if __name__=='__main__':unittest.main()

