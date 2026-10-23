"""Keep-only Soldier's Peak history must never alter DAI world-state bytes."""
from itertools import product
from pathlib import Path
import tempfile
import unittest

from export_worldstate import ROOT, read_mod
from gui import EditorApp
from world_profiles import Catalog, ProfileStore
from world_profiles.compiler import build_profile_mod, compile_profile

PAIRS=tuple(product(('drank','did_not_drink'),('both_perished','sided_sophia','unrestricted_research','ethical_research')))


class WardensKeepTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.catalog=Catalog()

 def test_all_eight_combinations_preserve_payloads_across_every_preset_and_allow_strict_mode(self):
  for preset in self.catalog.presets:
   base=self.catalog.create('Wardens Keep',base_preset=preset,mode='experimental');raw,_=build_profile_mod(base,catalog=self.catalog)
   original=compile_profile(base,catalog=self.catalog)
   for blood,avernus in PAIRS:
    p=base.edited(choices={'dao.power_of_blood':blood,'dao.avernus_fate':avernus});other,_=build_profile_mod(p,catalog=self.catalog);c=compile_profile(p,catalog=self.catalog)
    self.assertEqual(read_mod(raw)['ebx'],read_mod(other)['ebx'])
    self.assertEqual(c.effective_values,original.effective_values);self.assertEqual(c.values,original.values);self.assertEqual(c.max_overrides,original.max_overrides)
    self.assertEqual(c.report['resolved_choices']['dao.power_of_blood']['answer_id'],blood)
    self.assertEqual(c.report['resolved_choices']['dao.avernus_fate']['answer_id'],avernus)
  for blood,avernus in PAIRS:
   p=self.catalog.create('Strict Keep history',mode='keep',choices={'dao.dagna_outcome':'not_met','dao.power_of_blood':blood,'dao.avernus_fate':avernus})
   self.assertEqual(compile_profile(p,catalog=self.catalog).report['story_conflicts'],[])

 def test_unselected_defaults_portable_roundtrips_and_clearing(self):
  base=self.catalog.create('No inferred answers',mode='experimental');c=compile_profile(base,catalog=self.catalog)
  for key in ('dao.power_of_blood','dao.avernus_fate'):
   self.assertIsNone(c.report['resolved_choices'][key]['answer_id'])
   self.assertEqual(self.catalog.choices[key]['export_behavior'],'profile-only')
   for answer in self.catalog.choices[key]['answers'].values():self.assertEqual(answer['export_values'],{})
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as d:
   store=ProfileStore(Path(d)/'profiles',catalog=self.catalog)
   for blood,avernus in PAIRS:
    p=store.create('Portable Keep',mode='keep',choices={'dao.dagna_outcome':'not_met','dao.power_of_blood':blood,'dao.avernus_fate':avernus})
    path=Path(d)/(p.profile_id+'.json');store.export_json(p.profile_id,path);imported=store.import_profile(path)
    self.assertEqual(imported.choices,p.choices);self.assertNotEqual(imported.profile_id,p.profile_id)
    cleared=p.edited(choices={'dao.dagna_outcome':'not_met'})
    for key in ('dao.power_of_blood','dao.avernus_fate'):self.assertIsNone(compile_profile(cleared,catalog=self.catalog).report['resolved_choices'][key]['answer_id'])

 def test_proposals_need_no_related_changes_and_do_not_write_history(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as d:
   app=EditorApp(Path(d)/'profiles',Path(d)/'exports');saved=app.store.create('Keep',mode='keep',choices={'dao.dagna_outcome':'not_met'})
   draft={k:saved.to_dict()[k] for k in ('profile_id','revision','name','base_preset','mode','choices')}
   snapshot={str(p):p.read_bytes() for p in Path(d).rglob('*') if p.is_file()}
   for mode,(blood,avernus) in product(('keep','experimental'),PAIRS):
    r=app.propose(dict(draft=draft,updates={'dao.power_of_blood':blood,'dao.avernus_fate':avernus},mode=mode))
    self.assertEqual(r['changes'],[]);self.assertEqual(r['draft']['choices'],{**draft['choices'],'dao.power_of_blood':blood,'dao.avernus_fate':avernus})
   self.assertEqual(snapshot,{str(p):p.read_bytes() for p in Path(d).rglob('*') if p.is_file()});self.assertEqual(app.store.load(saved.profile_id),saved)

 def test_catalog37_upgrade_preserves_original_payload_rules_and_saved_history(self):
  old=Catalog(mapping_version=37);self.assertEqual(old.story_rules,Catalog(mapping_version=38).story_rules)
  for preset in old.presets:
   p=old.create('Old history',base_preset=preset,mode='experimental',choices={'dao.architect_fate':'spared','dao.awakening_protection':'both','dao.oghren_felsi':'parted'})
   upgraded=self.catalog.upgrade(p);before,_=build_profile_mod(p,catalog=self.catalog);after,_=build_profile_mod(upgraded,catalog=self.catalog)
   self.assertEqual(read_mod(before)['ebx'],read_mod(after)['ebx'])
   self.assertNotIn('dao.power_of_blood',upgraded.choices);self.assertNotIn('dao.avernus_fate',upgraded.choices)
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as d:
   store=ProfileStore(Path(d)/'profiles',catalog=old);p=store.create('History',mode='keep',choices={'dao.dagna_outcome':'not_met'})
   snapshot={str(p):p.read_bytes() for p in Path(d).rglob('*') if p.is_file()};self.catalog.upgrade(p)
   self.assertEqual(snapshot,{str(p):p.read_bytes() for p in Path(d).rglob('*') if p.is_file()})

if __name__=='__main__':unittest.main(verbosity=2)
