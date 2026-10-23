"""Permanent removal is scoped to confirmed deleted histories, never exports."""
from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from gui import EditorApp, create_server, ROOT
from world_profiles import ProfileError, RevisionConflict


def selection(record):
    return {key: record[key] for key in ('profile_id', 'revision', 'deletion_token')}


class ProfilePurgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'prototype', prefix='.purge-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.app = EditorApp(self.root / 'profiles', self.root / 'exports')
        self.store = self.app.store

    def deleted(self, name):
        profile = self.store.create(name)
        latest = self.store.save(profile.edited(name=name + ' latest'))
        self.store.delete(latest.profile_id, latest.revision)
        return next(r for r in self.store.deleted_records() if r['profile_id'] == latest.profile_id)

    def test_erases_all_revisions_preserving_active_histories_exports_and_backups(self):
        active = self.store.create('Keep active')
        first, second = self.deleted('First'), self.deleted('Second')
        exported = self.root / 'Already exported.fbmod'
        backup = self.root / 'Independent profile.json'
        exported.write_bytes(b'preserve export'); backup.write_bytes(b'preserve backup')
        removed = self.store.purge([selection(first), selection(second)])
        self.assertEqual(set(removed), {first['profile_id'], second['profile_id']})
        for profile_id in removed:
            self.assertFalse((self.store.profile_directory(profile_id)).exists())
        self.assertEqual(self.store.load(active.profile_id), active)
        self.assertEqual(self.store.deleted_records(), [])
        self.assertEqual(exported.read_bytes(), b'preserve export')
        self.assertEqual(backup.read_bytes(), b'preserve backup')

    def test_empty_is_an_exact_snapshot_and_does_not_sweep_new_deletions(self):
        reviewed = self.deleted('Reviewed')
        later = self.deleted('Later')
        self.store.purge([selection(reviewed)])
        self.assertEqual(self.store.deleted_records(), [later])

    def test_restored_or_redeleted_history_invalidates_the_confirmation(self):
        first, second = self.deleted('First'), self.deleted('Second')
        self.store.restore(second['profile_id'], second['revision'])
        with self.assertRaises(RevisionConflict):
            self.store.purge([selection(first), selection(second)])
        self.assertTrue((self.store.profile_directory(first['profile_id']) / 'History').is_dir())
        # Re-deletion at the same revision still requires a fresh confirmation.
        self.store.delete(second['profile_id'], second['revision'])
        with self.assertRaises(RevisionConflict): self.store.purge([selection(second)])
        current = next(r for r in self.store.deleted_records() if r['profile_id'] == second['profile_id'])
        self.assertNotEqual(current['deletion_token'], second['deletion_token'])
        self.store.purge([selection(current)])

    def test_stale_revision_competing_lock_and_invalid_payloads_preserve_files(self):
        record = self.deleted('Protected')
        for invalid in ([], {}, [selection(record), selection(record)],
                        [{**selection(record), 'revision': True}],
                        [{**selection(record), 'revision': 1}],
                        [{**selection(record), 'profile_id': '../elsewhere'}],
                        [{**selection(record), 'deletion_token': 'x' * 64}]):
            with self.subTest(invalid=invalid), self.assertRaises(ProfileError):
                self.store.purge(invalid)
        with self.store._lock(self.store.profile_directory(record['profile_id'])):
            with self.assertRaises(RevisionConflict): self.store.purge([selection(record)])
        self.assertEqual(self.store.deleted_records(), [record])

    def test_partial_filesystem_failure_stays_listed_and_can_be_retried(self):
        record = self.deleted('Retry cleanup')
        unlink = Path.unlink
        def deny_revision(path, *args, **kwargs):
            if path.parent.name == 'History':
                raise PermissionError('File in use')
            return unlink(path, *args, **kwargs)
        with patch('world_profiles.storage.Path.unlink', autospec=True, side_effect=deny_revision):
            with self.assertRaises(PermissionError): self.store.purge([selection(record)])
        pending, = self.store.deleted_records()
        self.assertTrue(pending['purge_incomplete'])
        self.assertEqual(pending['name'], record['name'])
        with self.assertRaisesRegex(ProfileError, 'Permanent deletion has started'):
            self.store.restore(record['profile_id'], record['revision'])
        self.store.purge([selection(pending)])
        self.assertFalse((self.store.profile_directory(record['profile_id'])).exists())

    def test_other_files_inside_a_profile_folder_are_not_erased(self):
        record = self.deleted('Keep external files')
        directory = self.store.profile_directory(record['profile_id'])
        exported = directory / 'My export.fbmod'
        exported.write_bytes(b'preserve this export')
        with self.assertRaisesRegex(ProfileError, 'other files'):
            self.store.purge([selection(record)])
        self.assertEqual(exported.read_bytes(), b'preserve this export')
        self.assertEqual(self.store.deleted_records(), [record])
        self.assertTrue((directory / 'History/00000001.json').is_file())

    def test_cleanup_can_resume_when_head_is_gone_but_owned_current_copy_remains(self):
        record = self.deleted('Copy cleanup retry')
        directory = self.store.profile_directory(record['profile_id'])
        current = directory / self.store._head(record['profile_id'])['portable_files'][0]
        unlink = Path.unlink
        def deny_copy(path, *args, **kwargs):
            if path == current:
                # Simulate an interruption after the commit pointer was erased,
                # independent of the filesystem's enumeration order.
                unlink(directory / 'head.json', missing_ok=True)
                raise PermissionError('Copy is in use')
            return unlink(path, *args, **kwargs)
        with patch('world_profiles.storage.Path.unlink', autospec=True, side_effect=deny_copy):
            with self.assertRaises(PermissionError): self.store.purge([selection(record)])
        self.assertFalse((directory / 'head.json').exists())
        pending, = self.store.deleted_records()
        self.assertTrue(pending['purge_incomplete'])
        self.store.purge([selection(pending)])
        self.assertFalse(directory.exists())

    def test_redirected_profile_directory_cannot_erase_another_location(self):
        record = self.deleted('Redirected')
        directory = self.store.profile_directory(record['profile_id'])
        held = self.root / 'Held original profile'
        self.assertTrue(directory.resolve().is_relative_to(self.root))
        self.assertTrue(held.resolve().is_relative_to(self.root))
        directory.rename(held)
        outside = self.root / 'Outside profiles'
        outside.mkdir(); marker = outside / 'keep.txt'; marker.write_text('preserve')
        try:
            directory.symlink_to(outside, target_is_directory=True)
        except OSError as error:
            try:
                import _winapi
                _winapi.CreateJunction(str(outside), str(directory))
            except (ImportError, AttributeError, OSError):
                held.rename(directory)
                self.skipTest('Directory redirects unavailable: ' + str(error))
        try:
            with self.assertRaises(ProfileError): self.store.purge([selection(record)])
            self.assertEqual(marker.read_text(), 'preserve')
        finally:
            if directory.is_junction(): directory.rmdir()
            else: directory.unlink()
            held.rename(directory)

    def test_api_requires_authorization_and_a_reviewed_snapshot(self):
        record = self.deleted('API deletion')
        server = create_server(self.app)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.02), daemon=True)
        thread.start()
        def request(body, authorized=True, origin=None):
            headers = {'Content-Type': 'application/json'}
            if authorized: headers['Authorization'] = 'Bearer ' + self.app.token
            if origin: headers['Origin'] = origin
            connection = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            try:
                connection.request('POST', '/api/profiles/purge', json.dumps(body), headers)
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally: connection.close()
        try:
            payload = dict(profiles=[selection(record)])
            self.assertEqual(request(payload, authorized=False)[0], 403)
            self.assertEqual(request(payload, origin='https://example.org')[0], 403)
            self.assertEqual(request({})[0], 400)
            self.assertEqual(request(dict(profiles=[]))[0], 400)
            self.assertEqual(request(payload), (200, dict(purged=[record['profile_id']])))
        finally:
            server.shutdown(); server.server_close(); thread.join(2)


if __name__ == '__main__': unittest.main()
