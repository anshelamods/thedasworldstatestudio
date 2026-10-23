"""Witch Hunt boolean mapping, explicit Keep extension and transactional gates."""
from itertools import product
from pathlib import Path
import tempfile
import unittest

from export_worldstate import ROOT, EbxParser, read_mod
from gui import EditorApp
from world_profiles import Catalog, ProfileStore
from world_profiles.compiler import StoryConflict, build_profile_mod, compile_profile
from world_profiles.story_rules import propose

ANSWERS=('did_not_follow','followed','stabbed')


class WitchHuntTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.catalog=Catalog()

 def test_all_answers_across_nine_presets_change_only_the_reviewed_field_and_answer_specific_range(self):
  for preset in self.catalog.presets:
   base=self.catalog.create('Witch Hunt',base_preset=preset,mode='experimental');original=compile_profile(base,catalog=self.catalog)
   for value,answer in enumerate(ANSWERS):
    p=base.edited(choices={'dao.witch_hunt':answer});c=compile_profile(p,catalog=self.catalog);data,_=build_profile_mod(p,catalog=self.catalog)
    self.assertEqual(dict(c.effective_values),{**dict(original.effective_values),'dao_warden_eluvian':value})
    self.assertEqual(dict(c.values),{**dict(original.values),'dao_warden_eluvian':value})
    self.assertEqual(dict(c.max_overrides),{'dao_warden_eluvian':2} if value==2 else {})
    objects={o['value']['VariableNameOnServer']:o['value'] for o in EbxParser(read_mod(data)['ebx']).parse()['objects'] if o['class']=='GameVaultVarInt'}
    field=objects['dao_warden_eluvian'];self.assertEqual(field['DefaultValue'],value)
    self.assertEqual((field['MinValue'],field['MaxValue']),(0,2 if value==2 else 1))
    self.assertEqual(field['PlotFlag']['PlotFlagId']['Guid'],'67824ec6-f5b1-46a3-8ba9-a35724f5015c')
    self.assertEqual(len(objects),382)

 def test_twelve_romance_survival_outcome_combinations_and_unrestricted_bypass(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as d:
   app=EditorApp(Path(d)/'profiles',Path(d)/'exports');base=self.catalog.create('Consistent',mode='keep',choices={'dao.dagna_outcome':'not_met'})
   for romance,survival in product(('none','morrigan'),('alive','sacrificed')):
    consistent=propose(base,{'dao.warden_romance':romance,'dao.warden_fate':survival},mode='keep',catalog=self.catalog,editable=app.presentation)
    for answer in ANSWERS:
     p=consistent.edited(choices={**consistent.choices,'dao.witch_hunt':answer})
     if answer=='followed' and (romance!='morrigan' or survival!='alive'):
      with self.assertRaises(StoryConflict):compile_profile(p,catalog=self.catalog)
     else:compile_profile(p,catalog=self.catalog)
     self.assertEqual(compile_profile(p.edited(mode='experimental'),catalog=self.catalog).effective_values['dao_warden_eluvian'],ANSWERS.index(answer))

 def test_follow_proposals_repair_identity_romance_survival_and_reverse_gates_without_writes(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as d:
   app=EditorApp(Path(d)/'profiles',Path(d)/'exports');saved=app.store.create('Witch Hunt',mode='keep',choices={'dao.dagna_outcome':'not_met'})
   draft={k:saved.to_dict()[k] for k in ('profile_id','revision','name','base_preset','mode','choices')};snapshot={str(p):p.read_bytes() for p in Path(d).rglob('*') if p.is_file()}
   followed=app.propose(dict(draft=draft,updates={'dao.witch_hunt':'followed'},mode='keep'))
   c=compile_profile(app.draft(followed['draft']),catalog=self.catalog)
   for key,value in {'dao_warden_eluvian':1,'dao_warden_romance':2,'dao_warden_state':1,'dao_warden_alive':1,'dao_warden_mf':0}.items():self.assertEqual(c.effective_values[key],value)
   self.assertEqual({x['choice_id'] for x in followed['changes']},{'dao.warden_identity','dao.warden_romance','dao.warden_fate','dao.morrigan_child'})
   reverse=app.propose(dict(draft=followed['draft'],updates={'dao.warden_romance':'none'},mode='keep'))
   self.assertEqual(reverse['draft']['choices']['dao.witch_hunt'],'did_not_follow')
   dead=app.propose(dict(draft=followed['draft'],updates={'dao.warden_fate':'sacrificed'},mode='keep'))
   self.assertNotEqual(dead['draft']['choices']['dao.witch_hunt'],'followed')
   revived=app.propose(dict(draft=dead['draft'],updates={'dao.witch_hunt':'followed'},mode='keep'))
   self.assertEqual(revived['draft']['choices']['dao.warden_fate'],'alive');self.assertEqual(revived['draft']['choices']['dao.witch_hunt'],'followed')
   free=app.propose(dict(draft=draft,updates={'dao.witch_hunt':'followed'},mode='experimental'))
   self.assertEqual(free['changes'],[])
   self.assertEqual(snapshot,{str(p):p.read_bytes() for p in Path(d).rglob('*') if p.is_file()});self.assertEqual(app.store.load(saved.profile_id),saved)

 def test_follow_preserves_every_origin_and_class_when_only_gender_needs_to_change(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as d:
   app=EditorApp(Path(d)/'profiles',Path(d)/'exports')
   origins={'human_noble':'warrior','human_mage':'mage','dalish_elf':'rogue','city_elf':'rogue','elven_mage':'mage','dwarf_noble':'warrior','dwarf_commoner':'rogue'}
   for origin,job in origins.items():
    p=self.catalog.create('Preserve origin',mode='keep',choices={'dao.dagna_outcome':'not_met','dao.warden_identity':'female_'+origin,'dao.warden_class':job})
    result=propose(p,{'dao.witch_hunt':'followed'},mode='keep',catalog=self.catalog,editable=app.presentation)
    self.assertEqual(result.choices['dao.warden_identity'],'male_'+origin)
    self.assertEqual(result.choices['dao.warden_class'],job)
    self.assertEqual(result.choices['dao.warden_romance'],'morrigan')

 def test_catalog39_upgrade_portable_answers_and_clearing_preserve_history_and_original_range(self):
  old=Catalog(mapping_version=39)
  for preset in old.presets:
   p=old.create('Old Witch Hunt',base_preset=preset,mode='experimental',choices={'dao.shale_fate':'alive','dao.kitty_amalia':'both_unpossessed'})
   upgraded=self.catalog.upgrade(p);before,_=build_profile_mod(p,catalog=self.catalog);after,_=build_profile_mod(upgraded,catalog=self.catalog)
   self.assertEqual(read_mod(before)['ebx'],read_mod(after)['ebx']);self.assertNotIn('dao.witch_hunt',upgraded.choices)
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as d:
   store=ProfileStore(Path(d)/'old',catalog=old);saved=store.create('History',mode='keep',choices={'dao.dagna_outcome':'not_met'})
   snapshot={str(p):p.read_bytes() for p in Path(d).rglob('*') if p.is_file()};compile_profile(self.catalog.upgrade(saved),catalog=self.catalog)
   self.assertEqual(snapshot,{str(p):p.read_bytes() for p in Path(d).rglob('*') if p.is_file()})
   current=ProfileStore(Path(d)/'current',catalog=self.catalog)
   for answer in ANSWERS:
    p=current.create('Portable Witch Hunt',mode='experimental',choices={'dao.witch_hunt':answer});path=Path(d)/(p.profile_id+'.json');current.export_json(p.profile_id,path);imported=current.import_profile(path)
    self.assertEqual(imported.choices,p.choices);self.assertNotEqual(imported.profile_id,p.profile_id)
   cleared=p.edited(choices={});c=compile_profile(cleared,catalog=self.catalog)
   self.assertEqual(c.report['resolved_choices']['dao.witch_hunt']['answer_id'],'did_not_follow');self.assertEqual(dict(c.max_overrides),{})

if __name__=='__main__':unittest.main(verbosity=2)
