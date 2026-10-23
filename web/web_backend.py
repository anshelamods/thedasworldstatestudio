"""Browser request router for the GitHub Pages build. No network server is used.

Pyodide runs this module in a Web Worker. It replaces only the HTTP layer of
prototype/gui.py: requests reach the same EditorApp, profile store, compiler
and save importers as in the desktop application. Desktop-only actions (folder
pickers, opening Explorer, the window lifecycle) do not exist in a browser, and
exports are returned to the page for download instead of written to a folder.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
import traceback
from urllib.parse import parse_qs, unquote, urlsplit

from gui import MAX_BODY, EditorApp
from world_profiles import Profile, ProfileError, RevisionConflict
from world_profiles.model import canonical_json
from game_saves.gff import MAX_SAVE_BYTES

SAVE_UPLOADS = {'/api/save-import/preview': 'da2', '/api/dao-save-import/preview': 'dao'}
# Requests that leave stored World States and settings unchanged.
READ_ONLY = {'/api/preview', '/api/propose', '/api/save-import/plan', '/api/save-import/cancel', *SAVE_UPLOADS}
ART_PREFIXES = ('/art/', '/interface-art/')


def _relative_art(value):
    """Serve artwork beside the page, whatever path GitHub Pages hosts it under."""
    if isinstance(value, str):
        return value[1:] if value.startswith(ART_PREFIXES) else value
    if isinstance(value, dict):
        return {key: _relative_art(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_relative_art(item) for item in value]
    return value


class WebEditor:
    def __init__(self, data_dir, exports):
        data_dir = Path(data_dir)
        self.app = EditorApp(data_dir / 'profiles', exports)

    def read_only(self, method, path):
        return method == 'GET' or urlsplit(path).path in READ_ONLY

    def handle(self, method, path, content_type, body):
        """Return (status, JSON text) for one editor request."""
        try:
            result = self.get(path) if method == 'GET' else self.post(path, content_type, body)
            status = 200 if result is not None else 404
            result = {'error': 'Unknown action'} if result is None else result
        except RevisionConflict as error:
            status, result = 409, {'error': str(error)}
        except (ValueError, OSError, AssertionError, TypeError) as error:
            status, result = 400, {'error': str(error)}
        except Exception as error:  # Report unexpected failures instead of losing the request.
            traceback.print_exc()
            status, result = 500, {'error': 'The editor encountered an unexpected error: ' + str(error)}
        return status, canonical_json(_relative_art(result)).decode('utf8')

    def get(self, raw_path):
        app = self.app
        path = unquote(urlsplit(raw_path).path)
        query = parse_qs(urlsplit(raw_path).query)
        if path == '/api/bootstrap':
            return app.bootstrap()
        if path == '/api/ping':
            return {'ok': True}
        if path == '/api/export-settings':
            return app.export_settings(query.get('base_preset', [None])[0])
        if path == '/api/deleted-profiles':
            return app.store.deleted_records()
        if path.startswith('/api/profile/'):
            return app.editor_profile(app.store.load(path.removeprefix('/api/profile/')))
        if path.startswith('/api/history/'):
            return [profile.to_dict() for profile in app.store.history(path.removeprefix('/api/history/'))]
        return None

    def post(self, raw_path, content_type, body):
        app = self.app
        path = urlsplit(raw_path).path
        body = body.to_bytes() if hasattr(body, 'to_bytes') else bytes(body or b'')
        content_type = (content_type or '').split(';')[0].strip()
        if not 0 < len(body) <= (MAX_SAVE_BYTES if path in SAVE_UPLOADS else MAX_BODY):
            raise ValueError('Document is missing or too large')
        if path in SAVE_UPLOADS:
            if content_type != 'application/octet-stream':
                raise ValueError('Expected a game save file')
            return app.save_imports.preview(body, game=SAVE_UPLOADS[path])
        if content_type != 'application/json':
            raise ValueError('Expected a JSON document')
        data = json.loads(body.decode('utf8'))
        if not isinstance(data, dict):
            raise ProfileError('Expected a JSON object')
        if path == '/api/preview':
            return app.preview(data)
        if path == '/api/propose':
            return app.propose(data)
        if path == '/api/save':
            profile = app.save(data)
            result = profile.to_dict()
            if profile.profile_id in app.store.copy_warnings:
                result['storage_warning'] = app.store.copy_warnings[profile.profile_id]
            return result
        if path in ('/api/profile/delete', '/api/profile/restore'):
            if set(data) != {'profile_id', 'revision'}:
                raise ProfileError('Invalid World State deletion/restore request')
            if path.endswith('/delete'):
                profile = app.store.delete(data['profile_id'], data['revision'])
                return dict(deleted=True, profile_id=profile.profile_id)
            return app.editor_profile(app.store.restore(data['profile_id'], data['revision']))
        if path == '/api/profiles/purge':
            if set(data) != {'profiles'}:
                raise ProfileError('Invalid permanent deletion request')
            return dict(purged=app.store.purge(data['profiles']))
        if path == '/api/profile/clear-history':
            if set(data) != {'profile_id', 'revision'}:
                raise ProfileError('Invalid saved revisions request')
            app.store.clear_history(data['profile_id'], data['revision'])
            result = dict(cleared=True)
            if data['profile_id'] in app.store.copy_warnings:
                result['storage_warning'] = app.store.copy_warnings[data['profile_id']]
            return result
        if path == '/api/save-import/commit':
            return app.save_imports.commit(data).to_dict()
        if path == '/api/save-import/plan':
            return app.save_imports.plan(data)
        if path == '/api/save-import/cancel':
            return app.save_imports.cancel(data)
        if path == '/api/export':
            return self.export(data)
        if path == '/api/export-settings':
            return app.fbmod_settings.save(data)
        if path == '/api/duplicate':
            if set(data) != {'profile_id', 'revision', 'name'}:
                raise ProfileError('Invalid duplicate request')
            if type(data['revision']) is not int:
                raise RevisionConflict('The saved profile changed; reopen it before duplicating')
            return app.store.duplicate(data['profile_id'], data['name'], revision=data['revision']).to_dict()
        if path == '/api/import':
            if set(data) != {'document'}:
                raise ProfileError('Invalid import request')
            profile = app.catalog.upgrade(Profile.from_dict(data['document']))
            app.catalog.validate(profile)
            # Reject unavailable legacy templates before committing a
            # history that the next bootstrap could not display.
            app.catalog.template_path(profile.base_preset)
            return app.store.create(profile.name, base_preset=profile.base_preset,
                                    mode=profile.mode, choices=dict(profile.choices)).to_dict()
        return None

    def export(self, data):
        """Write the FBMOD in temporary memory and hand both files to the page."""
        if not isinstance(data, dict) or 'directory' in data:
            raise ProfileError('Export requires a saved profile and revision')
        result = self.app.export(dict(data, directory=str(self.app.exports)))
        mod, report = self.app.downloads.pop(result['download_id'])
        try:
            files = dict(mod=base64.b64encode(mod.read_bytes()).decode('ascii'),
                         report=base64.b64encode(report.read_bytes()).decode('ascii'))
        finally:
            mod.unlink(missing_ok=True)
            report.unlink(missing_ok=True)
        return dict(name=mod.name, report_name=report.name, revision=result['revision'],
                    sha256=result['sha256'], warnings=result['warnings'], files=files)
