"""Origins GFF4 imports and reviewed DAO-only merges; no personal fixture bytes."""
from http.client import HTTPConnection
import json
from pathlib import Path
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from game_saves.dao import DaoSaveHistory, import_save
from game_saves.gff import SaveReader, SaveFormatError
from game_saves.worldvault import DIRECT
from fbmod_metadata import metadata_text
from gui import EditorApp, create_server
from test_save_import import make_save
from world_profiles import Catalog, ProfileError, RevisionConflict
from world_profiles.compiler import compile_profile


def dao_save(flags=None, **kwargs):
    plots = {}
    # Include known source records for explicitly supplied false values too.
    for key, value in (flags or {2005: True}).items():
        guid, bit = DIRECT[key]
        plots.setdefault(guid, [])
        if value: plots[guid].append(bit)
    return make_save(plots, game='dao', **kwargs)


class DaoImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.catalog = Catalog()

    def test_v40_identity_class_and_utf16_text(self):
        result = import_save(dao_save({2000: True}, name='Éléonore 🐉', primary=2, race=2), self.catalog)
        self.assertEqual(result['character'], 'Éléonore 🐉')
        self.assertEqual(result['choices']['dao.warden_identity'], 'female_elven_mage')
        self.assertEqual(result['choices']['dao.warden_class'], 'mage')
        self.assertTrue(all(k.startswith('dao.') for k in result['choices']))
        self.assertEqual(result['counts']['da2'], {'recovered': 0, 'unresolved': 0})
        self.assertEqual(result['counts']['dao']['recovered'] + result['counts']['dao']['unresolved'], 74)
        self.assertTrue(all(e['evidence'].startswith('DAO save active history') for e in result['recognized']))
        self.assertEqual(result['suggested_name'], 'Éléonore - imported DAO')
        metadata_text(result['suggested_name'], 'Mod title', 160, required=True)

    def test_generated_dao_names_simplify_punctuation_and_keep_supported_accents(self):
        result = import_save(dao_save(name='Élissa’s — Warden'), self.catalog)
        self.assertEqual(result['character'], 'Élissa’s — Warden')
        self.assertEqual(result['suggested_name'], "Élissa's - Warden - imported DAO")
        metadata_text(result['suggested_name'], 'Mod title', 160, required=True)

    def test_supported_games_are_explicit_and_bounded(self):
        raw = dao_save()
        with self.assertRaises(SaveFormatError): SaveReader(raw)
        with self.assertRaises(SaveFormatError): SaveReader(make_save(), game='dao')
        for bad in (raw[:27], b'not a save', raw[:8] + b'X360' + raw[12:], raw[:16] + b'V1.0' + raw[20:]):
            with self.subTest(bad=bad[:20]), self.assertRaises(SaveFormatError): SaveReader(bad, game='dao')
        broken = bytearray(raw)
        struct.pack_into('<I', broken, 24, len(raw) + 4)
        with self.assertRaises(SaveFormatError): SaveReader(bytes(broken), game='dao')
        reader = SaveReader(raw, game='dao')
        with self.assertRaises(SaveFormatError): reader.string(len(raw))
        address = reader.get((16002, 16208)).offset
        pointer = reader.unpack('I', address + 4)[0]
        broken = bytearray(raw); struct.pack_into('<I', broken, reader.data_offset + pointer, 0xffffffff)
        with self.assertRaises(SaveFormatError): import_save(bytes(broken), self.catalog)

    def test_active_dao_plots_are_not_confused_with_foreign_vault(self):
        active = {2005: True, 2018: True}
        raw = dao_save(active, dao_bools={2019: 1, 2018: 0}, dao_plots={DIRECT[2019][0]: [DIRECT[2019][1]]})
        result = import_save(raw, self.catalog)
        self.assertEqual(result['choices']['dao.orzammar_ruler'], 'bhelen')
        guid, bit = DIRECT[2018]
        raw = make_save({guid: [bit], guid.lower(): []}, game='dao')
        with self.assertRaisesRegex(SaveFormatError, 'Duplicate'): import_save(raw, self.catalog)

    def test_derived_completion_and_ritual_keep_missing_distinct_from_false(self):
        raw = dao_save({2030: True, 2035: True, 2100: False, 2101: False, 2102: False,
                        2034: False, 2036: False, 2047: False})
        result = import_save(raw, self.catalog)
        self.assertEqual(result['stage'], 'Origins completed')
        self.assertEqual(result['choices']['dao.warden_fate'], 'alive')
        self.assertEqual(result['choices']['dao.morrigan_child'], 'old_god_warden')
        result = import_save(dao_save({2030: True}), self.catalog)
        self.assertNotIn('dao.warden_fate', result['choices'])
        self.assertNotIn('dao.morrigan_child', result['choices'])
        history = DaoSaveHistory(SaveReader(dao_save({2030: False}), game='dao'))
        self.assertIs(history.flag(2089), False)
        self.assertIsNone(history.flag(2091))
        self.assertIsNone(history.flag(2104))

    def test_custom_class_is_not_replaced_by_a_background_guess(self):
        result = import_save(dao_save({2000: True}, primary=5, race=2), self.catalog)
        self.assertEqual(result['choices']['dao.warden_identity'], 'female_elven_mage')
        self.assertNotIn('dao.warden_class', result['choices'])
        entry = next(e for e in result['unresolved'] if e['choice_id'] == 'dao.warden_class')
        self.assertIn('custom', entry['reason'])
        result = import_save(dao_save(primary=float('nan')), self.catalog)
        self.assertNotIn('dao.warden_class', result['choices'])


class DaoMergeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.app = EditorApp(root / 'profiles', root / 'exports')
        self.imports, self.store = self.app.save_imports, self.app.store
        self.raw = dao_save({2005: True, 2040: True, 2018: True}, primary=3)

    def preview(self): return self.imports.preview(self.raw, game='dao')

    def plan(self, result, target=None, policy='missing'):
        return self.imports.plan(dict(import_id=result['import_id'], target_profile_id=target.profile_id if target else None,
                                      target_revision=target.revision if target else 0, policy=policy))

    def commit(self, result, name=None):
        return self.imports.commit(dict(import_id=result['import_id'], name=name or result['profile_name']))

    def test_new_import_uses_original_defaults_without_touching_other_histories(self):
        other = self.store.create('Existing')
        result = self.preview()
        self.assertEqual(len(self.store.list()), 1)
        created = self.commit(result, 'Imported DAO')
        self.assertEqual(created.base_preset, self.app.catalog.default_preset)
        self.assertEqual(dict(created.choices), result['choices'])
        self.assertEqual(self.store.load(other.profile_id), other)
        self.assertNotEqual(created.profile_id, other.profile_id)

    def test_fill_missing_protects_explicit_default_values_and_all_da2_answers(self):
        target = self.store.create('DA2 history', mode='experimental', choices={
            'da2.hawke_romance': 'anders', 'da2.hawke_personality': 'humourous',
            'dao.warden_romance': 'none', 'dao.dagna_outcome': 'stayed'})
        result = self.plan(self.preview(), target)
        self.assertEqual(self.store.load(target.profile_id), target, 'review cannot write')
        self.assertEqual(next(e for e in result['changes'] if e['choice_id'] == 'dao.warden_romance')['status'], 'kept')
        saved = self.commit(result)
        self.assertEqual(saved.profile_id, target.profile_id)
        self.assertEqual(saved.revision, target.revision + 1)
        self.assertEqual(saved.choices['dao.warden_romance'], 'none')
        self.assertEqual(saved.choices['dao.orzammar_ruler'], 'bhelen')
        for key, value in target.choices.items(): self.assertEqual(saved.choices[key], value)
        self.assertEqual(self.store.history(target.profile_id), [saved, target])

    def test_replace_updates_recovered_dao_only_missing_data_clears_nothing(self):
        target = self.store.create('Destination', mode='experimental', choices={
            'da2.hawke_romance': 'fenris', 'dao.warden_romance': 'none', 'dao.dagna_outcome': 'stayed'})
        result = self.plan(self.preview(), target, 'replace')
        self.assertEqual(next(e for e in result['changes'] if e['choice_id'] == 'dao.warden_romance')['status'], 'replaced')
        saved = self.commit(result)
        self.assertEqual(saved.choices['dao.warden_romance'], 'alistair')
        self.assertEqual(saved.choices['dao.dagna_outcome'], target.choices['dao.dagna_outcome'])
        self.assertEqual(saved.choices['da2.hawke_romance'], 'fenris')

    def test_plan_rotation_back_to_new_and_tamper_guards(self):
        target = self.store.create('Existing', mode='experimental', choices={'da2.hawke_romance': 'fenris'})
        original = self.preview()
        planned = self.plan(original, target)
        with self.assertRaisesRegex(ProfileError, 'expired'): self.commit(original)
        back = self.plan(planned)
        self.assertIsNone(back['target_profile_id'])
        created = self.commit(back, 'New instead')
        self.assertNotIn('da2.hawke_romance', created.choices)
        self.assertEqual(self.store.load(target.profile_id), target)
        planned = self.plan(self.preview(), target)
        with self.assertRaisesRegex(ProfileError, 'rename'): self.commit(planned, 'Rename injection')
        with self.assertRaises(ProfileError): self.imports.commit(dict(import_id=planned['import_id'], name=target.name, choices={}))
        planned['choices']['dao.warden_romance'] = 'none'
        planned['changes'].clear()
        self.assertEqual(self.commit(planned).choices['dao.warden_romance'], 'alistair')

    def test_cancel_and_expiry(self):
        target = self.store.create('Existing')
        planned = self.plan(self.preview(), target)
        self.imports.cancel({'import_id': planned['import_id']})
        self.assertEqual(self.store.load(target.profile_id), target)
        with self.assertRaisesRegex(ProfileError, 'expired'): self.commit(planned)
        result = self.preview()
        with patch('game_saves.service.time.monotonic', return_value=time.monotonic() + 601):
            with self.assertRaisesRegex(ProfileError, 'expired'): self.plan(result, target)

    def test_stale_revision_or_deleted_destination_cannot_be_overwritten(self):
        target = self.store.create('Existing')
        result = self.preview()
        newest = self.store.save(target.edited(name='Changed elsewhere'))
        with self.assertRaises(RevisionConflict): self.plan(result, target)
        planned = self.plan(result, newest)
        latest = self.store.save(newest.edited(name='Changed after review'))
        with self.assertRaises(RevisionConflict): self.commit(planned)
        self.assertEqual(self.store.load(latest.profile_id), latest)
        planned = self.plan(self.preview(), latest)
        self.store.delete(latest.profile_id, latest.revision)
        with self.assertRaisesRegex(ProfileError, 'deleted'): self.commit(planned)
        self.assertEqual(self.store.restore(latest.profile_id, latest.revision), latest)

    def test_conflicts_enable_unrestricted_mode_only_for_merged_destination(self):
        target = self.store.create('Strict destination', mode='keep', choices={'dao.warden_class': 'warrior'})
        other = self.store.create('Unrelated', mode='keep')
        self.raw = dao_save({2000: True}, primary=2, race=2)
        result = self.plan(self.preview(), target)
        self.assertEqual(result['mode'], 'experimental')
        self.assertTrue(result['restriction_reasons'])
        self.assertEqual(self.store.load(target.profile_id), target)
        saved = self.commit(result)
        self.assertEqual(saved.choices['dao.warden_class'], 'warrior')
        self.assertEqual(saved.choices['dao.warden_identity'], 'female_elven_mage')
        self.assertEqual(saved.mode, 'experimental')
        self.assertEqual(self.store.load(other.profile_id), other)

    def test_noop_has_no_extra_revision_and_failed_commit_remains_retryable(self):
        created = self.commit(self.preview(), 'Existing')
        result = self.plan(self.preview(), created)
        self.assertFalse(result['has_changes'])
        self.assertEqual(self.commit(result), created)
        self.assertEqual(len(self.store.history(created.profile_id)), 1)
        self.raw = dao_save({2019: True})
        result = self.plan(self.preview(), created, 'replace')
        with patch('world_profiles.storage._replace_json', side_effect=OSError('interrupted write')):
            with self.assertRaises(OSError): self.commit(result)
        self.assertEqual(self.store.load(created.profile_id), created)
        self.assertIn(result['import_id'], self.imports.pending)
        saved = self.commit(result)
        self.assertEqual(saved.choices['dao.orzammar_ruler'], 'harrowmont')
        self.assertEqual(self.store.load(created.profile_id, revision=1), created)

    def test_dao_binary_api_preview_plan_commit_and_auth(self):
        target = self.store.create('Destination', mode='experimental', choices={'da2.hawke_romance': 'anders'})
        server = create_server(self.app)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.02), daemon=True)
        thread.start()
        def request(path, data, binary=False, auth=True):
            connection = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            headers = {'Content-Type': 'application/octet-stream' if binary else 'application/json'}
            if auth: headers['Authorization'] = 'Bearer ' + self.app.token
            try:
                connection.request('POST', path, data if binary else json.dumps(data).encode(), headers)
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally: connection.close()
        try:
            path = '/api/dao-save-import/preview'
            self.assertEqual(request(path, self.raw, True, False)[0], 403)
            self.assertEqual(request(path, make_save(), True)[0], 400)
            code, review = request(path, self.raw, True)
            self.assertEqual(code, 200)
            payload = dict(import_id=review['import_id'], target_profile_id=target.profile_id,
                           target_revision=target.revision, policy='missing')
            self.assertEqual(request('/api/save-import/plan', payload, auth=False)[0], 403)
            code, review = request('/api/save-import/plan', payload)
            self.assertEqual(code, 200)
            code, saved = request('/api/save-import/commit', dict(import_id=review['import_id'], name=target.name))
            self.assertEqual(code, 200)
            self.assertEqual(saved['revision'], 2)
            self.assertEqual(saved['choices']['da2.hawke_romance'], 'anders')
        finally:
            server.shutdown(); server.server_close(); thread.join(2)


if __name__ == '__main__': unittest.main()
