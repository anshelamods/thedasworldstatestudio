"""Nature of the Beast side quests: export values, independence and legacy history."""
from itertools import product
from pathlib import Path
import tempfile
import unittest

from export_worldstate import ROOT, read_mod
from world_profiles import Catalog, ProfileStore
from world_profiles.compiler import build_profile_mod, compile_profile
from test_da2_main_story import flags_from_mod

CASES = {
 'dao.cammen_relationship': ('dao_ntb_cammen_lament', {'not_met':0,'broke_up':1,'together':2}),
 'dao.elora_halla': ('dao_ntb_elora_halla', {'not_helped':0,'saved':1,'killed':2}),
 'dao.athras_danyla': ('dao_ntb_lost_curse', {'not_told':0,'told':1}),
 'dao.varathorn_ironbark': ('dao_ntb_rare_ironbark', {'not_brought':0,'brought':1}),
 'dao.deygan_fate': ('dao_ntb_wounded_forest', {'not_met':0,'returned':1,'killed':2})}

class NatureSideQuestTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.catalog=Catalog()

 def test_all_108_combinations_across_nine_presets(self):
  for preset in self.catalog.presets:
   for answers in product(*(definition[1] for definition in CASES.values())):
    choices=dict(zip(CASES,answers))
    with self.subTest(preset=preset,choices=choices):
     compiled=compile_profile(self.catalog.create('Forest history',base_preset=preset,mode='experimental',choices=choices),catalog=self.catalog)
     for group,(field,values) in CASES.items():self.assertEqual(compiled.effective_values[field],values[choices[group]])
     self.assertFalse(set(compiled.max_overrides)&{field for field,_ in CASES.values()})

 def test_single_edits_preserve_every_unowned_field_across_nine_presets(self):
  for preset in self.catalog.presets:
   profile=self.catalog.create('Independent forest history',base_preset=preset,mode='experimental')
   before=compile_profile(profile,catalog=self.catalog)
   for group,(field,answers) in CASES.items():
    for answer in answers:
     after=compile_profile(profile.edited(choices={group:answer}),catalog=self.catalog)
     self.assertEqual({n:v for n,v in before.effective_values.items() if n!=field},{n:v for n,v in after.effective_values.items() if n!=field})
     self.assertEqual(before.max_overrides,after.max_overrides)
     self.assertEqual(after.report['resolved_choices'][group]['answer_id'],answer)

 def test_every_answer_roundtrips_through_fbmod_with_original_ranges(self):
  for group,(field,answers) in CASES.items():
   for answer,expected in answers.items():
    profile=self.catalog.create('Export forest answer',mode='experimental',choices={group:answer})
    raw,report=build_profile_mod(profile,catalog=self.catalog)
    flags=flags_from_mod(raw)
    self.assertEqual(flags[field]['DefaultValue'],expected)
    self.assertEqual(flags[field]['MinValue'],0)
    self.assertEqual(flags[field]['MaxValue'],2 if len(answers)==3 else 1)
    self.assertFalse(report['profile']['gameplay_tested'])

 def test_all_eight_released_presets_reproduce_exact_payloads(self):
  for preset in self.catalog.presets:
   if not preset.startswith('template-'):continue
   profile=self.catalog.create('Released forest choices',base_preset=preset,mode='experimental')
   resolved=compile_profile(profile,catalog=self.catalog).report['resolved_choices']
   choices={group:resolved[group]['answer_id'] for group in CASES}
   self.assertTrue(all(choices.values()))
   raw,_=build_profile_mod(profile.edited(choices=choices),catalog=self.catalog)
   self.assertEqual(read_mod(raw)['ebx'],read_mod(self.catalog.template_path(preset).read_bytes())['ebx'])

 def test_catalog28_keep_upgrade_preserves_payload_and_immutable_revision(self):
  old=Catalog(mapping_version=28)
  with tempfile.TemporaryDirectory(dir=ROOT/'prototype') as directory:
   store=ProfileStore(directory,catalog=old)
   profile=store.create('Previous restricted history',mode='keep',choices={'dao.dagna_outcome':'not_met'})
   path=store.profile_directory(profile.profile_id)/'History/00000001.json';before=path.read_bytes()
   upgraded=self.catalog.upgrade(profile)
   original_mod,_=build_profile_mod(profile,catalog=self.catalog)
   upgraded_mod,_=build_profile_mod(upgraded,catalog=self.catalog)
   self.assertEqual(read_mod(original_mod)['ebx'],read_mod(upgraded_mod)['ebx'])
   self.assertEqual(upgraded.mode,'keep')
   current=ProfileStore(directory,catalog=self.catalog)
   saved=current.save(upgraded.edited(choices=dict(upgraded.choices,**{'dao.deygan_fate':'returned'})))
   self.assertEqual(saved.revision,2)
   self.assertEqual(path.read_bytes(),before)
   self.assertEqual(current.load(profile.profile_id,revision=1),profile)

 def test_keep_has_no_new_gates_for_earlier_forest_side_quests(self):
  # Side quests can precede the faction outcome; do not invent a Dalish-survival gate.
  for outcome in ('peace','elves','werewolves'):
   profile=self.catalog.create('Earlier quests',mode='keep',choices={'dao.dagna_outcome':'not_met',
    'dao.nature_outcome':outcome,'dao.cammen_relationship':'together','dao.elora_halla':'saved',
    'dao.athras_danyla':'told','dao.varathorn_ironbark':'brought','dao.deygan_fate':'returned'})
   compiled=compile_profile(profile,catalog=self.catalog)
   self.assertFalse(compiled.report['story_conflicts'])
   for group,(field,values) in CASES.items():self.assertEqual(compiled.effective_values[field],values[profile.choices[group]])

if __name__=='__main__':unittest.main(verbosity=2)
