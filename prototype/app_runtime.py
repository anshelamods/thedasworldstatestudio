"""Stable resource and user-data paths for source and standalone builds."""
import os
from pathlib import Path
import sys

APP_VERSION = '1.0.4'
APP_NAME = 'Thedas World State Studio'


def resource_root():
    return Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent


def application_data_dir():
    local = os.environ.get('LOCALAPPDATA')
    return (Path(local) if local else Path.home() / 'AppData/Local') / 'ThedasWorldstateStudio'


def editor_directories(data_dir=None, store=None, exports=None):
    base = Path(data_dir) if data_dir is not None else (
        application_data_dir() if getattr(sys, 'frozen', False) else resource_root())
    return Path(store) if store is not None else base / 'profiles', Path(exports) if exports is not None else base / 'exports'
