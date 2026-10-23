"""Orzammar source values, dependency repair, ranges and historical payloads."""
from itertools import product
from pathlib import Path
import tempfile
import unittest

from export_worldstate import ROOT, read_mod
from gui import EditorApp
from world_profiles import Catalog, ProfileStore
from world_profiles.compiler import StoryConflict, build_profile_mod, compile_profile
from world_profiles.story_rules import propose
from test_da2_main_story import flags_from_mod

CASES={
 'dao.filda_ruck':('dao_par_mothers_hope',{'not_met':0,'said_dead':1,'condition_truth':2,'killed_lied':3,'killed_truth':4,'killed_heroic':5}),
 'dao.burkel_chantry':('dao_par_chant_deeps',{'not_helped':0,'helped':1}),
 'dao.zerlinda_fate':('dao_par_zerlinda_woe',{'dust_town':0,'reconciled':1,'surface':2,'chantry':3,'deep_roads':4}),
 'dao.orta_ancestry':('dao_par_lost_memories',{'not_helped':0,'helped':1})}

class OrzammarSideQuestTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.catalog=Catalog()

 def test_all_120_combinations_across_nine_presets(self):
  for preset in self.catalog.presets:
   for answers in product(*(values for field,values in CASES.values())):
    choices=dict(zip(CASES,answers))
    compiled=compile_profile(self.catalog.create('Orzammar',base_preset=preset,choices=choices,mode='experimental'),catalog=self.catalog)
    for group,(field,values) in CASES.items():self.assertEqual(compiled.effective_values[field],values[choices[group]])

 def test_single_edits_preserve_all_unowned_values_and_ranges(self):
  for preset in self.catalog.presets:
   profile=self.catalog.create('Original',base_preset=preset,mode='experimental');before=compile_profile(profile,catalog=self.catalog)
   for group,(field,answers) in CASES.items():
    for answer,value in answers.items():
     after=compile_profile(profile.edited(choices={group:answer}),catalog=self.catalog)
     self.assertEqual({n:v for n,v in before.effective_values.items() if n!=field},{n:v for n,v in after.effective_values.items() if n!=field})
     self.assertEqual(after.max_overrides,{field:4} if group=='dao.zerlinda_fate' and value>1 else {})

 def test_all_fifteen_answers_roundtrip_with_only_explicit_zerlinda_range_extension(self):
  for group,(field,answers) in CASES.items():
   for answer,value in answers.items():
    raw,_=build_profile_mod(self.catalog.create('Answer',mode='experimental',choices={group:answer}),catalog=self.catalog)
    flag=flags_from_mod(raw)[field]
    self.assertEqual(flag['DefaultValue'],value)
    maximum=5 if group=='dao.filda_ruck' else 4 if group=='dao.zerlinda_fate' and value>1 else 1
    self.assertEqual(flag['MaxValue'],maximum);self.assertEqual(flag['MinValue'],0)

 def test_released_presets_reproduce_exact_payload_and_resolve_original_answers(self):
  for preset in self.catalog.presets:
   if not preset.startswith('template-'):continue
   profile=self.catalog.create('Released',base_preset=preset,mode='experimental')
   resolved=compile_profile(profile,catalog=self.catalog).report['resolved_choices']
   choices={group:resolved[group]['answer_id'] for group in CASES}
   self.assertEqual(list(choices.values()),['not_met','not_helped','dust_town','helped'])
   raw,_=build_profile_mod(profile.edited(choices=choices),catalog=self.catalog)
   self.assertEqual(read_mod(raw)['ebx'],read_mod(self.catalog.template_path(preset).read_bytes())['ebx'])

 def test_catalog30_upgrade_preserves_payload_and_saved_revision(self):
  old=Catalog(mapping_version=30)
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as directory:
   app=EditorApp(Path(directory)/'profiles',Path(directory)/'exports')
   for preset in old.presets:
    legacy=old.create('Catalog30',base_preset=preset,mode='experimental',choices={'dao.bevin_fate':'returned_sword','dao.bella_fate':'brewery'})
    upgraded=self.catalog.upgrade(legacy)
    before,_=build_profile_mod(legacy,catalog=self.catalog);after,_=build_profile_mod(upgraded,catalog=self.catalog)
    self.assertEqual(read_mod(before)['ebx'],read_mod(after)['ebx'])
   old_store=ProfileStore(Path(directory)/'profiles',catalog=old)
   saved=old_store.create('Saved30',mode='experimental',choices={'dao.bevin_fate':'returned_sword'})
   snapshot={str(p):p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()}
   self.catalog.upgrade(app.store.load(saved.profile_id))
   self.assertEqual(snapshot,{str(p):p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()})
   self.assertEqual(app.store.load(saved.profile_id),saved)
   self.assertEqual(legacy.mapping_version,30);self.assertEqual(upgraded.mapping_version,self.catalog.version)
   self.assertEqual(legacy.choices,upgraded.choices)

 def test_chantry_truth_table_and_unrestricted_bypass(self):
  for burkel,zerlinda in product(('not_helped','helped'),CASES['dao.zerlinda_fate'][1]):
   profile=self.catalog.create('Chantry',mode='keep',choices={'dao.dagna_outcome':'not_met','dao.burkel_chantry':burkel,'dao.zerlinda_fate':zerlinda})
   if burkel=='not_helped' and zerlinda=='chantry':
    with self.assertRaises(StoryConflict):compile_profile(profile,catalog=self.catalog)
   else:compile_profile(profile,catalog=self.catalog)
   self.assertEqual(len(compile_profile(profile.edited(mode='experimental'),catalog=self.catalog).effective_values),382)

 def test_repair_proposals_keep_requested_answer_and_leave_saved_history_untouched(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as directory:
   app=EditorApp(Path(directory)/'profiles',Path(directory)/'exports')
   saved=app.store.create('Chantry history',mode='keep',choices={'dao.dagna_outcome':'not_met','dao.burkel_chantry':'not_helped','dao.zerlinda_fate':'dust_town'})
   draft={key:saved.to_dict()[key] for key in ('profile_id','revision','name','base_preset','mode','choices')}
   snapshot={str(p):p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()}
   response=app.propose(dict(draft=draft,updates={'dao.zerlinda_fate':'chantry'},mode='keep'))
   self.assertEqual(response['draft']['choices']['dao.zerlinda_fate'],'chantry')
   self.assertEqual(response['draft']['choices']['dao.burkel_chantry'],'helped')
   self.assertEqual([c['choice_id'] for c in response['changes']],['dao.burkel_chantry'])
   self.assertEqual(snapshot,{str(p):p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()})
   self.assertEqual(app.store.load(saved.profile_id),saved)
   candidate=app.draft(response['draft'])
   changed=propose(candidate,{'dao.burkel_chantry':'not_helped'},mode='keep',catalog=self.catalog,editable=app.presentation)
   self.assertEqual(changed.choices['dao.burkel_chantry'],'not_helped')
   self.assertNotEqual(changed.choices['dao.zerlinda_fate'],'chantry')
   compile_profile(changed,catalog=self.catalog)

 def test_bevin_note_does_not_impose_gameplay_gate_or_change_assignments(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as directory:
   app=EditorApp(Path(directory)/'profiles',Path(directory)/'exports')
   self.assertNotIn('requires verification',app.presentation['dao.bevin_fate']['verification_note'])
  self.assertEqual(self.catalog.choices['dao.bevin_fate']['answers'],Catalog(mapping_version=30).choices['dao.bevin_fate']['answers'])

if __name__=='__main__':unittest.main(verbosity=2)
