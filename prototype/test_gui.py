"""Local GUI/API integration with real profiles, artwork, and exported payloads."""
import json
from http.client import HTTPConnection
from pathlib import Path
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from export_worldstate import ROOT, read_mod
from gui import EditorApp, create_server
from world_profiles import Catalog, ProfileStore
from fbmod_metadata import DEFAULT_SETTINGS, image_data_url
from test_fbmod_metadata import test_icon
from fbmod_metadata import available_export
from world_profiles.compiler import ExportCollision, export_profile_mod


class GuiApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / 'prototype', prefix='.gui-test-')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.app = EditorApp(self.directory / 'profiles', self.directory / 'exports')
        self.server = create_server(self.app)
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.02), daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.draft = dict(profile_id=None, revision=0, name='GUI test history', base_preset='early-tests-v1',
                          mode='ordinary', choices={})

    def stop_server(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)

    def request(self, path, body=None, *, authorized=True, origin=None, json_response=True):
        headers = {'Authorization': 'Bearer ' + self.app.token} if authorized else {}
        if origin: headers['Origin'] = origin
        if body is not None: headers['Content-Type'] = 'application/json'
        connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=15)
        try:
            connection.request('POST' if body is not None else 'GET', path,
                               body=json.dumps(body).encode() if body is not None else None, headers=headers)
            with connection.getresponse() as response:
                # Drain image responses in bounded blocks and always close the
                # response socket, including a failed/interrupted transfer.
                raw = b''.join(iter(lambda: response.read(8192), b''))
                return response.status, json.loads(raw) if json_response else raw
        finally:
            connection.close()

    def test_static_content_types_do_not_depend_on_windows_file_associations(self):
        expected = {'/app.js': 'text/javascript', '/choice-controls.js': 'text/javascript',
                    '/': 'text/html', '/style.css': 'text/css', '/tapestry-layout.css': 'text/css',
                    '/keep-interactions.css': 'text/css', '/fonts/Inquisition.woff': 'font/woff',
                    '/interface-art/favicon.png': 'image/png', '/interface-art/bg-eye.jpg': 'image/jpeg'}
        with patch('mimetypes.guess_type', return_value=('text/plain', None)):
            for path, mime in expected.items():
                with self.subTest(path=path):
                    connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=15)
                    try:
                        connection.request('GET', path)
                        with connection.getresponse() as response:
                            response.read()
                            self.assertEqual(response.status, 200)
                            self.assertEqual(response.getheader('Content-Type').split(';')[0], mime)
                            self.assertEqual(response.getheader('X-Content-Type-Options'), 'nosniff')
                    finally:
                        connection.close()

    def test_bootstrap_contains_local_art_and_correct_anders_art(self):
        status, data = self.request('/api/bootstrap')
        self.assertEqual(status, 200)
        self.assertEqual(len(data['choices']), 137)
        self.assertFalse(data['bridge_available'])
        anders = next(choice for choice in data['choices'] if choice['id'] == 'da2.anders_fate')
        alive = next(answer for answer in anders['answers'] if answer['id'] == 'alive')
        self.assertEqual(alive['art'], '/art/da2_anders_fate/alive_detail.jpg')
        for choice in data['choices']:
            for answer in choice['answers']:
                if not answer['art']:
                    self.assertEqual(choice['display'], 'context')
                    continue
                status, image = self.request(answer['art'], authorized=False, json_response=False)
                self.assertEqual(status, 200)
                self.assertTrue(image.startswith(b'\xff\xd8'))

    def test_window_close_requires_session_and_same_origin(self):
        opened = dict(client_id='test-window', event='open', sequence=1)
        closed = dict(opened, event='close', sequence=2)
        self.assertEqual(self.request('/api/window', opened)[0], 200)
        self.assertEqual(self.request('/api/window', closed, authorized=False)[0], 403)
        self.assertEqual(self.request('/api/window', closed, origin='https://example.org')[0], 403)
        self.assertIsNone(self.app.lifecycle.close_after)
        self.assertEqual(self.request('/api/window', dict(closed, sequence=True))[0], 400)
        self.assertEqual(self.request('/api/window', closed)[0], 200)
        self.assertIsNotNone(self.app.lifecycle.close_after)
        # A fresh document during a reload keeps the server running.
        self.assertEqual(self.request('/api/window', dict(opened, client_id='reload'))[0], 200)
        self.assertIsNone(self.app.lifecycle.close_after)

    def test_window_socket_disconnect_releases_lease_without_pagehide(self):
        connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        connection.request('GET', '/api/window-stream?client_id=socket-test&sequence=1',
            headers={'Authorization': 'Bearer ' + self.app.token})
        response = connection.getresponse()
        try:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(14), b': editor open\n')
            self.assertIsNone(self.app.lifecycle.close_after)
        finally:
            response.close()
            connection.close()
        deadline = time.monotonic() + 3
        while self.app.lifecycle.close_after is None and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertIsNotNone(self.app.lifecycle.close_after)

    def test_story_proposal_is_authenticated_read_only_and_accepts_as_one_revision(self):
        _, boot = self.request('/api/bootstrap')
        self.assertTrue(all(preset['mode'] == 'keep' for preset in boot['presets']))
        request = dict(draft=dict(self.draft, mode='keep'), updates={}, mode='keep')
        self.assertEqual(self.request('/api/propose', request, authorized=False)[0], 403)
        self.assertEqual(self.request('/api/propose', request, origin='https://example.org')[0], 403)
        self.assertEqual(self.request('/api/save', request['draft'])[0], 400)
        status, first = self.request('/api/propose', request)
        self.assertEqual(status, 200)
        self.assertTrue(first['changes'])
        self.assertEqual(self.app.store.list(), [])
        self.assertFalse(self.app.exports.exists())
        _, saved = self.request('/api/save', first['draft'])
        draft = {key: saved[key] for key in self.draft}
        before = {str(path): path.read_bytes() for path in self.directory.rglob('*') if path.is_file()}
        status, proposal = self.request('/api/propose', dict(draft=draft,
                        updates={'da2.hawke_identity':'female_mage'}, mode='keep'))
        self.assertEqual(status, 200)
        self.assertEqual(proposal['draft']['choices']['da2.hawke_identity'], 'female_mage')
        self.assertTrue({'da2.bethany_fate','da2.carver_fate'} <= {change['choice_id'] for change in proposal['changes']})
        self.assertEqual(before, {str(path):path.read_bytes() for path in self.directory.rglob('*') if path.is_file()})
        # Declining a proposal requires no endpoint call and changes no revision.
        self.assertEqual(self.app.store.load(saved['profile_id']).revision,1)
        _, accepted = self.request('/api/save', proposal['draft'])
        self.assertEqual(accepted['revision'],2)
        self.assertEqual(self.request('/api/propose', dict(draft=draft,updates={},mode='keep'))[0],409)
        accepted_draft={key:accepted[key] for key in self.draft}
        status, free = self.request('/api/propose', dict(draft=accepted_draft,
            updates={'da2.bethany_fate':'warden','da2.carver_fate':'warden'},mode='experimental'))
        self.assertEqual(status,200)
        self.assertEqual(free['changes'],[])
        self.assertTrue(self.request('/api/preview',free['draft'])[1]['can_export'])

    def test_export_settings_persist_without_changing_profile_revisions(self):
        _, saved = self.request('/api/save', self.draft)
        revision = self.app.store.profile_directory(saved['profile_id']) / 'History/00000001.json'
        before = revision.read_bytes()
        status, result = self.request('/api/export-settings')
        self.assertEqual(status, 200)
        self.assertEqual(result['settings'], DEFAULT_SETTINGS)
        self.assertEqual(result['category'], 'World States')
        settings = dict(author='My Author', description='A custom history.\nWith two lines.', icon_data_url=image_data_url(test_icon()))
        self.assertEqual(self.request('/api/export-settings', settings)[0], 200)
        reopened = EditorApp(self.directory / 'profiles', self.directory / 'exports')
        self.assertEqual(reopened.export_settings()['settings'], settings)
        self.assertEqual(revision.read_bytes(), before)
        self.assertEqual(self.app.store.load(saved['profile_id']).revision, 1)

    def test_named_exports_use_saved_metadata_and_preserve_existing_files(self):
        _, saved = self.request('/api/save', self.draft)
        settings = dict(author='Thedas test author', description='My named mod.', icon_data_url=image_data_url(test_icon()))
        self.request('/api/export-settings', settings)
        request = dict(profile_id=saved['profile_id'], revision=1, title='A royal history', filename='Queen Cousland.fbmod')
        status, first = self.request('/api/export', request)
        self.assertEqual(status, 200)
        self.assertEqual(first['name'], 'Queen Cousland.fbmod')
        raw = Path(first['path']).read_bytes()
        mod = read_mod(raw)
        self.assertEqual(mod['details'][:3], ['A royal history', settings['author'], 'World States'])
        self.assertEqual(mod['details'][4], settings['description'])
        self.assertEqual(mod['payloads'][mod['records'][0]['index']], test_icon())
        self.app.exports.joinpath('Queen Cousland (2).report.json').write_bytes(b'preserve orphan report')
        _, second = self.request('/api/export', request)
        self.assertEqual(second['name'], 'Queen Cousland (3).fbmod')
        self.assertEqual(Path(first['path']).read_bytes(), raw)
        report = json.loads(Path(first['report_path']).read_text(encoding='utf8'))
        self.assertEqual(report['mod_metadata']['author'], settings['author'])

    def test_two_instances_export_same_candidate_to_distinct_numbered_pairs(self):
        saved = self.app.save(self.draft)
        second = EditorApp(self.app.store.directory, self.app.exports)
        barrier = threading.Barrier(2)
        seen = set()
        def choose(directory, filename):
            path = available_export(directory, filename)
            identity = threading.get_ident()
            if identity not in seen:
                seen.add(identity)
                barrier.wait(timeout=10)
            return path
        request = dict(profile_id=saved.profile_id, revision=1, filename='Simultaneous')
        with patch('gui.available_export', side_effect=choose), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda app: app.export(request), [self.app, second]))
        self.assertEqual({item['name'] for item in results}, {'Simultaneous.fbmod', 'Simultaneous (2).fbmod'})
        for item in results:
            report = json.loads(Path(item['report_path']).read_text())
            self.assertEqual(report['output'], item['path'])
            self.assertEqual(report['output_sha256'], item['sha256'])
            self.assertEqual(report['profile']['revision'], 1)
            self.assertEqual(read_mod(Path(item['path']).read_bytes())['ebx'],
                             read_mod(Path(results[0]['path']).read_bytes())['ebx'])

    def test_mod_claimed_after_report_reservation_is_preserved_and_retried(self):
        from world_profiles.storage import write_new_bytes
        saved = self.app.save(self.draft)
        def claim(path, data):
            if Path(path).name == 'Race.fbmod':
                Path(path).write_bytes(b'other writer')
            return write_new_bytes(path, data)
        with patch('world_profiles.storage.write_new_bytes', side_effect=claim):
            result = self.app.export(dict(profile_id=saved.profile_id, revision=1, filename='Race'))
        self.assertEqual(result['name'], 'Race (2).fbmod')
        self.assertEqual((self.app.exports / 'Race.fbmod').read_bytes(), b'other writer')
        self.assertFalse((self.app.exports / 'Race.report.json').exists())
        self.assertTrue(Path(result['report_path']).is_file())

    def test_permission_failure_is_not_retried_and_removes_own_report(self):
        from world_profiles.storage import write_new_bytes
        saved = self.app.save(self.draft)
        def deny(path, data):
            if Path(path).suffix == '.fbmod':
                raise PermissionError('Access denied')
            return write_new_bytes(path, data)
        with patch('world_profiles.storage.write_new_bytes', side_effect=deny), \
             patch('gui.available_export', wraps=available_export) as choose:
            with self.assertRaisesRegex(PermissionError, 'Access denied'):
                self.app.export(dict(profile_id=saved.profile_id, revision=1))
        self.assertEqual(choose.call_count, 1)
        self.assertEqual(list(self.app.exports.iterdir()), [])
        self.assertFalse(self.app.export_location.path.exists())

    def test_completed_export_succeeds_if_remembering_the_folder_fails(self):
        _, saved = self.request('/api/save', self.draft)
        with patch.object(self.app.export_location, 'remember', side_effect=PermissionError('Settings folder is read only')):
            status, result = self.request('/api/export', dict(profile_id=saved['profile_id'], revision=1))
        self.assertEqual(status, 200, result)
        self.assertTrue(Path(result['path']).is_file())
        self.assertTrue(Path(result['report_path']).is_file())
        self.assertTrue(read_mod(Path(result['path']).read_bytes())['ebx'])
        self.assertEqual(len(result['warnings']), 1)
        self.assertIn('folder', result['warnings'][0])
        self.assertIn(result['download_id'], self.app.downloads)

    def test_folder_picker_accepts_a_removed_nested_starting_folder(self):
        missing = self.directory / 'Removed export folder' / 'Child'
        destination = self.directory / 'New export folder'
        destination.mkdir()
        with patch('gui.choose_export_folder', return_value=str(destination)) as choose:
            status, result = self.request('/api/choose-export-folder', dict(directory=str(missing)))
        self.assertEqual(status, 200, result)
        self.assertEqual(result, dict(directory=str(destination)))
        choose.assert_called_once_with(missing)
        self.assertFalse(missing.exists())
        # An accepted picker starting point must not relax export validation.
        _, saved = self.request('/api/save', self.draft)
        self.assertEqual(self.request('/api/export', dict(profile_id=saved['profile_id'], revision=1,
                                                        directory=str(missing)))[0], 400)

    def test_native_folder_picker_uses_a_surviving_parent_or_home(self):
        from export_destination import folder_picker_main
        missing = self.directory / 'Removed folder' / 'Child'
        result = self.directory / 'selection.json'
        args = [str(missing), '--result-file', str(result)]
        with patch('tkinter.Tk') as root, patch('tkinter.filedialog.askdirectory', return_value='') as choose:
            folder_picker_main(args)
        self.assertEqual(choose.call_args.kwargs['initialdir'], str(self.directory))
        self.assertTrue(choose.call_args.kwargs['mustexist'])
        self.assertIsNone(json.loads(result.read_text()))
        root.return_value.destroy.assert_called_once()
        # An unplugged drive can have no available ancestor at all.
        with patch('export_destination.Path.is_dir', return_value=False), patch('tkinter.Tk'), \
             patch('tkinter.filedialog.askdirectory', return_value='') as choose:
            folder_picker_main(args)
        self.assertEqual(choose.call_args.kwargs['initialdir'], str(Path.home()))

    def test_duplicate_copies_the_revision_checked_before_a_concurrent_save(self):
        original = self.app.store.create('Source', base_preset='original-game-v1', mode='experimental',
                                         choices={'dao.warden_romance': 'none'})
        load = self.app.store.load
        advanced = False
        def racing_load(profile_id, **kwargs):
            nonlocal advanced
            profile = load(profile_id, **kwargs)
            if profile_id == original.profile_id and not advanced:
                advanced = True
                self.app.store.save(profile.edited(choices={'dao.warden_romance': 'morrigan'}))
            return profile
        with patch.object(self.app.store, 'load', side_effect=racing_load):
            status, copied = self.request('/api/duplicate', dict(profile_id=original.profile_id,
                                                                revision=1, name='My copy'))
        self.assertEqual(status, 200, copied)
        self.assertEqual(copied['choices'], dict(original.choices))
        self.assertEqual(load(original.profile_id).revision, 2)
        self.assertEqual(self.request('/api/duplicate', dict(profile_id=original.profile_id,
                                                            revision=1, name='Stale copy'))[0], 409)

    def test_repeated_collision_is_bounded_and_cli_still_refuses_existing_output(self):
        saved = self.app.save(self.draft)
        with patch('gui.export_profile_mod', side_effect=ExportCollision('busy')) as export:
            with self.assertRaisesRegex(ValueError, 'filenames are busy'):
                self.app.export(dict(profile_id=saved.profile_id, revision=1))
        self.assertEqual(export.call_count, 100)
        self.app.exports.mkdir(exist_ok=True)
        existing = self.app.exports / 'Preserved.fbmod'
        existing.write_bytes(b'keep')
        with self.assertRaises(ExportCollision):
            export_profile_mod(saved, existing)
        self.assertEqual(existing.read_bytes(), b'keep')

    def test_original_game_default_saves_and_exports_without_selecting_a_personal_preset(self):
        _, boot = self.request('/api/bootstrap')
        self.assertEqual(boot['default_preset'], 'original-game-v1')
        self.assertEqual(len(boot['presets']), 3)
        draft = dict(self.draft, base_preset=boot['default_preset'], mode='keep')
        status, preview = self.request('/api/preview', draft)
        self.assertEqual(status, 200)
        self.assertTrue(preview['can_export'])
        status, saved = self.request('/api/save', draft)
        self.assertEqual(status, 200)
        self.assertEqual(saved['choices'], {})
        status, exported = self.request('/api/export', dict(profile_id=saved['profile_id'], revision=1))
        self.assertEqual(status, 200)
        mod = read_mod(Path(exported['path']).read_bytes())
        self.assertEqual(mod['details'][1:3], ['Thedas World State Studio', 'World States'])
        self.assertEqual(mod['records'][0]['index'], -1)
        from world_profiles.compiler import compile_profile
        compiled = compile_profile(self.app.store.load(saved['profile_id']), catalog=self.app.catalog)
        self.assertEqual(dict(compiled.values), dict(dao_played=1, da2_played=1, dao_or_da2_played=1))
        self.assertEqual(len(self.app.store.list()), 1)

    def test_unavailable_legacy_template_import_cannot_commit_an_unopenable_history(self):
        from world_profiles import ProfileError
        document = Catalog(41).create('Legacy import', mode='experimental').to_dict()
        with patch.object(self.app.catalog, 'template_path', side_effect=ProfileError('Legacy preset is not included')):
            status, result = self.request('/api/import', {'document': document})
        self.assertEqual(status, 400)
        self.assertIn('not included', result['error'])
        self.assertEqual(self.app.store.list(), [])

    def test_default_export_filename_is_readable_and_icon_is_inherited(self):
        self.draft['name'] = 'A New Beginning'
        _, saved = self.request('/api/save', self.draft)
        _, exported = self.request('/api/export', dict(profile_id=saved['profile_id'], revision=1))
        self.assertEqual(exported['name'], 'A New Beginning.fbmod')
        mod = read_mod(Path(exported['path']).read_bytes())
        template = read_mod(self.app.catalog.template_path(saved['base_preset']).read_bytes())
        self.assertEqual(mod['details'][1], 'Thedas World State Studio')
        self.assertEqual(mod['details'][2], template['details'][2])
        self.assertEqual(mod['payloads'][mod['records'][0]['index']], template['payloads'][template['records'][0]['index']])
        from world_profiles.compiler import build_profile_mod
        expected = read_mod(build_profile_mod(self.app.store.load(saved['profile_id']))[0])
        self.assertEqual(mod['ebx'], expected['ebx'])

    def test_original_defaults_export_has_bundled_icon_and_preview_matches_reset(self):
        draft = dict(self.draft, base_preset=self.app.catalog.default_preset)
        saved = self.app.save(draft)
        original = read_mod(self.app.catalog.template_path(saved.base_preset).read_bytes())
        self.assertEqual(original['records'][0]['index'], -1)
        preset = read_mod(self.app.catalog.template_path('template-8a03712331e995d7').read_bytes())
        expected_icon = preset['payloads'][preset['records'][0]['index']]
        preview = self.app.export_settings(saved.base_preset)
        self.assertEqual(preview['settings'], DEFAULT_SETTINGS)
        self.assertEqual(preview['preset_icon_data_url'], image_data_url(expected_icon))
        request = dict(profile_id=saved.profile_id, revision=saved.revision)
        exported = self.app.export(request)
        default = read_mod(Path(exported['path']).read_bytes())
        self.assertEqual(default['payloads'][default['records'][0]['index']], expected_icon)
        self.app.fbmod_settings.save(dict(DEFAULT_SETTINGS, icon_data_url=image_data_url(test_icon())))
        custom = read_mod(Path(self.app.export(request)['path']).read_bytes())
        self.assertEqual(custom['payloads'][custom['records'][0]['index']], test_icon())
        self.app.fbmod_settings.save(dict(DEFAULT_SETTINGS))
        reset = read_mod(Path(self.app.export(request)['path']).read_bytes())
        self.assertEqual(reset['payloads'][reset['records'][0]['index']], expected_icon)
        from world_profiles.compiler import build_profile_mod
        self.assertEqual(default['ebx'], read_mod(build_profile_mod(saved)[0])['ebx'])
        self.assertEqual(custom['ebx'], default['ebx'])
        self.assertEqual(reset['ebx'], default['ebx'])

    def test_direct_export_uses_remembered_folder_preserves_collisions_and_rejects_invalid_destinations(self):
        _, saved = self.request('/api/save', self.draft)
        profile = self.app.store.load(saved['profile_id'])
        destination = self.directory / 'My selected export folder'
        destination.mkdir()
        request = dict(profile_id=saved['profile_id'], revision=saved['revision'], filename='My world.fbmod', directory=str(destination))
        status, first = self.request('/api/export', request)
        self.assertEqual(status, 200)
        self.assertEqual(Path(first['path']).parent, destination)
        self.assertTrue(Path(first['report_path']).is_file())
        original = Path(first['path']).read_bytes()
        _, second = self.request('/api/export', request)
        self.assertEqual(second['name'], 'My world (2).fbmod')
        self.assertEqual(Path(first['path']).read_bytes(), original)
        reopened = EditorApp(self.directory / 'profiles', self.directory / 'exports')
        self.assertEqual(reopened.bootstrap()['export_directory'], str(destination))
        third = reopened.export(dict(profile_id=saved['profile_id'], revision=saved['revision'], filename='Remembered.fbmod'))
        self.assertEqual(Path(third['path']).parent, destination)
        self.assertEqual(read_mod(Path(third['path']).read_bytes())['ebx'], read_mod(original)['ebx'])
        snapshot = {str(path): path.read_bytes() for path in self.directory.rglob('*') if path.is_file()}
        for invalid in ('', 'relative-folder', None, [], str(destination / 'missing'), first['path']):
            self.assertEqual(self.request('/api/export', dict(request, directory=invalid))[0], 400)
        self.assertEqual(self.request('/api/export', request, authorized=False)[0], 403)
        self.assertEqual(self.request('/api/export', request, origin='https://example.org')[0], 403)
        self.assertEqual(snapshot, {str(path): path.read_bytes() for path in self.directory.rglob('*') if path.is_file()})
        self.assertEqual(self.app.store.load(saved['profile_id']), profile)
        self.assertFalse(self.app.exports.exists())

    def test_folder_dialog_and_open_folder_require_authorization_and_registered_exports(self):
        destination = self.directory / 'Selected folder'
        destination.mkdir()
        request = dict(directory=str(self.app.exports))
        with patch('gui.choose_export_folder', return_value=str(destination)) as choose:
            self.assertEqual(self.request('/api/choose-export-folder', request, authorized=False)[0], 403)
            self.assertEqual(self.request('/api/choose-export-folder', request, origin='https://example.org')[0], 403)
            choose.assert_not_called()
            status, result = self.request('/api/choose-export-folder', request)
            self.assertEqual((status, result['directory']), (200, str(destination)))
            choose.assert_called_once_with(self.app.exports)
        with patch('gui.choose_export_folder', return_value=None):
            self.assertEqual(self.request('/api/choose-export-folder', request), (200, {'directory': None}))
        self.assertFalse(self.app.export_location.path.exists())
        _, saved = self.request('/api/save', self.draft)
        _, exported = self.request('/api/export', dict(profile_id=saved['profile_id'], revision=1, directory=str(destination)))
        with patch('gui.open_export_folder') as open_folder:
            self.assertEqual(self.request('/api/open-export-folder', dict(download_id='unknown'))[0], 400)
            self.assertEqual(self.request('/api/open-export-folder', dict(path=str(destination)))[0], 400)
            self.assertEqual(self.request('/api/open-export-folder', dict(download_id=exported['download_id']), authorized=False)[0], 403)
            open_folder.assert_not_called()
            self.assertEqual(self.request('/api/open-export-folder', dict(download_id=exported['download_id'])), (200, {'opened': True}))
            open_folder.assert_called_once_with(destination)

    def test_open_world_state_folder_uses_configured_store_and_preserves_saved_files(self):
        with patch('gui.open_export_folder') as open_folder:
            self.assertEqual(self.request('/api/open-world-state-folder', {}, authorized=False)[0], 403)
            self.assertEqual(self.request('/api/open-world-state-folder', {}, origin='https://example.org')[0], 403)
            self.assertEqual(self.request('/api/open-world-state-folder', dict(path=str(self.directory)))[0], 400)
            open_folder.assert_not_called()
            self.assertFalse(self.app.store.directory.exists())
            self.assertEqual(self.request('/api/open-world-state-folder', {}), (200, {'opened': True}))
            open_folder.assert_called_once_with(self.app.store.directory)
            self.assertTrue(self.app.store.directory.is_dir())
            self.assertEqual(list(self.app.store.directory.iterdir()), [])
        self.request('/api/save', self.draft)
        before = {path: path.read_bytes() for path in self.app.store.directory.rglob('*') if path.is_file()}
        with patch('gui.open_export_folder') as open_folder:
            self.assertEqual(self.request('/api/open-world-state-folder', {}), (200, {'opened': True}))
            open_folder.assert_called_once_with(self.app.store.directory)
        with patch('gui.open_export_folder', side_effect=OSError('Folder could not be opened')):
            self.assertEqual(self.request('/api/open-world-state-folder', {}),
                             (400, {'error': 'Folder could not be opened'}))
        self.assertEqual(before, {path: path.read_bytes() for path in self.app.store.directory.rglob('*') if path.is_file()})

    def test_clear_history_requires_authorization_and_exact_current_revision(self):
        _, first = self.request('/api/save', self.draft)
        _, second = self.request('/api/save', dict(self.draft, profile_id=first['profile_id'], revision=1, name='Latest'))
        request = dict(profile_id=second['profile_id'], revision=second['revision'])
        self.assertEqual(self.request('/api/profile/clear-history', request, authorized=False)[0], 403)
        self.assertEqual(self.request('/api/profile/clear-history', request, origin='https://example.org')[0], 403)
        self.assertEqual(self.request('/api/profile/clear-history', dict(request, revision=1))[0], 409)
        self.assertEqual(self.request('/api/profile/clear-history', dict(request, revision=True))[0], 409)
        self.assertEqual(self.request('/api/profile/clear-history', dict(request, directory=str(self.directory)))[0], 400)
        self.assertEqual(len(self.app.store.history(second['profile_id'])), 2)
        current = self.app.store.load(second['profile_id'])
        self.assertEqual(self.request('/api/profile/clear-history', request), (200, {'cleared': True}))
        self.assertEqual(self.app.store.history(second['profile_id']), [current])
        self.assertEqual(self.app.store.load(second['profile_id']), current)
        self.assertEqual(self.request('/api/history/' + second['profile_id'])[1], [current.to_dict()])

    def test_copy_refresh_failure_reports_a_saved_world_state_and_can_be_repaired(self):
        from world_profiles.storage import _replace_json
        def deny_copy(path, value):
            if path.name != 'head.json':
                raise PermissionError('JSON copy locked')
            return _replace_json(path, value)
        with patch('world_profiles.storage._replace_json', side_effect=deny_copy):
            status, response = self.request('/api/save', self.draft)
        self.assertEqual(status, 200)
        self.assertIn('current JSON copy could not be refreshed', response['storage_warning'])
        profile_id = response['profile_id']
        self.assertEqual(self.app.store.load(profile_id).name, self.draft['name'])
        with patch('gui.open_export_folder'):
            self.assertEqual(self.request('/api/open-world-state-folder', {})[0], 200)
        self.assertNotIn(profile_id, self.app.store.copy_warnings)

    def test_bad_export_settings_and_filenames_cannot_write_outputs(self):
        _, saved = self.request('/api/save', self.draft)
        for filename in ('../escape.fbmod', 'C:\\escape.fbmod', 'NUL', '.fbmod', 'bad?.fbmod'):
            self.assertEqual(self.request('/api/export', dict(profile_id=saved['profile_id'], revision=1, filename=filename))[0], 400)
        for settings in (dict(DEFAULT_SETTINGS, category='Other'), dict(DEFAULT_SETTINGS, icon_data_url='https://example.org/icon.png')):
            self.assertEqual(self.request('/api/export-settings', settings)[0], 400)
        self.assertEqual(self.request('/api/export-settings', dict(DEFAULT_SETTINGS), authorized=False)[0], 403)
        self.assertEqual(self.request('/api/export-settings', dict(DEFAULT_SETTINGS), origin='https://example.org')[0], 403)
        self.assertEqual(self.request('/api/export-settings', authorized=False)[0], 403)
        self.assertFalse(self.app.exports.exists())
        self.assertFalse(self.app.fbmod_settings.path.exists())

    def test_unauthorized_and_foreign_origin_requests_cannot_read_or_write_profiles(self):
        self.assertEqual(self.request('/api/bootstrap', authorized=False)[0], 403)
        self.assertEqual(self.request('/api/save', self.draft, authorized=False)[0], 403)
        self.assertEqual(self.request('/api/save', self.draft, origin='https://example.org')[0], 403)
        self.assertEqual(self.app.store.list(), [])

    def test_category_navigation_covers_supported_choices_with_local_art_only(self):
        # A future category must not appear as editable before it has mappings.
        self.app.categories.append(dict(id='dao.future', game='dao', title='Future',
                                        art='dao_ruler_state/alistair_top_1x1.jpg', layout='portrait'))
        status, data = self.request('/api/bootstrap')
        self.assertEqual(status, 200)
        categories = {category['id']: category for category in data['categories']}
        self.assertEqual(set(categories), {choice['category_id'] for choice in data['choices']})
        self.assertNotIn('dao.future', categories)
        for choice in data['choices']:
            self.assertEqual(categories[choice['category_id']]['game'], choice['game'])
        for category in categories.values():
            self.assertTrue(category['art'].startswith(('/art/', '/interface-art/')))
            status, image = self.request(category['art'], authorized=False, json_response=False)
            self.assertEqual(status, 200)
            self.assertTrue(image.startswith(b'\xff\xd8'))

    def test_sibling_carousels_offer_four_standard_and_one_unrestricted_outcome(self):
        _, data = self.request('/api/bootstrap')
        choices = {choice['id']: choice for choice in data['choices']}
        for sibling in ('bethany', 'carver'):
            answers = choices['da2.' + sibling + '_fate']['answers']
            self.assertEqual(len([a for a in answers if not a.get('unrestricted_only')]), 4)
            special = [a for a in answers if a.get('unrestricted_only')]
            self.assertEqual([a['id'] for a in special], ['alive_unspecified'])
            lothering = next(answer for answer in answers if answer['id'] == 'lothering_death')
            self.assertEqual(lothering['art'], '/art/da2_' + sibling + '_career/died-lothering_detail.jpg')

    def test_romances_have_all_answers_local_art_and_saved_export(self):
        _, data = self.request('/api/bootstrap')
        choices = {choice['id']: choice for choice in data['choices']}
        for key, answers in (('dao.warden_romance', ['none', 'alistair', 'morrigan', 'leliana', 'zevran']),
                             ('da2.hawke_romance', ['none', 'anders', 'fenris', 'isabela', 'merrill', 'sebastian'])):
            choice = choices[key]
            self.assertEqual(choice['category_id'], choice['game'] + '.companions')
            self.assertEqual([a['id'] for a in choice['answers']], answers)
            self.assertEqual(choice['quick_kind'], 'select')
            self.assertTrue(all(a['art'].startswith('/art/') for a in choice['answers']))
        self.assertEqual(choices['dao.warden_romance']['answers'][0]['art'], '/art/dao_warden_romance/no-one_detail_2x1.jpg')
        self.assertEqual(choices['da2.hawke_romance']['answers'][-1]['art'], '/art/da2_hawke_romance/sebastian_detail.jpg')
        self.draft['choices'] = {'dao.warden_romance': 'leliana', 'da2.hawke_romance': 'merrill'}
        _, preview = self.request('/api/preview', self.draft)
        self.assertTrue(preview['can_export'])
        self.assertEqual(preview['resolved_choices']['dao.warden_romance']['answer_id'], 'leliana')
        _, saved = self.request('/api/save', self.draft)
        _, exported = self.request('/api/export', dict(profile_id=saved['profile_id'], revision=saved['revision']))
        from export_worldstate import EbxParser
        flags = {o['value']['VariableNameOnServer']: o['value']['DefaultValue']
                 for o in EbxParser(read_mod(Path(exported['path']).read_bytes())['ebx']).parse()['objects']
                 if o['class'] == 'GameVaultVarInt'}
        self.assertEqual(flags['dao_warden_romance'], 3)
        self.assertEqual(flags['dao_warden_romance_leliana'], 1)
        self.assertEqual(flags['da2_hawke_romance'], 4)
        self.assertEqual(flags['da2_hawke_romance_merrill'], 1)

    def test_hero_categories_have_paintings_and_appearance_from_inherited_gender(self):
        _, data = self.request('/api/bootstrap')
        choices = {choice['id']: choice for choice in data['choices']}
        artwork = set()
        for choice_id, count in (('da2.hawke_identity', 6), ('da2.hawke_personality', 3),
                                 ('dao.warden_class', 3), ('dao.warden_identity', 14)):
            choice = choices[choice_id]
            self.assertEqual(choice['category_id'], choice['game'] + '.hero')
            self.assertEqual(len(choice['answers']), count)
            for answer in choice['answers']:
                artwork.update(answer['art_variants'].values())
        for art in sorted(artwork):
            status, raw = self.request(art, authorized=False, json_response=False)
            self.assertEqual(status, 200)
            self.assertTrue(raw.startswith(b'\xff\xd8'))
        self.draft['choices'] = {'da2.hawke_class': 'mage', 'da2.hawke_personality': 'humourous',
                                 'da2.bethany_fate': 'circle', 'da2.carver_fate': 'templar'}
        _, preview = self.request('/api/preview', self.draft)
        self.assertTrue(preview['can_export'])
        self.assertEqual(preview['hero_appearance']['da2']['gender'], 'female')
        self.assertEqual(preview['resolved_choices']['da2.hawke_personality']['answer_id'], 'humourous')

    def test_backgrounds_are_local_and_art_routes_are_whitelisted(self):
        for filename in ('bg-eye.jpg', 'bg-tile.jpg', 'dragons-bg.png'):
            status, data = self.request('/interface-art/' + filename, authorized=False, json_response=False)
            self.assertEqual(status, 200)
            self.assertTrue(data.startswith((b'\xff\xd8', b'\x89PNG\r\n\x1a\n')))
        for path in ('/interface-art/manifest.json', '/interface-art/../manifest.json',
                     '/interface-art/../keep/manifest.json'):
            self.assertEqual(self.request(path, authorized=False)[0], 404)

    def test_portrait_over_64k_is_served_without_truncation(self):
        path = 'dao_heroes/dwarf_female_rogue.jpg'
        expected = (ROOT / 'assets/keep-interface' / path).read_bytes()
        self.assertGreater(len(expected), 65_536)
        status, actual = self.request('/interface-art/' + path, authorized=False, json_response=False)
        self.assertEqual(status, 200)
        self.assertEqual(actual, expected)

    def test_v3_profile_editor_choices_are_lossless_and_not_written_until_save(self):
        legacy = ProfileStore(self.directory / 'profiles', catalog=Catalog(mapping_version=3))
        original = legacy.create('Existing identities', choices={'da2.hawke_class': 'rogue',
            'dao.warden_origin': 'dalish_elf', 'dao.warden_class': 'warrior'})
        path = legacy.profile_directory(original.profile_id) / 'History/00000001.json'
        before = path.read_bytes()
        _, loaded = self.request('/api/profile/' + original.profile_id)
        self.assertEqual(loaded['choices'], dict(original.choices))
        editor = loaded['editor_choices']
        self.assertEqual(editor['da2.hawke_identity'], 'female_rogue')
        self.assertEqual(editor['dao.warden_identity'], 'female_dalish_elf')
        self.assertNotIn('dao.warden_origin', editor)
        draft = {key: loaded[key] for key in self.draft}
        draft['choices'] = editor
        _, preview = self.request('/api/preview', draft)
        self.assertTrue(preview['mapping_upgrade_pending'])
        self.assertEqual(self.app.store.load(original.profile_id), original)
        # Both combined controls remain editable before committing the upgrade.
        draft['choices'] = dict(editor, **{'da2.hawke_identity': 'male_mage',
                                          'dao.warden_identity': 'male_dwarf_noble'})
        _, preview = self.request('/api/preview', draft)
        self.assertEqual(preview['hero_appearance']['da2']['gender'], 'male')
        self.assertEqual(preview['hero_appearance']['dao']['race'], 'dwarf')
        _, saved = self.request('/api/save', draft)
        self.assertEqual(saved['mapping_version'], self.app.catalog.version)
        self.assertEqual(saved['choices'], draft['choices'])
        self.assertEqual(path.read_bytes(), before)
        # Editor-only metadata must not be required in portable documents.
        from world_profiles import Profile
        self.assertEqual(Profile.from_dict(saved).choices, saved['choices'])

    def test_legacy_profile_is_upgraded_only_on_explicit_save(self):
        legacy_store = ProfileStore(self.directory / 'profiles', catalog=Catalog(mapping_version=1))
        original = legacy_store.create('Old history', choices={'da2.bethany_fate': 'warden'})
        draft = {key: original.to_dict()[key] for key in self.draft}
        _, preview = self.request('/api/preview', draft)
        self.assertTrue(preview['mapping_upgrade_pending'])
        self.assertEqual(self.app.store.load(original.profile_id), original)
        _, saved = self.request('/api/save', draft)
        self.assertEqual(saved['mapping_version'], self.app.catalog.version)
        self.assertEqual(saved['revision'], 2)
        self.assertEqual(saved['choices'], dict(original.choices))
        self.assertEqual(self.app.store.load(original.profile_id, revision=1), original)

    def test_ui_workflow_create_edit_save_export_and_download(self):
        status, profile = self.request('/api/save', self.draft)
        self.assertEqual(status, 200)
        draft = {key: profile[key] for key in self.draft}
        draft['choices'] = {'da2.bethany_fate': 'warden'}
        status, preview = self.request('/api/preview', draft)
        self.assertEqual(status, 200)
        self.assertTrue(preview['can_export'])
        self.assertEqual(preview['resolved_choices']['da2.bethany_fate']['answer_id'], 'warden')
        status, saved = self.request('/api/save', draft)
        self.assertEqual(saved['revision'], 2)
        status, exported = self.request('/api/export', dict(profile_id=saved['profile_id'], revision=2))
        self.assertEqual(status, 200)
        status, downloaded = self.request('/downloads/' + exported['download_id'] + '/mod', json_response=False)
        self.assertEqual(status, 200)
        self.assertEqual(downloaded, Path(exported['path']).read_bytes())
        expected = (ROOT / 'prototype/output/early-tests/01-bethany-warden.fbmod').read_bytes()
        self.assertEqual(read_mod(downloaded)['ebx'], read_mod(expected)['ebx'])
        status, report = self.request('/downloads/' + exported['download_id'] + '/report')
        self.assertEqual(report['profile']['revision'], 2)
        self.assertFalse(report['gameplay_tested'])

    def test_stale_save_is_rejected_with_conflict_status(self):
        _, profile = self.request('/api/save', self.draft)
        draft = {key: profile[key] for key in self.draft}
        draft['name'] = 'Newer revision'
        self.assertEqual(self.request('/api/save', draft)[0], 200)
        draft['name'] = 'Stale revision'
        self.assertEqual(self.request('/api/save', draft)[0], 409)
        _, latest = self.request('/api/profile/' + profile['profile_id'])
        self.assertEqual(latest['name'], 'Newer revision')

    def test_preview_explains_conflict_and_export_still_blocks_it(self):
        self.draft['choices'] = {'dao.loghain_fate': 'alive_recruited',
                                 'dao.ferelden_leadership': 'anora_queen_alistair_warden'}
        status, preview = self.request('/api/preview', self.draft)
        self.assertEqual(status, 200)
        self.assertFalse(preview['can_export'])
        self.assertTrue(preview['errors'])
        self.assertEqual(preview['resolved_choices']['dao.loghain_fate']['answer_id'], 'alive_recruited')
        _, saved = self.request('/api/save', self.draft)
        self.assertEqual(self.request('/api/export', dict(profile_id=saved['profile_id'], revision=1))[0], 400)
        self.assertFalse(self.app.exports.exists())
        self.draft['mode'] = 'experimental'
        _, preview = self.request('/api/preview', self.draft)
        self.assertTrue(preview['can_export'])
        self.assertTrue(preview['experimental_conflicts'])

    def test_profile_duplicate_import_and_history(self):
        _, profile = self.request('/api/save', self.draft)
        _, copied = self.request('/api/duplicate', dict(profile_id=profile['profile_id'], revision=1, name='Copy'))
        _, imported = self.request('/api/import', dict(document=profile))
        self.assertEqual(len({profile['profile_id'], copied['profile_id'], imported['profile_id']}), 3)
        _, history = self.request('/api/history/' + copied['profile_id'])
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['name'], 'Copy')

    def test_unknown_answers_and_arbitrary_file_paths_are_rejected(self):
        self.draft['choices'] = {'da2.bethany_fate': 'invented'}
        self.assertEqual(self.request('/api/save', self.draft)[0], 400)
        self.assertEqual(self.request('/art/../manifest.json')[0], 404)
        self.assertEqual(self.request('/downloads/../../world_profiles/catalog.json')[0], 404)
        self.assertEqual(self.app.store.list(), [])

    def test_static_interface_loads_and_quick_editor_is_hidden_by_default(self):
        status, html = self.request('/', authorized=False, json_response=False)
        self.assertEqual(status, 200)
        self.assertIn(b'id="quick-editor"', html)
        self.assertIn(b'id="quick-editor" class="quick-editor" aria-label="Quick editor" hidden', html)
        self.assertIn(b'Export as FBMod', html)
        self.assertEqual(self.request('/app.js', authorized=False, json_response=False)[0], 200)
        self.assertEqual(self.request('/style.css', authorized=False, json_response=False)[0], 200)

    def test_icon_and_dropdown_art_are_available_locally(self):
        for name in ('favicon.png', 'frame-border-pattern.png', 'frame-decor.png', 'dropdown-arrow.png',
                     'main-nav-bg.png', 'nav-bg-secondary.png'):
            status, data = self.request('/interface-art/' + name, authorized=False, json_response=False)
            self.assertEqual(status, 200)
            self.assertEqual(data, (ROOT / 'assets/keep-interface' / name).read_bytes())
            self.assertTrue(data.startswith(b'\x89PNG\r\n\x1a\n'))

    def test_political_controls_use_local_art_and_save_export_together(self):
        _, data = self.request('/api/bootstrap')
        choices = {choice['id']: choice for choice in data['choices']}
        groups = ('dao.ferelden_ruler', 'dao.alistair_fate', 'dao.alistair_relationship')
        self.assertNotIn('dao.ferelden_leadership', choices)
        for group in groups:
            self.assertEqual(choices[group]['category_id'],
                             'dao.landsmeet' if group == 'dao.ferelden_ruler' else 'dao.companions')
            self.assertEqual(len(choices[group]['answers']), 5)
            for answer in choices[group]['answers']:
                status, image = self.request(answer['art'], authorized=False, json_response=False)
                self.assertEqual(status, 200)
                self.assertTrue(image.startswith(b'\xff\xd8'))
        self.draft['choices'] = dict(zip(groups, ('anora_alone', 'warden', 'wardens_together')))
        status, preview = self.request('/api/preview', self.draft)
        self.assertEqual(status, 200)
        self.assertTrue(preview['can_export'])
        status, saved = self.request('/api/save', self.draft)
        self.assertEqual(status, 200)
        status, exported = self.request('/api/export', dict(profile_id=saved['profile_id'], revision=saved['revision']))
        self.assertEqual(status, 200)
        report = json.loads(Path(exported['report_path']).read_text(encoding='utf-8'))
        selections = {item['choice_id']: item['answer_id'] for item in report['profile']['selections']}
        self.assertEqual(selections, self.draft['choices'])

    def test_old_leadership_control_is_split_for_editing_without_touching_saved_revision(self):
        legacy = ProfileStore(self.directory / 'profiles', catalog=Catalog(mapping_version=5))
        original = legacy.create('Old combined politics', choices={'dao.ferelden_leadership': 'alistair_king_alone'})
        path = legacy.profile_directory(original.profile_id) / 'History/00000001.json'
        before = path.read_bytes()
        _, loaded = self.request('/api/profile/' + original.profile_id)
        self.assertEqual(loaded['choices'], dict(original.choices))
        self.assertEqual(loaded['editor_choices'], {'dao.ferelden_ruler': 'alistair_alone',
            'dao.alistair_fate': 'king', 'dao.alistair_relationship': 'never_lovers'})
        draft = {key: loaded[key] for key in self.draft}
        draft['choices'] = loaded['editor_choices']
        _, preview = self.request('/api/preview', draft)
        self.assertTrue(preview['mapping_upgrade_pending'])
        self.assertTrue(preview['can_export'])
        self.assertEqual(path.read_bytes(), before)

        _, saved = self.request('/api/save', draft)
        self.assertEqual(saved['mapping_version'], self.app.catalog.version)
        self.assertEqual(saved['revision'], 2)
        self.assertEqual(path.read_bytes(), before)

    def test_circle_redcliffe_controls_have_local_art_and_save_export_together(self):
        _, data = self.request('/api/bootstrap')
        choices = {choice['id']: choice for choice in data['choices']}
        for group, category, count in [('dao.broken_circle', 'dao.circle', 2),
            ('dao.connor_fate', 'dao.redcliffe', 3), ('dao.isolde_fate', 'dao.redcliffe', 2)]:
            self.assertEqual(choices[group]['category_id'], category)
            self.assertEqual(len(choices[group]['answers']), count)
            for answer in choices[group]['answers']:
                status, image = self.request(answer['art'], authorized=False, json_response=False)
                self.assertEqual(status, 200)
                self.assertTrue(image.startswith(b'\xff\xd8'))
        self.draft['choices'] = {'dao.broken_circle': 'templars', 'dao.connor_fate': 'dead',
                                 'dao.isolde_fate': 'alive'}
        _, preview = self.request('/api/preview', self.draft)
        self.assertTrue(preview['can_export'])
        _, saved = self.request('/api/save', self.draft)
        self.assertEqual(saved['choices'], self.draft['choices'])
        status, exported = self.request('/api/export', {'profile_id': saved['profile_id'], 'revision': saved['revision']})
        self.assertEqual(status, 200)
        report = json.loads(Path(exported['report_path']).read_text(encoding='utf8'))
        selected = {item['choice_id']: item['answer_id'] for item in report['profile']['selections']}
        self.assertEqual(selected, self.draft['choices'])
        self.assertFalse(report['profile']['gameplay_tested'])

    def test_nature_orzammar_controls_have_local_art_and_export_all_three_anvil_answers(self):
        _, data = self.request('/api/bootstrap')
        choices = {choice['id']: choice for choice in data['choices']}
        for group, category, count in [('dao.nature_outcome', 'dao.nature', 3),
            ('dao.orzammar_ruler', 'dao.paragon', 2), ('dao.anvil_fate', 'dao.paragon', 3)]:
            self.assertEqual(choices[group]['category_id'], category)
            self.assertEqual(len(choices[group]['answers']), count)
            for answer in choices[group]['answers']:
                status, image = self.request(answer['art'], authorized=False, json_response=False)
                self.assertEqual(status, 200)
                self.assertTrue(image.startswith(b'\xff\xd8'))
        self.assertIn('verification', choices['dao.anvil_fate']['verification_note'])
        for anvil in ('warden_destroyed', 'branka_destroyed', 'preserved'):
            draft = dict(self.draft, choices={'dao.nature_outcome': 'werewolves',
                'dao.orzammar_ruler': 'harrowmont', 'dao.anvil_fate': anvil})
            _, preview = self.request('/api/preview', draft)
            self.assertTrue(preview['can_export'])
            _, saved = self.request('/api/save', draft)
            status, exported = self.request('/api/export', {'profile_id': saved['profile_id'], 'revision': saved['revision']})
            self.assertEqual(status, 200)
            report = json.loads(Path(exported['report_path']).read_text(encoding='utf8'))
            selected = {item['choice_id']: item['answer_id'] for item in report['profile']['selections']}
            self.assertEqual(selected, draft['choices'])
            self.assertFalse(report['profile']['gameplay_tested'])

    def test_origins_companion_controls_have_local_art_and_export_without_changing_romance(self):
        _, data = self.request('/api/bootstrap')
        choices = {choice['id']: choice for choice in data['choices']}
        for group, count in [('dao.leliana_fate', 4), ('dao.wynne_fate', 4),
                             ('dao.zevran_recruited', 2), ('dao.zevran_fate', 2)]:
            choice = choices[group]
            self.assertEqual(choice['category_id'], 'dao.companions')
            self.assertEqual(len(choice['answers']), count)
            self.assertEqual(choice['quick_kind'], 'checkbox' if 'zevran' in group else 'select')
            for answer in choice['answers']:
                status, image = self.request(answer['art'], authorized=False, json_response=False)
                self.assertEqual(status, 200)
                self.assertTrue(image.startswith(b'\xff\xd8'))
        self.assertIn('original game label disagrees', choices['dao.leliana_fate']['verification_note'])
        self.draft['choices'] = {'dao.leliana_fate': 'left_after_urn', 'dao.wynne_fate': 'died_at_circle',
            'dao.zevran_recruited': 'not_recruited', 'dao.zevran_fate': 'dead', 'dao.warden_romance': 'zevran'}
        _, preview = self.request('/api/preview', self.draft)
        self.assertTrue(preview['can_export'])
        self.assertEqual(preview['resolved_choices']['dao.leliana_fate']['answer_id'], 'left_after_urn')
        _, saved = self.request('/api/save', self.draft)
        self.assertEqual(saved['choices'], self.draft['choices'])
        status, exported = self.request('/api/export', {'profile_id': saved['profile_id'], 'revision': saved['revision']})
        self.assertEqual(status, 200)
        report = json.loads(Path(exported['report_path']).read_text(encoding='utf8'))
        selected = {item['choice_id']: item['answer_id'] for item in report['profile']['selections']}
        self.assertEqual(selected, self.draft['choices'])
        self.assertFalse(report['profile']['gameplay_tested'])

    def test_sten_and_dagna_controls_have_local_art_and_independent_permission_export(self):
        _, data = self.request('/api/bootstrap')
        choices = {choice['id']: choice for choice in data['choices']}
        self.assertEqual(choices['dao.dagna_permission']['display'], 'quick-only')
        self.assertNotEqual(choices['dao.dagna_outcome'].get('display'), 'quick-only')
        for group, count, category in [('dao.sten_recruited', 2, 'dao.companions'),
                ('dao.sten_release', 4, 'dao.companions'), ('dao.sten_sword', 3, 'dao.companions'),
                ('dao.dagna_outcome', 5, 'dao.paragon'), ('dao.dagna_permission', 2, 'dao.paragon')]:
            choice = choices[group]
            self.assertEqual(choice['category_id'], category)
            self.assertEqual(len(choice['answers']), count)
            for answer in choice['answers']:
                status, image = self.request(answer['art'], authorized=False, json_response=False)
                self.assertEqual(status, 200)
                self.assertTrue(image.startswith(b'\xff\xd8'))
        permission = {answer['id']: answer['art'] for answer in choices['dao.dagna_permission']['answers']}
        self.assertEqual(permission['requested'], '/art/dao_par_unlikely_scholar/ask-for-permission_detail.jpg')
        self.assertEqual(permission['not_requested'], '/art/dao_par_unlikely_scholar/never-met_detail.jpg')
        self.draft['choices'] = {'dao.sten_recruited': 'recruited', 'dao.sten_release': 'picked_lock',
            'dao.sten_sword': 'returned', 'dao.dagna_outcome': 'circle_destroyed', 'dao.dagna_permission': 'requested'}
        _, preview = self.request('/api/preview', self.draft)
        self.assertTrue(preview['can_export'])
        self.assertEqual(preview['resolved_choices']['dao.dagna_outcome']['answer_id'], 'circle_destroyed')
        _, saved = self.request('/api/save', self.draft)
        self.assertEqual(saved['choices'], self.draft['choices'])
        status, exported = self.request('/api/export', {'profile_id': saved['profile_id'], 'revision': saved['revision'],
            'filename': 'Sten and Dagna.fbmod', 'title': 'Sten and Dagna'})
        self.assertEqual(status, 200)
        from export_worldstate import EbxParser
        flags = {obj['value']['VariableNameOnServer']: obj['value']['DefaultValue']
                 for obj in EbxParser(read_mod(Path(exported['path']).read_bytes())['ebx']).parse()['objects']
                 if obj['class'] == 'GameVaultVarInt'}
        self.assertEqual(flags['dao_par_unlikely_scholar'], 4)
        self.assertEqual(flags['dao_par_dagna_circle'], 1)
        self.assertEqual(flags['dao_lot_qunari_prisoner'], 1)

    def test_da2_companions_have_local_art_correct_handover_painting_and_saved_export(self):
        from test_da2_companions import CASES, flags_from_mod
        _, data = self.request('/api/bootstrap')
        choices = {choice['id']: choice for choice in data['choices']}
        for group, (_, answers) in CASES.items():
            choice = choices[group]
            self.assertEqual(choice['category_id'], 'da2.companions')
            self.assertEqual(len(choice['answers']), len(answers))
            self.assertEqual(choice['quick_kind'], 'select' if group in
                ('da2.fenris_fate', 'da2.fenris_danarius', 'da2.isabela_book') else 'checkbox')
            for answer in choice['answers']:
                status, image = self.request(answer['art'], authorized=False, json_response=False)
                self.assertEqual(status, 200)
                self.assertTrue(image.startswith(b'\xff\xd8'))
        handover = choices['da2.isabela_handover']
        self.assertIn('older game descriptions disagree', handover['verification_note'])
        artwork = {answer['id']: answer['art'] for answer in handover['answers']}
        self.assertEqual(artwork['handed_over'], '/art/da2_isabela_turned_over/not-present_detail.jpg')
        self.assertEqual(artwork['not_handed_over'], '/art/da2_isabela_turned_over/no_detail.jpg')
        self.assertIn('value 4', choices['da2.fenris_fate']['verification_note'])
        self.draft['choices'] = {group: next(reversed(answers)) for group, (_, answers) in CASES.items()}
        self.draft['choices'].update({'da2.hawke_romance': 'merrill', 'da2.hawke_identity': 'female_mage',
            'da2.bethany_fate': 'warden', 'da2.carver_fate': 'warden'})
        _, preview = self.request('/api/preview', self.draft)
        self.assertTrue(preview['can_export'])
        _, saved = self.request('/api/save', self.draft)
        self.assertEqual(saved['choices'], self.draft['choices'])
        status, exported = self.request('/api/export', {'profile_id': saved['profile_id'], 'revision': saved['revision'],
            'filename': 'DA2 companion history.fbmod', 'title': 'DA2 companion history'})
        self.assertEqual(status, 200)
        flags = flags_from_mod(Path(exported['path']).read_bytes())
        for group, (fields, answers) in CASES.items():
            self.assertEqual(tuple(flags[field]['DefaultValue'] for field in fields), answers[self.draft['choices'][group]])
        self.assertEqual(flags['da2_fenris_alive']['MaxValue'], 4)
        self.assertEqual(flags['da2_isabela_turned_over']['DefaultValue'], 1)
        self.assertEqual(flags['da2_hawke_romance']['DefaultValue'], 4)
        _, loaded = self.request('/api/profile/' + saved['profile_id'])
        self.assertEqual(loaded['editor_choices'], self.draft['choices'])

    def test_aveline_varric_sebastian_art_save_export_and_reload(self):
        from test_aveline_varric_sebastian import CASES, flags_from_mod
        _, data = self.request('/api/bootstrap')
        choices = {choice['id']: choice for choice in data['choices']}
        for group in CASES:
            choice = choices[group]
            self.assertEqual(choice['category_id'], 'da2.companions')
            self.assertEqual(len(choice['answers']), 2)
            self.assertEqual(choice['quick_kind'], 'select' if group in
                ('da2.varric_relationship', 'da2.bartrand_fate') else 'checkbox')
            for answer in choice['answers']:
                status, image = self.request(answer['art'], authorized=False, json_response=False)
                self.assertEqual(status, 200)
                self.assertTrue(image.startswith(b'\xff\xd8'))
        for index in (0, 1):
            self.draft['choices'] = {group: list(answers)[index] for group, (_, answers) in CASES.items()}
            self.draft['choices'].update({'da2.hawke_romance': 'sebastian', 'da2.anders_fate': 'alive',
                'da2.bethany_fate': 'warden', 'da2.carver_fate': 'warden'})
            _, preview = self.request('/api/preview', self.draft)
            self.assertTrue(preview['can_export'])
            _, saved = self.request('/api/save', self.draft)
            self.assertEqual(saved['choices'], self.draft['choices'])
            status, exported = self.request('/api/export', {'profile_id': saved['profile_id'], 'revision': saved['revision'],
                'filename': 'Aveline Varric Sebastian.fbmod', 'title': 'Aveline Varric Sebastian'})
            self.assertEqual(status, 200)
            flags = flags_from_mod(Path(exported['path']).read_bytes())
            for group, (fields, answers) in CASES.items():
                self.assertEqual(tuple(flags[field]['DefaultValue'] for field in fields), answers[self.draft['choices'][group]])
            self.assertEqual(flags['da2_hawke_romance']['DefaultValue'], 5)
            self.assertEqual(flags['da2_anders_alive']['DefaultValue'], 1)
            _, loaded = self.request('/api/profile/' + saved['profile_id'])
            self.assertEqual(loaded['editor_choices'], self.draft['choices'])

    def test_da2_main_story_categories_local_art_and_independent_saved_export(self):
        from test_da2_main_story import CASES, flags_from_mod
        _, data = self.request('/api/bootstrap')
        choices = {choice['id']: choice for choice in data['choices']}
        categories = {category['id']: category for category in data['categories']}
        self.assertEqual(categories['da2.act2']['title'], 'Act II')
        self.assertEqual(categories['da2.act3']['title'], 'Act III')
        for group in CASES:
            choice = choices[group]
            self.assertEqual(choice['category_id'], {'da2.arishok_fate': 'da2.act2', 'da2.anders_approval': 'da2.companions', 'da2.final_allegiance': 'da2.act3'}[group])
            self.assertEqual(choice['quick_kind'], 'select' if group == 'da2.final_allegiance' else 'checkbox')
            self.assertEqual(len(choice['answers']), 2)
            for answer in choice['answers']:
                status, image = self.request(answer['art'], authorized=False, json_response=False)
                self.assertEqual(status, 200)
                self.assertTrue(image.startswith(b'\xff\xd8'))
        for index in (0, 1):
            self.draft['choices'] = {group: list(answers)[index] for group, (_, answers) in CASES.items()}
            self.draft['choices'].update({'da2.anders_fate': 'executed', 'da2.isabela_handover': 'handed_over',
                'da2.bartrand_fate': 'killed', 'da2.bethany_fate': 'warden', 'da2.carver_fate': 'warden'})
            _, preview = self.request('/api/preview', self.draft)
            self.assertTrue(preview['can_export'])
            _, saved = self.request('/api/save', self.draft)
            self.assertEqual(saved['choices'], self.draft['choices'])
            status, exported = self.request('/api/export', {'profile_id': saved['profile_id'], 'revision': saved['revision'],
                'filename': 'Kirkwall history.fbmod', 'title': 'Kirkwall history'})
            self.assertEqual(status, 200)
            flags = flags_from_mod(Path(exported['path']).read_bytes())
            for group, (fields, answers) in CASES.items():
                self.assertEqual(tuple(flags[field]['DefaultValue'] for field in fields), answers[self.draft['choices'][group]])
            self.assertEqual(flags['da2_anders_alive']['DefaultValue'], 0)
            self.assertEqual(flags['da2_isabela_turned_over']['DefaultValue'], 1)
            self.assertEqual(flags['da2_varric_bartrand_killed']['DefaultValue'], 1)
            _, loaded = self.request('/api/profile/' + saved['profile_id'])
            self.assertEqual(loaded['editor_choices'], self.draft['choices'])

    def test_legacy_category_art_and_independent_export_reload(self):
        from test_legacy import CASES
        from test_da2_main_story import flags_from_mod
        _, data = self.request('/api/bootstrap')
        choices = {choice['id']: choice for choice in data['choices']}
        category = next(category for category in data['categories'] if category['id'] == 'da2.legacy')
        self.assertEqual(category['title'], 'Legacy DLC')
        for group in CASES:
            choice = choices[group]
            self.assertEqual(choice['category_id'], 'da2.legacy')
            self.assertEqual(choice['quick_kind'], 'checkbox' if group == 'da2.legacy_played' else 'select')
            for answer in choice['answers']:
                status, image = self.request(answer['art'], authorized=False, json_response=False)
                self.assertEqual(status, 200)
                self.assertTrue(image.startswith(b'\xff\xd8'))
        for index in (0, 1):
            self.draft['choices'] = {group: list(answers)[index] for group, (_, answers) in CASES.items()}
            self.draft['choices'].update({'da2.hawke_identity': 'female_mage',
                'da2.bethany_fate': 'warden', 'da2.carver_fate': 'warden'})
            _, preview = self.request('/api/preview', self.draft)
            self.assertTrue(preview['can_export'])
            _, saved = self.request('/api/save', self.draft)
            status, exported = self.request('/api/export', {'profile_id': saved['profile_id'],
                'revision': saved['revision'], 'filename': 'Legacy.fbmod', 'title': 'Legacy'})
            self.assertEqual(status, 200)
            flags = flags_from_mod(Path(exported['path']).read_bytes())
            for group, (fields, answers) in CASES.items():
                self.assertEqual(tuple(flags[n]['DefaultValue'] for n in fields), answers[self.draft['choices'][group]])
            _, loaded = self.request('/api/profile/' + saved['profile_id'])
            self.assertEqual(loaded['editor_choices'], self.draft['choices'])

    def test_da2_zevran_three_answer_selectors_art_layout_export_reload(self):
        from test_zevran_da2 import CASES
        from test_da2_main_story import flags_from_mod
        _, data = self.request('/api/bootstrap')
        choices = {choice['id']: choice for choice in data['choices']}
        category = next(c for c in data['categories'] if c['id'] == 'da2.act3')
        self.assertEqual([tile['choice_id'] for tile in category['tile_blocks'][0]], list(CASES))
        for group in CASES:
            choice = choices[group]
            self.assertEqual(choice['category_id'], 'da2.act3')
            self.assertEqual(choice['quick_kind'], 'select')
            self.assertEqual(len(choice['answers']), 3)
            for answer in choice['answers']:
                status, image = self.request(answer['art'], authorized=False, json_response=False)
                self.assertEqual(status, 200)
                self.assertTrue(image.startswith(b'\xff\xd8'))
        for index in (0, 1, 2):
            self.draft['choices'] = {group: list(answers)[index] for group, (_, answers) in CASES.items()}
            self.draft['choices'].update({'dao.zevran_fate': 'dead', 'da2.hawke_identity': 'female_mage',
                'da2.bethany_fate': 'warden', 'da2.carver_fate': 'warden'})
            _, preview = self.request('/api/preview', self.draft)
            self.assertTrue(preview['can_export'])
            _, saved = self.request('/api/save', self.draft)
            status, exported = self.request('/api/export', {'profile_id': saved['profile_id'],
                'revision': saved['revision'], 'filename': 'Zevran history.fbmod', 'title': 'Zevran history'})
            self.assertEqual(status, 200)
            flags = flags_from_mod(Path(exported['path']).read_bytes())
            self.assertEqual(flags['dao_zevran_alive']['DefaultValue'], 0)
            for group, (fields, answers) in CASES.items():
                self.assertEqual(tuple(flags[n]['DefaultValue'] for n in fields), answers[self.draft['choices'][group]])
            _, loaded = self.request('/api/profile/' + saved['profile_id'])
            self.assertEqual(loaded['editor_choices'], self.draft['choices'])

    def test_nathaniel_gamlen_portrait_pair_art_export_and_reload(self):
        from test_nathaniel_gamlen import CASES
        from test_da2_main_story import flags_from_mod
        _, data = self.request('/api/bootstrap')
        choices = {choice['id']: choice for choice in data['choices']}
        category = next(c for c in data['categories'] if c['id'] == 'da2.act3')
        pair = category['tile_blocks'][1]
        self.assertEqual([t['choice_id'] for t in pair], list(CASES))
        self.assertEqual([(t['x'], t['y'], t['width'], t['height']) for t in pair], [(0, 0, 1, 2), (1, 0, 1, 2)])
        for group in CASES:
            choice = choices[group]
            self.assertEqual(choice['category_id'], 'da2.act3')
            self.assertEqual(choice['quick_kind'], 'select')
            self.assertEqual(len(choice['answers']), 3)
            for answer in choice['answers']:
                status, image = self.request(answer['art'], authorized=False, json_response=False)
                self.assertEqual(status, 200)
                self.assertTrue(image.startswith(b'\xff\xd8'))
        death = next(a for a in choices['da2.finding_nathaniel']['answers'] if a['id'] == 'not_survived')
        self.assertIn('Awakening', death['description'])
        for index in (0, 1, 2):
            self.draft['choices'] = {group: list(answers)[index] for group, (_, answers) in CASES.items()}
            self.draft['choices'].update({'da2.zevran_freed': 'not_freed', 'da2.hawke_identity': 'female_mage',
                'da2.bethany_fate': 'warden', 'da2.carver_fate': 'warden'})
            _, preview = self.request('/api/preview', self.draft)
            self.assertTrue(preview['can_export'])
            _, saved = self.request('/api/save', self.draft)
            status, exported = self.request('/api/export', {'profile_id': saved['profile_id'],
                'revision': saved['revision'], 'filename': 'Nathaniel and Gamlen.fbmod', 'title': 'Nathaniel and Gamlen'})
            self.assertEqual(status, 200)
            flags = flags_from_mod(Path(exported['path']).read_bytes())
            self.assertEqual(flags['da2_act3_zevran_freed']['DefaultValue'], 1)
            for group, (fields, answers) in CASES.items():
                self.assertEqual(tuple(flags[n]['DefaultValue'] for n in fields), answers[self.draft['choices'][group]])
            _, loaded = self.request('/api/profile/' + saved['profile_id'])
            self.assertEqual(loaded['editor_choices'], self.draft['choices'])

    def test_legacy_has_two_keep_tiles_will_art_and_preserved_quick_played_flag(self):
        from test_da2_main_story import flags_from_mod
        _, data = self.request('/api/bootstrap')
        choices = {c['id']: c for c in data['choices']}
        visible = {c['id'] for c in data['choices'] if c['category_id'] == 'da2.legacy' and c.get('display') != 'quick-only'}
        self.assertEqual(visible, {'da2.legacy_side', 'da2.malcolm_will'})
        self.assertEqual(choices['da2.legacy_played']['display'], 'quick-only')
        category = next(c for c in data['categories'] if c['id'] == 'da2.legacy')
        self.assertEqual([t['choice_id'] for block in category['tile_blocks'] for t in block],
                         ['da2.legacy_side', 'da2.malcolm_will'])
        choice = choices['da2.malcolm_will']
        self.assertEqual(choice['quick_kind'], 'checkbox')
        for answer in choice['answers']:
            self.assertEqual(answer['art'], '/art/da2_legacy_malcolm_will/' + ('yes' if answer['id'] == 'found' else 'no') + '_detail.jpg')
            status, image = self.request(answer['art'], authorized=False, json_response=False)
            self.assertEqual(status, 200)
            self.assertTrue(image.startswith(b'\xff\xd8'))
        for answer, value in [('not_found', 0), ('found', 1)]:
            self.draft['choices'] = {'da2.malcolm_will': answer, 'da2.legacy_played': 'not_played', 'da2.legacy_side': 'janeka'}
            _, preview = self.request('/api/preview', self.draft)
            self.assertTrue(preview['can_export'])
            _, saved = self.request('/api/save', self.draft)
            status, exported = self.request('/api/export', {'profile_id': saved['profile_id'], 'revision': saved['revision'],
                'filename': 'Malcolm Legacy.fbmod', 'title': 'Malcolm Legacy'})
            self.assertEqual(status, 200)
            flags = flags_from_mod(Path(exported['path']).read_bytes())
            self.assertEqual(flags['da2_legacy_malcolm_will']['DefaultValue'], value)
            self.assertEqual(flags['da2_dlc_legacy_played']['DefaultValue'], 0)
            self.assertEqual(flags['da2_legacy_side_chosen']['DefaultValue'], 1)
            _, loaded = self.request('/api/profile/' + saved['profile_id'])
            self.assertEqual(loaded['editor_choices'], self.draft['choices'])

    def test_act_three_conspirators_emile_keran_art_export_and_reload(self):
        from test_act3_conspirators import CASES
        from test_da2_main_story import flags_from_mod
        _, data = self.request('/api/bootstrap')
        choices = {c['id']: c for c in data['choices']}
        category = next(c for c in data['categories'] if c['id'] == 'da2.act3')
        added = [block[0] for block in category['tile_blocks'][-3:]]
        self.assertEqual([t['choice_id'] for t in added], list(CASES))
        self.assertEqual([(t['width'], t['height']) for t in added], [(2, 2), (2, 2), (2, 1)])
        for group, (_, answers) in CASES.items():
            choice = choices[group]
            self.assertEqual(choice['category_id'], 'da2.act3')
            self.assertEqual(choice['quick_kind'], 'select')
            self.assertEqual(len(choice['answers']), len(answers))
            for answer in choice['answers']:
                status, image = self.request(answer['art'], authorized=False, json_response=False)
                self.assertEqual(status, 200)
                self.assertTrue(image.startswith(b'\xff\xd8'))
        for index in (0, 1, 2):
            self.draft['choices'] = {group: list(answers)[index % len(answers)] for group, (_, answers) in CASES.items()}
            self.draft['choices'].update({'da2.final_allegiance': 'templars', 'da2.hawke_identity': 'female_mage',
                'da2.bethany_fate': 'warden', 'da2.carver_fate': 'warden'})
            _, preview = self.request('/api/preview', self.draft)
            self.assertTrue(preview['can_export'])
            _, saved = self.request('/api/save', self.draft)
            status, exported = self.request('/api/export', {'profile_id': saved['profile_id'], 'revision': saved['revision'],
                'filename': 'Act III choices.fbmod', 'title': 'Act III choices'})
            self.assertEqual(status, 200)
            flags = flags_from_mod(Path(exported['path']).read_bytes())
            self.assertEqual(flags['da2_hawke_chosen_side']['DefaultValue'], 1)
            for group, (fields, answers) in CASES.items():
                self.assertEqual(tuple(flags[n]['DefaultValue'] for n in fields), answers[self.draft['choices'][group]])
            _, loaded = self.request('/api/profile/' + saved['profile_id'])
            self.assertEqual(loaded['editor_choices'], self.draft['choices'])

    def test_profile_only_dragon_completes_act_three_without_changing_exported_game_data(self):
        _, data = self.request('/api/bootstrap')
        choice = next(c for c in data['choices'] if c['id'] == 'da2.bone_pit_dragon')
        self.assertEqual(choice['export_behavior'], 'profile-only')
        self.assertEqual(choice['export_note'], 'Not exported to DAI')
        self.assertEqual(choice['custom_answer_label'], 'Not selected')
        category = next(c for c in data['categories'] if c['id'] == 'da2.act3')
        self.assertEqual([t['choice_id'] for t in category['tile_blocks'][-1]], ['da2.keran_fate', 'da2.bone_pit_dragon'])
        self.assertEqual(category['tile_blocks'][-1][1]['y'], 1)
        for answer in choice['answers']:
            status, image = self.request(answer['art'], authorized=False, json_response=False)
            self.assertEqual(status, 200)
            self.assertTrue(image.startswith(b'\xff\xd8'))
        baseline = None
        for answer in (None, 'not_killed', 'killed', None):
            self.draft['choices'] = {'da2.bone_pit_dragon': answer} if answer else {}
            _, preview = self.request('/api/preview', self.draft)
            resolved = preview['resolved_choices']['da2.bone_pit_dragon']
            self.assertEqual(resolved['answer_id'], answer)
            self.assertEqual(resolved['source'], 'explicit_selection' if answer else 'not_selected')
            self.assertTrue(preview['can_export'])
            _, saved = self.request('/api/save', self.draft)
            _, imported = self.request('/api/import', {'document': saved})
            self.assertEqual(imported['choices'], self.draft['choices'])
            status, exported = self.request('/api/export', {'profile_id': saved['profile_id'], 'revision': saved['revision'],
                'filename': 'Dragon profile.fbmod', 'title': 'Dragon profile'})
            self.assertEqual(status, 200)
            ebx = read_mod(Path(exported['path']).read_bytes())['ebx']
            if baseline is None: baseline = ebx
            self.assertEqual(ebx, baseline)
            _, loaded = self.request('/api/profile/' + saved['profile_id'])
            self.assertEqual(loaded['editor_choices'], self.draft['choices'])

    def test_act_two_feynriel_gascard_javaris_art_export_and_reload(self):
        from test_act2_fates import CASES
        from test_da2_main_story import flags_from_mod
        _, data = self.request('/api/bootstrap')
        choices = {c['id']: c for c in data['choices']}
        category = next(c for c in data['categories'] if c['id'] == 'da2.act2')
        self.assertEqual([b[0]['choice_id'] for b in category['tile_blocks']],
            ['da2.gascard_fate', 'da2.hubert_caravans', 'da2.cliff_raiders', 'da2.varnell_side', 'da2.javaris_fate', 'da2.arishok_fate'])
        self.assertEqual(category['tile_blocks'][2][1]['choice_id'], 'da2.feynriel_fate')
        self.assertEqual(category['tile_blocks'][2][1]['width'], 1)
        self.assertEqual(category['tile_blocks'][2][1]['x'], 1)
        for group, (_, answers) in CASES.items():
            choice = choices[group]
            self.assertEqual(choice['category_id'], 'da2.act2')
            self.assertEqual(choice['quick_kind'], 'select' if group == 'da2.feynriel_fate' else 'checkbox')
            self.assertEqual(len(choice['answers']), len(answers))
            for answer in choice['answers']:
                status, image = self.request(answer['art'], authorized=False, json_response=False)
                self.assertEqual(status, 200)
                self.assertTrue(image.startswith(b'\xff\xd8'))
        for index in (0, 1, 2):
            self.draft['choices'] = {group: list(answers)[index % len(answers)] for group, (_, answers) in CASES.items()}
            self.draft['choices'].update({'da2.arishok_fate': 'not_killed', 'da2.hawke_identity': 'female_mage',
                'da2.bethany_fate': 'warden', 'da2.carver_fate': 'warden', 'da2.bone_pit_dragon': 'killed'})
            _, preview = self.request('/api/preview', self.draft)
            self.assertTrue(preview['can_export'])
            _, saved = self.request('/api/save', self.draft)
            status, exported = self.request('/api/export', {'profile_id': saved['profile_id'], 'revision': saved['revision'],
                'filename': 'Act II fates.fbmod', 'title': 'Act II fates'})
            self.assertEqual(status, 200)
            flags = flags_from_mod(Path(exported['path']).read_bytes())
            self.assertEqual(flags['da2_arishok_killed']['DefaultValue'], 0)
            self.assertNotIn('da2_act3_bone_pit_dragon', flags)
            for group, (fields, answers) in CASES.items():
                self.assertEqual(tuple(flags[n]['DefaultValue'] for n in fields), answers[self.draft['choices'][group]])
            _, loaded = self.request('/api/profile/' + saved['profile_id'])
            self.assertEqual(loaded['editor_choices'], self.draft['choices'])

    def test_remaining_act_two_controls_match_keep_layout_art_and_saved_exports(self):
        from test_act2_remaining import CASES
        from test_da2_main_story import flags_from_mod
        _, data = self.request('/api/bootstrap')
        choices = {c['id']: c for c in data['choices']}
        category = next(c for c in data['categories'] if c['id'] == 'da2.act2')
        visible = {c['id'] for c in data['choices'] if c['category_id'] == 'da2.act2'}
        self.assertEqual(len(visible), 9)
        tiles = [t for b in category['tile_blocks'] for t in b]
        self.assertEqual({t['choice_id'] for t in tiles}, visible)
        self.assertEqual(len(tiles), 9)
        self.assertEqual([t['choice_id'] for t in category['tile_blocks'][1]], ['da2.hubert_caravans', 'da2.fools_gold'])
        self.assertEqual([t['choice_id'] for t in category['tile_blocks'][2]], ['da2.cliff_raiders', 'da2.feynriel_fate'])
        self.assertEqual([t['choice_id'] for t in category['tile_blocks'][3]], ['da2.varnell_side', 'da2.petrice_side'])
        self.assertIn('older game descriptions reverse', choices['da2.fools_gold']['verification_note'])
        self.assertEqual(choices['da2.fools_gold']['evidence_status'], 'disputed')
        for group, (_, answers) in CASES.items():
            choice = choices[group]
            self.assertEqual(choice['category_id'], 'da2.act2')
            self.assertEqual(choice['quick_kind'], 'select' if group in ('da2.fools_gold', 'da2.cliff_raiders') else 'checkbox')
            self.assertEqual(len(choice['answers']), len(answers))
            for answer in choice['answers']:
                status, image = self.request(answer['art'], authorized=False, json_response=False)
                self.assertEqual(status, 200)
                self.assertTrue(image.startswith(b'\xff\xd8'))
        for index in range(4):
            self.draft['choices'] = {group: list(answers)[index % len(answers)] for group, (_, answers) in CASES.items()}
            self.draft['choices'].update({'da2.feynriel_fate': 'possessed', 'da2.arishok_fate': 'not_killed',
                'da2.hawke_identity': 'female_mage', 'da2.bethany_fate': 'warden', 'da2.carver_fate': 'warden',
                'da2.bone_pit_dragon': 'killed'})
            _, preview = self.request('/api/preview', self.draft)
            self.assertTrue(preview['can_export'])
            _, saved = self.request('/api/save', self.draft)
            status, exported = self.request('/api/export', {'profile_id': saved['profile_id'], 'revision': saved['revision'],
                'filename': 'Act II quests.fbmod', 'title': 'Act II quests'})
            self.assertEqual(status, 200)
            flags = flags_from_mod(Path(exported['path']).read_bytes())
            self.assertEqual(flags['da2_act2_fenriel_end']['DefaultValue'], 2)
            self.assertNotIn('da2_act3_bone_pit_dragon', flags)
            for group, (fields, answers) in CASES.items():
                self.assertEqual(tuple(flags[n]['DefaultValue'] for n in fields), answers[self.draft['choices'][group]])
            _, loaded = self.request('/api/profile/' + saved['profile_id'])
            self.assertEqual(loaded['editor_choices'], self.draft['choices'])

    def test_act_one_controls_match_keep_layout_art_and_saved_exports(self):
        from test_act1_feynriel_templars import CASES
        from test_da2_main_story import flags_from_mod
        _, data = self.request('/api/bootstrap')
        choices = {c['id']: c for c in data['choices']}
        category = next(c for c in data['categories'] if c['id'] == 'da2.act1')
        visible = {c['id'] for c in data['choices'] if c['category_id'] == 'da2.act1'}
        self.assertEqual(len(visible), 14)
        tiles = [tile for block in category['tile_blocks'] for tile in block]
        self.assertEqual({tile['choice_id'] for tile in tiles}, visible)
        self.assertEqual([tile['choice_id'] for tile in tiles],
            ['da2.act1_templars', 'da2.saemus_rescue', 'da2.ginnis_fate', 'da2.ghyslain_truth',
             'da2.thrask_blackmail', 'da2.feynriel_destination', 'da2.ketojan_fate', 'da2.martin_cargo', 'da2.kelder_fate', 'da2.danzig_fate',
             'da2.bone_pit_miners', 'da2.idunna_fate', 'da2.keran_templars', 'da2.karras_fate'])
        da2_categories = [c['id'] for c in data['categories'] if c['game'] == 'da2']
        self.assertEqual(da2_categories, ['da2.hero', 'da2.companions', 'da2.prologue', 'da2.act1', 'da2.act2', 'da2.act3', 'da2.legacy'])
        for group, (_, answers) in CASES.items():
            choice = choices[group]
            self.assertEqual(choice['category_id'], 'da2.act1')
            self.assertEqual(choice['quick_kind'], 'select' if group in ('da2.feynriel_destination', 'da2.act1_templars') else 'checkbox')
            self.assertEqual(len(choice['answers']), len(answers))
            for answer in choice['answers']:
                status, image = self.request(answer['art'], authorized=False, json_response=False)
                self.assertEqual(status, 200)
                self.assertTrue(image.startswith(b'\xff\xd8'))
        for index in range(3):
            self.draft['choices'] = {group: list(answers)[index % len(answers)] for group, (_, answers) in CASES.items()}
            self.draft['choices'].update({'da2.feynriel_fate': 'possessed', 'da2.final_allegiance': 'templars',
                'da2.hawke_identity': 'female_mage', 'da2.bethany_fate': 'warden', 'da2.carver_fate': 'warden',
                'da2.bone_pit_dragon': 'killed'})
            _, preview = self.request('/api/preview', self.draft)
            self.assertTrue(preview['can_export'])
            _, saved = self.request('/api/save', self.draft)
            status, exported = self.request('/api/export', {'profile_id': saved['profile_id'], 'revision': saved['revision'],
                'filename': 'Act I history.fbmod', 'title': 'Act I history'})
            self.assertEqual(status, 200)
            flags = flags_from_mod(Path(exported['path']).read_bytes())
            self.assertEqual(flags['da2_act2_fenriel_end']['DefaultValue'], 2)
            self.assertNotIn('da2_act3_bone_pit_dragon', flags)
            for group, (fields, answers) in CASES.items():
                self.assertEqual(tuple(flags[n]['DefaultValue'] for n in fields), answers[self.draft['choices'][group]])
            _, loaded = self.request('/api/profile/' + saved['profile_id'])
            self.assertEqual(loaded['editor_choices'], self.draft['choices'])

    def test_more_act_one_controls_match_keep_layout_art_and_saved_exports(self):
        from test_act1_rescues import CASES
        from test_da2_main_story import flags_from_mod
        _, data = self.request('/api/bootstrap')
        choices = {c['id']: c for c in data['choices']}
        category = next(c for c in data['categories'] if c['id'] == 'da2.act1')
        visible = {c['id'] for c in data['choices'] if c['category_id'] == 'da2.act1'}
        self.assertEqual(len(visible), 14)
        tiles = [tile for block in category['tile_blocks'] for tile in block]
        self.assertEqual({tile['choice_id'] for tile in tiles}, visible)
        self.assertEqual([tile['choice_id'] for tile in tiles],
            ['da2.act1_templars', 'da2.saemus_rescue', 'da2.ginnis_fate', 'da2.ghyslain_truth',
             'da2.thrask_blackmail', 'da2.feynriel_destination', 'da2.ketojan_fate', 'da2.martin_cargo', 'da2.kelder_fate', 'da2.danzig_fate',
             'da2.bone_pit_miners', 'da2.idunna_fate', 'da2.keran_templars', 'da2.karras_fate'])
        self.assertEqual(len(category['tile_blocks']), 12)
        pair = category['tile_blocks'][1]
        self.assertEqual([tile['choice_id'] for tile in pair], ['da2.saemus_rescue', 'da2.ginnis_fate'])
        self.assertEqual([(tile['x'], tile['y'], tile['width'], tile['height']) for tile in pair], [(0, 0, 1, 2), (1, 0, 1, 2)])
        da2_categories = [c['id'] for c in data['categories'] if c['game'] == 'da2']
        self.assertEqual(da2_categories, ['da2.hero', 'da2.companions', 'da2.prologue', 'da2.act1', 'da2.act2', 'da2.act3', 'da2.legacy'])
        for group, (_, answers) in CASES.items():
            choice = choices[group]
            self.assertEqual(choice['category_id'], 'da2.act1')
            self.assertEqual(choice['quick_kind'], 'select' if group in ('da2.ghyslain_truth', 'da2.ketojan_fate') else 'checkbox')
            self.assertEqual(len(choice['answers']), len(answers))
            for answer in choice['answers']:
                status, image = self.request(answer['art'], authorized=False, json_response=False)
                self.assertEqual(status, 200)
                self.assertTrue(image.startswith(b'\xff\xd8'))
        for index in range(3):
            self.draft['choices'] = {group: list(answers)[index % len(answers)] for group, (_, answers) in CASES.items()}
            self.draft['choices'].update({'da2.feynriel_fate': 'possessed', 'da2.final_allegiance': 'templars',
                'da2.hawke_identity': 'female_mage', 'da2.bethany_fate': 'warden', 'da2.carver_fate': 'warden',
                'da2.bone_pit_dragon': 'killed', 'da2.feynriel_destination': 'dalish', 'da2.act1_templars': 'persuaded',
                'da2.danzig_fate': 'not_killed', 'da2.idunna_fate': 'killed'})
            _, preview = self.request('/api/preview', self.draft)
            self.assertTrue(preview['can_export'])
            _, saved = self.request('/api/save', self.draft)
            status, exported = self.request('/api/export', {'profile_id': saved['profile_id'], 'revision': saved['revision'],
                'filename': 'Act I history.fbmod', 'title': 'Act I history'})
            self.assertEqual(status, 200)
            flags = flags_from_mod(Path(exported['path']).read_bytes())
            self.assertEqual(flags['da2_act2_fenriel_end']['DefaultValue'], 2)
            self.assertNotIn('da2_act3_bone_pit_dragon', flags)
            for group, (fields, answers) in CASES.items():
                self.assertEqual(tuple(flags[n]['DefaultValue'] for n in fields), answers[self.draft['choices'][group]])
            _, loaded = self.request('/api/profile/' + saved['profile_id'])
            self.assertEqual(loaded['editor_choices'], self.draft['choices'])

    def test_remaining_act_one_controls_match_keep_layout_art_and_saved_exports(self):
        from test_act1_remaining import CASES
        from test_da2_main_story import flags_from_mod
        _, data = self.request('/api/bootstrap')
        choices = {c['id']: c for c in data['choices']}
        category = next(c for c in data['categories'] if c['id'] == 'da2.act1')
        visible = {c['id'] for c in data['choices'] if c['category_id'] == 'da2.act1'}
        self.assertEqual(len(visible), 14)
        tiles = [tile for block in category['tile_blocks'] for tile in block]
        self.assertEqual({tile['choice_id'] for tile in tiles}, visible)
        self.assertEqual([tile['choice_id'] for tile in tiles],
            ['da2.act1_templars', 'da2.saemus_rescue', 'da2.ginnis_fate', 'da2.ghyslain_truth',
             'da2.thrask_blackmail', 'da2.feynriel_destination', 'da2.ketojan_fate', 'da2.martin_cargo', 'da2.kelder_fate', 'da2.danzig_fate',
             'da2.bone_pit_miners', 'da2.idunna_fate', 'da2.keran_templars', 'da2.karras_fate'])
        self.assertEqual(len(category['tile_blocks']), 12)
        pair = category['tile_blocks'][1]
        self.assertEqual([tile['choice_id'] for tile in pair], ['da2.saemus_rescue', 'da2.ginnis_fate'])
        self.assertEqual([(tile['x'], tile['y'], tile['width'], tile['height']) for tile in pair], [(0, 0, 1, 2), (1, 0, 1, 2)])
        stack = category['tile_blocks'][6]
        self.assertEqual([tile['choice_id'] for tile in stack], ['da2.martin_cargo', 'da2.kelder_fate'])
        self.assertEqual([(tile['x'], tile['y'], tile['width'], tile['height']) for tile in stack], [(0, 0, 2, 1), (0, 1, 2, 1)])
        da2_categories = [c['id'] for c in data['categories'] if c['game'] == 'da2']
        self.assertEqual(da2_categories, ['da2.hero', 'da2.companions', 'da2.prologue', 'da2.act1', 'da2.act2', 'da2.act3', 'da2.legacy'])
        for group, (_, answers) in CASES.items():
            choice = choices[group]
            self.assertEqual(choice['category_id'], 'da2.act1')
            self.assertEqual(choice['quick_kind'], 'select' if group in ('da2.keran_templars',) else 'checkbox')
            self.assertEqual(len(choice['answers']), len(answers))
            for answer in choice['answers']:
                status, image = self.request(answer['art'], authorized=False, json_response=False)
                self.assertEqual(status, 200)
                self.assertTrue(image.startswith(b'\xff\xd8'))
        for index in range(3):
            self.draft['choices'] = {group: list(answers)[index % len(answers)] for group, (_, answers) in CASES.items()}
            self.draft['choices'].update({'da2.feynriel_fate': 'possessed', 'da2.final_allegiance': 'templars',
                'da2.hawke_identity': 'female_mage', 'da2.bethany_fate': 'warden', 'da2.carver_fate': 'warden',
                'da2.bone_pit_dragon': 'killed', 'da2.feynriel_destination': 'dalish', 'da2.act1_templars': 'persuaded',
                'da2.danzig_fate': 'not_killed', 'da2.idunna_fate': 'killed',
                'da2.keran_fate': ('released', 'killed', 'templars')[index], 'da2.hubert_caravans': 'discovered'})
            _, preview = self.request('/api/preview', self.draft)
            self.assertTrue(preview['can_export'])
            _, saved = self.request('/api/save', self.draft)
            status, exported = self.request('/api/export', {'profile_id': saved['profile_id'], 'revision': saved['revision'],
                'filename': 'Act I history.fbmod', 'title': 'Act I history'})
            self.assertEqual(status, 200)
            flags = flags_from_mod(Path(exported['path']).read_bytes())
            self.assertEqual(flags['da2_act2_fenriel_end']['DefaultValue'], 2)
            self.assertNotIn('da2_act3_bone_pit_dragon', flags)
            for group, (fields, answers) in CASES.items():
                self.assertEqual(tuple(flags[n]['DefaultValue'] for n in fields), answers[self.draft['choices'][group]])
            _, loaded = self.request('/api/profile/' + saved['profile_id'])
            self.assertEqual(loaded['editor_choices'], self.draft['choices'])

    def test_final_da2_choices_layout_art_ownership_and_saved_exports(self):
        from test_da2_final_choices import CASES
        from test_da2_main_story import flags_from_mod
        _, data = self.request('/api/bootstrap')
        choices = {choice['id']: choice for choice in data['choices']}
        categories = {category['id']: category for category in data['categories']}
        self.assertEqual(categories['da2.prologue']['tile_blocks'][0][0]['choice_id'], 'da2.prologue_allegiance')
        blocks = categories['da2.companions']['tile_blocks']
        self.assertEqual(len(blocks), 16)
        self.assertEqual(sum(map(len, blocks)), 23)
        self.assertEqual(blocks[2][0]['choice_id'], 'da2.bethany_final_battle')
        self.assertEqual([(tile['choice_id'], tile['x']) for tile in blocks[-1]], [('da2.tallis_reaction', 0), ('da2.tallis_kiss', 1)])
        self.assertIn('beyond the original game range', choices['da2.tallis_reaction']['verification_note'])
        self.assertEqual(choices['da2.tallis_reaction']['evidence_status'], 'disputed')
        for group, (_, answers) in CASES.items():
            choice = choices[group]
            self.assertEqual(choice['quick_kind'], 'checkbox' if group == 'da2.tallis_kiss' else 'select')
            for answer in choice['answers']:
                status, raw = self.request(answer['art'], authorized=False, json_response=False)
                self.assertEqual(status, 200)
                self.assertTrue(raw.startswith(b'\xff\xd8'))
        for index in range(3):
            self.draft['choices'] = {group: list(answers)[index % len(answers)] for group, (_, answers) in CASES.items()}
            self.draft['choices'].update({'da2.bethany_fate': 'warden', 'da2.carver_fate': 'warden',
                'da2.hawke_identity': 'female_mage', 'da2.hawke_romance': 'anders', 'da2.final_allegiance': 'mages',
                'da2.bone_pit_dragon': 'killed'})
            _, preview = self.request('/api/preview', self.draft)
            self.assertTrue(preview['can_export'])
            self.assertEqual(preview['resolved_choices']['da2.bethany_fate']['answer_id'], 'warden')
            _, saved = self.request('/api/save', self.draft)
            status, exported = self.request('/api/export', {'profile_id': saved['profile_id'], 'revision': saved['revision'], 'title': 'DA2 complete'})
            self.assertEqual(status, 200)
            flags = flags_from_mod(Path(exported['path']).read_bytes())
            for group, (fields, answers) in CASES.items():
                self.assertEqual(tuple(flags[field]['DefaultValue'] for field in fields), answers[self.draft['choices'][group]])
            self.assertEqual(flags['da2_mark_tallis_angry']['MaxValue'], 2 if index == 2 else 1)
            self.assertNotIn('da2_act3_bone_pit_dragon', flags)
            _, loaded = self.request('/api/profile/' + saved['profile_id'])
            self.assertEqual(loaded['editor_choices'], self.draft['choices'])

    def test_origins_prologue_dog_art_layout_saved_exports_and_da2_overview_pair(self):
        from test_dao_prologue import CASES
        from test_da2_main_story import flags_from_mod
        _, data = self.request('/api/bootstrap')
        choices = {choice['id']: choice for choice in data['choices']}
        categories = {category['id']: category for category in data['categories']}
        self.assertEqual([tile['choice_id'] for block in categories['dao.prologue']['tile_blocks'] for tile in block], ['dao.ostagar_deserter', 'dao.ostagar_mabari'])
        blocks = categories['dao.companions']['tile_blocks']
        self.assertEqual([tile['choice_id'] for tile in blocks[0]], ['dao.warden_romance', 'dao.dog_recruited'])
        self.assertEqual([(tile['y'], tile['width'], tile['height']) for tile in blocks[0]], [(0, 2, 1), (1, 2, 1)])
        self.assertEqual(categories['da2.prologue']['overview_pair'], categories['da2.legacy']['overview_pair'])
        self.assertEqual(categories['da2.legacy']['title'], 'Legacy DLC')
        self.assertEqual(len(categories['da2.legacy']['tile_blocks']), 2)
        for group, (_, answers) in CASES.items():
            self.assertEqual(choices[group]['quick_kind'], 'checkbox' if group == 'dao.dog_recruited' else 'select')
            self.assertEqual(len(choices[group]['answers']), len(answers))
            for answer in choices[group]['answers']:
                status, raw = self.request(answer['art'], authorized=False, json_response=False)
                self.assertEqual(status, 200)
                self.assertTrue(raw.startswith(b'\xff\xd8'))
        for index in range(6):
            self.draft['choices'] = {group: list(answers)[index % len(answers)] for group, (_, answers) in CASES.items()}
            self.draft['choices'].update({'da2.hawke_identity': 'female_mage', 'da2.bethany_fate': 'warden',
                'da2.carver_fate': 'warden', 'da2.bethany_final_battle': 'died', 'da2.tallis_reaction': 'never_met',
                'da2.bone_pit_dragon': 'killed'})
            _, preview = self.request('/api/preview', self.draft)
            self.assertTrue(preview['can_export'])
            _, saved = self.request('/api/save', self.draft)
            status, exported = self.request('/api/export', {'profile_id': saved['profile_id'], 'revision': saved['revision'], 'title': 'Ostagar and Dog'})
            self.assertEqual(status, 200)
            flags = flags_from_mod(Path(exported['path']).read_bytes())
            for group, (fields, answers) in CASES.items():
                self.assertEqual(tuple(flags[field]['DefaultValue'] for field in fields), answers[self.draft['choices'][group]])
            self.assertEqual(flags['dao_pre_mabari_hound']['MaxValue'], 4)
            self.assertEqual(flags['da2_bethany_final_battle_death']['DefaultValue'], 2)
            self.assertEqual(flags['da2_mark_tallis_angry']['MaxValue'], 2)
            _, loaded = self.request('/api/profile/' + saved['profile_id'])
            self.assertEqual(loaded['editor_choices'], self.draft['choices'])

    def test_nature_side_quests_original_layout_art_and_restricted_exports(self):
        from test_nature_side_quests import CASES
        from test_da2_main_story import flags_from_mod
        _, data = self.request('/api/bootstrap')
        choices = {choice['id']: choice for choice in data['choices']}
        category = next(c for c in data['categories'] if c['id'] == 'dao.nature')
        self.assertEqual([tile['choice_id'] for block in category['tile_blocks'] for tile in block],
                         ['dao.nature_outcome', *CASES])
        for group, (_, answers) in CASES.items():
            self.assertEqual(len(choices[group]['answers']), len(answers))
            self.assertEqual(choices[group]['quick_kind'], 'checkbox' if len(answers) == 2 else 'select')
            for answer in choices[group]['answers']:
                status, raw = self.request(answer['art'], authorized=False, json_response=False)
                self.assertEqual(status, 200)
                self.assertTrue(raw.startswith(b'\xff\xd8'))
        self.draft['mode'] = 'keep'
        for index in range(3):
            self.draft['choices'] = {group: list(answers)[index % len(answers)] for group, (_, answers) in CASES.items()}
            self.draft['choices']['dao.dagna_outcome'] = 'not_met'
            self.assertTrue(self.request('/api/preview', self.draft)[1]['can_export'])
            status, saved = self.request('/api/save', self.draft)
            self.assertEqual(status, 200)
            status, exported = self.request('/api/export', dict(profile_id=saved['profile_id'], revision=saved['revision']))
            self.assertEqual(status, 200)
            flags = flags_from_mod(Path(exported['path']).read_bytes())
            for group, (field, answers) in CASES.items():
                self.assertEqual(flags[field]['DefaultValue'], answers[self.draft['choices'][group]])
            reopened = self.request('/api/profile/' + saved['profile_id'])[1]
            self.assertEqual(reopened['editor_choices'], self.draft['choices'])

    def test_redcliffe_layout_art_local_bella_and_bevin_range_export(self):
        from test_redcliffe_village import CASES
        from test_da2_main_story import flags_from_mod
        _, data = self.request('/api/bootstrap')
        choices = {choice['id']: choice for choice in data['choices']}
        category = next(c for c in data['categories'] if c['id'] == 'dao.redcliffe')
        self.assertEqual([t['choice_id'] for b in category['tile_blocks'] for t in b],
            ['dao.redcliffe_defense','dao.redcliffe_preparation','dao.connor_fate','dao.bella_fate','dao.bevin_fate','dao.valena_fate','dao.isolde_fate'])
        for group in [*CASES, 'dao.bella_fate']:
            for answer in choices[group]['answers']:
                status, raw = self.request(answer['art'], authorized=False, json_response=False)
                self.assertEqual(status, 200)
                self.assertTrue(raw.startswith(b'\xff\xd8'))
        self.assertEqual(choices['dao.bella_fate']['export_behavior'], 'profile-only')
        self.assertEqual(choices['dao.bella_fate']['export_note'], 'Not exported to DAI')
        self.assertIn('value 5', choices['dao.bevin_fate']['verification_note'])
        for index, answer in enumerate(CASES['dao.bevin_fate'][1]):
            self.draft['mode'] = 'keep'
            self.draft['choices'] = {'dao.dagna_outcome':'not_met','dao.bevin_fate':answer,'dao.bella_fate':'brewery'}
            self.assertTrue(self.request('/api/preview', self.draft)[1]['can_export'])
            _, saved = self.request('/api/save', self.draft)
            status, exported = self.request('/api/export', dict(profile_id=saved['profile_id'],revision=saved['revision']))
            self.assertEqual(status, 200)
            flags = flags_from_mod(Path(exported['path']).read_bytes())
            self.assertEqual(flags['dao_red_missing_child']['DefaultValue'], index)
            self.assertEqual(flags['dao_red_missing_child']['MaxValue'], 5 if index == 5 else 4)
            self.assertNotIn('dao_red_bella_tavern', flags)
            reopened = self.request('/api/profile/' + saved['profile_id'])[1]
            self.assertEqual(reopened['editor_choices']['dao.bella_fate'], 'brewery')

    def test_orzammar_side_quests_original_layout_art_and_restricted_exports(self):
        from test_orzammar_side_quests import CASES
        from test_da2_main_story import flags_from_mod
        _, data = self.request('/api/bootstrap')
        choices = {choice['id']: choice for choice in data['choices']}
        category = next(c for c in data['categories'] if c['id'] == 'dao.paragon')
        self.assertEqual([t['choice_id'] for b in category['tile_blocks'] for t in b if t['choice_id'] in {*CASES,'dao.anvil_fate','dao.orzammar_ruler','dao.dagna_outcome'}],
            ['dao.anvil_fate','dao.orzammar_ruler','dao.filda_ruck','dao.burkel_chantry','dao.zerlinda_fate','dao.orta_ancestry','dao.dagna_outcome'])
        self.assertEqual(len(category['tile_blocks']), 9)
        self.assertEqual([(t['y'],t['height']) for t in category['tile_blocks'][3]], [(0,1),(1,1)])
        for group in CASES:
            for answer in choices[group]['answers']:
                status, raw = self.request(answer['art'], authorized=False, json_response=False)
                self.assertEqual(status, 200)
                self.assertTrue(raw.startswith(b'\xff\xd8'))
        self.assertIn('unconfirmed', choices['dao.zerlinda_fate']['verification_note'])
        for values in [(0,0,0,0),(1,1,1,1),(2,0,2,0),(3,1,3,1),(4,0,4,0),(5,1,0,1)]:
            self.draft['mode'] = 'keep'
            self.draft['choices'] = {'dao.dagna_outcome':'not_met'}
            self.draft['choices'].update({g:next(a for a,n in answers.items() if n==v) for (g,(f,answers)),v in zip(CASES.items(),values)})
            self.assertTrue(self.request('/api/preview', self.draft)[1]['can_export'])
            _, saved = self.request('/api/save', self.draft)
            status, exported = self.request('/api/export', dict(profile_id=saved['profile_id'],revision=saved['revision']))
            self.assertEqual(status, 200)
            flags = flags_from_mod(Path(exported['path']).read_bytes())
            for (group,(field,answers)),value in zip(CASES.items(),values):
                self.assertEqual(flags[field]['DefaultValue'], value)
                self.assertEqual(flags[field]['MaxValue'],5 if group=='dao.filda_ruck' else 4 if group=='dao.zerlinda_fate' and value>1 else 1)
            reopened = self.request('/api/profile/' + saved['profile_id'])[1]
            self.assertEqual(reopened['editor_choices'], self.draft['choices'])

    def test_remaining_paragon_complete_layout_art_and_all_answer_exports(self):
        from test_remaining_paragon import CASES
        from test_da2_main_story import flags_from_mod
        _, data = self.request('/api/bootstrap')
        choices = {choice['id']: choice for choice in data['choices']}
        category = next(c for c in data['categories'] if c['id'] == 'dao.paragon')
        self.assertEqual([t['choice_id'] for b in category['tile_blocks'] for t in b],
            ['dao.anvil_fate','dao.orzammar_ruler','dao.filda_ruck','dao.burkel_chantry','dao.zerlinda_fate','dao.orta_ancestry','dao.dagna_outcome',
             'dao.mardy_relationship','dao.mardy_son','dao.legion_noble_house','dao.shaperate_tome','dao.rogek_lyrium'])
        self.assertEqual(len(category['tile_blocks']), 9)
        self.assertEqual([(t['x'],t['width'],t['height']) for t in category['tile_blocks'][6]], [(0,1,2),(1,1,2)])
        self.assertEqual([(t['y'],t['width'],t['height']) for t in category['tile_blocks'][7]], [(0,2,1),(1,2,1)])
        for group in CASES:
            for answer in choices[group]['answers']:
                status, raw = self.request(answer['art'], authorized=False, json_response=False)
                self.assertEqual(status, 200); self.assertTrue(raw.startswith(b'\xff\xd8'))
        self.assertIn('unconfirmed', choices['dao.mardy_son']['verification_note'])
        for values in [(0,0,0,0,0),(1,0,1,1,1),(2,1,0,2,0),(2,2,1,0,1),(2,3,0,1,0)]:
            self.draft['mode'] = 'keep'
            self.draft['choices'] = {'dao.dagna_outcome':'not_met','dao.warden_identity':'male_dwarf_noble'}
            self.draft['choices'].update({g:next(a for a,n in answers.items() if n==v) for (g,(f,answers)),v in zip(CASES.items(),values)})
            self.assertTrue(self.request('/api/preview', self.draft)[1]['can_export'])
            _, saved = self.request('/api/save', self.draft)
            status, exported = self.request('/api/export', dict(profile_id=saved['profile_id'],revision=saved['revision']))
            self.assertEqual(status, 200)
            flags = flags_from_mod(Path(exported['path']).read_bytes())
            for (group,(field,answers)),value in zip(CASES.items(),values):
                self.assertEqual(flags[field]['DefaultValue'], value)
                self.assertEqual(flags[field]['MaxValue'],3 if group=='dao.mardy_son' and value==3 else 1 if group in ('dao.legion_noble_house','dao.rogek_lyrium') else 2)
            reopened = self.request('/api/profile/' + saved['profile_id'])[1]
            self.assertEqual(reopened['editor_choices'], self.draft['choices'])

    def test_companion_caption_names_and_sten_mode_aware_transactional_links(self):
        _, data = self.request('/api/bootstrap')
        choices = {choice['id']: choice for choice in data['choices']}
        self.assertEqual(next(a for a in choices['dao.zevran_fate']['answers'] if a['id']=='alive')['title'], 'Zevran alive and well')
        self.assertEqual(next(a for a in choices['dao.sten_sword']['answers'] if a['id']=='not_recruited')['title'], 'Didn’t recruit Sten')
        self.draft['mode']='keep'
        self.draft['choices']={'dao.dagna_outcome':'not_met','dao.sten_recruited':'recruited','dao.sten_release':'persuaded','dao.sten_sword':'returned'}
        _, saved=self.request('/api/save',self.draft)
        for key in ('profile_id','revision'):self.draft[key]=saved[key]
        for key in ('dao.sten_sword','dao.sten_recruited'):
            _, response=self.request('/api/propose',dict(draft=self.draft,updates={key:'not_recruited'},mode='keep'))
            self.assertEqual(response['draft']['choices']['dao.sten_recruited'],'not_recruited')
            self.assertEqual(response['draft']['choices']['dao.sten_sword'],'not_recruited')
            other='dao.sten_recruited' if key=='dao.sten_sword' else 'dao.sten_sword'
            self.assertEqual([c['choice_id'] for c in response['changes']],[other])
            reopened=self.request('/api/profile/'+saved['profile_id'])[1]
            self.assertEqual(reopened['editor_choices'],self.draft['choices'])
        inconsistent=dict(self.draft,choices=dict(self.draft['choices'],**{'dao.sten_sword':'not_recruited'}))
        self.assertFalse(self.request('/api/preview',inconsistent)[1]['can_export'])
        _, response=self.request('/api/propose',dict(draft=self.draft,updates={'dao.sten_sword':'not_recruited'},mode='experimental'))
        self.assertEqual(response['changes'],[])
        self.assertEqual(response['draft']['choices']['dao.sten_recruited'],'recruited')
        self.assertTrue(self.request('/api/preview',response['draft'])[1]['can_export'])

    def test_denerim_side_quests_original_layout_local_art_and_restricted_export(self):
        from test_denerim_side_quests import CASES
        from test_da2_main_story import flags_from_mod
        _, data=self.request('/api/bootstrap')
        choices={choice['id']:choice for choice in data['choices']}
        category=next(c for c in data['categories'] if c['id']=='dao.denerim_quests')
        self.assertEqual([t['choice_id'] for b in category['tile_blocks'] for t in b if t['choice_id'] in CASES],
            ['dao.landry_fate','dao.oswyn_sighard','dao.irminric_ring','dao.beggar_amulet','dao.justine_scroll'])
        self.assertEqual(len(category['tile_blocks']),8)
        self.assertEqual([(t['y'],t['width'],t['height']) for t in category['tile_blocks'][0]],[(0,2,1),(1,2,1)])
        self.assertEqual([(t['x'],t['width'],t['height']) for t in category['tile_blocks'][2]],[(0,1,2),(1,1,2)])
        self.assertEqual(choices['dao.archdemon_killer']['category_id'],'dao.denerim')
        for group in CASES:
            for answer in choices[group]['answers']:
                status,raw=self.request(answer['art'],authorized=False,json_response=False)
                self.assertEqual(status,200);self.assertTrue(raw.startswith(b'\xff\xd8'))
        for value in (0,1):
            self.draft['mode']='keep'
            self.draft['choices']={'dao.dagna_outcome':'not_met',**{g:next(a for a,n in answers.items() if n==value) for g,(f,answers) in CASES.items()}}
            self.assertTrue(self.request('/api/preview',self.draft)[1]['can_export'])
            _,saved=self.request('/api/save',self.draft)
            status,exported=self.request('/api/export',dict(profile_id=saved['profile_id'],revision=saved['revision']))
            self.assertEqual(status,200)
            flags=flags_from_mod(Path(exported['path']).read_bytes())
            for field,answers in CASES.values():
                self.assertEqual(flags[field]['DefaultValue'],value)
                self.assertEqual(flags[field]['MaxValue'],1)
            reopened=self.request('/api/profile/'+saved['profile_id'])[1]
            self.assertEqual(reopened['editor_choices'],self.draft['choices'])

    def test_remaining_denerim_complete_layout_local_history_art_and_exports(self):
        from test_remaining_denerim import CASES,LOCAL
        from test_da2_main_story import flags_from_mod
        _,data=self.request('/api/bootstrap')
        choices={c['id']:c for c in data['choices']}
        category=next(c for c in data['categories'] if c['id']=='dao.denerim_quests')
        self.assertEqual([t['choice_id'] for b in category['tile_blocks'] for t in b],
            ['dao.landry_fate','dao.oswyn_sighard','dao.slim_couldry','dao.irminric_ring','dao.beggar_amulet','dao.alistair_family',
             'dao.justine_scroll','dao.kylon_falcons','dao.kylon_crimson_oars','dao.ignacio_fate','dao.leliana_past'])
        self.assertEqual(len(category['tile_blocks']),8)
        for group in [*CASES,*LOCAL]:
            for answer in choices[group]['answers']:
                status,raw=self.request(answer['art'],authorized=False,json_response=False)
                self.assertEqual(status,200);self.assertTrue(raw.startswith(b'\xff\xd8'))
        for group in LOCAL:
            self.assertEqual(choices[group]['export_behavior'],'profile-only')
            self.assertEqual(choices[group]['export_note'],'Not exported to DAI')
        self.assertIn('unconfirmed',choices['dao.ignacio_fate']['verification_note'])
        for values,family,past in [((0,0,0,0),'not_encountered','not_encountered'),((1,1,1,1),'helped','sent_away'),((0,1,0,2),'not_helped','killed')]:
            self.draft['mode']='keep'
            self.draft['choices']={'dao.dagna_outcome':'not_met','dao.alistair_family':family,'dao.leliana_past':past,
                **{g:next(a for a,n in answers.items() if n==v) for (g,(f,answers)),v in zip(CASES.items(),values)}}
            self.assertTrue(self.request('/api/preview',self.draft)[1]['can_export'])
            _,saved=self.request('/api/save',self.draft)
            status,exported=self.request('/api/export',dict(profile_id=saved['profile_id'],revision=saved['revision']))
            self.assertEqual(status,200)
            flags=flags_from_mod(Path(exported['path']).read_bytes())
            for (field,answers),value in zip(CASES.values(),values):
                self.assertEqual(flags[field]['DefaultValue'],value);self.assertEqual(flags[field]['MaxValue'],2 if value==2 else 1)
            self.assertNotIn('dao_den_alistairs_family',flags);self.assertNotIn('dao_den_lelianas_past',flags)
            reopened=self.request('/api/profile/'+saved['profile_id'])[1]
            self.assertEqual(reopened['editor_choices'],self.draft['choices'])

    def test_remaining_origins_companions_art_layout_wynne_ownership_and_exports(self):
        from test_da2_main_story import flags_from_mod
        _,data=self.request('/api/bootstrap');choices={c['id']:c for c in data['choices']}
        category=next(c for c in data['categories'] if c['id']=='dao.companions')
        self.assertEqual([t['choice_id'] for b in category['tile_blocks'] for t in b],
            ['dao.warden_romance','dao.dog_recruited','dao.sten_release','dao.sten_recruited','dao.sten_sword','dao.wynne_recruited',
             'dao.wynne_fate','dao.morrigan_child','dao.loghain_fate','dao.oghren_recruited','dao.zevran_recruited','dao.zevran_fate',
             'dao.alistair_fate','dao.alistair_relationship','dao.leliana_fate','dao.flemeth_grimoire'])
        self.assertEqual(len(category['tile_blocks']),12)
        for group in ('dao.wynne_recruited','dao.oghren_recruited','dao.flemeth_grimoire'):
            for answer in choices[group]['answers']:
                status,raw=self.request(answer['art'],authorized=False,json_response=False)
                self.assertEqual(status,200);self.assertTrue(raw.startswith(b'\xff\xd8'))
        self.assertEqual(choices['dao.flemeth_grimoire']['export_note'],'Not exported to DAI')
        self.assertEqual(choices['dao.flemeth_grimoire']['custom_answer_label'],'Not selected')
        for fate,value,recruit,oghren,grimoire in [('not_recruited',0,'not_recruited','not_recruited','not_acquired'),('alive',1,'recruited','recruited','peaceful'),('killed_at_urn',3,'recruited','not_recruited','defeated_flemeth'),('died_at_circle',2,'not_recruited','recruited','not_acquired')]:
            self.draft['mode']='keep';self.draft['choices']={'dao.dagna_outcome':'not_met','dao.urn_poisoned':'poisoned','dao.wynne_fate':fate,'dao.wynne_recruited':recruit,'dao.oghren_recruited':oghren,'dao.flemeth_grimoire':grimoire}
            self.assertTrue(self.request('/api/preview',self.draft)[1]['can_export'])
            _,saved=self.request('/api/save',self.draft)
            status,exported=self.request('/api/export',dict(profile_id=saved['profile_id'],revision=saved['revision']));self.assertEqual(status,200)
            flags=flags_from_mod(Path(exported['path']).read_bytes())
            self.assertEqual(flags['dao_wynne_fate']['DefaultValue'],value)
            self.assertEqual(flags['dao_wynne_recruited']['DefaultValue'],int(recruit=='recruited'))
            self.assertEqual(flags['dao_oghren_recruited']['DefaultValue'],int(oghren=='recruited'))
            self.assertNotIn('dao_flemeth_grimoire',flags)
            self.assertEqual(self.request('/api/profile/'+saved['profile_id'])[1]['editor_choices'],self.draft['choices'])

    def test_broken_circle_completion_and_original_origins_overview(self):
        from test_da2_main_story import flags_from_mod
        _,data=self.request('/api/bootstrap');choices={c['id']:c for c in data['choices']};categories={c['id']:c for c in data['categories']}
        self.assertEqual([t['choice_id'] for b in categories['dao.circle']['tile_blocks'] for t in b],['dao.broken_circle','dao.irving_fate','dao.cullen_request'])
        self.assertNotIn('display',choices['dao.irving_fate']);self.assertEqual(choices['dao.urn_poisoned']['category_id'],'dao.urn')
        self.assertEqual(categories['dao.companions']['overview_tile']['width'],2)
        self.assertTrue(categories['dao.companions']['art'].endswith('morrigan_detail.jpg'))
        self.assertTrue(categories['dao.redcliffe']['art'].endswith('yes_top_1x2.jpg'))
        self.assertEqual([(categories[k]['overview_tile']['x'],categories[k]['overview_tile']['y'],categories[k]['overview_tile']['width'],categories[k]['overview_tile']['height']) for k in ('dao.prologue','dao.urn','dao.redcliffe')],[(0,0,1,1),(0,1,1,1),(1,0,1,2)])
        self.assertEqual([(categories[k]['overview_tile']['x'],categories[k]['overview_tile']['y'],categories[k]['overview_tile']['width'],categories[k]['overview_tile']['height']) for k in ('dao.circle','dao.denerim_quests','dao.landsmeet')],[(0,0,1,2),(1,0,1,1),(1,1,1,1)])
        for group in ('dao.irving_fate','dao.cullen_request','dao.urn_poisoned'):
            for answer in choices[group]['answers']:
                status,raw=self.request(answer['art'],authorized=False,json_response=False);self.assertEqual(status,200);self.assertTrue(raw.startswith(b'\xff\xd8'))
        for answer,value in [('disagreed',0),('agreed',1)]:
            self.draft['mode']='keep';self.draft['choices']={'dao.dagna_outcome':'not_met','dao.connor_fate':'dead','dao.cullen_request':answer,'dao.irving_fate':'dead' if value else 'alive','dao.broken_circle':'templars' if value else 'mages','dao.wynne_fate':'died_at_circle' if value else 'alive','dao.wynne_recruited':'not_recruited' if value else 'recruited'}
            self.assertTrue(self.request('/api/preview',self.draft)[1]['can_export'])
            _,saved=self.request('/api/save',self.draft);status,exported=self.request('/api/export',dict(profile_id=saved['profile_id'],revision=saved['revision']));self.assertEqual(status,200)
            flags=flags_from_mod(Path(exported['path']).read_bytes());self.assertEqual(flags['dao_bc_irving_survive']['DefaultValue'],1-value);self.assertEqual(flags['dao_wynne_recruited']['DefaultValue'],1-value)
            self.assertNotIn('dao_broken_circle_cullen_request',flags)
            self.assertEqual(self.request('/api/profile/'+saved['profile_id'])[1]['editor_choices'],self.draft['choices'])

    def test_awakening_category_artwork_local_history_and_saved_exports(self):
        from test_da2_main_story import flags_from_mod
        _,data=self.request('/api/bootstrap');choices={c['id']:c for c in data['choices']};categories={c['id']:c for c in data['categories']}
        order=['dao.architect_fate','dao.awakening_protection','dao.nathaniel_fate','dao.oghren_felsi']
        category=categories['dao.awakening']
        self.assertEqual([t['choice_id'] for b in category['tile_blocks'] for t in b],order)
        self.assertEqual(category['overview_tile'],dict(block='origins-3',x=0,y=0,width=2,height=2))
        self.assertEqual([c['id'] for c in data['categories']][5],'dao.awakening')
        self.assertNotIn('display',choices['dao.nathaniel_fate'])
        self.assertEqual(choices['dao.nathaniel_fate']['category_id'],'dao.awakening')
        for key in order:
            self.assertEqual(choices[key]['quick_kind'],'select')
            for answer in choices[key]['answers']:
                status,raw=self.request(answer['art'],authorized=False,json_response=False);self.assertEqual(status,200);self.assertTrue(raw.startswith(b'\xff\xd8'))
        for key in ('dao.awakening_protection','dao.oghren_felsi'):
            self.assertEqual(choices[key]['export_note'],'Not exported to DAI');self.assertEqual(choices[key]['custom_answer_label'],'Not selected')
        cases=[('killed','dead','keep','not_helped'),('spared','alive','amaranthine','reunited'),('spared','alive','both','parted')]
        payloads=[]
        for architect,nathaniel,protection,felsi in cases:
            self.draft['mode']='keep';self.draft['choices']={'dao.dagna_outcome':'not_met','dao.oghren_recruited':'recruited','dao.architect_fate':architect,'dao.nathaniel_fate':nathaniel,'dao.awakening_protection':protection,'dao.oghren_felsi':felsi,'da2.finding_nathaniel':'rescued' if nathaniel=='alive' else 'not_survived'}
            self.assertTrue(self.request('/api/preview',self.draft)[1]['can_export'])
            _,saved=self.request('/api/save',self.draft);status,exported=self.request('/api/export',dict(profile_id=saved['profile_id'],revision=saved['revision']));self.assertEqual(status,200)
            raw=Path(exported['path']).read_bytes();flags=flags_from_mod(raw);payloads.append(read_mod(raw)['ebx'])
            self.assertEqual(flags['dao_awakenings_architect_fate']['DefaultValue'],int(architect=='spared'));self.assertEqual(flags['dao_awakenings_nathaniel_live']['DefaultValue'],int(nathaniel=='alive'))
            for field in ('dao_awakenings_architect_fate','dao_awakenings_nathaniel_live'):
                self.assertEqual((flags[field]['MinValue'],flags[field]['MaxValue']),(0,1))
            self.assertNotIn('dao_awakening_keep_protected',flags);self.assertNotIn('dao_awakening_oghren_felsi',flags)
            self.assertEqual(self.request('/api/profile/'+saved['profile_id'])[1]['editor_choices'],self.draft['choices'])
        self.assertEqual(payloads[1],payloads[2])

    def test_wardens_keep_artwork_profile_only_answers_and_unchanged_exports(self):
        from itertools import product
        _,data=self.request('/api/bootstrap');choices={c['id']:c for c in data['choices']};categories={c['id']:c for c in data['categories']}
        category=categories['dao.wardens_keep'];order=['dao.power_of_blood','dao.avernus_fate']
        self.assertEqual([t['choice_id'] for b in category['tile_blocks'] for t in b],order)
        self.assertEqual(category['overview_tile'],dict(block='origins-dlc',x=0,y=1,width=1,height=1))
        for key in order:
            self.assertEqual(choices[key]['export_behavior'],'profile-only');self.assertEqual(choices[key]['export_note'],'Not exported to DAI')
            self.assertEqual(choices[key]['custom_answer_label'],'Not selected');self.assertEqual(choices[key]['quick_kind'],'select')
            for answer in choices[key]['answers']:
                status,raw=self.request(answer['art'],authorized=False,json_response=False);self.assertEqual(status,200);self.assertTrue(raw.startswith(b'\xff\xd8'))
        baseline=None
        for blood,avernus in product(('drank','did_not_drink'),('both_perished','sided_sophia','unrestricted_research','ethical_research')):
            self.draft['mode']='keep';self.draft['choices']={'dao.dagna_outcome':'not_met','dao.power_of_blood':blood,'dao.avernus_fate':avernus}
            self.assertTrue(self.request('/api/preview',self.draft)[1]['can_export'])
            _,saved=self.request('/api/save',self.draft);status,exported=self.request('/api/export',dict(profile_id=saved['profile_id'],revision=saved['revision']));self.assertEqual(status,200)
            payload=read_mod(Path(exported['path']).read_bytes())['ebx']
            if baseline is None:baseline=payload
            else:self.assertEqual(payload,baseline)
            report=json.loads(Path(exported['report_path']).read_text(encoding='utf8'))
            for key,answer in [('dao.power_of_blood',blood),('dao.avernus_fate',avernus)]:self.assertEqual(report['profile']['resolved_choices'][key]['answer_id'],answer)
            self.assertEqual(self.request('/api/profile/'+saved['profile_id'])[1]['editor_choices'],self.draft['choices'])

    def test_stone_prisoner_artwork_rules_and_saved_exports(self):
        from test_da2_main_story import flags_from_mod
        _,data=self.request('/api/bootstrap');choices={c['id']:c for c in data['choices']};categories={c['id']:c for c in data['categories']}
        category=categories['dao.stone_prisoner'];order=['dao.shale_fate','dao.kitty_amalia','dao.shale_recruited']
        self.assertEqual([t['choice_id'] for b in category['tile_blocks'] for t in b],order)
        self.assertEqual(choices['dao.shale_recruited']['checked_answer'],'recruited');self.assertEqual(choices['dao.shale_recruited']['unchecked_answer'],'not_recruited')
        self.assertEqual(choices['dao.shale_recruited']['quick_kind'],'checkbox')
        for key in order:
            for answer in choices[key]['answers']:
                status,raw=self.request(answer['art'],authorized=False,json_response=False);self.assertEqual(status,200);self.assertTrue(raw.startswith(b'\xff\xd8'))
        self.assertEqual(choices['dao.kitty_amalia']['export_note'],'Not exported to DAI');self.assertEqual(choices['dao.kitty_amalia']['custom_answer_label'],'Not selected')
        cases=[('not_recruited','not_recruited','warden_destroyed','both_unpossessed'),('alive','recruited','warden_destroyed','amalia_possessed'),('died_with_branka','recruited','branka_destroyed','matthias_possessed'),('died_with_branka','recruited','preserved','matthias_dead'),('died_with_branka','recruited','preserved','amalia_dead')]
        payloads=[]
        for fate,recruit,anvil,kitty in cases:
            self.draft['mode']='keep';self.draft['choices']={'dao.dagna_outcome':'not_met','dao.shale_fate':fate,'dao.shale_recruited':recruit,'dao.anvil_fate':anvil,'dao.kitty_amalia':kitty}
            self.assertTrue(self.request('/api/preview',self.draft)[1]['can_export'])
            _,saved=self.request('/api/save',self.draft);status,exported=self.request('/api/export',dict(profile_id=saved['profile_id'],revision=saved['revision']));self.assertEqual(status,200)
            raw=Path(exported['path']).read_bytes();flags=flags_from_mod(raw);payloads.append(read_mod(raw)['ebx'])
            self.assertEqual(flags['dao_shale_fate']['DefaultValue'],['not_recruited','alive','died_with_branka'].index(fate))
            self.assertEqual(flags['dao_shale_recruited']['DefaultValue'],int(recruit=='recruited'))
            self.assertEqual(flags['dao_paragon_anvil_fate']['DefaultValue'],['warden_destroyed','branka_destroyed','preserved'].index(anvil))
            for field,maximum in [('dao_shale_fate',2),('dao_shale_recruited',1)]:self.assertEqual((flags[field]['MinValue'],flags[field]['MaxValue']),(0,maximum))
            self.assertNotIn('dao_stone_prisoner_kitty',flags)
            self.assertEqual(self.request('/api/profile/'+saved['profile_id'])[1]['editor_choices'],self.draft['choices'])
        self.assertEqual(payloads[3],payloads[4])

    def test_witch_hunt_answers_range_note_and_completed_dlc_overview(self):
        from test_da2_main_story import flags_from_mod
        _,data=self.request('/api/bootstrap');choices={c['id']:c for c in data['choices']};categories={c['id']:c for c in data['categories']}
        category=categories['dao.witch_hunt'];choice=choices['dao.witch_hunt']
        self.assertEqual([t['choice_id'] for b in category['tile_blocks'] for t in b],['dao.witch_hunt'])
        for key,xywh in [('dao.witch_hunt',(0,0,2,1)),('dao.wardens_keep',(0,1,1,1)),('dao.stone_prisoner',(1,1,1,1))]:
            tile=categories[key]['overview_tile'];self.assertEqual(tile['block'],'origins-dlc');self.assertEqual(tuple(tile[k] for k in ('x','y','width','height')),xywh)
            status,raw=self.request(categories[key]['art'],authorized=False,json_response=False);self.assertEqual(status,200);self.assertTrue(raw.startswith(b'\xff\xd8'))
        self.assertEqual(choice['quick_kind'],'select');self.assertIn('value 2',choice['verification_note']);self.assertIn('unconfirmed',choice['verification_note'])
        for answer in choice['answers']:
            status,raw=self.request(answer['art'],authorized=False,json_response=False);self.assertEqual(status,200);self.assertTrue(raw.startswith(b'\xff\xd8'))
        for value,answer in enumerate(('did_not_follow','followed','stabbed')):
            self.draft['mode']='keep';self.draft['choices']={'dao.dagna_outcome':'not_met','dao.warden_identity':'male_human_noble','dao.warden_romance':'morrigan','dao.warden_fate':'alive','dao.witch_hunt':answer}
            self.assertTrue(self.request('/api/preview',self.draft)[1]['can_export'])
            _,saved=self.request('/api/save',self.draft);status,exported=self.request('/api/export',dict(profile_id=saved['profile_id'],revision=saved['revision']));self.assertEqual(status,200)
            flags=flags_from_mod(Path(exported['path']).read_bytes());field=flags['dao_warden_eluvian']
            self.assertEqual(field['DefaultValue'],value);self.assertEqual((field['MinValue'],field['MaxValue']),(0,2 if value==2 else 1))
            self.assertEqual(field['PlotFlag']['PlotFlagId']['Guid'],'67824ec6-f5b1-46a3-8ba9-a35724f5015c')
            self.assertEqual(self.request('/api/profile/'+saved['profile_id'])[1]['editor_choices'],self.draft['choices'])

    def test_grouped_fenris_controls_and_keep_layout_are_available_offline(self):
        _, data = self.request('/api/bootstrap')
        categories = {category['id']: category for category in data['categories']}
        self.assertNotIn('da2.family', categories)
        choices = {choice['id']: choice for choice in data['choices']}
        self.assertEqual(choices['da2.bethany_fate']['category_id'], 'da2.companions')
        self.assertEqual(choices['da2.carver_fate']['category_id'], 'da2.companions')
        self.assertEqual(choices['da2.fenris_recruited']['display'], 'quick-only')
        self.assertEqual(choices['da2.fenris_danarius']['display'], 'quick-only')
        answer = next(answer for answer in choices['da2.fenris_fate']['answers'] if answer['id'] == 'not_recruited')
        self.assertEqual(answer['related_choices'], {'da2.fenris_recruited': 'not_recruited', 'da2.fenris_danarius': 'not_recruited'})
        status, script = self.request('/choice-controls.js', authorized=False, json_response=False)
        self.assertEqual(status, 200)
        self.assertIn(b'currentAnswer', script)
        self.assertTrue(categories['da2.companions']['tile_blocks'])

    def test_finale_choices_have_local_art_and_morrigan_verification_note(self):
        _, data = self.request('/api/bootstrap')
        choices = {choice['id']: choice for choice in data['choices']}
        self.assertEqual(choices['dao.warden_fate']['category_id'], 'dao.hero')
        self.assertEqual(choices['dao.archdemon_killer']['category_id'], 'dao.denerim')
        self.assertEqual(choices['dao.morrigan_child']['category_id'], 'dao.companions')
        self.assertNotIn('dao.ritual', {category['id'] for category in data['categories']})
        self.assertIn('needs verification', choices['dao.morrigan_child']['verification_note'])
        self.assertEqual(choices['dao.loghain_fate']['quick_kind'], 'select')
        self.assertIn('sacrificed', {a['id'] for a in choices['dao.loghain_fate']['answers']})
        for group, count in [('dao.warden_fate', 2), ('dao.archdemon_killer', 3), ('dao.morrigan_child', 5)]:
            self.assertEqual(len(choices[group]['answers']), count)
            for answer in choices[group]['answers']:
                status, image = self.request(answer['art'], authorized=False, json_response=False)
                self.assertEqual(status, 200)
                self.assertTrue(image.startswith(b'\xff\xd8'))
        self.draft['choices'] = {'dao.warden_fate': 'sacrificed', 'dao.archdemon_killer': 'warden',
                                 'dao.morrigan_child': 'human_warden'}
        _, preview = self.request('/api/preview', self.draft)
        self.assertTrue(preview['can_export'])
        _, saved = self.request('/api/save', self.draft)
        status, exported = self.request('/api/export', {'profile_id': saved['profile_id'], 'revision': saved['revision']})
        self.assertEqual(status, 200)
        report = json.loads(Path(exported['report_path']).read_text(encoding='utf8'))
        self.assertTrue(any('dao_morrigan_has_child needs verification' in x for x in report['profile']['warnings']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
