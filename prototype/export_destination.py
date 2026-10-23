"""User-selected FBMOD folders, separate from world-state/profile data."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def export_directory(value, default, *, must_exist=True):
    if not isinstance(value, str) or not value.strip() or '\0' in value:
        raise ValueError('Choose an export folder')
    path = Path(value.strip()).expanduser()
    if not path.is_absolute():
        raise ValueError('Enter the full path to an export folder')
    path = path.resolve()
    if path.exists() and not path.is_dir():
        raise ValueError('The export destination must be a folder')
    # The launcher's default folder can be created on first export.
    if must_exist and not path.is_dir() and path != Path(default).resolve():
        raise ValueError('The export folder does not exist. Choose an existing folder.')
    return path


class ExportLocation:
    def __init__(self, path, default):
        self.path = Path(path)
        self.default = Path(default).resolve()

    def load(self):
        try:
            value = json.loads(self.path.read_text(encoding='utf8'))
            directory = value['directory']
            if isinstance(directory, str) and '\0' not in directory and Path(directory).is_absolute():
                return Path(directory).resolve()
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return self.default

    def remember(self, directory):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix='.export-location-', dir=self.path.parent)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf8') as stream:
                json.dump({'directory': str(directory)}, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)


def choose_export_folder(initial):
    # A separate main thread owns the native dialog; HTTP heartbeats continue.
    try:
        command = ([sys.executable, '--choose-export-folder', str(initial)] if getattr(sys, 'frozen', False)
                   else [sys.executable, '-X', 'utf8', str(Path(__file__).resolve()), str(initial)])
        # A windowed executable has no stdout. A short-lived result file works
        # for both builds and carries only the selected local folder path.
        with tempfile.TemporaryDirectory(prefix='thedas-folder-') as temporary:
            response = Path(temporary) / 'selection.json'
            command.extend(['--result-file', str(response)])
            result = subprocess.run(command,
                capture_output=True, text=True, encoding='utf8', timeout=300,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            selected = json.loads(response.read_text(encoding='utf8')) if response.is_file() else None
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError('Could not open the folder chooser. Enter the folder path instead.') from error
    if result.returncode:
        raise ValueError('Could not open the folder chooser. Enter the folder path instead.')
    return selected


def open_export_folder(directory):
    if os.name == 'nt':
        os.startfile(str(directory))
    else:
        subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(directory)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def folder_picker_main(argv=None):
    import argparse
    import tkinter as tk
    from tkinter import filedialog
    parser = argparse.ArgumentParser()
    parser.add_argument('initial', type=Path)
    parser.add_argument('--result-file', type=Path, required=True)
    args = parser.parse_args(argv)
    initial = args.initial
    while not initial.is_dir() and initial != initial.parent:
        initial = initial.parent
    if not initial.is_dir():
        initial = Path.home()
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    try:
        selected = filedialog.askdirectory(parent=root, title='Choose FBMOD export folder',
            initialdir=str(initial), mustexist=True)
        args.result_file.write_text(json.dumps(selected or None), encoding='utf8')
    finally:
        root.destroy()


if __name__ == '__main__':
    folder_picker_main()
