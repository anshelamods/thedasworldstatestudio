"""Independent companion fields, Wynne ownership and preserved legacy payloads."""
from itertools import product
from pathlib import Path
import tempfile
import unittest

from export_worldstate import ROOT, read_mod
from gui import EditorApp
from world_profiles import Catalog, ProfileStore
from world_profiles.compiler import StoryConflict, build_profile_mod, compile_profile
from test_da2_main_story import flags_from_mod

RECRUITS=('not_recruited','recruited')
FATES={'not_recruited':(0,0),'alive':(1,1),'died_at_circle':(2,0),'killed_at_urn':(3,1)}
GRIMOIRE=('not_acquired','peaceful','defeated_flemeth')

class RemainingOriginsCompanionTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.catalog=Catalog()

 def test_all_48_combinations_across_nine_presets_allow_free_history(self):
  for preset in self.catalog.presets:
   for (fate,(value,fallback)),recruit,oghren,grimoire in product(FATES.items(),RECRUITS,RECRUITS,GRIMOIRE):
    profile=self.catalog.create('Companions',base_preset=preset,mode='experimental',choices={'dao.wynne_fate':fate,'dao.wynne_recruited':recruit,'dao.oghren_recruited':oghren,'dao.flemeth_grimoire':grimoire})
    compiled=compile_profile(profile,catalog=self.catalog)
    self.assertEqual(compiled.effective_values['dao_wynne_fate'],value)
    self.assertEqual(compiled.effective_values['dao_wynne_recruited'],RECRUITS.index(recruit))
    self.assertEqual(compiled.effective_values['dao_oghren_recruited'],RECRUITS.index(oghren))
    self.assertEqual(compiled.report['resolved_choices']['dao.wynne_fate']['answer_id'],fate)

 def test_explicit_recruitment_owns_only_its_boolean_and_clearing_restores_fate_fallback(self):
  for fate,(value,fallback) in FATES.items():
   profile=self.catalog.create('Wynne',mode='experimental',choices={'dao.wynne_fate':fate})
   before=compile_profile(profile,catalog=self.catalog)
   for answer in RECRUITS:
    changed=profile.edited(choices={**profile.choices,'dao.wynne_recruited':answer})
    after=compile_profile(changed,catalog=self.catalog)
    self.assertEqual({k:v for k,v in before.effective_values.items() if k!='dao_wynne_recruited'},{k:v for k,v in after.effective_values.items() if k!='dao_wynne_recruited'})
    self.assertEqual(after.effective_values['dao_wynne_recruited'],RECRUITS.index(answer))
    cleared=changed.edited(choices={k:v for k,v in changed.choices.items() if k!='dao.wynne_recruited'})
    raw,_=build_profile_mod(profile,catalog=self.catalog);restored,_=build_profile_mod(cleared,catalog=self.catalog)
    self.assertEqual(read_mod(raw)['ebx'],read_mod(restored)['ebx']);self.assertEqual(compile_profile(cleared,catalog=self.catalog).effective_values['dao_wynne_recruited'],fallback)

 def test_all_fate_recruit_pairs_serialize_without_duplicate_owners_and_keep_original_ranges(self):
  for fate,(value,fallback) in FATES.items():
   for recruit,oghren in product(RECRUITS,RECRUITS):
    raw,_=build_profile_mod(self.catalog.create('Payload',mode='experimental',choices={'dao.wynne_fate':fate,'dao.wynne_recruited':recruit,'dao.oghren_recruited':oghren}),catalog=self.catalog)
    flags=flags_from_mod(raw)
    self.assertEqual(flags['dao_wynne_fate']['DefaultValue'],value)
    for field,answer in [('dao_wynne_recruited',recruit),('dao_oghren_recruited',oghren)]:
     self.assertEqual(flags[field]['DefaultValue'],RECRUITS.index(answer));self.assertEqual(flags[field]['MaxValue'],1);self.assertEqual(flags[field]['MinValue'],0)
    self.assertEqual(flags['dao_wynne_fate']['MaxValue'],3)

 def test_grimoire_is_unselected_until_chosen_and_never_changes_ebx_bytes(self):
  profile=self.catalog.create('Grimoire',mode='experimental');raw,_=build_profile_mod(profile,catalog=self.catalog)
  self.assertIsNone(compile_profile(profile,catalog=self.catalog).report['resolved_choices']['dao.flemeth_grimoire']['answer_id'])
  for answer in GRIMOIRE:
   changed=profile.edited(choices={'dao.flemeth_grimoire':answer});other,_=build_profile_mod(changed,catalog=self.catalog)
   compiled=compile_profile(changed,catalog=self.catalog)
   self.assertEqual(read_mod(raw)['ebx'],read_mod(other)['ebx']);self.assertEqual(len(compiled.effective_values),382)
   self.assertNotIn('dao_flemeth_grimoire',compiled.values);self.assertNotIn('dao_flemeth_grimoire',compiled.effective_values)

 def test_catalog34_payloads_remain_exact_for_every_fate_and_preset(self):
  old=Catalog(mapping_version=34)
  for preset,fate in product(old.presets,FATES):
   profile=old.create('Catalog34',base_preset=preset,mode='experimental',choices={'dao.wynne_fate':fate})
   upgraded=self.catalog.upgrade(profile)
   raw,_=build_profile_mod(profile,catalog=self.catalog);other,_=build_profile_mod(upgraded,catalog=self.catalog)
   self.assertEqual(read_mod(raw)['ebx'],read_mod(other)['ebx'])
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as directory:
   store=ProfileStore(Path(directory)/'profiles',catalog=old);saved=store.create('History',mode='experimental',choices={'dao.wynne_fate':'died_at_circle'})
   snapshot={str(p):p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()};self.catalog.upgrade(saved)
   self.assertEqual(snapshot,{str(p):p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()});self.assertEqual(store.load(saved.profile_id),saved)

 def test_restricted_wynne_pairs_and_free_bypass(self):
  for fate,(value,expected) in FATES.items():
   for answer in RECRUITS:
    profile=self.catalog.create('Wynne links',mode='keep',choices={'dao.dagna_outcome':'not_met','dao.urn_poisoned':'poisoned','dao.wynne_fate':fate,'dao.wynne_recruited':answer})
    if RECRUITS.index(answer)==expected:compile_profile(profile,catalog=self.catalog)
    else:
     with self.assertRaises(StoryConflict):compile_profile(profile,catalog=self.catalog)
    compile_profile(profile.edited(mode='experimental'),catalog=self.catalog)

 def test_recruitment_and_fate_proposals_are_linked_in_both_directions_without_writes(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as directory:
   app=EditorApp(Path(directory)/'profiles',Path(directory)/'exports');saved=app.store.create('Wynne alive',mode='keep',choices={'dao.dagna_outcome':'not_met','dao.wynne_fate':'alive'})
   draft={k:saved.to_dict()[k] for k in ('profile_id','revision','name','base_preset','mode','choices')}
   snapshot={str(p):p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()}
   response=app.propose(dict(draft=draft,updates={'dao.wynne_recruited':'not_recruited'},mode='keep'))
   self.assertEqual(response['draft']['choices']['dao.wynne_recruited'],'not_recruited')
   self.assertIn(response['draft']['choices']['dao.wynne_fate'],('not_recruited','died_at_circle'))
   self.assertEqual([x['choice_id'] for x in response['changes']],['dao.wynne_fate'])
   reverse=app.propose(dict(draft=response['draft'],updates={'dao.wynne_fate':'alive'},mode='keep'))
   self.assertEqual(reverse['draft']['choices']['dao.wynne_recruited'],'recruited');self.assertEqual([x['choice_id'] for x in reverse['changes']],['dao.wynne_recruited'])
   self.assertEqual(app.propose(dict(draft=draft,updates={'dao.wynne_recruited':'not_recruited'},mode='experimental'))['changes'],[])
   self.assertEqual(snapshot,{str(p):p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()})

 def test_released_presets_reproduce_exact_payload_and_local_history_roundtrips(self):
  for preset in self.catalog.presets:
   if not preset.startswith('template-'):continue
   profile=self.catalog.create('Released',base_preset=preset,mode='experimental',choices={'dao.wynne_recruited':'recruited','dao.oghren_recruited':'recruited'})
   raw,_=build_profile_mod(profile,catalog=self.catalog);self.assertEqual(read_mod(raw)['ebx'],read_mod(self.catalog.template_path(preset).read_bytes())['ebx'])
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as directory:
   store=ProfileStore(Path(directory)/'profiles',catalog=self.catalog)
   for answer in GRIMOIRE:
    saved=store.create('Grimoire',mode='experimental',choices={'dao.flemeth_grimoire':answer});path=Path(directory)/(saved.profile_id+'.json');store.export_json(saved.profile_id,path);imported=store.import_profile(path)
    self.assertEqual(imported.choices,saved.choices);self.assertNotEqual(imported.profile_id,saved.profile_id)

if __name__=='__main__':unittest.main(verbosity=2)
