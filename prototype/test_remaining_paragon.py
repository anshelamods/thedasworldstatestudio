"""Remaining Paragon flags, family dependencies, Sten linkage and frozen history."""
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
 'dao.mardy_relationship':('dao_dno_mardy_son',{'not_met':0,'no_relations':1,'had_relations':2}),
 'dao.mardy_son':('dao_par_noble_birth',{'no_son':0,'not_restored':1,'restored':2,'not_encountered':3}),
 'dao.legion_noble_house':('dao_par_dead_caste',{'not_proven':0,'proven':1}),
 'dao.shaperate_tome':('dao_par_thief_house_learning',{'not_investigated':0,'returned':1,'sold':2}),
 'dao.rogek_lyrium':('dao_par_precious_metals',{'not_completed':0,'completed':1})}

class RemainingParagonTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.catalog=Catalog()
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as directory:
   cls.editable=EditorApp(Path(directory)/'profiles',Path(directory)/'exports').presentation

 def test_all_144_combinations_across_nine_presets(self):
  for preset in self.catalog.presets:
   for answers in product(*(values for field,values in CASES.values())):
    choices=dict(zip(CASES,answers));compiled=compile_profile(self.catalog.create('Paragon',base_preset=preset,choices=choices,mode='experimental'),catalog=self.catalog)
    for group,(field,values) in CASES.items():self.assertEqual(compiled.effective_values[field],values[choices[group]])

 def test_single_edits_preserve_every_other_value_and_only_son_three_extends_range(self):
  for preset in self.catalog.presets:
   profile=self.catalog.create('Original',base_preset=preset,mode='experimental');before=compile_profile(profile,catalog=self.catalog)
   for group,(field,answers) in CASES.items():
    for answer,value in answers.items():
     after=compile_profile(profile.edited(choices={group:answer}),catalog=self.catalog)
     self.assertEqual({n:v for n,v in before.effective_values.items() if n!=field},{n:v for n,v in after.effective_values.items() if n!=field})
     self.assertEqual(after.max_overrides,{field:3} if group=='dao.mardy_son' and value==3 else {})

 def test_all_fourteen_answers_roundtrip_with_original_and_explicit_extended_ranges(self):
  for group,(field,answers) in CASES.items():
   for answer,value in answers.items():
    raw,_=build_profile_mod(self.catalog.create('Answer',mode='experimental',choices={group:answer}),catalog=self.catalog)
    flag=flags_from_mod(raw)[field]
    self.assertEqual(flag['DefaultValue'],value);self.assertEqual(flag['MinValue'],0)
    maximum=3 if group=='dao.mardy_son' and value==3 else 1 if group in ('dao.legion_noble_house','dao.rogek_lyrium') else 2
    self.assertEqual(flag['MaxValue'],maximum)

 def test_all_released_presets_resolve_and_reproduce_exact_payload(self):
  for preset in self.catalog.presets:
   if not preset.startswith('template-'):continue
   profile=self.catalog.create('Released',base_preset=preset,mode='experimental')
   resolved=compile_profile(profile,catalog=self.catalog).report['resolved_choices']
   choices={group:resolved[group]['answer_id'] for group in CASES}
   self.assertEqual(list(choices.values()),['not_met','no_son','proven','returned','not_completed'])
   raw,_=build_profile_mod(profile.edited(choices=choices),catalog=self.catalog)
   self.assertEqual(read_mod(raw)['ebx'],read_mod(self.catalog.template_path(preset).read_bytes())['ebx'])

 def test_catalog31_upgrades_preserve_game_payload_and_immutable_saved_revisions(self):
  old=Catalog(mapping_version=31)
  for preset in old.presets:
   profile=old.create('Catalog31',base_preset=preset,mode='experimental',choices={'dao.zerlinda_fate':'surface','dao.bevin_fate':'returned_sword'})
   upgraded=self.catalog.upgrade(profile);before,_=build_profile_mod(profile,catalog=self.catalog);after,_=build_profile_mod(upgraded,catalog=self.catalog)
   self.assertEqual(read_mod(before)['ebx'],read_mod(after)['ebx'])
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as directory:
   store=ProfileStore(Path(directory)/'profiles',catalog=old);saved=store.create('History',mode='ordinary',choices={'dao.sten_recruited':'recruited','dao.sten_sword':'not_recruited'})
   snapshot={str(p):p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()}
   self.catalog.upgrade(saved)
   self.assertEqual(store.load(saved.profile_id),saved)
   self.assertEqual(snapshot,{str(p):p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()})

 def test_mardy_identity_and_son_truth_table_with_unrestricted_bypass(self):
  for identity,relations,son in product(self.catalog.choices['dao.warden_identity']['answers'],CASES['dao.mardy_relationship'][1],CASES['dao.mardy_son'][1]):
   choices={'dao.dagna_outcome':'not_met','dao.warden_identity':identity,'dao.warden_class':'mage' if identity.endswith('_mage') else 'warrior','dao.mardy_relationship':relations,'dao.mardy_son':son}
   profile=self.catalog.create('Family',mode='keep',choices=choices)
   valid=(relations=='not_met' or identity=='male_dwarf_noble') and ((relations=='had_relations') == (son!='no_son'))
   with self.subTest(identity=identity,relations=relations,son=son):
    if valid:compile_profile(profile,catalog=self.catalog)
    else:
     with self.assertRaises(StoryConflict):compile_profile(profile,catalog=self.catalog)
    self.assertEqual(len(compile_profile(profile.edited(mode='experimental'),catalog=self.catalog).effective_values),382)

 def test_family_proposals_lock_requested_answer_and_require_atomic_review_without_writes(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as directory:
   app=EditorApp(Path(directory)/'profiles',Path(directory)/'exports');saved=app.store.create('Family',mode='keep',choices={'dao.dagna_outcome':'not_met'})
   draft={k:saved.to_dict()[k] for k in ('profile_id','revision','name','base_preset','mode','choices')}
   snapshot={str(p):p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()}
   response=app.propose(dict(draft=draft,updates={'dao.mardy_son':'restored'},mode='keep'))
   self.assertEqual(response['draft']['choices']['dao.mardy_son'],'restored')
   self.assertEqual(response['draft']['choices']['dao.mardy_relationship'],'had_relations')
   self.assertEqual(response['draft']['choices']['dao.warden_identity'],'male_dwarf_noble')
   self.assertEqual({c['choice_id'] for c in response['changes']},{'dao.mardy_relationship','dao.warden_identity'})
   self.assertEqual(snapshot,{str(p):p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()})
   changed=propose(app.draft(response['draft']),{'dao.warden_identity':'female_human_noble'},mode='keep',catalog=self.catalog,editable=self.editable)
   self.assertEqual(changed.choices['dao.warden_identity'],'female_human_noble')
   self.assertEqual(changed.choices['dao.mardy_relationship'],'not_met');self.assertEqual(changed.choices['dao.mardy_son'],'no_son')

 def test_sten_complete_truth_table_respects_release_recruitment_and_sword(self):
  for recruited,released,sword in product(('not_recruited','recruited'),('not_freed','picked_lock','persuaded','intimidated'),('not_recruited','not_returned','returned')):
   profile=self.catalog.create('Sten',mode='keep',choices={'dao.dagna_outcome':'not_met','dao.sten_recruited':recruited,'dao.sten_release':released,'dao.sten_sword':sword})
   valid=((recruited=='recruited')==(sword!='not_recruited')) and (recruited=='not_recruited' or released!='not_freed')
   if valid:compile_profile(profile,catalog=self.catalog)
   else:
    with self.assertRaises(StoryConflict):compile_profile(profile,catalog=self.catalog)
   compile_profile(profile.edited(mode='experimental'),catalog=self.catalog)

 def test_sten_both_directions_cascade_and_unrestricted_preserves_custom_combination(self):
  base=self.catalog.create('Sten recruited',mode='keep',choices={'dao.dagna_outcome':'not_met','dao.sten_recruited':'recruited','dao.sten_release':'persuaded','dao.sten_sword':'returned'})
  for updates in ({'dao.sten_sword':'not_recruited'},{'dao.sten_recruited':'not_recruited'},{'dao.sten_release':'not_freed'}):
   candidate=propose(base,updates,mode='keep',catalog=self.catalog,editable=self.editable)
   self.assertEqual(candidate.choices['dao.sten_sword'],'not_recruited');self.assertEqual(candidate.choices['dao.sten_recruited'],'not_recruited')
   restored=propose(candidate,{'dao.sten_sword':'returned'},mode='keep',catalog=self.catalog,editable=self.editable)
   self.assertEqual(restored.choices['dao.sten_recruited'],'recruited')
   self.assertNotEqual(compile_profile(restored,catalog=self.catalog).effective_values['dao_lot_qunari_prisoner'],0)
  custom=propose(base,{'dao.sten_sword':'not_recruited'},mode='experimental',catalog=self.catalog,editable=self.editable)
  self.assertEqual(custom.choices['dao.sten_recruited'],'recruited');self.assertEqual(custom.choices['dao.sten_sword'],'not_recruited')

if __name__=='__main__':unittest.main(verbosity=2)
