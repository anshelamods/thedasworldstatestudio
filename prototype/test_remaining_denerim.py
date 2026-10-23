"""Remaining Denerim exports, local companion history, dependencies and upgrades."""
from itertools import product
from pathlib import Path
import tempfile
import unittest

from export_worldstate import ROOT, read_mod
from gui import EditorApp
from world_profiles import Catalog, ProfileStore
from world_profiles.compiler import StoryConflict, build_profile_mod, compile_profile
from test_da2_main_story import flags_from_mod

CASES={
 'dao.slim_couldry':('dao_den_crime_wave',{'not_completed':0,'completed':1}),
 'dao.kylon_falcons':('dao_den_pearls_swine',{'not_helped':0,'helped':1}),
 'dao.kylon_crimson_oars':('dao_den_crimson_oars',{'not_handled':0,'handled':1}),
 'dao.ignacio_fate':('dao_den_murder_crows',{'not_completed':0,'completed':1,'killed':2})}
LOCAL={'dao.alistair_family':('not_encountered','helped','not_helped'),'dao.leliana_past':('not_encountered','sent_away','killed')}

class RemainingDenerimTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.catalog=Catalog()

 def test_all_24_mapped_combinations_across_nine_presets(self):
  for preset in self.catalog.presets:
   for answers in product(*(values for field,values in CASES.values())):
    choices=dict(zip(CASES,answers));compiled=compile_profile(self.catalog.create('Denerim',base_preset=preset,choices=choices,mode='experimental'),catalog=self.catalog)
    for group,(field,values) in CASES.items():self.assertEqual(compiled.effective_values[field],values[choices[group]])

 def test_single_edits_preserve_every_unowned_value_and_only_ignacio_two_extends_range(self):
  for preset in self.catalog.presets:
   profile=self.catalog.create('Original',base_preset=preset,mode='experimental');before=compile_profile(profile,catalog=self.catalog)
   for group,(field,answers) in CASES.items():
    for answer,value in answers.items():
     after=compile_profile(profile.edited(choices={group:answer}),catalog=self.catalog)
     self.assertEqual({n:v for n,v in before.effective_values.items() if n!=field},{n:v for n,v in after.effective_values.items() if n!=field})
     self.assertEqual(after.max_overrides,{field:2} if value==2 else {})

 def test_all_nine_mapped_answers_roundtrip_with_original_or_explicit_extended_range(self):
  for group,(field,answers) in CASES.items():
   for answer,value in answers.items():
    raw,_=build_profile_mod(self.catalog.create('Answer',mode='experimental',choices={group:answer}),catalog=self.catalog)
    flag=flags_from_mod(raw)[field]
    self.assertEqual(flag['DefaultValue'],value);self.assertEqual(flag['MinValue'],0);self.assertEqual(flag['MaxValue'],2 if value==2 else 1)

 def test_local_answers_change_no_ebx_bytes_and_never_invent_inherited_answers_or_flags(self):
  profile=self.catalog.create('Local history',mode='experimental');raw,_=build_profile_mod(profile,catalog=self.catalog)
  resolved=compile_profile(profile,catalog=self.catalog).report['resolved_choices']
  for group,answers in LOCAL.items():
   self.assertIsNone(resolved[group]['answer_id'])
   for answer in answers:
    changed=profile.edited(choices={group:answer});compiled=compile_profile(changed,catalog=self.catalog);other,_=build_profile_mod(changed,catalog=self.catalog)
    self.assertEqual(read_mod(raw)['ebx'],read_mod(other)['ebx']);self.assertEqual(len(compiled.effective_values),382)
    self.assertEqual(compiled.report['resolved_choices'][group]['answer_id'],answer)
    self.assertEqual(compiled.report['resolved_choices'][group]['export_behavior'],'profile-only')
    self.assertNotIn('dao_den_alistairs_family',compiled.effective_values);self.assertNotIn('dao_den_lelianas_past',compiled.effective_values)
    self.assertNotIn('dao_den_lelianas_past',compiled.values)

 def test_released_presets_and_catalog33_payloads_and_saved_revisions_are_preserved(self):
  old=Catalog(mapping_version=33)
  for preset in old.presets:
   profile=self.catalog.create('Released',base_preset=preset,mode='experimental')
   if preset.startswith('template-'):
    resolved=compile_profile(profile,catalog=self.catalog).report['resolved_choices'];choices={group:resolved[group]['answer_id'] for group in CASES}
    self.assertEqual(list(choices.values()),['not_completed','helped','handled','not_completed'])
    raw,_=build_profile_mod(profile.edited(choices=choices),catalog=self.catalog)
    self.assertEqual(read_mod(raw)['ebx'],read_mod(self.catalog.template_path(preset).read_bytes())['ebx'])
   legacy=old.create('Catalog33',base_preset=preset,mode='experimental',choices={'dao.landry_fate':'alive'})
   upgraded=self.catalog.upgrade(legacy);before,_=build_profile_mod(legacy,catalog=self.catalog);after,_=build_profile_mod(upgraded,catalog=self.catalog)
   self.assertEqual(read_mod(before)['ebx'],read_mod(after)['ebx'])
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as directory:
   store=ProfileStore(Path(directory)/'profiles',catalog=old);saved=store.create('Saved33',mode='keep',choices={'dao.dagna_outcome':'not_met'})
   snapshot={str(p):p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()};self.catalog.upgrade(saved)
   self.assertEqual(store.load(saved.profile_id),saved);self.assertEqual(snapshot,{str(p):p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()})

 def test_strict_truth_tables_and_unrestricted_bypass_for_local_and_game_dependencies(self):
  for falcons,crimson,leliana,past in product(('not_helped','helped'),('not_handled','handled'),('not_recruited','alive'),(None,*LOCAL['dao.leliana_past'])):
   choices={'dao.dagna_outcome':'not_met','dao.kylon_falcons':falcons,'dao.kylon_crimson_oars':crimson,'dao.leliana_fate':leliana}
   if past:choices['dao.leliana_past']=past
   profile=self.catalog.create('Rules',mode='keep',choices=choices)
   valid=(crimson!='handled' or falcons=='helped') and (past in (None,'not_encountered') or leliana!='not_recruited')
   if valid:compile_profile(profile,catalog=self.catalog)
   else:
    with self.assertRaises(StoryConflict):compile_profile(profile,catalog=self.catalog)
   compile_profile(profile.edited(mode='experimental'),catalog=self.catalog)

 def test_local_and_kylon_proposals_lock_requested_answer_and_leave_history_untouched(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as directory:
   app=EditorApp(Path(directory)/'profiles',Path(directory)/'exports')
   saved=app.store.create('Local links',mode='keep',choices={'dao.dagna_outcome':'not_met','dao.leliana_fate':'not_recruited','dao.kylon_falcons':'not_helped','dao.kylon_crimson_oars':'not_handled'})
   draft={k:saved.to_dict()[k] for k in ('profile_id','revision','name','base_preset','mode','choices')}
   snapshot={str(p):p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()}
   for key,answer,other,value in [('dao.leliana_past','sent_away','dao.leliana_fate','alive'),('dao.kylon_crimson_oars','handled','dao.kylon_falcons','helped')]:
    response=app.propose(dict(draft=draft,updates={key:answer},mode='keep'))
    self.assertEqual(response['draft']['choices'][key],answer);self.assertEqual(response['draft']['choices'][other],value)
    self.assertEqual([x['choice_id'] for x in response['changes']],[other])
    reverse=app.propose(dict(draft=response['draft'],updates={other:saved.choices[other]},mode='keep'))
    self.assertEqual(reverse['draft']['choices'][key],'not_encountered' if key=='dao.leliana_past' else 'not_handled')
    self.assertEqual(app.propose(dict(draft=draft,updates={key:answer},mode='experimental'))['changes'],[])
   self.assertEqual(snapshot,{str(p):p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()})

 def test_both_local_answers_survive_portable_profile_roundtrip(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as directory:
   store=ProfileStore(Path(directory)/'profiles',catalog=self.catalog)
   for family,past in product(*LOCAL.values()):
    saved=store.create('Local history',mode='experimental',choices={'dao.alistair_family':family,'dao.leliana_past':past})
    path=Path(directory)/(saved.profile_id+'.json');store.export_json(saved.profile_id,path);imported=store.import_profile(path)
    self.assertEqual(imported.choices,saved.choices);self.assertNotEqual(imported.profile_id,saved.profile_id)

if __name__=='__main__':unittest.main(verbosity=2)
