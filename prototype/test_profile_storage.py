"""Readable storage migration, bounded recovery history and failure safety."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from world_profiles import Catalog, Profile, ProfileError, ProfileStore, RevisionConflict
from world_profiles.storage import HISTORY_LIMIT, _replace_json, write_new_json


class StorageLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent, prefix='.storage-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.store = ProfileStore(self.root / 'profiles', catalog=self.catalog)

    def current_copy(self, profile):
        directory = self.store.profile_directory(profile.profile_id)
        return directory / self.store._head(profile.profile_id)['portable_files'][0]

    def legacy(self, name='Legacy Warden', *, deleted=False):
        profile = self.catalog.create(name, choices={'dao.warden_romance': 'none'})
        directory = self.store.directory / profile.profile_id
        revision = directory / 'revisions/00000001.json'
        write_new_json(revision, dict(profile=profile.to_dict(), sha256=profile.sha256, parent_revision=None))
        write_new_json(directory / 'head.json', dict(revision=1, sha256=profile.sha256))
        if deleted:
            self.store.delete(profile.profile_id, profile.revision)
        return profile, directory

    def test_legacy_migration_preserves_ids_choices_revision_bytes_and_deleted_records(self):
        active, old = self.legacy()
        deleted, old_deleted = self.legacy('Deleted legacy', deleted=True)
        revision_bytes = (old / 'revisions/00000001.json').read_bytes()
        head_bytes = (old / 'head.json').read_bytes()
        marker = (old_deleted / 'deleted.json').read_bytes()
        self.assertEqual(self.store.prepare(), [])
        directory = self.store.profile_directory(active.profile_id)
        self.assertTrue(directory.name.startswith('Legacy Warden -- '))
        self.assertFalse(old.exists())
        self.assertFalse((directory / 'revisions').exists())
        self.assertEqual((directory / 'History/00000001.json').read_bytes(), revision_bytes)
        self.assertEqual({key: self.store._head(active.profile_id)[key] for key in ('revision', 'sha256')}, json.loads(head_bytes))
        self.assertEqual(Profile.load(self.current_copy(active)), active)
        self.assertEqual(self.store.load(active.profile_id), active)
        self.assertEqual(self.store.load(deleted.profile_id, include_deleted=True), deleted)
        self.assertEqual((self.store.profile_directory(deleted.profile_id) / 'deleted.json').read_bytes(), marker)
        before = {p.relative_to(self.store.directory): p.read_bytes() for p in self.store.directory.rglob('*') if p.is_file()}
        self.assertEqual(self.store.prepare(), [])
        self.assertEqual(before, {p.relative_to(self.store.directory): p.read_bytes() for p in self.store.directory.rglob('*') if p.is_file()})

    def test_renames_and_independent_store_instances_keep_the_same_identity(self):
        first = self.store.create('Marian')
        other = ProfileStore(self.store.directory, catalog=self.catalog)
        self.assertEqual(other.load(first.profile_id), first)
        old = self.store.profile_directory(first.profile_id)
        saved = self.store.save(first.edited(name='Marian — Mage'))
        self.assertFalse(old.exists())
        self.assertEqual(other.load(first.profile_id), saved)
        self.assertEqual(other.load(first.profile_id, revision=1), first)
        self.assertEqual(Profile.load(self.current_copy(saved)), saved)
        self.assertEqual(self.current_copy(saved).name, 'Marian — Mage.json')
        self.assertEqual(len(list(self.store.profile_directory(saved.profile_id).glob('*.json'))), 2)
        with self.assertRaises(RevisionConflict): other.save(first.edited(name='Stale edit'))
        imported = self.store.import_profile(self.current_copy(saved), name='Independent import')
        self.assertNotEqual(imported.profile_id, saved.profile_id)
        self.assertEqual(imported.choices, saved.choices)

    def test_names_are_windows_safe_and_duplicates_do_not_collide(self):
        for name in ('Head', 'deleted', 'CON', 'COM1.txt', '...','Warden / Mage: "Name"?', 'Éléonore 🐉', 'A' * 120):
            with self.subTest(name=name):
                first = self.store.create(name)
                second = self.store.create(name)
                folder = self.store.profile_directory(first.profile_id)
                self.assertEqual(folder.resolve().parent, self.store.directory)
                self.assertNotEqual(folder, self.store.profile_directory(second.profile_id))
                self.assertLess(len(folder.name), 90)
                self.assertEqual(Profile.load(self.current_copy(first)), first)
                self.assertEqual(self.store.load(first.profile_id), first)

    def test_retention_keeps_twenty_committed_versions_and_rejects_pruned_reads(self):
        current = self.store.create('Long history')
        originals = []
        for i in range(30):
            originals.append(current)
            current = self.store.save(current.edited(choices={'dao.warden_romance': 'none'} if i % 2 else {}))
            # The very first empty override is a no-op; use the name to force it.
            if current == originals[-1]:
                current = self.store.save(current.edited(name='Long history ' + str(i)))
        history = self.store.history(current.profile_id)
        self.assertEqual(len(history), HISTORY_LIMIT)
        self.assertEqual(history[0], current)
        self.assertEqual(len(list((self.store.profile_directory(current.profile_id) / 'History').glob('*.json'))), HISTORY_LIMIT)
        for old in history:
            self.assertEqual(self.store.load(current.profile_id, revision=old.revision), old)
        with self.assertRaisesRegex(ProfileError, 'committed'):
            self.store.load(current.profile_id, revision=1)
        files = {p: p.read_bytes() for p in self.store.profile_directory(current.profile_id).rglob('*') if p.is_file()}
        self.assertEqual(self.store.save(current), current)
        self.assertEqual(files, {p: p.read_bytes() for p in self.store.profile_directory(current.profile_id).rglob('*') if p.is_file()})

    def test_clear_preserves_current_and_next_save_continues_numbering(self):
        first = self.store.create('Clear me')
        current = self.store.save(first.edited(choices={'dao.warden_romance': 'none'}))
        copy_bytes = self.current_copy(current).read_bytes()
        with self.assertRaises(RevisionConflict): self.store.clear_history(first.profile_id, 1)
        with self.assertRaises(RevisionConflict): self.store.clear_history(first.profile_id, True)
        self.assertEqual(self.store.clear_history(current.profile_id, current.revision), current)
        self.assertEqual(self.store.load(current.profile_id), current)
        self.assertEqual(self.store.history(current.profile_id), [current])
        self.assertEqual(self.current_copy(current).read_bytes(), copy_bytes)
        self.assertEqual(list((self.store.profile_directory(current.profile_id) / 'History').glob('*.json'))[0].name, '00000002.json')
        saved = self.store.save(current.edited(choices={}))
        self.assertEqual(saved.revision, 3)
        self.assertEqual(self.store.history(saved.profile_id), [saved, current])

    def test_failed_head_updates_never_delete_history_or_change_the_committed_state(self):
        first = self.store.create('Keep this state')
        current = self.store.save(first.edited(choices={'dao.warden_romance': 'none'}))
        def deny_head(path, value):
            if path.name == 'head.json': raise OSError('Interrupted head replacement')
            return _replace_json(path, value)
        with patch('world_profiles.storage._replace_json', side_effect=deny_head):
            with self.assertRaises(OSError): self.store.clear_history(current.profile_id, current.revision)
            with self.assertRaises(OSError): self.store.save(current.edited(name='Uncommitted rename'))
        self.assertEqual(self.store.load(current.profile_id), current)
        self.assertEqual(self.store.history(current.profile_id), [current, first])
        self.assertEqual(Profile.load(self.current_copy(current)), current)
        saved = self.store.save(current.edited(name='Recovered'))
        self.assertEqual(saved.revision, 4, 'abandoned writes must not become committed history')
        self.assertEqual([p.revision for p in self.store.history(saved.profile_id)], [4, 2, 1])

    def test_failed_cleanup_keeps_a_usable_current_state_and_retries_on_prepare(self):
        current = self.store.create('Locked old revision')
        for i in range(1, HISTORY_LIMIT):
            current = self.store.save(current.edited(choices={'dao.warden_romance': 'none'} if i % 2 else {}))
        unlink = Path.unlink
        def deny_old(path, *args, **kwargs):
            if path.parent.name == 'History' and path.name == '00000001.json':
                raise PermissionError('Old revision temporarily in use')
            return unlink(path, *args, **kwargs)
        with patch('world_profiles.storage.Path.unlink', autospec=True, side_effect=deny_old):
            saved = self.store.save(current.edited(choices={}))
            self.assertEqual(len(self.store.history(saved.profile_id)), HISTORY_LIMIT)
        self.assertEqual(self.store.load(saved.profile_id), saved)
        self.assertEqual(self.store.prepare(), [])
        self.assertEqual(len(list((self.store.profile_directory(saved.profile_id) / 'History').glob('*.json'))), HISTORY_LIMIT)

    def test_unrelated_json_is_not_replaced_or_deleted(self):
        profile = self.store.create('Protected')
        path = self.store.profile_directory(profile.profile_id) / 'New name.json'
        path.write_text('{"my_document":true}', encoding='utf8')
        saved = self.store.save(profile.edited(name='New name'))
        path = self.store.profile_directory(saved.profile_id) / path.name
        self.assertEqual(json.loads(path.read_text()), {'my_document': True})
        self.assertEqual(self.store.load(profile.profile_id), saved)
        self.assertEqual(self.current_copy(saved).name, 'New name (current).json')
        self.store.delete(saved.profile_id, saved.revision)
        record, = self.store.deleted_records()
        with self.assertRaisesRegex(ProfileError, 'other files'):
            self.store.purge([{key: record[key] for key in ('profile_id', 'revision', 'deletion_token')}])
        self.assertTrue(path.exists())

    def test_migration_blocked_by_file_handles_is_retryable_without_losing_access(self):
        profile, old = self.legacy()
        with patch('world_profiles.storage.Path.rename', side_effect=PermissionError('File in use')):
            warnings = self.store.prepare()
        self.assertEqual(len(warnings), 1)
        self.assertEqual(self.store.load(profile.profile_id), profile)
        self.assertTrue(old.exists())
        self.assertEqual(self.store.prepare(), [])
        self.assertFalse(old.exists())

    def test_duplicate_ids_are_rejected_instead_of_picking_an_arbitrary_world_state(self):
        profile, _ = self.legacy()
        duplicate = self.store.directory / ('Extra -- ' + profile.profile_id)
        duplicate.mkdir()
        fresh = ProfileStore(self.store.directory, catalog=self.catalog)
        with self.assertRaisesRegex(ProfileError, 'Multiple folders'):
            fresh.load(profile.profile_id)

    def test_save_commits_even_when_the_cosmetic_folder_rename_is_temporarily_blocked(self):
        first = self.store.create('Original name')
        old = self.store.profile_directory(first.profile_id)
        with patch('world_profiles.storage.Path.rename', side_effect=PermissionError('Explorer handle')):
            saved = self.store.save(first.edited(name='Updated name'))
        self.assertTrue(old.exists())
        self.assertFalse((old / '.write.lock').exists())
        self.assertEqual(self.store.load(saved.profile_id), saved)
        self.assertEqual(Profile.load(self.current_copy(saved)), saved)
        self.assertEqual(self.store.prepare(), [])
        self.assertFalse(old.exists())
        self.assertTrue(self.store.profile_directory(saved.profile_id).name.startswith('Updated name -- '))

    def test_partially_completed_layout_migration_is_retryable(self):
        profile, old = self.legacy()
        rename = Path.rename
        def deny_outer(path, target):
            if path == old:
                raise PermissionError('Folder still in use')
            return rename(path, target)
        with patch('world_profiles.storage.Path.rename', autospec=True, side_effect=deny_outer):
            self.assertEqual(len(self.store.prepare()), 1)
        self.assertTrue((old / 'History').is_dir())
        self.assertFalse((old / '.write.lock').exists())
        self.assertEqual(self.store.load(profile.profile_id), profile)
        self.assertEqual(self.store.prepare(), [])
        self.assertEqual(self.store.history(profile.profile_id), [profile])

    def test_untracked_same_id_json_backups_are_preserved_during_migration_and_rename(self):
        profile, directory = self.legacy('Warden')
        backup = directory / 'Warden.json'
        backup_profile = profile.edited(choices={})
        backup.write_text(json.dumps(backup_profile.to_dict()), encoding='utf8')
        raw = backup.read_bytes()
        self.assertEqual(self.store.prepare(), [])
        directory = self.store.profile_directory(profile.profile_id)
        backup = directory / backup.name
        self.assertEqual(backup.read_bytes(), raw)
        self.assertEqual(self.current_copy(profile).name, 'Warden (current).json')
        saved = self.store.save(profile.edited(name='Updated Warden'))
        self.assertEqual((self.store.profile_directory(saved.profile_id) / backup.name).read_bytes(), raw)
        self.assertEqual(Profile.load(self.current_copy(saved)), saved)

    def test_derived_copy_failure_does_not_invalidate_committed_save_and_restart_repairs_it(self):
        first = self.store.create('Original')
        def deny_copy(path, value):
            if path.name != 'head.json':
                raise PermissionError('JSON preview locked')
            return _replace_json(path, value)
        with patch('world_profiles.storage._replace_json', side_effect=deny_copy):
            saved = self.store.save(first.edited(name='Updated'))
        self.assertEqual(self.store.load(first.profile_id), saved)
        self.assertEqual(self.store.history(first.profile_id), [saved, first])
        self.assertIn(first.profile_id, self.store.copy_warnings)
        restarted = ProfileStore(self.store.directory, catalog=self.catalog)
        self.assertEqual(restarted.prepare(), [])
        self.assertEqual(Profile.load(restarted.profile_directory(saved.profile_id) /
            restarted._head(saved.profile_id)['portable_files'][0]), saved)

    def test_invalid_copy_paths_and_unreachable_history_boundaries_are_rejected(self):
        first = self.store.create('Invalid metadata')
        # Create a legitimate gap from an interrupted save, then ensure a
        # boundary cannot point at that uncommitted revision.
        with patch('world_profiles.storage._replace_json', side_effect=OSError('Interrupted')):
            with self.assertRaises(OSError): self.store.save(first.edited(name='Abandoned'))
        saved = self.store.save(first.edited(name='Committed'))
        path = self.store.profile_directory(saved.profile_id) / 'head.json'
        head = json.loads(path.read_text(encoding='utf8'))
        path.write_text(json.dumps(dict(head, history_start=2)), encoding='utf8')
        with self.assertRaisesRegex(ProfileError, 'boundary'):
            self.store.history(saved.profile_id)
        for invalid in ('../backup.json', 'HEAD.json', 'deleted.json', '.head-other.json'):
            path.write_text(json.dumps(dict(head, portable_files=[invalid])), encoding='utf8')
            with self.assertRaisesRegex(ProfileError, 'current JSON'):
                self.store.load(saved.profile_id)


if __name__ == '__main__': unittest.main()
