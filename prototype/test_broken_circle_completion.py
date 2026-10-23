"""Local Cullen history, guarded dependencies and historical compatibility."""
from itertools import product
from pathlib import Path
import tempfile
import unittest

from export_worldstate import ROOT, read_mod
from gui import EditorApp
from world_profiles import Catalog, ProfileStore
from world_profiles.compiler import StoryConflict, build_profile_mod, compile_profile
from world_profiles.story_rules import RuleSet

class BrokenCircleCompletionTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.catalog=Catalog()

 def test_local_answers_never_serialize_or_fabricate_an_inherited_answer(self):
  profile=self.catalog.create('Circle',mode='experimental',choices={'dao.dagna_outcome':'not_met'})
  raw,_=build_profile_mod(profile,catalog=self.catalog)
  self.assertIsNone(compile_profile(profile,catalog=self.catalog).report['resolved_choices']['dao.cullen_request']['answer_id'])
  for answer in ('disagreed','agreed'):
   changed=profile.edited(choices={**profile.choices,'dao.cullen_request':answer});compiled=compile_profile(changed,catalog=self.catalog);other,_=build_profile_mod(changed,catalog=self.catalog)
   self.assertEqual(read_mod(raw)['ebx'],read_mod(other)['ebx']);self.assertEqual(len(compiled.effective_values),382)
   self.assertNotIn('dao_broken_circle_cullen_request',compiled.effective_values);self.assertNotIn('dao_broken_circle_cullen_request',compiled.values)

 def test_48_strict_combinations_and_free_mode_preserve_unknown_local_history(self):
  fates=('not_recruited','alive','died_at_circle','killed_at_urn')
  for cullen,irving,side,fate in product((None,'disagreed','agreed'),('dead','alive'),('mages','templars'),fates):
   choices={'dao.dagna_outcome':'not_met','dao.connor_fate':'dead','dao.urn_poisoned':'poisoned','dao.irving_fate':irving,'dao.broken_circle':side,'dao.wynne_fate':fate}
   if cullen:choices['dao.cullen_request']=cullen
   profile=self.catalog.create('Circle truth table',mode='keep',choices=choices)
   valid=(side!='mages' or irving=='alive') and (cullen!='agreed' or (irving=='dead' and fate == 'died_at_circle'))
   if valid:compile_profile(profile,catalog=self.catalog)
   else:
    with self.assertRaises(StoryConflict):compile_profile(profile,catalog=self.catalog)
   compile_profile(profile.edited(mode='experimental'),catalog=self.catalog)
  # Solver evaluation supplies virtual local inputs directly, while compiler
  # validation supplies them through choices; both must activate the same gates.
  base=compile_profile(self.catalog.create('Base',mode='experimental',choices={'dao.dagna_outcome':'not_met'}),catalog=self.catalog)
  rules=RuleSet(self.catalog);field='dao_broken_circle_cullen_request'
  self.assertEqual(rules.violations(base.effective_values,preset_id=self.catalog.default_preset),[])
  self.assertEqual(rules.violations(base.effective_values,{'dao.cullen_request':'agreed'}),rules.violations({**base.effective_values,field:1}))

 def test_agreement_proposal_repairs_game_fields_but_cancellation_writes_nothing(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as directory:
   app=EditorApp(Path(directory)/'profiles',Path(directory)/'exports');saved=app.store.create('Circle',base_preset='early-tests-v1',mode='keep',choices={'dao.dagna_outcome':'not_met'})
   draft={k:saved.to_dict()[k] for k in ('profile_id','revision','name','base_preset','mode','choices')};snapshot={str(p):p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()}
   response=app.propose(dict(draft=draft,updates={'dao.cullen_request':'agreed'},mode='keep'));compiled=compile_profile(app.draft(response['draft']),catalog=self.catalog)
   self.assertEqual(response['draft']['choices']['dao.cullen_request'],'agreed')
   for field,value in {'dao_bc_irving_survive':0,'dao_wynne_recruited':0,'dao_broken_circle_choice':1}.items():self.assertEqual(compiled.effective_values[field],value)
   self.assertEqual(compiled.effective_values['dao_wynne_fate'],2)
   self.assertEqual({c['choice_id'] for c in response['changes']},{'dao.irving_fate','dao.wynne_fate','dao.wynne_recruited','dao.broken_circle','dao.isolde_fate'})
   self.assertEqual(snapshot,{str(p):p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()})
   self.assertEqual(app.store.load(saved.profile_id),saved)

 def test_irving_or_wynne_request_can_propose_changing_explicit_cullen_history(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as directory:
   app=EditorApp(Path(directory)/'profiles',Path(directory)/'exports');base=app.catalog.create('Circle',mode='keep',choices={'dao.dagna_outcome':'not_met'})
   draft={k:base.to_dict()[k] for k in ('profile_id','revision','name','base_preset','mode','choices')};draft.update(profile_id=None,revision=0)
   agreed=app.propose(dict(draft=draft,updates={'dao.cullen_request':'agreed'},mode='keep'))['draft']
   for key,answer in [('dao.irving_fate','alive'),('dao.wynne_recruited','recruited')]:
    response=app.propose(dict(draft=agreed,updates={key:answer},mode='keep'))
    self.assertEqual(response['draft']['choices'][key],answer);self.assertEqual(response['draft']['choices']['dao.cullen_request'],'disagreed')
    compile_profile(app.draft(response['draft']),catalog=self.catalog)
   free=app.propose(dict(draft=draft,updates={'dao.cullen_request':'agreed'},mode='experimental'))
   self.assertEqual(free['changes'],[])

 def test_catalog35_upgrade_preserves_payload_without_selecting_cullen(self):
  old=Catalog(mapping_version=35)
  for preset in old.presets:
   profile=old.create('Catalog35',base_preset=preset,mode='experimental',choices={'dao.wynne_fate':'alive','dao.wynne_recruited':'recruited'})
   upgraded=self.catalog.upgrade(profile);before,_=build_profile_mod(profile,catalog=self.catalog);after,_=build_profile_mod(upgraded,catalog=self.catalog)
   self.assertEqual(read_mod(before)['ebx'],read_mod(after)['ebx']);self.assertNotIn('dao.cullen_request',upgraded.choices)
  profile=old.create('Strict35',mode='keep',choices={'dao.dagna_outcome':'not_met'});compile_profile(self.catalog.upgrade(profile),catalog=self.catalog)
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as directory:
   store=ProfileStore(Path(directory)/'profiles',catalog=old);saved=store.create('History',mode='keep',choices={'dao.dagna_outcome':'not_met'})
   snapshot={str(p):p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()};self.catalog.upgrade(saved)
   self.assertEqual(snapshot,{str(p):p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()})

 def test_cullen_answers_survive_portable_profile_roundtrip(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as directory:
   store=ProfileStore(Path(directory)/'profiles',catalog=self.catalog)
   for answer in ('disagreed','agreed'):
    saved=store.create('Cullen',mode='experimental',choices={'dao.cullen_request':answer});path=Path(directory)/(saved.profile_id+'.json');store.export_json(saved.profile_id,path);imported=store.import_profile(path)
    self.assertEqual(imported.choices,saved.choices);self.assertNotEqual(imported.profile_id,saved.profile_id)

if __name__=='__main__':unittest.main(verbosity=2)
