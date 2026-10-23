"""Packaged path selection and the windowless folder-picker protocol."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app_runtime
import export_destination


class BetaRuntimeTests(unittest.TestCase):
    def test_source_paths_remain_in_workspace_and_frozen_data_is_outside_install(self):
        source = Path(__file__).resolve().parent.parent
        with patch.object(app_runtime.sys, 'frozen', False, create=True):
            self.assertEqual(app_runtime.resource_root(), source)
            self.assertEqual(app_runtime.editor_directories(), (source / 'profiles', source / 'exports'))
        with patch.object(app_runtime.sys, 'frozen', True, create=True), \
             patch.object(app_runtime.sys, '_MEIPASS', str(source / 'fake-internal'), create=True), \
             patch.dict(app_runtime.os.environ, {'LOCALAPPDATA': str(source / 'fake-user')}):
            self.assertEqual(app_runtime.resource_root(), source / 'fake-internal')
            expected = source / 'fake-user/ThedasWorldstateStudio'
            self.assertEqual(app_runtime.editor_directories(), (expected / 'profiles', expected / 'exports'))
            custom = source / 'explicit-data'
            self.assertEqual(app_runtime.editor_directories(custom), (custom / 'profiles', custom / 'exports'))

    def test_frozen_folder_picker_uses_executable_helper_and_result_file_without_stdout(self):
        selected = str(Path(__file__).resolve().parent / 'output')
        def launch(command, **kwargs):
            self.assertEqual(command[1:3], ['--choose-export-folder', selected])
            self.assertNotIn('-X', command)
            result_path = Path(command[command.index('--result-file') + 1])
            result_path.write_text(json.dumps(selected), encoding='utf-8')
            return type('Result', (), {'returncode': 0, 'stdout': ''})()
        with patch.object(export_destination.sys, 'frozen', True, create=True), \
             patch.object(export_destination.subprocess, 'run', side_effect=launch):
            self.assertEqual(export_destination.choose_export_folder(selected), selected)

    def test_cancelled_folder_picker_leaves_no_selected_destination(self):
        def launch(command, **kwargs):
            result_path = Path(command[command.index('--result-file') + 1])
            result_path.write_text('null', encoding='utf-8')
            return type('Result', (), {'returncode': 0})()
        with patch.object(export_destination.subprocess, 'run', side_effect=launch):
            self.assertIsNone(export_destination.choose_export_folder(Path(__file__).parent))


if __name__ == '__main__':
    unittest.main()
