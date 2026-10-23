"""Recoverable world-state deletion and explicit/default import boundaries."""
from http.client import HTTPConnection
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest

from gui import EditorApp, create_server
from world_profiles import ProfileError, RevisionConflict
from world_profiles.compiler import compile_profile
from test_save_import import ACT, make_save


class ManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.app = EditorApp(root / 'profiles', root / 'exports')
        self.store = self.app.store

    def test_delete_restore_keeps_exact_history_and_exports(self):
        first = self.store.create('Recover me', choices={'dao.warden_romance': 'none'})
        latest = self.store.save(first.edited(name='Recover me later'))
        copy = self.store.duplicate(first.profile_id, 'Unaffected copy')
        directory = self.store.profile_directory(first.profile_id)
        hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in (directory / 'History').iterdir()}
        exported = self.store.directory.parent / 'Already exported.fbmod'
        exported.write_bytes(b'completed export')
        self.store.delete(latest.profile_id, latest.revision)
        self.assertEqual(self.store.list(), [copy])
        self.assertEqual(self.store.list(deleted=True), [latest])
        self.assertEqual([p.revision for p in self.store.history(first.profile_id, include_deleted=True)], [2, 1])
        for action in (lambda: self.store.load(first.profile_id),
                       lambda: self.store.load(first.profile_id, revision=1),
                       lambda: self.store.save(latest.edited(name='Stale window')),
                       lambda: self.store.duplicate(first.profile_id, 'Do not resurrect'),
                       lambda: self.store.export_json(first.profile_id, directory / 'blocked.json')):
            with self.assertRaisesRegex(ProfileError, 'deleted'):
                action()
        self.assertEqual(self.store.restore(latest.profile_id, latest.revision), latest)
        self.assertEqual(self.store.history(first.profile_id), [latest, first])
        self.assertFalse(self.store.list(deleted=True))
        self.assertEqual(hashes, {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in (directory / 'History').iterdir()})
        self.assertEqual(exported.read_bytes(), b'completed export')
        self.assertFalse((directory / '.write.lock').exists())

    def test_stale_or_competing_delete_cannot_remove_newer_work(self):
        first = self.store.create('First')
        latest = self.store.save(first.edited(name='Newer work'))
        with self.assertRaises(RevisionConflict):
            self.store.delete(first.profile_id, first.revision)
        with self.assertRaises(RevisionConflict):
            self.store.delete(first.profile_id, True)
        with self.store._lock(self.store.profile_directory(first.profile_id)):
            with self.assertRaises(RevisionConflict):
                self.store.delete(latest.profile_id, latest.revision)
        self.assertEqual(self.store.load(first.profile_id), latest)
        self.store.delete(latest.profile_id, latest.revision)
        with self.assertRaises(RevisionConflict):
            self.store.restore(first.profile_id, 1)
        self.assertEqual(self.store.list(deleted=True), [latest])
        self.store.restore(first.profile_id, 2)
        with self.assertRaisesRegex(ProfileError, 'not deleted'):
            self.store.restore(first.profile_id, 2)
        for unsafe in ('..', '../elsewhere', 'C:/outside'):
            with self.assertRaises(ProfileError): self.store.delete(unsafe, 1)
            with self.assertRaises(ProfileError): self.store.restore(unsafe, 1)

    def test_missing_imports_remain_inherited_and_equal_default_explicit_answers_stay_explicit(self):
        result = self.app.save_imports.preview(make_save({ACT: [0, 2, 4, 8]}))
        profile = self.app.save_imports.commit({'import_id': result['import_id'], 'name': 'Imported'})
        self.assertEqual(dict(profile.choices), result['choices'])
        self.assertNotIn('dao.dagna_outcome', profile.choices)
        compiled = compile_profile(profile, catalog=self.app.catalog)
        default_answer = compiled.report['resolved_choices']['dao.dagna_outcome']['answer_id']
        selected = self.store.save(profile.edited(choices={**profile.choices, 'dao.dagna_outcome': default_answer}))
        self.assertEqual(compile_profile(selected, catalog=self.app.catalog).effective_values, compiled.effective_values)
        self.assertIn('dao.dagna_outcome', self.store.load(profile.profile_id).choices)
        # A future fill-missing merge uses key presence, never value equality.
        self.assertNotIn('dao.dagna_outcome', set(self.app.catalog.choices) - selected.choices.keys())

    def test_authenticated_api_deletes_and_restores_without_changing_identity(self):
        profile = self.store.create('API history')
        server = create_server(self.app)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.02), daemon=True)
        thread.start()
        def request(path, body=None, authorized=True):
            connection = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            headers = {'Content-Type': 'application/json'}
            if authorized: headers['Authorization'] = 'Bearer ' + self.app.token
            try:
                connection.request('GET' if body is None else 'POST', path,
                                   None if body is None else json.dumps(body), headers)
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally: connection.close()
        try:
            payload = dict(profile_id=profile.profile_id, revision=profile.revision)
            self.assertEqual(request('/api/profile/delete', payload, False)[0], 403)
            self.assertEqual(request('/api/profile/delete', {**payload, 'extra': True})[0], 400)
            self.assertEqual(request('/api/profile/delete', payload)[0], 200)
            self.assertEqual(request('/api/bootstrap')[1]['profiles'], [])
            self.assertEqual(request('/api/deleted-profiles', authorized=False)[0], 403)
            deleted = request('/api/deleted-profiles')[1]
            self.assertEqual(len(deleted), 1)
            self.assertEqual({k: deleted[0][k] for k in ('profile_id', 'revision', 'name')}, dict(payload, name=profile.name))
            self.assertEqual(len(deleted[0]['deletion_token']), 64)
            self.assertEqual(request('/api/profile/' + profile.profile_id)[0], 400)
            self.assertEqual(request('/api/history/' + profile.profile_id)[0], 400)
            self.assertEqual(request('/api/save', dict(payload, name='Stale', base_preset=profile.base_preset,
                                                      mode=profile.mode, choices={}))[0], 400)
            code, restored = request('/api/profile/restore', payload)
            self.assertEqual(code, 200)
            self.assertEqual(restored['profile_id'], profile.profile_id)
            self.assertEqual(restored['revision'], profile.revision)
            self.assertEqual(len(request('/api/bootstrap')[1]['profiles']), 1)
            self.assertEqual(request('/api/deleted-profiles')[1], [])
        finally:
            server.shutdown(); server.server_close(); thread.join(2)


if __name__ == '__main__': unittest.main()
