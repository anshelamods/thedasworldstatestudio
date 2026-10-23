"""Awakening mappings, local history, cross-game proposals and compatibility."""
from itertools import product
from pathlib import Path
import tempfile
import unittest

from export_worldstate import ROOT, read_mod
from gui import EditorApp
from world_profiles import Catalog, ProfileStore
from world_profiles.compiler import StoryConflict, build_profile_mod, compile_profile


class AwakeningTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.catalog=Catalog()

 def test_all_36_combinations_across_nine_presets_preserve_unrelated_fields_and_ranges(self):
  for preset in self.catalog.presets:
   base=self.catalog.create('Awakening',base_preset=preset,mode='experimental')
   original=compile_profile(base,catalog=self.catalog)
   for architect,nathaniel,protection,felsi in product(('killed','spared'),('dead','alive'),('keep','amaranthine','both'),('not_helped','reunited','parted')):
    p=base.edited(choices={'dao.architect_fate':architect,'dao.nathaniel_fate':nathaniel,'dao.awakening_protection':protection,'dao.oghren_felsi':felsi})
    c=compile_profile(p,catalog=self.catalog)
    wanted=dict(dao_awakenings_architect_fate=int(architect=='spared'),dao_awakenings_nathaniel_live=int(nathaniel=='alive'))
    self.assertEqual(dict(c.values),{**dict(original.values),**wanted})
    self.assertEqual(dict(c.effective_values),{**dict(original.effective_values),**wanted})
    self.assertEqual(dict(c.max_overrides),{})
    self.assertEqual(c.effective_values['dao_awakenings_played'],original.effective_values['dao_awakenings_played'])
    self.assertNotIn('dao_awakening_keep_protected',c.effective_values);self.assertNotIn('dao_awakening_oghren_felsi',c.effective_values)

 def test_local_answers_change_no_game_payload_and_begin_unselected(self):
  p=self.catalog.create('Local Awakening',mode='experimental');raw,_=build_profile_mod(p,catalog=self.catalog)
  c=compile_profile(p,catalog=self.catalog)
  for key in ('dao.awakening_protection','dao.oghren_felsi'):
   self.assertIsNone(c.report['resolved_choices'][key]['answer_id'])
   for answer in self.catalog.choices[key]['answers']:
    changed,_=build_profile_mod(p.edited(choices={key:answer}),catalog=self.catalog)
    self.assertEqual(read_mod(changed)['ebx'],read_mod(raw)['ebx'])

 def test_recruitment_dependency_truth_table_and_free_mode(self):
  for felsi,recruit in product((None,'not_helped','reunited','parted'),('not_recruited','recruited')):
   choices={'dao.dagna_outcome':'not_met','dao.oghren_recruited':recruit}
   if felsi:choices['dao.oghren_felsi']=felsi
   p=self.catalog.create('Felsi',mode='keep',choices=choices)
   if felsi in ('reunited','parted') and recruit=='not_recruited':
    with self.assertRaises(StoryConflict):compile_profile(p,catalog=self.catalog)
   else:compile_profile(p,catalog=self.catalog)
   self.assertEqual(compile_profile(p.edited(mode='experimental'),catalog=self.catalog).effective_values['dao_oghren_recruited'],int(recruit=='recruited'))

 def test_both_directions_of_felsi_proposal_preserve_requested_answers_and_history(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as d:
   app=EditorApp(Path(d)/'profiles',Path(d)/'exports');saved=app.store.create('Oghren',mode='keep',choices={'dao.dagna_outcome':'not_met','dao.oghren_recruited':'not_recruited'})
   draft={k:saved.to_dict()[k] for k in ('profile_id','revision','name','base_preset','mode','choices')}
   snapshot={str(p):p.read_bytes() for p in Path(d).rglob('*') if p.is_file()}
   for answer in ('reunited','parted'):
    r=app.propose(dict(draft=draft,updates={'dao.oghren_felsi':answer},mode='keep'))
    self.assertEqual(r['draft']['choices']['dao.oghren_felsi'],answer);self.assertEqual(r['draft']['choices']['dao.oghren_recruited'],'recruited')
    self.assertEqual({x['choice_id'] for x in r['changes']},{'dao.oghren_recruited'})
    reverse=app.propose(dict(draft=r['draft'],updates={'dao.oghren_recruited':'not_recruited'},mode='keep'))
    self.assertEqual(reverse['draft']['choices']['dao.oghren_felsi'],'not_helped')
    self.assertEqual(reverse['draft']['choices']['dao.oghren_recruited'],'not_recruited')
    free=app.propose(dict(draft=draft,updates={'dao.oghren_felsi':answer},mode='experimental'))
    self.assertEqual(free['changes'],[]);self.assertEqual(free['draft']['choices']['dao.oghren_recruited'],'not_recruited')
   self.assertEqual(snapshot,{str(p):p.read_bytes() for p in Path(d).rglob('*') if p.is_file()})

 def test_nathaniel_promotion_preserves_cross_game_proposals(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as d:
   app=EditorApp(Path(d)/'profiles',Path(d)/'exports');saved=app.store.create('Nathaniel',mode='keep',choices={'dao.dagna_outcome':'not_met','dao.nathaniel_fate':'alive','da2.finding_nathaniel':'rescued'})
   draft={k:saved.to_dict()[k] for k in ('profile_id','revision','name','base_preset','mode','choices')}
   r=app.propose(dict(draft=draft,updates={'dao.nathaniel_fate':'dead'},mode='keep'))
   self.assertEqual(r['draft']['choices']['da2.finding_nathaniel'],'not_survived')
   reverse=app.propose(dict(draft=r['draft'],updates={'da2.finding_nathaniel':'rescued'},mode='keep'))
   self.assertEqual(reverse['draft']['choices']['dao.nathaniel_fate'],'alive')
   self.assertEqual(app.store.load(saved.profile_id),saved)

 def test_catalog36_payload_history_and_local_portable_roundtrips(self):
  old=Catalog(mapping_version=36)
  for preset in old.presets:
   for fate in ('alive','dead'):
    p=old.create('Old Awakening',base_preset=preset,mode='experimental',choices={'dao.nathaniel_fate':fate})
    upgraded=self.catalog.upgrade(p);before,_=build_profile_mod(p,catalog=self.catalog);after,_=build_profile_mod(upgraded,catalog=self.catalog)
    self.assertEqual(read_mod(before)['ebx'],read_mod(after)['ebx'])
    for key in ('dao.architect_fate','dao.awakening_protection','dao.oghren_felsi'):self.assertNotIn(key,upgraded.choices)
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as d:
   store=ProfileStore(Path(d)/'profiles',catalog=old);p=store.create('History',mode='keep',choices={'dao.dagna_outcome':'not_met'})
   snapshot={str(p):p.read_bytes() for p in Path(d).rglob('*') if p.is_file()};self.catalog.upgrade(p)
   self.assertEqual(snapshot,{str(p):p.read_bytes() for p in Path(d).rglob('*') if p.is_file()})
   current=ProfileStore(Path(d)/'new',catalog=self.catalog)
   for protection,felsi in product(('keep','amaranthine','both'),('not_helped','reunited','parted')):
    saved=current.create('Local history',mode='experimental',choices={'dao.awakening_protection':protection,'dao.oghren_felsi':felsi})
    path=Path(d)/(saved.profile_id+'.json');current.export_json(saved.profile_id,path);imported=current.import_profile(path)
    self.assertEqual(imported.choices,saved.choices);self.assertNotEqual(imported.profile_id,saved.profile_id)

if __name__=='__main__':unittest.main(verbosity=2)
