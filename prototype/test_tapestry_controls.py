"""Exercise the actual browser composition helper against profile/FBMOD output."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from export_worldstate import ROOT, EbxParser, read_mod
from gui import EditorApp
from world_profiles import Catalog, ProfileStore
from world_profiles.compiler import build_profile_mod, compile_profile


def control(operation, *args):
    result = subprocess.run(['node', '-e', "const fs=require('fs');const c=require('./prototype/gui/choice-controls.js');const p=JSON.parse(fs.readFileSync(0,'utf8'));process.stdout.write(JSON.stringify(c[p.operation](...p.args)));"],
        cwd=ROOT, input=json.dumps(dict(operation=operation, args=args)), text=True, encoding='utf8',
        capture_output=True, check=True)
    return json.loads(result.stdout)


class TapestryControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(dir=ROOT / 'prototype', prefix='.tapestry-test-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.app = EditorApp(Path(cls.temporary.name) / 'profiles', Path(cls.temporary.name) / 'exports')
        cls.choice = next(choice for choice in cls.app.choices() if choice['id'] == 'da2.fenris_fate')

    def test_five_illustrated_outcomes_export_all_related_flags_across_nine_bases(self):
        fields = ('da2_fenris_alive', 'da2_fenris_still_alive', 'da2_fenris_joined',
                  'da2_fenris_enslaved', 'da2_fenris_returned_to_master')
        expected = {'not_recruited': (0, 1, 0, 0, 0), 'dead': (1, 0, 1, 1, 0),
                    'alive': (2, 1, 1, 1, 0), 'returned': (3, 1, 1, 2, 1), 'pursued': (4, 1, 1, 1, 0)}
        for answer, values in expected.items():
            changes = control('apply', {'da2.hawke_romance': 'fenris'}, self.choice, answer)
            self.assertEqual(changes['da2.hawke_romance'], 'fenris')
            for preset in self.app.catalog.presets:
                profile = self.app.catalog.create('Illustrated Fenris', base_preset=preset, mode='experimental', choices=changes)
                before = compile_profile(self.app.catalog.create('Same base', base_preset=preset,
                    mode='experimental', choices={'da2.hawke_romance': 'fenris'}))
                mod, _ = build_profile_mod(profile)
                flags = {o['value']['VariableNameOnServer']: o['value']['DefaultValue']
                         for o in EbxParser(read_mod(mod)['ebx']).parse()['objects'] if o['class'] == 'GameVaultVarInt'}
                self.assertEqual(tuple(flags[name] for name in fields), values)
                self.assertEqual({n: v for n, v in flags.items() if n not in fields},
                                 {n: v for n, v in before.effective_values.items() if n not in fields})

    def test_custom_combinations_are_detected_without_changing_the_draft(self):
        draft = dict(choices={'da2.fenris_fate': 'alive', 'da2.fenris_recruited': 'not_recruited',
                              'da2.fenris_danarius': 'returned', 'da2.carver_fate': 'warden'})
        original = json.loads(json.dumps(draft))
        self.assertIsNone(control('currentAnswer', draft, {}, self.choice))
        self.assertEqual(control('currentAnswer', draft, {}, self.choice, True), 'alive')
        self.assertTrue(control('explicit', draft, self.choice))
        corrected = control('apply', draft['choices'], self.choice, 'not_recruited')
        self.assertEqual(corrected['da2.fenris_recruited'], 'not_recruited')
        self.assertEqual(corrected['da2.fenris_danarius'], 'not_recruited')
        self.assertEqual(corrected['da2.carver_fate'], 'warden')
        self.assertEqual(control('currentAnswer', {'choices': corrected}, {}, self.choice), 'not_recruited')
        self.assertEqual(draft, original)

    def test_group_reset_clears_all_three_overrides_and_resolves_inherited_answers(self):
        choices = control('apply', {'da2.bethany_fate': 'warden'}, self.choice, 'returned')
        reset = control('apply', choices, self.choice, None)
        self.assertEqual(reset, {'da2.bethany_fate': 'warden'})
        preview = {'resolved_choices': {group: {'answer_id': answer} for group, answer in
            [('da2.fenris_fate', 'alive'), ('da2.fenris_recruited', 'recruited'), ('da2.fenris_danarius', 'not_returned')]}}
        self.assertEqual(control('currentAnswer', {'choices': reset}, preview, self.choice), 'alive')
        self.assertFalse(control('explicit', {'choices': reset}, self.choice))
        preview['resolved_choices']['da2.fenris_danarius']['answer_id'] = 'returned'
        self.assertIsNone(control('currentAnswer', {'choices': reset}, preview, self.choice))

    def test_opening_custom_saved_profiles_does_not_migrate_or_rewrite_them(self):
        audit = json.loads((ROOT / 'assessment/reference/da2-main-story-mapping-review.json').read_text(encoding='utf8'))
        archived = Catalog(mapping_version=14)
        self.assertEqual(archived.sha256, audit['catalog_sha256'])
        old_store = ProfileStore(self.app.store.directory, catalog=archived)
        original = old_store.create('Custom legacy Fenris', choices={
            'da2.fenris_fate': 'alive', 'da2.fenris_recruited': 'not_recruited', 'da2.fenris_danarius': 'returned'})
        path = self.app.store.profile_directory(original.profile_id) / 'History/00000001.json'
        raw = path.read_bytes()
        before = build_profile_mod(original)[0]
        shown = self.app.editor_profile(original)
        self.assertEqual(shown['editor_choices'], dict(original.choices))
        self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(build_profile_mod(self.app.store.load(original.profile_id))[0], before)

    def test_companion_layout_matches_supported_captured_keep_blocks(self):
        data = self.app.bootstrap()
        categories = {category['id']: category for category in data['categories']}
        self.assertNotIn('da2.family', categories)
        choices = {choice['id']: choice for choice in data['choices']}
        for group in ('da2.bethany_fate', 'da2.carver_fate', 'da2.anders_approval'):
            self.assertEqual(choices[group]['category_id'], 'da2.companions')
        for group in ('da2.fenris_recruited', 'da2.fenris_danarius'):
            self.assertEqual(choices[group]['display'], 'quick-only')
        visible = {choice['id'] for choice in data['choices'] if choice['category_id'] == 'da2.companions'
                   and choice.get('display') != 'quick-only'}
        blocks = categories['da2.companions']['tile_blocks']
        tiles = [tile for block in blocks for tile in block]
        self.assertEqual(len(visible), 23)
        self.assertEqual({tile['choice_id'] for tile in tiles}, visible)
        self.assertEqual(len(tiles), len(visible))
        self.assertEqual({(tile['width'], tile['height']) for tile in tiles}, {(2, 2), (1, 2), (2, 1)})
        for block in blocks:
            occupied = set()
            for tile in block:
                cells = {(x, y) for x in range(tile['x'], tile['x'] + tile['width'])
                         for y in range(tile['y'], tile['y'] + tile['height'])}
                self.assertTrue(cells <= {(0, 0), (0, 1), (1, 0), (1, 1)})
                self.assertFalse(cells & occupied)
                occupied |= cells
