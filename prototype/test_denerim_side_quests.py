"""Five Denerim booleans, independent edits and immutable historical payloads."""
from itertools import product
from pathlib import Path
import tempfile
import unittest

from export_worldstate import ROOT, read_mod
from gui import EditorApp
from world_profiles import Catalog, ProfileStore
from world_profiles.compiler import build_profile_mod, compile_profile
from world_profiles.story_rules import propose
from test_da2_main_story import flags_from_mod

CASES={
 'dao.landry_fate':('dao_den_honor_bound',{'alive':0,'killed':1}),
 'dao.oswyn_sighard':('dao_den_tortured_noble',{'not_told':0,'told':1}),
 'dao.irminric_ring':('dao_den_lost_templar',{'not_given':0,'given':1}),
 'dao.beggar_amulet':('dao_den_hearing_voices',{'not_returned':0,'returned':1}),
 'dao.justine_scroll':('dao_den_forgotten_verses',{'not_brought':0,'brought':1})}

class DenerimSideQuestTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.catalog=Catalog()

 def test_all_32_combinations_across_nine_presets(self):
  for preset in self.catalog.presets:
   for answers in product(*(values for field,values in CASES.values())):
    choices=dict(zip(CASES,answers));compiled=compile_profile(self.catalog.create('Denerim',base_preset=preset,choices=choices,mode='experimental'),catalog=self.catalog)
    for group,(field,values) in CASES.items():self.assertEqual(compiled.effective_values[field],values[choices[group]])

 def test_single_edits_preserve_every_unowned_value_and_all_original_ranges(self):
  for preset in self.catalog.presets:
   profile=self.catalog.create('Original',base_preset=preset,mode='experimental');before=compile_profile(profile,catalog=self.catalog)
   for group,(field,answers) in CASES.items():
    for answer,value in answers.items():
     after=compile_profile(profile.edited(choices={group:answer}),catalog=self.catalog)
     self.assertEqual({n:v for n,v in before.effective_values.items() if n!=field},{n:v for n,v in after.effective_values.items() if n!=field})
     self.assertEqual(after.max_overrides,{})

 def test_all_ten_answers_roundtrip_with_boolean_range(self):
  for group,(field,answers) in CASES.items():
   for answer,value in answers.items():
    raw,_=build_profile_mod(self.catalog.create('Answer',mode='experimental',choices={group:answer}),catalog=self.catalog)
    flag=flags_from_mod(raw)[field]
    self.assertEqual(flag['DefaultValue'],value);self.assertEqual(flag['MinValue'],0);self.assertEqual(flag['MaxValue'],1)

 def test_released_presets_resolve_and_reproduce_exact_payload(self):
  for preset in self.catalog.presets:
   if not preset.startswith('template-'):continue
   profile=self.catalog.create('Released',base_preset=preset,mode='experimental')
   resolved=compile_profile(profile,catalog=self.catalog).report['resolved_choices']
   choices={group:resolved[group]['answer_id'] for group in CASES}
   self.assertEqual(list(choices.values()),['killed','told','given','returned','brought'])
   raw,_=build_profile_mod(profile.edited(choices=choices),catalog=self.catalog)
   self.assertEqual(read_mod(raw)['ebx'],read_mod(self.catalog.template_path(preset).read_bytes())['ebx'])

 def test_catalog32_upgrade_preserves_payloads_and_immutable_saved_revisions(self):
  old=Catalog(mapping_version=32)
  for preset in old.presets:
   profile=old.create('Catalog32',base_preset=preset,mode='experimental',choices={'dao.mardy_son':'not_encountered','dao.zerlinda_fate':'surface'})
   upgraded=self.catalog.upgrade(profile);before,_=build_profile_mod(profile,catalog=self.catalog);after,_=build_profile_mod(upgraded,catalog=self.catalog)
   self.assertEqual(read_mod(before)['ebx'],read_mod(after)['ebx'])
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as directory:
   store=ProfileStore(Path(directory)/'profiles',catalog=old);saved=store.create('History',mode='keep',choices={'dao.dagna_outcome':'not_met'})
   snapshot={str(p):p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()}
   upgraded=self.catalog.upgrade(saved);self.assertEqual(upgraded.choices,saved.choices)
   self.assertEqual(store.load(saved.profile_id),saved)
   self.assertEqual(snapshot,{str(p):p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()})

 def test_all_combinations_work_with_restrictions_and_no_new_rules_are_invented(self):
  for answers in product(*(values for field,values in CASES.values())):
   choices={'dao.dagna_outcome':'not_met',**dict(zip(CASES,answers))}
   profile=self.catalog.create('Restricted Denerim',mode='keep',choices=choices)
   compiled=compile_profile(profile,catalog=self.catalog)
   self.assertEqual(compiled.effective_values,compile_profile(profile.edited(mode='experimental'),catalog=self.catalog).effective_values)
  self.assertEqual(Catalog(mapping_version=33).story_rules,Catalog(mapping_version=32).story_rules)

 def test_proposals_keep_unrelated_choices_and_do_not_write_history(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as directory:
   app=EditorApp(Path(directory)/'profiles',Path(directory)/'exports')
   saved=app.store.create('Denerim',mode='keep',choices={'dao.dagna_outcome':'not_met'})
   snapshot={str(p):p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()}
   for group,(field,answers) in CASES.items():
    for answer in answers:
     changed=propose(saved,{group:answer},mode='keep',catalog=self.catalog,editable=app.presentation)
     self.assertEqual(changed.choices,{**saved.choices,group:answer})
   self.assertEqual(snapshot,{str(p):p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()})

if __name__=='__main__':unittest.main(verbosity=2)
