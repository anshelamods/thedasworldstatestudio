"""Metadata changes must preserve game resources and reviewed compression bytes."""
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from export_worldstate import ROOT, read_mod
from fbmod_metadata import (DEFAULT_SETTINGS, MAX_ICON_BYTES, FbmodSettings, decode_icon,
                            export_filename, image_data_url, suggested_filename, validate_icon)
from world_profiles import Catalog
from world_profiles.compiler import build_profile_mod


def test_icon():
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 2, 8, 2, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(b'\0\xff\0\0\0\xff\0\0\0\0\xff\xff\xff\0')) + chunk(b'IEND', b''))


class FbmodMetadataTests(unittest.TestCase):
    def test_metadata_and_png_icon_preserve_game_payload_and_screenshots_in_every_base(self):
        catalog = Catalog()
        for preset in catalog.presets:
            profile = catalog.create('Source profile', base_preset=preset, mode='experimental')
            old = read_mod(build_profile_mod(profile, catalog=catalog)[0])
            data, report = build_profile_mod(profile, catalog=catalog, title='My named mod',
                metadata=dict(author='Fénris & Friends', description='My history.\nSecond line.', icon=test_icon()))
            actual = read_mod(data)
            self.assertEqual(actual['details'][:3], ['My named mod', 'Fénris & Friends', old['details'][2]])
            self.assertEqual(actual['details'][4], 'My history.\nSecond line.')
            self.assertEqual(actual['details'][3], '1.0')
            self.assertEqual(report['mod_metadata']['version'], '1.0')
            self.assertEqual(actual['details'][5], old['details'][5])
            self.assertEqual(actual['target']['raw'], old['target']['raw'])
            self.assertEqual(actual['ebx'], old['ebx'])
            self.assertEqual(actual['payloads'][actual['target']['index']], old['payloads'][old['target']['index']])
            for before, after in zip(old['records'], actual['records']):
                if before['name'] == 'Icon':
                    self.assertEqual(actual['payloads'][after['index']], test_icon())
                    self.assertEqual(after['size'], len(test_icon()))
                else:
                    self.assertEqual(after['raw'], before['raw'])
            self.assertEqual(report['mod_metadata']['category'], old['details'][2])
            self.assertEqual(report['mod_metadata']['icon_bytes'], len(test_icon()))

    def test_mod_version_is_independent_of_app_and_writer_diagnostics(self):
        profile = Catalog().create('Version independence')
        before, _ = build_profile_mod(profile)
        with patch('export_worldstate.APP_VERSION', '9.9.9-test'), patch('export_worldstate.WRITER_VERSION', 'future-writer'):
            data, report = build_profile_mod(profile)
        self.assertEqual(read_mod(data)['details'][3], '1.0')
        self.assertEqual(report['mod_metadata']['version'], '1.0')
        self.assertEqual(report['app_version'], '9.9.9-test')
        self.assertEqual(report['writer_version'], 'future-writer')
        self.assertEqual(data, before, 'Diagnostic version changes cannot alter the exported mod')

    def test_jpeg_icon_is_embedded_unchanged_and_reset_preserves_the_preset_icon(self):
        jpeg = (ROOT / 'assets/keep/dao_leliana_fate/alive_detail.jpg').read_bytes()
        self.assertEqual(validate_icon(jpeg), 'image/jpeg')
        profile = Catalog().create('JPEG icon')
        custom = read_mod(build_profile_mod(profile, metadata={'icon': jpeg})[0])
        self.assertEqual(custom['payloads'][custom['records'][0]['index']], jpeg)
        reset = read_mod(build_profile_mod(profile, metadata={'icon': None, 'author': DEFAULT_SETTINGS['author'], 'description': ''})[0])
        original = read_mod(Catalog().template_path(profile.base_preset).read_bytes())
        self.assertEqual(reset['records'][0]['raw'], original['records'][0]['raw'])
        if original['records'][0]['index'] < 0:
            self.assertEqual(reset['records'][0]['index'], -1)
        else:
            self.assertEqual(reset['payloads'][reset['records'][0]['index']], original['payloads'][original['records'][0]['index']])
        self.assertEqual(reset['details'][1], 'Thedas World State Studio')
        self.assertEqual(reset['details'][4], '')

    def test_icon_round_trip_rejects_truncated_wrong_type_and_oversized_data(self):
        self.assertEqual(decode_icon(image_data_url(test_icon())), test_icon())
        for data in (b'<svg/>', test_icon()[:-10], test_icon()[:30] + b'bad checksum', b'x' * (MAX_ICON_BYTES + 1)):
            with self.subTest(data_length=len(data)), self.assertRaises(ValueError):
                validate_icon(data)
        with self.assertRaises(ValueError):
            decode_icon(image_data_url(test_icon()).replace('image/png', 'image/jpeg'))

    def test_category_or_other_unsupported_metadata_cannot_be_overridden(self):
        profile = Catalog().create('Metadata rejection')
        for metadata in ({'category': 'Other'}, {'author': 'bad\0author'}, {'description': 123}, {'icon': b'invalid'}):
            with self.subTest(metadata=list(metadata)), self.assertRaises(ValueError):
                build_profile_mod(profile, metadata=metadata)

    def test_native_single_byte_metadata_supports_accents_and_rejects_smart_punctuation(self):
        profile = Catalog().create('Accented author')
        data, _ = build_profile_mod(profile, title='Fénris', metadata={'author': 'André', 'description': 'Café history.'})
        self.assertIn(b'Andr\xe9\0', data)
        self.assertNotIn(b'Andr\xc3\xa9\0', data)
        self.assertEqual(read_mod(data)['details'][1], 'André')
        with self.assertRaisesRegex(ValueError, 'Frosty cannot display'):
            build_profile_mod(profile, metadata={'author': 'Thedas — Studio'})

    def test_settings_persist_atomically_and_bad_update_keeps_the_saved_settings(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'prototype', prefix='.metadata-test-') as directory:
            path = Path(directory) / 'fbmod-settings.json'
            store = FbmodSettings(path)
            self.assertEqual(store.load(), DEFAULT_SETTINGS)
            self.assertFalse(path.exists())
            settings = dict(author='My Author', description='My history', icon_data_url=image_data_url(test_icon()))
            store.save(settings)
            self.assertEqual(FbmodSettings(path).load(), settings)
            raw = path.read_bytes()
            with self.assertRaises(ValueError):
                store.save(dict(settings, category='Other'))
            self.assertEqual(path.read_bytes(), raw)
            store.save(dict(DEFAULT_SETTINGS))
            self.assertEqual(store.load(), DEFAULT_SETTINGS)

    def test_readable_filenames_preserve_spaces_unicode_and_reject_windows_paths(self):
        self.assertEqual(export_filename('My Queen Cousland'), 'My Queen Cousland.fbmod')
        self.assertEqual(export_filename('Éowyn.fbmod'), 'Éowyn.fbmod')
        self.assertEqual(suggested_filename('My world: Queen?'), 'My world- Queen-.fbmod')
        self.assertEqual(suggested_filename('CON'), 'World State - CON.fbmod')
        for value in ('../escape', 'C:\\escape.fbmod', 'escape/name', 'NUL', 'COM1.txt', '.fbmod', 'bad\0name', 'bad:name', 'bad?.fbmod', 'bad. .fbmod'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                export_filename(value)


if __name__ == '__main__':
    unittest.main(verbosity=2)
