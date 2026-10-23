"""Standalone Windows entry point, including the isolated native folder picker."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import sys
import traceback

from app_runtime import APP_NAME, APP_VERSION, application_data_dir


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ['--choose-export-folder']:
        from export_destination import folder_picker_main
        folder_picker_main(argv[1:])
        return 0
    if len(argv) == 2 and argv[0] == '--check-runtime':
        import hashlib
        import json
        import tkinter as tk
        from app_runtime import resource_root
        root = tk.Tk()
        root.withdraw()
        try:
            result = dict(version=APP_VERSION, frozen=bool(getattr(sys, 'frozen', False)),
                          python=sys.version, resource_root=str(resource_root()),
                          tcl=root.tk.call('info', 'patchlevel'),
                          tk=root.tk.call('package', 'require', 'Tk'),
                          window_system=root.tk.call('tk', 'windowingsystem'),
                          sha1_backend=hashlib.sha1.__module__, sha256_backend=hashlib.sha256.__module__,
                          sha1_abc=hashlib.sha1(b'abc').hexdigest(), sha256_abc=hashlib.sha256(b'abc').hexdigest())
            Path(argv[1]).write_text(json.dumps(result, indent=2), encoding='utf-8')
        finally:
            root.destroy()
        return 0
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--data-dir', type=Path, default=application_data_dir())
    known, _ = parser.parse_known_args(argv)
    directory = known.data_dir.resolve()
    logs = directory / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    filename = logs / (datetime.now().strftime('%Y%m%d-%H%M%S-') + str(os.getpid()) + '.log')
    with filename.open('w', encoding='utf-8', buffering=1) as stream:
        previous = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = stream
        try:
            print(APP_NAME + ' ' + APP_VERSION)
            from gui import main as gui_main
            gui_main([*argv, '--data-dir', str(directory)])
            return 0
        except Exception:
            traceback.print_exc()
            stream.flush()
            if '--no-open' not in argv and os.name == 'nt':
                import ctypes
                ctypes.windll.user32.MessageBoxW(None,
                    'The editor could not start. Details were saved to:\n' + str(filename), APP_NAME, 0x10)
            return 1
        finally:
            sys.stdout, sys.stderr = previous


if __name__ == '__main__':
    raise SystemExit(main())
