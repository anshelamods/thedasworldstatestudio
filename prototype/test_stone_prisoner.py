"""Shale mappings, captured Branka gates, local Kitty history and compatibility."""
from itertools import product
from pathlib import Path
import tempfile
import unittest

from export_worldstate import ROOT, read_mod
from gui import EditorApp
from world_profiles import Catalog, ProfileStore
from world_profiles.compiler import StoryConflict, build_profile_mod, compile_profile

FATES=('not_recruited','alive','died_with_branka')
RECRUIT=('not_recruited','recruited')
KITTY=('both_unpossessed','amalia_possessed','matthias_possessed','matthias_dead','amalia_dead')
ANVILS=('warden_destroyed','branka_destroyed','preserved')


class StonePrisonerTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.catalog=Catalog()

 def test_all_30_combinations_across_nine_presets_preserve_unrelated_values_and_ranges(self):
  for preset in self.catalog.presets:
   base=self.catalog.create('Stone Prisoner',base_preset=preset,mode='experimental');original=compile_profile(base,catalog=self.catalog)
   for fate,recruit,kitty in product(FATES,RECRUIT,KITTY):
    p=base.edited(choices={'dao.shale_fate':fate,'dao.shale_recruited':recruit,'dao.kitty_amalia':kitty});c=compile_profile(p,catalog=self.catalog)
    wanted=dict(dao_shale_fate=FATES.index(fate),dao_shale_recruited=RECRUIT.index(recruit))
    self.assertEqual(dict(c.effective_values),{**dict(original.effective_values),**wanted})
    self.assertEqual(dict(c.values),{**dict(original.values),**wanted});self.assertEqual(dict(c.max_overrides),{})
    self.assertNotIn('dao_stone_prisoner_kitty',c.effective_values)

 def test_all_18_recruitment_fate_anvil_combinations_match_captured_rules(self):
  for fate,recruit,anvil in product(FATES,RECRUIT,ANVILS):
   p=self.catalog.create('Strict Shale',mode='keep',choices={'dao.dagna_outcome':'not_met','dao.shale_fate':fate,'dao.shale_recruited':recruit,'dao.anvil_fate':anvil})
   valid=(fate!='not_recruited' or recruit=='not_recruited') and (fate!='died_with_branka' or (recruit=='recruited' and anvil!='warden_destroyed'))
   if valid:compile_profile(p,catalog=self.catalog)
   else:
    with self.assertRaises(StoryConflict):compile_profile(p,catalog=self.catalog)
   compile_profile(p.edited(mode='experimental'),catalog=self.catalog)
  # The captured Keep has no recruitment prerequisite on its alive answer.
  compile_profile(self.catalog.create('Captured alive semantics',mode='keep',choices={'dao.dagna_outcome':'not_met','dao.shale_fate':'alive','dao.shale_recruited':'not_recruited'}),catalog=self.catalog)

 def test_recruitment_and_anvil_proposals_lock_requests_and_never_write_history(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as d:
   app=EditorApp(Path(d)/'profiles',Path(d)/'exports');saved=app.store.create('Shale',mode='keep',choices={'dao.dagna_outcome':'not_met'})
   draft={k:saved.to_dict()[k] for k in ('profile_id','revision','name','base_preset','mode','choices')};snapshot={str(p):p.read_bytes() for p in Path(d).rglob('*') if p.is_file()}
   absent=app.propose(dict(draft=draft,updates={'dao.shale_fate':'not_recruited'},mode='keep'))
   self.assertEqual(absent['draft']['choices']['dao.shale_fate'],'not_recruited');self.assertEqual(absent['draft']['choices']['dao.shale_recruited'],'not_recruited')
   recruited=app.propose(dict(draft=absent['draft'],updates={'dao.shale_recruited':'recruited'},mode='keep'))
   self.assertEqual(recruited['draft']['choices']['dao.shale_fate'],'alive')
   dead=app.propose(dict(draft=absent['draft'],updates={'dao.shale_fate':'died_with_branka'},mode='keep'))
   self.assertEqual(dead['draft']['choices']['dao.shale_fate'],'died_with_branka');self.assertEqual(dead['draft']['choices']['dao.shale_recruited'],'recruited')
   self.assertIn(dead['draft']['choices']['dao.anvil_fate'],('branka_destroyed','preserved'))
   self.assertEqual({c['choice_id'] for c in dead['changes']},{'dao.shale_recruited','dao.anvil_fate'})
   reverse=app.propose(dict(draft=dead['draft'],updates={'dao.anvil_fate':'warden_destroyed'},mode='keep'))
   self.assertEqual(reverse['draft']['choices']['dao.anvil_fate'],'warden_destroyed');self.assertEqual(reverse['draft']['choices']['dao.shale_fate'],'alive')
   free=app.propose(dict(draft=draft,updates={'dao.shale_fate':'died_with_branka','dao.shale_recruited':'not_recruited'},mode='experimental'))
   self.assertEqual(free['changes'],[]);self.assertEqual(free['draft']['choices']['dao.shale_recruited'],'not_recruited')
   self.assertEqual(snapshot,{str(p):p.read_bytes() for p in Path(d).rglob('*') if p.is_file()});self.assertEqual(app.store.load(saved.profile_id),saved)

 def test_all_kitty_answers_preserve_game_bytes_and_roundtrip_locally(self):
  base=self.catalog.create('Local Kitty',mode='experimental');raw,_=build_profile_mod(base,catalog=self.catalog)
  self.assertIsNone(compile_profile(base,catalog=self.catalog).report['resolved_choices']['dao.kitty_amalia']['answer_id'])
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as d:
   store=ProfileStore(Path(d)/'profiles',catalog=self.catalog)
   for answer in KITTY:
    p=base.edited(choices={'dao.kitty_amalia':answer});other,_=build_profile_mod(p,catalog=self.catalog)
    self.assertEqual(read_mod(raw)['ebx'],read_mod(other)['ebx'])
    saved=store.create('Kitty',mode='experimental',choices=dict(p.choices));path=Path(d)/(saved.profile_id+'.json');store.export_json(saved.profile_id,path);imported=store.import_profile(path)
    self.assertEqual(saved.choices,imported.choices);self.assertNotEqual(saved.profile_id,imported.profile_id)

 def test_catalog38_upgrade_preserves_every_preset_payload_and_saved_history(self):
  old=Catalog(mapping_version=38)
  for preset in old.presets:
   p=old.create('Old history',base_preset=preset,mode='experimental',choices={'dao.power_of_blood':'drank','dao.avernus_fate':'ethical_research'})
   upgraded=self.catalog.upgrade(p);before,_=build_profile_mod(p,catalog=self.catalog);after,_=build_profile_mod(upgraded,catalog=self.catalog)
   self.assertEqual(read_mod(before)['ebx'],read_mod(after)['ebx'])
   for key in ('dao.shale_fate','dao.shale_recruited','dao.kitty_amalia'):self.assertNotIn(key,upgraded.choices)
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as d:
   store=ProfileStore(Path(d)/'profiles',catalog=old);p=store.create('History',mode='keep',choices={'dao.dagna_outcome':'not_met'})
   snapshot={str(p):p.read_bytes() for p in Path(d).rglob('*') if p.is_file()};compile_profile(self.catalog.upgrade(p),catalog=self.catalog)
   self.assertEqual(snapshot,{str(p):p.read_bytes() for p in Path(d).rglob('*') if p.is_file()})

if __name__=='__main__':unittest.main(verbosity=2)
