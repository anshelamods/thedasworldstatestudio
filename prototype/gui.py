"""Local GUI server and Windows app-window launcher. No Keep connection is used."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import threading
from urllib.parse import parse_qs, quote, unquote, urlsplit
import webbrowser

from world_profiles import Catalog, Profile, ProfileError, ProfileStore, RevisionConflict
from world_profiles.compiler import ExportCollision, StoryConflict, compile_profile, export_profile_mod
from world_profiles.model import canonical_json, read_json
from export_worldstate import read_mod
from fbmod_metadata import (FbmodSettings, MAX_ICON_BYTES, available_export, decode_icon,
                            image_data_url, metadata_text, suggested_filename)
from export_destination import ExportLocation, choose_export_folder, export_directory, open_export_folder
from app_runtime import APP_NAME, APP_VERSION, editor_directories, resource_root
from editor_lifecycle import EditorLifecycle, watch_editor
from game_saves.gff import MAX_SAVE_BYTES
from game_saves.service import SaveImports

ROOT = resource_root()
WEB = ROOT / 'prototype/gui'
MAX_BODY = 1_048_576
STATIC_CONTENT_TYPES = {
    '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8', '.woff': 'font/woff',
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.ico': 'image/vnd.microsoft.icon',
}


class EditorApp:
    def __init__(self, store, exports):
        self.catalog = Catalog()
        self.store = ProfileStore(store, catalog=self.catalog)
        self.storage_warnings = self.store.prepare()
        self.exports = Path(exports).resolve()
        self.fbmod_settings = FbmodSettings(self.store.directory.parent / 'fbmod-settings.json')
        self.export_location = ExportLocation(self.store.directory.parent / 'export-location.json', self.exports)
        self.export_lock = threading.Lock()
        self.token = secrets.token_urlsafe(32)
        self.downloads = {}
        self.lifecycle = EditorLifecycle()
        self.presentation = read_json(WEB / 'presentation.json')
        self.save_imports = SaveImports(self.catalog, self.store, self.presentation)
        self._media = {}
        self._category_media = {}
        manifest = read_json(ROOT / 'assets/keep/manifest.json')
        for asset in manifest['assets']:
            for reference in asset['references']:
                if reference['use'] == 'detail':
                    self._media[(reference['flag'], reference['keep_value'])] = asset['path']
                elif reference['use'] == 'top':
                    self._category_media[(reference['flag'], reference['keep_value'])] = asset['path']
        self.allowed_art = {asset['path'] for asset in manifest['assets']}
        interface_manifest = read_json(ROOT / 'assets/keep-interface/manifest.json')
        self.allowed_interface_art = {asset['path'] for asset in interface_manifest['assets']}
        self.categories = read_json(WEB / 'categories.json')
        categories = {category['id']: category for category in self.categories}
        if len(categories) != len(self.categories):
            raise ProfileError('Duplicate presentation category')
        for category in self.categories:
            if (category.get('art') not in self.allowed_art and
                    category.get('interface_art') not in self.allowed_interface_art):
                raise ProfileError('Category artwork is not in the local archive')
            driver = self.presentation.get(category.get('art_choice'))
            if category.get('art_choice') and (not driver or driver['category_id'] != category['id']):
                raise ProfileError('Category artwork references an unsupported choice')
        definitions = self.catalog.choices
        for choice in self.presentation.values():
            category = categories.get(choice.get('category_id'))
            if not category or category['game'] != choice['game']:
                raise ProfileError('Choice has an invalid presentation category')
            for answer in choice['answers'].values():
                for choice_id, answer_id in answer.get('related_choices', {}).items():
                    if choice_id not in definitions or answer_id not in definitions[choice_id]['answers']:
                        raise ProfileError('Illustrated answer references an unsupported related choice')
                if answer.get('archive_art') and answer['archive_art'] not in self.allowed_art:
                    raise ProfileError('Choice artwork is not in the local archive')
                for path in [answer.get('art'), *answer.get('art_variants', {}).values()]:
                    if path and path not in self.allowed_interface_art:
                        raise ProfileError('Hero artwork is not in the local archive')

    def choices(self):
        result = []
        definitions = self.catalog.choices
        for choice_id, presentation in self.presentation.items():
            definition = definitions[choice_id]
            answers = []
            for answer_id, answer in definition['answers'].items():
                copy = dict(presentation['answers'][answer_id])
                value = copy.pop('keep_art_value', answer.get('keep_art_value',
                    answer['export_values'].get(presentation.get('art_value_field'))))
                art = self._media.get((presentation.get('art_flag'), str(value)))
                art = copy.pop('archive_art', None) or art
                hero_art = copy.pop('art', None)
                variants = copy.pop('art_variants', {})
                answers.append(dict(id=answer_id, **copy,
                                    art='/interface-art/' + quote(hero_art, safe='/') if hero_art else
                                        '/art/' + quote(art, safe='/') if art else None,
                                    art_variants={key: '/interface-art/' + quote(path, safe='/')
                                                  for key, path in variants.items()}))
            result.append(dict(id=choice_id, **{key: value for key, value in presentation.items()
                                              if key not in ('answers', 'art_flag', 'art_value_field')},
                               answers=answers, evidence_status=definition['evidence_status']))
        return result

    def bootstrap(self):
        supported = {choice['category_id'] for choice in self.presentation.values()}
        categories = [dict(category, art=('/interface-art/' + quote(category['interface_art'], safe='/')
                                        if category.get('interface_art') else
                                        '/art/' + quote(category['art'], safe='/')))
                      for category in self.categories if category['id'] in supported]
        bundled = read_json(ROOT / 'prototype/bundled-presets.json')
        return dict(choices=self.choices(), categories=categories, presets=[dict(id=entry['id'], label=entry['label'], mode='keep')
                    for entry in bundled['presets']],
                    default_preset=self.catalog.default_preset,
                    app_version=APP_VERSION, app_name=APP_NAME,
                    storage_warnings=self.storage_warnings,
                    preset_labels={key: value['label'] for key, value in self.catalog.presets.items()},
                    profiles=[self.editor_profile(profile) for profile in self.store.list()],
                    bridge_available=False, mapping_version=self.catalog.version,
                    export_directory=str(self.export_location.load()))

    def category_art(self, compiled):
        """Use Keep's category banners for the effective, approved history.

        Top artwork can differ from the decision painting, notably romance,
        the narrow Circle/Redcliffe banners and the Anvil's grouped outcomes.
        Unselected local-only history retains the category's placeholder art.
        """
        result = {}
        definitions = self.catalog.choices
        for category in self.categories:
            key = category.get('art_choice')
            if not key:
                continue
            view = self.presentation[key]
            answer_id = compiled.report['resolved_choices'][key]['answer_id']
            answer = definitions[key]['answers'].get(answer_id, {})
            display = view['answers'].get(answer_id, {})
            if not view.get('art_flag'):
                # Hawke's combined gender/class control supplies its own art.
                path = display.get('art')
                if path:
                    result[category['id']] = '/interface-art/' + quote(path, safe='/')
                continue
            value = display.get('keep_art_value', answer.get('keep_art_value',
                compiled.effective_values.get(view.get('art_value_field'))))
            reference = (view['art_flag'], str(value))
            path = self._category_media.get(reference) or self._media.get(reference)
            if path:
                result[category['id']] = '/art/' + quote(path, safe='/')
        return result

    def editor_profile(self, profile):
        # The portable document stays untouched; only the editor representation
        # uses the losslessly converted controls until the user saves.
        return dict(profile.to_dict(), editor_choices=dict(self.catalog.upgrade(profile).choices))

    def draft(self, data):
        if not isinstance(data, dict) or set(data) != {'profile_id', 'revision', 'name', 'base_preset', 'mode', 'choices'}:
            raise ProfileError('Invalid editor document')
        if data['profile_id'] is None:
            if type(data['revision']) is not int or data['revision'] != 0:
                raise ProfileError('An unsaved profile must have revision zero')
            return self.catalog.normalize(self.catalog.create(data['name'], base_preset=data['base_preset'],
                                       mode=data['mode'], choices=data['choices']))
        current = self.store.load(data['profile_id'])
        if type(data['revision']) is not int or data['revision'] != current.revision:
            raise RevisionConflict('This profile has a newer saved revision. Reopen it before saving your edits.')
        if data['base_preset'] != current.base_preset:
            raise ProfileError('A saved profile cannot change its inherited preset')
        return self.catalog.normalize(self.catalog.upgrade(current).edited(
            name=data['name'], mode=data['mode'], choices=data['choices']))

    def preview(self, data):
        profile = self.draft(data)
        try:
            compiled = compile_profile(profile, catalog=self.catalog)
            errors = []
        except StoryConflict:
            # Presentation can still show the choices that need correcting.
            # Only this temporary preview uses experimental mode; saving/export
            # continues to use the actual profile's mode.
            compiled = compile_profile(profile.edited(mode='experimental'), catalog=self.catalog)
            errors = compiled.report['story_conflicts']
            if profile.mode == 'keep':
                from world_profiles.story_rules import RuleSet
                fields = {field: key for key, definition in self.catalog.choices.items() if key in self.presentation
                          for answer in definition['answers'].values() for field in answer['export_values']}
                rule_set = RuleSet(self.catalog)
                fields.update({source['field']: key for key, source in rule_set.profile_inputs.items()})
                targets = dict.fromkeys(key[1] for key, _ in rule_set.violations(compiled.effective_values, profile.choices))
                errors = [self.presentation[fields[target]]['title'] + ': this answer needs changes to related choices.'
                          for target in targets if target in fields] or ['These outcomes need changes to related choices.']
        return dict(resolved_choices=compiled.report['resolved_choices'],
                    category_art=self.category_art(compiled),
                    hero_appearance=compiled.report['hero_appearance'], can_export=not errors,
                    errors=errors, experimental_conflicts=compiled.report['story_conflicts'] if profile.mode == 'experimental' else [],
                    mapping_upgrade_pending=bool(data['profile_id'] and self.store.load(data['profile_id']).mapping_version != profile.mapping_version),
                    changed_choices=len(profile.choices), inherited_flag_count=compiled.report['inherited_flag_count'])

    def propose(self, data):
        from world_profiles.story_rules import propose
        if not isinstance(data, dict) or set(data) != {'draft', 'updates', 'mode'}:
            raise ProfileError('Invalid story change request')
        if data['mode'] not in ('keep', 'experimental'):
            raise ProfileError('Invalid story restriction mode')
        original = self.draft(data['draft'])
        candidate = propose(original, data['updates'], mode=data['mode'], catalog=self.catalog,
                            editable=self.presentation)
        before = compile_profile(original.edited(mode='experimental'), catalog=self.catalog)
        after = compile_profile(candidate, catalog=self.catalog)
        changes = []
        # Include effective inherited changes, not just new explicit selections.
        for key, presentation in self.presentation.items():
            old = before.report['resolved_choices'][key]
            new = after.report['resolved_choices'][key]
            if candidate.mode == 'keep' and key not in data['updates'] and old['answer_id'] != new['answer_id']:
                changes.append(dict(choice_id=key, title=presentation['title'],
                                    before=old['answer_id'], after=new['answer_id'],
                                    before_label=old['label'] or 'Other inherited outcome',
                                    after_label=new['label'] or 'Other inherited outcome'))
        draft = dict(data['draft'], mode=candidate.mode, choices=dict(candidate.choices))
        return dict(draft=draft, changes=changes)

    def save(self, data):
        profile = self.draft(data)
        if profile.mode == 'keep':
            compile_profile(profile, catalog=self.catalog)
        if data['profile_id'] is None:
            return self.store.create(profile.name, base_preset=profile.base_preset,
                                     mode=profile.mode, choices=dict(profile.choices))
        return self.store.save(profile)

    def _preset_icon(self, template):
        icon = next(record for record in template['records'] if record['kind'] == 0 and record['name'] == 'Icon')
        if icon['index'] >= 0:
            return template['payloads'][icon['index']]
        # The original game baseline contains no image. Reuse an icon from the
        # reviewed, bundled presets rather than exporting an empty icon slot.
        bundled = read_json(ROOT / 'prototype/bundled-presets.json')
        for entry in bundled['presets']:
            fallback = read_mod(self.catalog.template_path(entry['id']).read_bytes())
            icon = next(record for record in fallback['records'] if record['kind'] == 0 and record['name'] == 'Icon')
            if icon['index'] >= 0:
                return fallback['payloads'][icon['index']]
        raise ProfileError('The bundled FBMOD preset icon is missing.')

    def export_settings(self, preset_id=None):
        preset_id = self.catalog.default_preset if preset_id is None else preset_id
        template = read_mod(self.catalog.template_path(preset_id).read_bytes())
        data = self._preset_icon(template)
        return dict(settings=self.fbmod_settings.load(), category=template['details'][2],
                    preset_icon_data_url=image_data_url(data) if data else None, max_icon_bytes=MAX_ICON_BYTES)

    def export(self, data):
        if (not isinstance(data, dict) or not {'profile_id', 'revision'} <= set(data)
                or set(data) - {'profile_id', 'revision', 'filename', 'title', 'directory'}):
            raise ProfileError('Export requires a saved profile and revision')
        # Export the precise saved revision, even if another process saves later.
        profile = self.store.load(data['profile_id'], revision=data['revision'])
        title = metadata_text(data.get('title', profile.name), 'Mod title', 160, required=True)
        settings = self.fbmod_settings.load()
        icon = decode_icon(settings['icon_data_url'])
        if icon is None:
            template = read_mod(self.catalog.template_path(profile.base_preset).read_bytes())
            icon = self._preset_icon(template)
        metadata = dict(author=settings['author'], description=settings['description'], icon=icon)
        directory = export_directory(data.get('directory', str(self.export_location.load())), self.exports)
        warnings = []
        with self.export_lock:
            filename = data.get('filename', suggested_filename(profile.name))
            for attempt in range(100):
                path = available_export(directory, filename)
                try:
                    report = export_profile_mod(profile, path, catalog=self.catalog, title=title, metadata=metadata)
                    break
                except ExportCollision:
                    # Exclusive writes in the compiler arbitrate across app
                    # processes. Only a taken name is safe to retry.
                    if attempt == 99:
                        raise ProfileError('Export filenames are busy. Please try exporting again.')
            try:
                self.export_location.remember(directory)
            except OSError:
                # The completed mod/report remain successful even if a separate
                # preference write fails. Preserve their paths and folder action.
                warnings.append('The FBMOD was saved, but the export folder could not be remembered. Choose the folder again next time.')
        download_id = secrets.token_urlsafe(18)
        self.downloads[download_id] = (path, path.with_suffix('.report.json'))
        return dict(name=path.name, path=str(path), directory=str(directory), report_path=str(path.with_suffix('.report.json')),
                    revision=profile.revision, download_id=download_id, sha256=report['output_sha256'], warnings=warnings)


def create_server(app, port=0):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'WorldstateEditor'

        def log_message(self, *_):
            pass

        def respond(self, status, data, content_type='application/json; charset=utf-8', *, filename=None):
            if not isinstance(data, bytes):
                data = canonical_json(data)
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            if filename:
                self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + quote(filename))
            self.end_headers()
            # Keep each write bounded, including portraits larger than 64 KiB.
            for offset in range(0, len(data), 16_384):
                self.wfile.write(data[offset:offset + 16_384])

        def authorized(self):
            supplied = self.headers.get('Authorization', '')
            origin = self.headers.get('Origin')
            expected_origin = f'http://127.0.0.1:{self.server.server_port}'
            if origin and origin != expected_origin:
                return False
            return secrets.compare_digest(supplied, 'Bearer ' + app.token)

        def do_GET(self):
            try:
                path = unquote(urlsplit(self.path).path)
                if path.startswith(('/api/', '/downloads/')):
                    if not self.authorized():
                        return self.respond(403, {'error': 'This editor session is not authorized. Reopen the application.'})
                    app.lifecycle.touch()
                if path == '/api/bootstrap':
                    return self.respond(200, app.bootstrap())
                if path == '/api/ping':
                    return self.respond(200, {'ok': True})
                if path == '/api/window-stream':
                    query = parse_qs(urlsplit(self.path).query)
                    client = query.get('client_id', [''])[0]
                    sequence = int(query.get('sequence', ['0'])[0])
                    app.lifecycle.update(dict(client_id=client, event='open', sequence=sequence))
                    try:
                        self.connection.settimeout(2)
                        self.send_response(200)
                        self.send_header('Content-Type', 'text/event-stream')
                        self.send_header('Cache-Control', 'no-store')
                        self.send_header('Referrer-Policy', 'no-referrer')
                        self.end_headers()
                        while not self.server.editor_stopped.is_set():
                            self.wfile.write(b': editor open\n\n')
                            self.wfile.flush()
                            app.lifecycle.touch()
                            if self.server.editor_stopped.wait(.25):
                                break
                    except OSError:
                        pass  # Browser closed or navigated; release its lease.
                    finally:
                        app.lifecycle.disconnected(client, sequence)
                    return
                if path == '/api/export-settings':
                    query = parse_qs(urlsplit(self.path).query)
                    return self.respond(200, app.export_settings(query.get('base_preset', [None])[0]))
                if path == '/api/deleted-profiles':
                    return self.respond(200, app.store.deleted_records())
                if path.startswith('/api/profile/'):
                    return self.respond(200, app.editor_profile(app.store.load(path.removeprefix('/api/profile/'))))
                if path.startswith('/api/history/'):
                    profiles = app.store.history(path.removeprefix('/api/history/'))
                    return self.respond(200, [profile.to_dict() for profile in profiles])
                if path.startswith('/downloads/'):
                    parts = path.split('/')
                    if len(parts) != 4 or parts[2] not in app.downloads or parts[3] not in ('mod', 'report'):
                        return self.respond(404, {'error': 'Export is unavailable'})
                    file = app.downloads[parts[2]][parts[3] == 'report']
                    return self.respond(200, file.read_bytes(), 'application/octet-stream', filename=file.name)
                if path in ('/fonts/Inquisition.woff', '/fonts/InquisitionSc.woff'):
                    file = ROOT / 'assets/keep-fonts' / path.rsplit('/', 1)[1]
                elif path.startswith('/interface-art/'):
                    relative = path.removeprefix('/interface-art/')
                    if relative not in app.allowed_interface_art:
                        return self.respond(404, {'error': 'Artwork not found'})
                    file = ROOT / 'assets/keep-interface' / relative
                elif path.startswith('/art/'):
                    relative = path.removeprefix('/art/')
                    if relative not in app.allowed_art:
                        return self.respond(404, {'error': 'Artwork not found'})
                    file = ROOT / 'assets/keep' / relative
                else:
                    files = {'/': 'index.html', '/app.js': 'app.js', '/choice-controls.js': 'choice-controls.js', '/style.css': 'style.css',
                             '/tapestry-layout.css': 'tapestry-layout.css',
                             '/keep-interactions.css': 'keep-interactions.css'}
                    if path not in files:
                        return self.respond(404, {'error': 'Page not found'})
                    file = WEB / files[path]
                self.respond(200, file.read_bytes(), STATIC_CONTENT_TYPES.get(file.suffix.lower(), 'application/octet-stream'))
            except (ValueError, OSError, AssertionError) as error:
                self.respond(400, {'error': str(error)})

        def do_POST(self):
            with app.lifecycle.request():
                self.handle_post()

        def handle_post(self):
            try:
                length = int(self.headers.get('Content-Length', '0'))
                path = urlsplit(self.path).path
                save_upload = path in ('/api/save-import/preview', '/api/dao-save-import/preview')
                if not 0 < length <= (MAX_SAVE_BYTES if save_upload else MAX_BODY):
                    return self.respond(413, {'error': 'Document is missing or too large'})
                # Consume bounded request bodies before sending a rejection;
                # otherwise Windows may reset the socket before the response arrives.
                self.connection.settimeout(10)
                raw = self.rfile.read(length)
                if not self.authorized():
                    return self.respond(403, {'error': 'This editor session is not authorized. Reopen the application.'})
                if save_upload:
                    if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/octet-stream':
                        return self.respond(415, {'error': 'Expected a game save file'})
                    app.lifecycle.touch()
                    return self.respond(200, app.save_imports.preview(raw, game='dao' if path == '/api/dao-save-import/preview' else 'da2'))
                if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
                    return self.respond(415, {'error': 'Expected a JSON document'})
                data = json.loads(raw.decode('utf8'))
                if not isinstance(data, dict):
                    raise ProfileError('Expected a JSON object')
                app.lifecycle.touch()
                path = urlsplit(self.path).path
                if path == '/api/window':
                    app.lifecycle.update(data)
                    result = {'ok': True}
                elif path == '/api/preview':
                    result = app.preview(data)
                elif path == '/api/propose':
                    result = app.propose(data)
                elif path == '/api/save':
                    profile = app.save(data)
                    result = profile.to_dict()
                    if profile.profile_id in app.store.copy_warnings:
                        result['storage_warning'] = app.store.copy_warnings[profile.profile_id]
                elif path in ('/api/profile/delete', '/api/profile/restore'):
                    if set(data) != {'profile_id', 'revision'}:
                        raise ProfileError('Invalid World State deletion/restore request')
                    if path.endswith('/delete'):
                        profile = app.store.delete(data['profile_id'], data['revision'])
                        result = dict(deleted=True, profile_id=profile.profile_id)
                    else:
                        result = app.editor_profile(app.store.restore(data['profile_id'], data['revision']))
                elif path == '/api/profiles/purge':
                    if set(data) != {'profiles'}:
                        raise ProfileError('Invalid permanent deletion request')
                    result = dict(purged=app.store.purge(data['profiles']))
                elif path == '/api/profile/clear-history':
                    if set(data) != {'profile_id', 'revision'}:
                        raise ProfileError('Invalid saved revisions request')
                    app.store.clear_history(data['profile_id'], data['revision'])
                    result = dict(cleared=True)
                    if data['profile_id'] in app.store.copy_warnings:
                        result['storage_warning'] = app.store.copy_warnings[data['profile_id']]
                elif path == '/api/save-import/commit':
                    result = app.save_imports.commit(data).to_dict()
                elif path == '/api/save-import/plan':
                    result = app.save_imports.plan(data)
                elif path == '/api/save-import/cancel':
                    result = app.save_imports.cancel(data)
                elif path == '/api/export':
                    result = app.export(data)
                elif path == '/api/choose-export-folder':
                    if not isinstance(data, dict) or set(data) != {'directory'}:
                        raise ProfileError('Invalid folder selection request')
                    initial = export_directory(data['directory'], app.exports, must_exist=False)
                    selected = choose_export_folder(initial)
                    result = dict(directory=str(export_directory(selected, app.exports)) if selected else None)
                elif path == '/api/open-export-folder':
                    if not isinstance(data, dict) or set(data) != {'download_id'} or not isinstance(data['download_id'], str) or data['download_id'] not in app.downloads:
                        raise ProfileError('Unknown export')
                    open_export_folder(app.downloads[data['download_id']][0].parent)
                    result = dict(opened=True)
                elif path == '/api/export-settings':
                    result = app.fbmod_settings.save(data)
                elif path == '/api/open-world-state-folder':
                    if data:
                        raise ProfileError('Invalid World State folder request')
                    app.store.prepare(strict=True)
                    app.storage_warnings = []
                    app.store.directory.mkdir(parents=True, exist_ok=True)
                    open_export_folder(app.store.directory)
                    result = dict(opened=True)
                elif path == '/api/duplicate':
                    if set(data) != {'profile_id', 'revision', 'name'}:
                        raise ProfileError('Invalid duplicate request')
                    if type(data['revision']) is not int:
                        raise RevisionConflict('The saved profile changed; reopen it before duplicating')
                    result = app.store.duplicate(data['profile_id'], data['name'], revision=data['revision']).to_dict()
                elif path == '/api/import':
                    if set(data) != {'document'}:
                        raise ProfileError('Invalid import request')
                    profile = app.catalog.upgrade(Profile.from_dict(data['document']))
                    app.catalog.validate(profile)
                    # Reject unavailable legacy templates before committing a
                    # history that the next bootstrap could not display.
                    app.catalog.template_path(profile.base_preset)
                    result = app.store.create(profile.name, base_preset=profile.base_preset,
                                              mode=profile.mode, choices=dict(profile.choices)).to_dict()
                else:
                    return self.respond(404, {'error': 'Unknown action'})
                self.respond(200, result)
            except RevisionConflict as error:
                self.respond(409, {'error': str(error)})
            except (ValueError, OSError, AssertionError, TypeError) as error:
                self.respond(400, {'error': str(error)})

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    server.editor_stopped = threading.Event()
    return server


def open_app(url):
    candidates = [Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe',
                  Path(os.environ.get('PROGRAMFILES', 'C:/Program Files')) / 'Microsoft/Edge/Application/msedge.exe']
    for edge in candidates:
        if edge.exists():
            subprocess.Popen([str(edge), '--app=' + url, '--no-first-run'])
            return
    webbrowser.open(url)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, help='Profile/settings root (standalone default: Local AppData)')
    parser.add_argument('--store', type=Path)
    parser.add_argument('--exports', type=Path)
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--no-open', action='store_true')
    parser.add_argument('--idle-timeout', type=int, default=180)
    args = parser.parse_args(argv)
    store, exports = editor_directories(args.data_dir, args.store, args.exports)
    app = EditorApp(store, exports)
    server = create_server(app, args.port)
    url = f'http://127.0.0.1:{server.server_port}/#session={app.token}'
    print(url, flush=True)
    if not args.no_open:
        open_app(url)
    stopped = server.editor_stopped
    watcher = threading.Thread(target=watch_editor,
        args=(server, app.lifecycle, args.idle_timeout, stopped), daemon=True)
    watcher.start()
    try:
        server.serve_forever(poll_interval=.1)
    except KeyboardInterrupt:
        pass
    finally:
        stopped.set()
        server.server_close()
        watcher.join(timeout=1)


if __name__ == '__main__':
    main()
