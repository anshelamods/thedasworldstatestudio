"""Redcliffe flags, Keep gates, local Bella history and immutable legacy exports."""
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
 'dao.redcliffe_preparation':('dao_red_village_siege',{'not_helped':0,'helped':1}),
 'dao.redcliffe_defense':('dao_red_attack_nightfall',{'not_helped':0,'helped':1}),
 'dao.bevin_fate':('dao_red_missing_child',{'not_helped':0,'took_sword':1,'paid_for_sword':2,'no_sword':3,'scared_to_chantry':4,'returned_sword':5}),
 'dao.valena_fate':('dao_red_lost_castle',{'not_rescued':0,'rescued':1})}
BELLA=('left','tavern_owner','brewery','died')

class RedcliffeVillageTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.catalog=Catalog()

 def test_all_48_combinations_across_nine_presets_in_unrestricted_mode(self):
  for preset in self.catalog.presets:
   for answers in product(*(values for field,values in CASES.values())):
    choices=dict(zip(CASES,answers));compiled=compile_profile(self.catalog.create('Redcliffe',base_preset=preset,choices=choices,mode='experimental'),catalog=self.catalog)
    for group,(field,values) in CASES.items():self.assertEqual(compiled.effective_values[field],values[choices[group]])

 def test_single_edits_preserve_every_unowned_value_and_range(self):
  for preset in self.catalog.presets:
   profile=self.catalog.create('Original',base_preset=preset,mode='experimental');before=compile_profile(profile,catalog=self.catalog)
   for group,(field,answers) in CASES.items():
    for answer,value in answers.items():
     after=compile_profile(profile.edited(choices={group:answer}),catalog=self.catalog)
     self.assertEqual({n:v for n,v in before.effective_values.items() if n!=field},{n:v for n,v in after.effective_values.items() if n!=field})
     self.assertEqual(after.max_overrides, {field:5} if value==5 else {})

 def test_all_twelve_mapped_answers_roundtrip_and_only_bevin_five_extends_range(self):
  for group,(field,answers) in CASES.items():
   for answer,value in answers.items():
    raw,_=build_profile_mod(self.catalog.create('Redcliffe answer',mode='experimental',choices={group:answer}),catalog=self.catalog)
    flag=flags_from_mod(raw)[field]
    self.assertEqual(flag['DefaultValue'],value)
    self.assertEqual(flag['MaxValue'],(5 if value==5 else 4) if group=='dao.bevin_fate' else 1)
    self.assertEqual(flag['MinValue'],0)

 def test_every_bella_answer_changes_no_ebx_bytes_or_game_values(self):
  profile=self.catalog.create('Local Bella',mode='experimental');original,_=build_profile_mod(profile,catalog=self.catalog)
  for answer in BELLA:
   changed=profile.edited(choices={'dao.bella_fate':answer});raw,report=build_profile_mod(changed,catalog=self.catalog)
   self.assertEqual(read_mod(raw)['ebx'],read_mod(original)['ebx'])
   compiled=compile_profile(changed,catalog=self.catalog)
   self.assertEqual(len(compiled.effective_values),382)
   self.assertNotIn('dao_red_bella_tavern',compiled.effective_values)
   self.assertNotIn('dao_red_bella_tavern',compiled.values)
   self.assertEqual(compiled.report['resolved_choices']['dao.bella_fate']['answer_id'],answer)
   self.assertEqual(compiled.report['resolved_choices']['dao.bella_fate']['export_behavior'],'profile-only')
  self.assertIsNone(compile_profile(profile,catalog=self.catalog).report['resolved_choices']['dao.bella_fate']['answer_id'])

 def test_strict_truth_table_and_unrestricted_bypass_for_local_and_game_questions(self):
  for prepared,defended,bella in product((0,1),(0,1),(None,*BELLA)):
   choices={'dao.dagna_outcome':'not_met','dao.redcliffe_preparation':'helped' if prepared else 'not_helped','dao.redcliffe_defense':'helped' if defended else 'not_helped'}
   if bella:choices['dao.bella_fate']=bella
   candidate=self.catalog.create('Story table',mode='keep',choices=choices)
   valid=(not defended or prepared) and (bella is None or prepared==int(bella!='died'))
   with self.subTest(prepared=prepared,defended=defended,bella=bella):
    if valid:compile_profile(candidate,catalog=self.catalog)
    else:
     with self.assertRaises(StoryConflict):compile_profile(candidate,catalog=self.catalog)
    self.assertEqual(len(compile_profile(candidate.edited(mode='experimental'),catalog=self.catalog).effective_values),382)

 def test_proposals_preserve_requested_answer_and_repair_local_inputs_without_writes(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as directory:
   app=EditorApp(Path(directory)/'profiles',Path(directory)/'exports')
   saved=app.store.create('Prepared village',mode='keep',choices={'dao.dagna_outcome':'not_met','dao.bella_fate':'tavern_owner'})
   draft={key:saved.to_dict()[key] for key in ('profile_id','revision','name','base_preset','mode','choices')}
   snapshot={str(p):p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()}
   response=app.propose(dict(draft=draft,updates={'dao.redcliffe_preparation':'not_helped'},mode='keep'))
   self.assertEqual(response['draft']['choices']['dao.redcliffe_preparation'],'not_helped')
   self.assertEqual(response['draft']['choices']['dao.redcliffe_defense'],'not_helped')
   self.assertEqual(response['draft']['choices']['dao.bella_fate'],'died')
   self.assertEqual({x['choice_id'] for x in response['changes']},{'dao.redcliffe_defense','dao.bella_fate'})
   self.assertEqual(snapshot,{str(p):p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()})
   self.assertEqual(app.store.load(saved.profile_id),saved)
   candidate=app.draft(response['draft'])
   restored=propose(candidate,{'dao.bella_fate':'brewery'},mode='keep',catalog=self.catalog,editable=app.presentation)
   compiled=compile_profile(restored,catalog=self.catalog)
   self.assertEqual(restored.choices['dao.bella_fate'],'brewery')
   self.assertEqual(compiled.effective_values['dao_red_village_siege'],1)
   self.assertEqual(compiled.effective_values['dao_red_attack_nightfall'],0)
   self.assertEqual(len(compiled.effective_values),382)

 def test_profile_only_bella_survives_portable_export_import(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as directory:
   store=ProfileStore(Path(directory)/'profiles',catalog=self.catalog)
   saved=store.create('Bella brewery',mode='experimental',choices={'dao.bella_fate':'brewery','dao.bevin_fate':'returned_sword'})
   output=Path(directory)/'portable.json';store.export_json(saved.profile_id,output)
   imported=store.import_profile(output)
   self.assertNotEqual(imported.profile_id,saved.profile_id)
   self.assertEqual(imported.choices,saved.choices)
   self.assertEqual(compile_profile(imported,catalog=self.catalog).effective_values,compile_profile(saved,catalog=self.catalog).effective_values)

 def test_all_released_presets_and_legacy_catalog29_payloads_remain_exact(self):
  old=Catalog(mapping_version=29)
  for preset in old.presets:
   profile=self.catalog.create('Released Redcliffe',base_preset=preset,mode='experimental')
   if preset.startswith('template-'):
    resolved=compile_profile(profile,catalog=self.catalog).report['resolved_choices']
    choices={group:resolved[group]['answer_id'] for group in CASES}
    self.assertEqual(choices['dao.bevin_fate'],'not_helped')
    raw,_=build_profile_mod(profile.edited(choices=choices),catalog=self.catalog)
    self.assertEqual(read_mod(raw)['ebx'],read_mod(self.catalog.template_path(preset).read_bytes())['ebx'])
   legacy=old.create('Catalog29',base_preset=preset,mode='experimental',choices={'dao.cammen_relationship':'together','dao.elora_halla':'saved'})
   upgraded=self.catalog.upgrade(legacy)
   before,_=build_profile_mod(legacy,catalog=self.catalog);after,_=build_profile_mod(upgraded,catalog=self.catalog)
   self.assertEqual(read_mod(before)['ebx'],read_mod(after)['ebx'])

if __name__=='__main__':unittest.main(verbosity=2)
