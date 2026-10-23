"""Save import safety, source-backed inference, and independent profile creation.

Synthetic GFF fixtures contain no personal saves. Optional local comparisons
exercise the four research cases without distributing any of their bytes.
"""
import json
from pathlib import Path
import struct
import tempfile
import threading
import time
import unittest
from http.client import HTTPConnection
from unittest.mock import patch
import zipfile

from game_saves.da2 import (ACT, BARTRAND, DANARIUS, FEYNRIEL, FINALE, IDOL,
                            PARTY, PERSONALITY, QUNARI, ROMANCES, SEBASTIAN,
                            Snapshot, import_save)
from game_saves.gff import MAX_SAVE_BYTES, SaveFormatError, SaveReader
from export_worldstate import read_mod
from fbmod_metadata import metadata_text
from gui import EditorApp, create_server
from world_profiles import Catalog
from world_profiles.compiler import StoryConflict, build_profile_mod, compile_profile
from app_runtime import resource_root

ROOT = resource_root()


def make_save(plots=None, party=(), approvals=(), *, gender=2, primary=3, name='Test Hawke',
              seen=(), dao_plots=None, dao_bools=None, dao_ints=None, game='da2', race=3):
    """Minimal PC GFF4 SAVEV2.0, with real field labels and relative pointers."""
    plots = plots if plots is not None else {ACT: [0, 2, 4]}
    R, L = 0x6000, 0xC000
    schemas = [
        (12, [(16003, 1, R, 0), (16002, 5, R, 4), (16024, 11, R, 8)]),
        (16, [(16400, 2, R, 0), (16204, 4, L, 4), (16275, 9, L, 8), (16503, 4, 0x8000, 12)]),
        (4, [(16401, 3, L, 0)]),
        (20, [(16402, 14, 0, 0), *[(label, 4, 0, 4 + (label - 16403) * 4) for label in range(16403, 16407)]]),
        (12, [(3, 14, 0, 0), (23, 4, 0, 4), (16203, 4, 0, 8)]),
        (4, [(16208, 6, R, 0)]),
        (16, [(16255, 17, 0, 0), (16320, 7, R, 8), (16209, 8, R, 12)]),
        (4, [(16322, 4, 0, 0)]),
        (4, [(16350, 10, L, 0)]),
        (8, [(16276, 4, 0, 0), (16277, 5, 0, 4)]),
        (12, [(16353, 4, 0, 0), (16300, 8, 0, 4), (16301, 8, 0, 8)]),
        (12, [(16401, 3, L, 0), (17603, 12, L, 4), (17607, 12, L, 8)]),
        (8, [(17601, 4, 0, 0), (17602, 5, 0, 4)]),
    ]
    if game == 'dao':
        schemas[6] = (20, [*schemas[6][1], (16460, 4, 0, 16)])
    strings = list(dict.fromkeys([name, *plots, *(dao_plots or {}), *[p[0] for p in party]]))
    indices = {value: i for i, value in enumerate(strings)}
    data = bytearray(12)

    def emit(raw):
        offset = len(data); data.extend(raw); return offset

    if game == 'dao':
        indices = {value: emit(struct.pack('<I', len((value + '\0').encode('utf-16le')) // 2) + (value + '\0').encode('utf-16le'))
                   for value in strings}

    def plot_list_data(records):
        rows = []
        for guid, bits in records.items():
            words = [sum(1 << (bit % 32) for bit in set(bits) if bit // 32 == i) for i in range(4)]
            rows.append(struct.pack('<5I', indices[guid], *words))
        return struct.pack('<I', len(rows)) + b''.join(rows)
    plot_list = emit(plot_list_data(plots))
    plot_table = emit(struct.pack('<I', plot_list))
    party_list = emit(struct.pack('<I', len(party)) + b''.join(struct.pack('<III', indices[t], oid, state) for t, oid, state in party))
    approval_list = emit(struct.pack('<I', len(approvals)) + b''.join(struct.pack('<Ii', oid, v) for oid, v in approvals))
    spoken = emit(struct.pack('<I', len(seen)) + b''.join(struct.pack('<I', ref) for ref in seen))
    world = emit(struct.pack('<IIII', plot_table, party_list, approval_list, spoken))
    appearance = emit(struct.pack('<I', gender))
    properties = emit(struct.pack('<IIff', 1, 27 if game == 'dao' else 50, primary, 0))
    stats = emit(struct.pack('<I', properties))
    creature = emit(struct.pack('<IIII', 0, indices[name], appearance, stats) + (struct.pack('<I', race) if game == 'dao' else b''))
    player = emit(struct.pack('<I', creature))
    vault = 0xFFFFFFFF
    if any(value is not None for value in (dao_plots, dao_bools, dao_ints)):
        dao_plot_list = emit(plot_list_data(dao_plots or {}))
        def values(records):
            return emit(struct.pack('<I', len(records)) + b''.join(struct.pack('<Ii', k, value) for k, value in records.items()))
        ints, bools = values(dao_ints or {}), values(dao_bools or {})
        vault = emit(struct.pack('<III', dao_plot_list, ints, bools))
    struct.pack_into('<III', data, 0, world, player, vault)
    cursor = (28 if game == 'dao' else 36) + len(schemas) * 16
    headers, fields = bytearray(), bytearray()
    for i, (size, rows) in enumerate(schemas):
        headers.extend(struct.pack('<4sIII', f'S{i:03}'.encode(), len(rows), cursor, size))
        for label, kind, flags, offset in rows:
            fields.extend(struct.pack('<III', label, kind | (flags << 16), offset))
        cursor += len(rows) * 12
    string_data = b''.join(s.encode() + b'\0' for s in strings)
    string_data += b'\0' * ((-(cursor + len(string_data))) % 4)
    if game == 'dao':
        return b'GFF V4.0PC  SAVEV1.1' + struct.pack('<II', len(schemas), cursor) + headers + fields + data
    return (b'GFF V4.1PC  SAVEV2.0' + struct.pack('<IIII', len(schemas), len(strings), cursor, cursor + len(string_data))
            + headers + fields + string_data + data)


class SaveImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def imported(self, plots=None, **kwargs):
        return import_save(make_save(plots, **kwargs), self.catalog)

    def test_reader_and_identity_are_independent_of_filename_and_inventory(self):
        raw = make_save(name='Éloïse', primary=2)
        reader = SaveReader(raw)
        self.assertEqual(reader.get((16002, 16208, 16255)), 'Éloïse')
        result = import_save(raw, self.catalog)
        self.assertEqual(result['choices']['da2.hawke_identity'], 'female_rogue')
        self.assertEqual(result['character'], 'Éloïse')
        self.assertNotIn('da2.hawke_identity', self.imported(primary=4)['choices'])

    def test_generated_import_names_are_exportable_without_losing_character_text(self):
        for character, expected in (
            ('Marian', 'Marian - imported DA2'),
            ('Éloïse “Hawke” — Ž 🐉', 'Éloïse "Hawke" - Z - imported DA2'),
            ('\u9f8d', 'World State - imported DA2'),
            ('\u2026' * 80, '.' * 105 + ' - imported DA2'),
        ):
            with self.subTest(character=character):
                result = self.imported(name=character)
                self.assertEqual(result['character'], character)
                self.assertEqual(result['suggested_name'], expected)
                self.assertLessEqual(len(result['suggested_name']), 120)
                metadata_text(result['suggested_name'], 'Mod title', 160, required=True)
        result = self.imported(name='Marian')
        profile = self.catalog.create(result['suggested_name'], mode='experimental', choices=result['choices'])
        data, _ = build_profile_mod(profile, catalog=self.catalog, title=profile.name)
        self.assertEqual(read_mod(data)['details'][0], 'Marian - imported DA2')

    def test_missing_and_clear_plots_do_not_become_negative_choices(self):
        result = self.imported()
        for key in ('hawke_romance', 'anders_fate', 'isabela_handover', 'isabela_book', 'bartrand_fate'):
            self.assertNotIn('da2.' + key, result['choices'])
        self.assertNotIn('da2.feynriel_fate', self.imported({ACT: [4], FEYNRIEL: []})['choices'])

    def test_completed_romance_beats_stale_active_history_but_not_polyamory(self):
        plots = {ACT: [4], ROMANCES['anders']: [13, 17, 18], ROMANCES['fenris']: [13, 17]}
        self.assertEqual(self.imported(plots)['choices']['da2.hawke_romance'], 'anders')
        plots[ROMANCES['fenris']].append(18)
        self.assertNotIn('da2.hawke_romance', self.imported(plots)['choices'])
        plots[ROMANCES['fenris']].append(15)
        self.assertEqual(self.imported(plots)['choices']['da2.hawke_romance'], 'anders')
        empty = {ACT: [4], SEBASTIAN: [], **{g: [] for g in ROMANCES.values()}}
        self.assertEqual(self.imported(empty)['choices']['da2.hawke_romance'], 'none')

    def test_modded_sibling_is_preserved_without_inventing_career_or_death(self):
        result = self.imported({ACT: [0, 2, 4, 8]}, party=[('gen00fl_bethany', 123, 2)])
        self.assertEqual(result['choices']['da2.bethany_fate'], 'alive_unspecified')
        self.assertEqual(result['choices']['da2.carver_fate'], 'templar')
        # Explicit death wins over a stale/modded pool entry. Conflicting markers
        # remain unresolved rather than prioritizing one arbitrary bit.
        result = self.imported({ACT: [2, 11]}, party=[('gen00fl_bethany', 123, 2)])
        self.assertEqual(result['choices']['da2.bethany_fate'], 'lothering_death')
        result = self.imported({ACT: [2, 7, 9]}, party=[('gen00fl_bethany', 123, 2)])
        self.assertNotIn('da2.bethany_fate', result['choices'])
        result = self.imported({ACT: [0]}, party=[('gen00fl_bethany', 123, 2)])
        self.assertNotIn('da2.bethany_fate', result['choices'])

    def test_battles_are_not_imported_as_completed_before_act3(self):
        self.assertNotIn('da2.arishok_fate', self.imported({ACT: [2], QUNARI: [26]})['choices'])
        result = self.imported({ACT: [4], QUNARI: [26]})['choices']
        self.assertEqual(result['da2.arishok_fate'], 'killed')
        self.assertEqual(result['da2.isabela_handover'], 'not_handed_over')
        self.assertNotIn('da2.isabela_book', result)

    def test_current_varric_approval_uses_object_id_not_historical_flags(self):
        result = self.imported(party=[('gen00fl_varric.utc', 122, 2)], approvals=[(122, -100), (999, 100)])
        self.assertEqual(result['choices']['da2.varric_relationship'], 'rivals')

    def test_no_departure_is_guessed_from_absent_or_inactive_followers(self):
        result = self.imported({ACT: [4], PARTY: [15, 19], FINALE: [0]}, party=[('gen00fl_carver', 1, 3)])
        for key in ('aveline_remained', 'anders_fate', 'fenris_fate', 'isabela_book'):
            self.assertNotIn('da2.' + key, result['choices'])

    def test_direct_outcomes_require_a_unique_terminal_marker(self):
        result = self.imported({ACT: [4], FEYNRIEL: [9], BARTRAND: [7], IDOL: [11]})['choices']
        self.assertEqual(result['da2.feynriel_fate'], 'tevinter')
        self.assertEqual(result['da2.varric_idol'], 'not_kept')
        self.assertEqual(result['da2.varric_quest'], 'completed')
        self.assertEqual(result['da2.bartrand_fate'], 'alive')
        self.assertNotIn('da2.feynriel_fate', self.imported({ACT: [4], FEYNRIEL: [8, 9]})['choices'])

    def test_nonstandard_mod_plots_are_ignored_and_duplicate_vanilla_plots_rejected(self):
        self.assertTrue(self.imported({ACT: [4], 'cov_mount_mac': [0]})['choices'])
        raw = bytearray(make_save({ACT: [4], ACT.lower(): [4]}))
        with self.assertRaisesRegex(SaveFormatError, 'Duplicate'):
            Snapshot(bytes(raw))

    def test_reader_rejects_wrong_types_truncation_schema_and_large_input(self):
        raw = make_save()
        for bad in (b'', b'PK' + raw, raw[:80], b'GFF V4.0' + raw[8:], raw[:12] + b'MET V2.0' + raw[20:], b'x' * (MAX_SAVE_BYTES + 1)):
            with self.subTest(length=len(bad)), self.assertRaises(SaveFormatError):
                import_save(bad, self.catalog)
        bad = bytearray(raw); struct.pack_into('<I', bad, 32, 0xFFFFFFF0)
        with self.assertRaises(SaveFormatError): SaveReader(bytes(bad))
        bad = bytearray(raw); struct.pack_into('<I', bad, 36 + 8, 0)
        with self.assertRaises(SaveFormatError): SaveReader(bytes(bad))

    def test_incomplete_sibling_answer_is_only_explicit_and_exports_survival_only(self):
        catalog = self.catalog
        base = compile_profile(catalog.create('Base', mode='experimental'), catalog=catalog)
        self.assertNotEqual(base.report['resolved_choices']['da2.bethany_fate']['answer_id'], 'alive_unspecified')
        profile = catalog.create('Imported', mode='experimental', choices={'da2.bethany_fate': 'alive_unspecified'})
        compiled = compile_profile(profile, catalog=catalog)
        self.assertEqual(compiled.values['da2_bethany_alive'], 1)
        self.assertEqual({k: v for k, v in compiled.values.items() if k.startswith('da2_bethany') and k not in base.values},
                         {'da2_bethany_alive': 1, 'da2_bethany_final_battle_death': 1})
        self.assertEqual(compiled.report['resolved_choices']['da2.bethany_fate']['answer_id'], 'alive_unspecified')
        with self.assertRaises(StoryConflict): compile_profile(profile.edited(mode='keep'), catalog=catalog)
        # An explicit final battle must not require a missing copied field.
        compile_profile(profile.edited(choices={**profile.choices, 'da2.bethany_final_battle': 'survived'}), catalog=catalog)

    def test_v42_profile_upgrade_preserves_choices_and_export_values(self):
        old = Catalog(42)
        profile = old.create('Existing history', mode='experimental', choices={'da2.bethany_fate': 'warden'})
        upgraded = self.catalog.upgrade(profile)
        self.assertEqual(dict(upgraded.choices), dict(profile.choices))
        self.assertEqual(dict(compile_profile(profile, catalog=old).values), dict(compile_profile(upgraded, catalog=self.catalog).values))

    def test_optional_local_comparison_saves(self):
        path = ROOT / 'assessment/output/save-import-survey/comparison-cases.json'
        if not path.exists(): self.skipTest('Local research fixtures unavailable')
        cases = json.loads(path.read_text(encoding='utf-8'))['cases']
        expected = [('anders', 'lothering_death'), ('none', 'alive_unspecified'), ('fenris', 'circle'), ('anders', 'alive_unspecified')]
        for case, (romance, bethany) in zip(cases, expected):
            p = Path(case['source'])
            if not p.exists(): self.skipTest('Original local comparison save unavailable')
            if p.suffix == '.zip':
                with zipfile.ZipFile(p) as z: raw = z.read(next(n for n in z.namelist() if n.endswith('.das')))
            else: raw = p.read_bytes()
            before = __import__('hashlib').sha256(raw).hexdigest()
            result = import_save(raw, self.catalog)
            self.assertEqual(result['save_sha256'], case['save_sha256'])
            self.assertEqual(before, result['save_sha256'])
            self.assertEqual(result['choices']['da2.hawke_romance'], romance)
            self.assertEqual(result['choices']['da2.bethany_fate'], bethany)
            self.assertEqual(result['choices']['da2.isabela_book'], 'returned')
            self.assertEqual(result['choices']['da2.isabela_handover'], 'not_handed_over')
            self.assertEqual(result['choices']['da2.aveline_remained'], 'stayed')
            snapshot = Snapshot(raw)
            for guid, words in snapshot.plots.items():
                bits = [i for i in range(128) if words[i // 32] & (1 << (i % 32))]
                self.assertEqual(bits, case['active_set_bits'][guid])


class SaveImportServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'prototype', prefix='.save-import-test-')
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.app = EditorApp(root / 'profiles', root / 'exports')
        self.imports = self.app.save_imports
        self.raw = make_save({ACT: [0, 2, 4, 8]}, party=[('gen00fl_bethany', 123, 2)])

    def test_preview_cancel_and_commit_preserve_modded_choices_without_touching_other_profiles(self):
        old = self.app.store.create('Existing', mode='keep')
        original = old.to_dict()
        result = self.imports.preview(self.raw)
        self.assertEqual(result['mode'], 'experimental')
        self.assertIn('No Story Restrictions will be enabled', result['restriction_message'])
        self.assertTrue(result['restriction_reasons'])
        self.assertEqual(result['choices']['da2.bethany_fate'], 'alive_unspecified')
        self.assertEqual(len(self.app.store.list()), 1)
        self.imports.cancel({'import_id': result['import_id']})
        with self.assertRaisesRegex(ValueError, 'expired'): self.imports.commit({'import_id': result['import_id'], 'name': 'Test'})
        result = self.imports.preview(self.raw)
        created = self.imports.commit({'import_id': result['import_id'], 'name': 'New imported state'})
        self.assertEqual(dict(created.choices), result['choices'])
        self.assertNotEqual(created.profile_id, old.profile_id)
        self.assertEqual(created.mode, 'experimental')
        self.assertEqual(self.app.store.load(old.profile_id).to_dict(), original)
        with self.assertRaisesRegex(ValueError, 'expired'): self.imports.commit({'import_id': result['import_id'], 'name': 'Replay'})

    def test_expiration_bounded_cache_and_failed_commit(self):
        first = self.imports.preview(self.raw)['import_id']
        with self.assertRaises(ValueError): self.imports.commit({'import_id': first, 'name': ''})
        self.assertIn(first, self.imports.pending)
        for _ in range(5): self.imports.preview(self.raw)
        self.assertEqual(len(self.imports.pending), 4)
        self.assertNotIn(first, self.imports.pending)
        with patch('game_saves.service.time.monotonic', return_value=time.monotonic() + 601):
            self.imports._expire()
        self.assertFalse(self.imports.pending)
        self.assertFalse(self.app.store.list())

    def test_binary_api_auth_limits_and_reviewed_commit(self):
        server = create_server(self.app)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.02), daemon=True)
        thread.start()
        def request(path, raw, token=True, content='application/octet-stream', origin=None, length=None):
            conn = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            headers = {'Content-Type': content}
            if token: headers['Authorization'] = 'Bearer ' + self.app.token
            if origin: headers['Origin'] = origin
            if length is not None: headers['Content-Length'] = str(length)
            try:
                conn.request('POST', path, raw, headers)
                response = conn.getresponse(); data = json.loads(response.read())
                return response.status, data
            finally: conn.close()
        try:
            path = '/api/save-import/preview'
            self.assertEqual(request(path, self.raw, False)[0], 403)
            self.assertEqual(request(path, self.raw, origin='https://example.com')[0], 403)
            self.assertEqual(request(path, self.raw, content='application/json')[0], 415)
            # Header-only oversized declaration: do not leave unread bytes on
            # a closing Windows socket, which intentionally resets the peer.
            self.assertEqual(request(path, b'', length=MAX_SAVE_BYTES + 1)[0], 413)
            self.assertEqual(request(path, b'not a save')[0], 400)
            code, result = request(path, self.raw)
            self.assertEqual(code, 200)
            self.assertFalse(self.app.store.list())
            code, result = request('/api/save-import/commit', json.dumps({'import_id': result['import_id'], 'name': 'Reviewed'}).encode(), content='application/json')
            self.assertEqual(code, 200)
            self.assertEqual(result['choices']['da2.bethany_fate'], 'alive_unspecified')
        finally:
            server.shutdown(); server.server_close(); thread.join(2)


if __name__ == '__main__': unittest.main()
