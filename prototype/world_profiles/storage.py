"""Local immutable revisions with an atomic head pointer and stale-edit protection."""
from contextlib import contextmanager, ExitStack
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import re
import secrets
import tempfile

from .catalog import Catalog
from .model import Profile, ProfileError, canonical_json, check_id, now, read_json


class RevisionConflict(ProfileError):
    pass


HISTORY_LIMIT = 20


def _safe_name(name):
    # Leave room for the stable ID and history paths on Windows.
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .')[:40].rstrip(' .')
    if not value or value.lower() in {'head', 'deleted'} or value.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL',
            *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        value = 'World State ' + value
    return value.rstrip()


def _folder_id(name):
    return check_id(name.rsplit(' -- ', 1)[-1])


def _copy_name(value):
    return (isinstance(value, str) and 5 < len(value) <= 100 and value.endswith('.json')
        and value.casefold() not in ('head.json', 'deleted.json') and not value.startswith('.')
        and not re.search(r'[<>:"/\\|?*\x00-\x1f]', value)
        and value == value.strip(' .'))


def write_new_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents a competing export from overwriting this file.
    with path.open('xb') as stream:
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            stream.close()
            path.unlink()
            raise


def write_new_json(path, value):
    write_new_bytes(path, canonical_json(value) + b'\n')


def _replace_json(path, value):
    descriptor, temporary = tempfile.mkstemp(prefix='.head-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(canonical_json(value) + b'\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class ProfileStore:
    def __init__(self, directory, *, catalog=None):
        self.directory = Path(directory).resolve()
        self.catalog = catalog or Catalog()
        self._paths = {}
        self.copy_warnings = {}

    def _directory(self, profile_id):
        check_id(profile_id)
        cached = self._paths.get(profile_id)
        if cached is not None and cached.is_dir() and not cached.is_symlink() and not cached.is_junction():
            return cached
        matches = []
        if self.directory.is_dir():
            for path in self.directory.iterdir():
                try:
                    if path.is_dir() and _folder_id(path.name) == profile_id:
                        matches.append(path)
                except ProfileError:
                    continue
        if len(matches) > 1:
            raise ProfileError('Multiple folders contain this World State ID. Move the extra copy outside profile storage.')
        path = matches[0] if matches else self.directory / profile_id
        if path.is_symlink() or path.is_junction() or path.resolve().parent != self.directory:
            raise ProfileError('The World State folder is outside profile storage.')
        self._paths[profile_id] = path
        return path

    def profile_directory(self, profile_id):
        """Locate a World State independently of its current folder display name."""
        return self._directory(profile_id)

    def _history_directory(self, directory):
        old, new = directory / 'revisions', directory / 'History'
        if old.exists() and new.exists():
            raise ProfileError('The World State contains two history folders. Keep the original layout until this is resolved.')
        path = old if old.exists() else new
        if path.is_symlink() or path.is_junction():
            raise ProfileError('The World State history folder is redirected.')
        return path

    @contextmanager
    def _lock(self, directory):
        path = directory / '.write.lock'
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as error:
            raise RevisionConflict('Profile is locked by another writer. If a process crashed, inspect/remove ' + str(path)) from error
        except FileNotFoundError as error:
            raise RevisionConflict('The World State folder moved; reopen it before trying again.') from error
        try:
            with os.fdopen(descriptor, 'w', encoding='utf8') as stream:
                stream.write(str(os.getpid()))
            yield
        finally:
            # A display-name migration may have moved the directory, including
            # this lock. The stable ID still locates it without a second index.
            if not path.exists():
                path = self._directory(_folder_id(directory.name)) / '.write.lock'
            path.unlink()

    def _head(self, profile_id):
        path = self._directory(profile_id) / 'head.json'
        try:
            value = read_json(path)
        except FileNotFoundError:
            moved = self._directory(profile_id) / 'head.json'
            if moved == path:
                raise
            value = read_json(moved)
        if (not isinstance(value, dict) or not {'revision', 'sha256'} <= set(value)
                or set(value) - {'revision', 'sha256', 'history_start', 'portable_files'}
                or type(value['revision']) is not int or not 1 <= value['revision'] <= 99_999_999
                or not isinstance(value['sha256'], str)
                or ('history_start' in value and (type(value['history_start']) is not int
                    or not 1 <= value['history_start'] <= value['revision']))):
            raise ProfileError('Invalid profile head: ' + profile_id)
        copies = value.get('portable_files', [])
        if (not isinstance(copies, list) or len(copies) > 1000
                or not all(_copy_name(name) for name in copies)
                or len({name.casefold() for name in copies}) != len(copies)):
            raise ProfileError('Invalid current JSON file record: ' + profile_id)
        return value

    def _revision(self, profile_id, revision):
        if type(revision) is not int or not 1 <= revision <= 99_999_999:
            raise ProfileError('Invalid requested revision')
        path = self._history_directory(self._directory(profile_id)) / f'{revision:08d}.json'
        try:
            value = read_json(path)
        except FileNotFoundError:
            moved = self._history_directory(self._directory(profile_id)) / path.name
            if moved == path:
                raise
            value = read_json(moved)
        if not isinstance(value, dict) or set(value) != {'profile', 'sha256', 'parent_revision'}:
            raise ProfileError('Invalid stored revision: ' + str(path))
        profile = Profile.from_dict(value['profile'])
        parent = value['parent_revision']
        if (profile.profile_id != profile_id or profile.revision != revision or profile.sha256 != value['sha256']
                or (parent is not None and (type(parent) is not int or not 1 <= parent < revision))):
            raise ProfileError('Stored revision integrity check failed: ' + str(path))
        return profile, parent

    def load(self, profile_id, *, revision=None, include_deleted=False):
        if not include_deleted and (self._directory(profile_id) / 'deleted.json').exists():
            raise ProfileError('This world state was deleted. Restore it from Manage world states before using it.')
        head = self._head(profile_id)
        if revision is None:
            profile, _ = self._revision(profile_id, head['revision'])
            if profile.sha256 != head['sha256']:
                raise ProfileError('Profile head checksum does not match its revision')
            return profile
        # Historical reads follow the committed chain, excluding abandoned writes.
        for profile in self.history(profile_id, include_deleted=include_deleted):
            if profile.revision == revision:
                return profile
        raise ProfileError('Revision is not part of the committed history')

    def history(self, profile_id, *, include_deleted=False):
        # A concurrent trim can retire files after our head read. Retry against
        # its new committed boundary rather than exposing a partial history.
        for attempt in range(3):
            head = self._head(profile_id)
            current = self.load(profile_id, include_deleted=include_deleted)
            if current.revision != head['revision']:
                continue
            revision, result = current.revision, []
            try:
                while True:
                    profile, parent = self._revision(profile_id, revision)
                    result.append(profile)
                    first = head.get('history_start')
                    if revision == first or (first is None and parent is None):
                        return result
                    if parent is None or (first is not None and parent < first):
                        raise ProfileError('Saved revision boundary is not part of the committed history')
                    revision = parent
            except FileNotFoundError:
                if self._head(profile_id) == head:
                    raise
        raise RevisionConflict('Saved revisions changed; reopen the list.')

    def list(self, *, deleted=False):
        if not self.directory.exists():
            return []
        result = []
        for path in self.directory.iterdir():
            if not path.is_dir() or not (path / 'head.json').is_file():
                continue
            try:
                profile_id = _folder_id(path.name)
            except ProfileError:
                continue
            if (path / 'deleted.json').exists() != deleted:
                continue
            result.append(self.load(profile_id, include_deleted=deleted))
        return sorted(result, key=lambda profile: (profile.name.casefold(), profile.profile_id))

    def delete(self, profile_id, revision):
        """Hide a history without removing its immutable revisions or exports."""
        directory = self._directory(profile_id)
        with self._lock(directory):
            current = self.load(profile_id)
            if type(revision) is not int or current.revision != revision:
                raise RevisionConflict('The world state changed; reopen it before deleting')
            _replace_json(directory / 'deleted.json', dict(revision=revision, deleted_at=now(),
                                                         deletion_id=secrets.token_hex(16)))
        return current

    def restore(self, profile_id, revision):
        directory = self._directory(profile_id)
        with self._lock(directory):
            if not (directory / 'deleted.json').is_file():
                raise ProfileError('This world state is not deleted')
            if read_json(directory / 'deleted.json').get('purge_started'):
                raise ProfileError('Permanent deletion has started. Retry Delete permanently to remove the remaining files.')
            current = self.load(profile_id, include_deleted=True)
            if type(revision) is not int or current.revision != revision:
                raise RevisionConflict('The deleted world state changed; refresh the list before restoring')
            (directory / 'deleted.json').unlink()
        return current

    def _deleted_record(self, profile_id):
        directory = self._directory(profile_id)
        marker = read_json(directory / 'deleted.json')
        if (not isinstance(marker, dict) or type(marker.get('revision')) is not int
                or not 1 <= marker['revision'] <= 99_999_999):
            raise ProfileError('Invalid deleted world state record')
        incomplete = marker.get('purge_started') is True
        if incomplete:
            name = marker.get('name')
            if not isinstance(name, str) or not name:
                raise ProfileError('Invalid permanent deletion record')
        else:
            profile = self.load(profile_id, include_deleted=True)
            if profile.revision != marker['revision']:
                raise RevisionConflict('The deleted world state changed. Refresh the list.')
            name = profile.name
        return dict(profile_id=profile_id, revision=marker['revision'], name=name,
                    deletion_token=hashlib.sha256(canonical_json(marker)).hexdigest(),
                    purge_incomplete=incomplete)

    def deleted_records(self):
        if not self.directory.exists():
            return []
        records = []
        for directory in self.directory.iterdir():
            try:
                profile_id = _folder_id(directory.name)
            except ProfileError:
                continue
            if directory.is_dir() and (directory / 'deleted.json').is_file():
                records.append(self._deleted_record(profile_id))
        return sorted(records, key=lambda r: (r['name'].casefold(), r['profile_id']))

    def _purge_files(self, directory):
        """Only known history files may be erased; never recurse into user data."""
        self._history_directory(directory)  # Refuse ambiguous/redirected layouts before erasing anything.
        record = self._head(_folder_id(directory.name)) if (directory / 'head.json').exists() else read_json(directory / 'deleted.json')
        owned = record.get('portable_files', [])
        if not isinstance(owned, list) or not all(_copy_name(name) for name in owned):
            raise ProfileError('Invalid current JSON file record')
        files, revisions = [], None
        for child in directory.iterdir():
            if child.is_symlink() or child.is_junction():
                raise ProfileError('The world state folder contains a redirected file or folder. Remove the redirect before deleting permanently.')
            if child.name in {'.write.lock', 'deleted.json'} and child.is_file():
                continue
            if child.name in ('revisions', 'History') and child.is_dir():
                revisions = child
                for revision in child.iterdir():
                    if (revision.is_symlink() or revision.is_junction() or not revision.is_file()
                            or len(revision.name) != 13 or not revision.name[:8].isdigit()
                            or not revision.name.endswith('.json')):
                        raise ProfileError('The world state folder contains other files. Move them elsewhere before deleting permanently.')
                    files.append(revision)
            elif child.is_file() and (child.name == 'head.json' or child.match('.head-*.tmp')):
                files.append(child)
            elif child.is_file() and child.name in owned:
                files.append(child)
            else:
                raise ProfileError('The world state folder contains other files. Move them elsewhere before deleting permanently.')
        return files, revisions

    def purge(self, profiles):
        """Erase only an explicitly reviewed snapshot of already-deleted histories."""
        if not isinstance(profiles, list) or not 1 <= len(profiles) <= 10_000:
            raise ProfileError('Select deleted world states to remove permanently.')
        seen, targets = set(), []
        for entry in profiles:
            if (not isinstance(entry, dict) or set(entry) != {'profile_id', 'revision', 'deletion_token'}
                    or type(entry['revision']) is not int or not isinstance(entry['deletion_token'], str)
                    or len(entry['deletion_token']) != 64):
                raise ProfileError('Invalid permanent deletion request')
            directory = self._directory(entry['profile_id'])
            if entry['profile_id'] in seen:
                raise ProfileError('A world state was selected more than once.')
            seen.add(entry['profile_id'])
            # Never recurse through a redirected profile folder or outside this store.
            if (directory.is_symlink() or directory.is_junction()
                    or directory.resolve().parent != self.directory):
                raise ProfileError('The world state folder is outside profile storage.')
            targets.append((directory, entry))
        completed = []
        try:
            with ExitStack() as locks:
                for directory, _ in sorted(targets, key=lambda item: str(item[0])):
                    locks.enter_context(self._lock(directory))
                # Validate every target before removing anything. A restore or a
                # new deletion of the same revision invalidates the reviewed token.
                for directory, entry in targets:
                    if not (directory / 'deleted.json').is_file():
                        raise RevisionConflict('A selected world state is no longer deleted. Refresh the list.')
                    current = self._deleted_record(entry['profile_id'])
                    if (current['revision'] != entry['revision']
                            or current['deletion_token'] != entry['deletion_token']):
                        raise RevisionConflict('The deleted list changed. Review it before deleting permanently.')
                    self._purge_files(directory)
                for directory, entry in targets:
                    record = self._deleted_record(entry['profile_id'])
                    marker = read_json(directory / 'deleted.json')
                    owned = self._head(entry['profile_id']).get('portable_files', []) if (directory / 'head.json').exists() else marker.get('portable_files', [])
                    marker.update(purge_started=True, name=record['name'], portable_files=owned)
                    _replace_json(directory / 'deleted.json', marker)
                    # Keep the marker and lock until all other files are gone.
                    # A failed cleanup remains listed and can be retried without
                    # needing revision files that have already been erased.
                    files, revisions = self._purge_files(directory)
                    for file in files:
                        file.unlink()
                    if revisions is not None:
                        revisions.rmdir()
                    if self._purge_files(directory)[0]:
                        raise RevisionConflict('The world state folder changed during deletion. Review the remaining files.')
                    (directory / 'deleted.json').unlink()
                    completed.append(directory)
        finally:
            # Locks have been released. Completed directories contain no history.
            for directory in completed:
                directory.rmdir()
        return [_folder_id(directory.name) for directory in completed]

    def _copy_files(self, directory, profile, owned):
        # Untracked files belong to the user, even when they contain this same
        # profile ID. Reserve a free name without replacing or adopting them.
        for number in range(1000):
            suffix = '' if number == 0 else ' (current)' if number == 1 else f' (current {number})'
            name = _safe_name(profile.name) + suffix + '.json'
            path = directory / name
            existing = next((old for old in owned if old.casefold() == name.casefold()), None)
            if existing is not None or not (path.exists() or path.is_symlink() or path.is_junction()):
                copies = [existing or name, *(old for old in owned if old != existing)]
                if len(copies) > 1000:
                    raise ProfileError('Too many current JSON copies are awaiting cleanup. Close programs using them and reopen the storage folder.')
                return copies
        raise ProfileError('No free filename is available for the current World State JSON')

    def _portable_copy(self, directory, profile, head, *, strict=False):
        try:
            owned = head['portable_files']
            target = directory / owned[0]
            if target.is_symlink() or target.is_junction():
                raise ProfileError('The current World State JSON file is redirected.')
            try:
                previous = Profile.load(target)
            except (OSError, ProfileError):
                previous = None  # This explicitly owned, derived copy is repairable.
            if previous != profile:
                _replace_json(target, profile.to_dict())
            remaining = [target.name]
            for name in owned[1:]:
                path = directory / name
                try:
                    if path.is_symlink() or path.is_junction():
                        raise ProfileError('An obsolete current JSON copy is redirected.')
                    path.unlink(missing_ok=True)
                except (OSError, ProfileError):
                    remaining.append(name)
            if remaining != owned:
                _replace_json(directory / 'head.json', dict(head, portable_files=remaining))
            self.copy_warnings.pop(profile.profile_id, None)
        except (OSError, ProfileError) as error:
            self.copy_warnings[profile.profile_id] = ('Your World State is saved, but its current JSON copy could not be refreshed. '
                'Use Open World State folder to retry. ' + str(error))
            if strict:
                raise

    def _organize(self, directory, profile):
        history = self._history_directory(directory)
        if history.name == 'revisions':
            history.rename(directory / 'History')
        destination = self.directory / (_safe_name(profile.name) + ' -- ' + profile.profile_id)
        if directory != destination:
            if destination.exists():
                raise ProfileError('The readable World State folder already exists. Move the extra folder outside profile storage.')
            # Both paths must be direct, non-redirected children of this store.
            if directory.resolve().parent != self.directory or destination.resolve().parent != self.directory:
                raise ProfileError('The World State folder is outside profile storage.')
            directory.rename(destination)
            self._paths[profile.profile_id] = destination
        return destination

    def prepare(self, *, strict=False):
        """Migrate names/copies without changing any committed revision or choices."""
        warnings = []
        profiles = self.list() + [self.load(record['profile_id'], include_deleted=True)
            for record in self.deleted_records() if not record['purge_incomplete']]
        for profile in profiles:
            directory = self._directory(profile.profile_id)
            try:
                with self._lock(directory):
                    current = self.load(profile.profile_id, include_deleted=True)
                    head = self._head(current.profile_id)
                    copies = self._copy_files(directory, current, head.get('portable_files', []))
                    if head.get('portable_files') != copies:
                        head = dict(head, portable_files=copies)
                        _replace_json(directory / 'head.json', head)
                    self._portable_copy(directory, current, head, strict=True)
                    directory = self._organize(directory, current)
                    self._prune(directory, self._head(current.profile_id).get('history_start'))
            except (OSError, ProfileError) as error:
                if strict:
                    raise
                warnings.append(profile.name + ': ' + str(error))
        return warnings

    def _prune(self, directory, first):
        if first is None:
            return
        # The head already excludes these revisions. Cleanup failure may leave
        # extra backups, but cannot make a successful save appear to have failed.
        try:
            candidates = list(self._history_directory(directory).glob('*.json'))
        except (OSError, ProfileError):
            return
        for path in candidates:
            if not re.fullmatch(r'\d{8}\.json', path.name) or int(path.stem) >= first or path.is_symlink():
                continue
            try:
                value = read_json(path)
                if Profile.from_dict(value['profile']).profile_id == _folder_id(directory.name):
                    path.unlink()
            except (OSError, ProfileError, KeyError, TypeError):
                continue

    def clear_history(self, profile_id, revision):
        """Keep the current committed revision and retire all earlier revisions."""
        directory = self._directory(profile_id)
        with self._lock(directory):
            current = self.load(profile_id)
            if type(revision) is not int or current.revision != revision:
                raise RevisionConflict('The World State changed; reopen saved revisions before clearing them.')
            head = dict(self._head(profile_id), history_start=current.revision)
            if not head.get('portable_files'):
                head['portable_files'] = self._copy_files(directory, current, [])
            _replace_json(directory / 'head.json', head)
            self._portable_copy(directory, current, head)
            self._prune(directory, current.revision)
        return current

    def _append(self, directory, profile, parent):
        path = self._history_directory(directory) / f'{profile.revision:08d}.json'
        write_new_json(path, dict(profile=profile.to_dict(), sha256=profile.sha256, parent_revision=parent))
        previous_head = self._head(profile.profile_id) if parent is not None else {}
        history = self.history(profile.profile_id) if parent is not None else []
        first = ([profile] + history[:HISTORY_LIMIT - 1])[-1].revision
        head = dict(revision=profile.revision, sha256=profile.sha256, history_start=first,
            portable_files=self._copy_files(directory, profile, previous_head.get('portable_files', [])))
        _replace_json(directory / 'head.json', head)
        self._portable_copy(directory, profile, head)
        self._prune(directory, first)

    def _insert(self, profile):
        self.catalog.validate(profile)
        directory = self.directory / (_safe_name(profile.name) + ' -- ' + profile.profile_id)
        directory.mkdir(parents=True, exist_ok=False)
        self._paths[profile.profile_id] = directory
        with self._lock(directory):
            self._append(directory, profile, None)
        return profile

    def create(self, name, *, base_preset=None, choices=None, mode=None):
        return self._insert(self.catalog.create(name, base_preset=base_preset, choices=choices, mode=mode))

    def save(self, profile):
        """Commit edits to the supplied current revision; never overwrite history."""
        self.catalog.validate(profile)
        directory = self._directory(profile.profile_id)
        with self._lock(directory):
            current = self.load(profile.profile_id)
            if profile.revision != current.revision:
                raise RevisionConflict('Profile changed since it was loaded; reload before saving')
            immutable = ('schema_version', 'profile_id', 'created_at', 'updated_at', 'base_preset')
            if any(getattr(profile, key) != getattr(current, key) for key in immutable):
                raise ProfileError('Save cannot change profile identity, baseline, timestamps, or mapping; create a new profile/migration')
            if (profile.mapping_version, profile.mapping_sha256) != (current.mapping_version, current.mapping_sha256):
                upgraded = self.catalog.upgrade(current)
                if (profile.mapping_version, profile.mapping_sha256) != (upgraded.mapping_version, upgraded.mapping_sha256):
                    raise ProfileError('Unrecognized mapping migration')
            if profile.to_dict() == current.to_dict():
                return current
            revision = current.revision + 1
            # A crash before head replacement can leave an uncommitted revision.
            while (self._history_directory(directory) / f'{revision:08d}.json').exists():
                revision += 1
            saved = replace(profile, revision=revision, updated_at=now())
            self._append(directory, saved, current.revision)
            # Cosmetic renames must not turn an already committed save into an
            # apparent failure (Explorer/antivirus may briefly hold a handle).
            try:
                self._organize(directory, saved)
            except (OSError, ProfileError):
                pass  # Retried on startup or when opening the storage folder.
            return saved

    def duplicate(self, profile_id, name, *, revision=None):
        original = self.load(profile_id)
        if revision is not None and (type(revision) is not int or original.revision != revision):
            raise RevisionConflict('The saved profile changed; reopen it before duplicating')
        # Duplicate the same immutable snapshot whose revision was checked.
        # A second head read could silently select a concurrent writer's edits.
        original = self.catalog.upgrade(original)
        return self.create(name, base_preset=original.base_preset, choices=dict(original.choices), mode=original.mode)

    def import_profile(self, path, *, name=None):
        source = self.catalog.upgrade(Profile.load(path))
        self.catalog.validate(source)
        # Imported documents are new independent profiles; IDs never overwrite a local history.
        return self.create(source.name if name is None else name, base_preset=source.base_preset,
                           choices=dict(source.choices), mode=source.mode)

    def export_json(self, profile_id, output, *, revision=None):
        profile = self.load(profile_id, revision=revision)
        write_new_json(output, profile.to_dict())
        return profile
