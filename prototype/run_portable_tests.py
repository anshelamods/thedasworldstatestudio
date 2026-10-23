"""Run self-contained source-distribution tests without personal/research data."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

MODULES = ('test_save_import', 'test_save_import_companions', 'test_dao_import',
           'test_carried_dao', 'test_da2_merge', 'test_profile_management',
           'test_profile_purge', 'test_profile_storage', 'test_beta_runtime', 'test_editor_lifecycle',
           'test_story_restrictions', 'test_dao_unresolved_outcomes')
WORKFLOWS = (('test_export_ui.cjs',), ('test_save_import_ui.cjs',),
             ('test_dao_import_ui.cjs',), ('test_dao_import_ui.cjs', 'da2'),
             ('test_profile_management_ui.cjs',), ('test_search_filters.cjs',),
             ('test_editor_navigation.cjs',),
             ('test_icon_selection_ui.cjs',), ('test_new_world_state_ui.cjs',), ('test_history_ui.cjs',),
             ('test_save_persistence_ui.cjs',))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--javascript', action='store_true', help='Also run UI workflows; requires Node.js on PATH')
    args = parser.parse_args()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(MODULES))
    if not result.wasSuccessful():
        return 1
    if args.javascript:
        node = shutil.which('node')
        if not node:
            parser.error('Node.js was not found on PATH; omit --javascript to run Python tests only.')
        for script, *arguments in WORKFLOWS:
            subprocess.run([node, str(Path(__file__).parent / script), *arguments], check=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
