"""FBMOD presentation settings, separate from versioned world-state profiles."""
import base64
import binascii
import json
import os
from pathlib import Path
import re
import struct
import tempfile
import unicodedata
import zlib

MAX_ICON_BYTES = 512 * 1024
# User-facing mod version is independent of application and writer releases.
FBMOD_VERSION = '1.0'
DEFAULT_SETTINGS = {'author': 'Thedas World State Studio', 'description': '', 'icon_data_url': None}


def suggested_title(value):
    """Make generated titles compatible with Frosty's single-byte metadata.

    Explicit user-entered metadata still goes through strict validation.
    Preserve Latin-1 accents, simplify punctuation and transliterate where
    Unicode decomposition permits it; unsupported characters are omitted.
    """
    value = value.translate(str.maketrans({
        '\u2018': "'", '\u2019': "'", '\u201a': "'", '\u201b': "'",
        '\u201c': '"', '\u201d': '"', '\u201e': '"', '\u201f': '"',
        '\u2010': '-', '\u2011': '-', '\u2012': '-', '\u2013': '-', '\u2014': '-',
        '\u2212': '-', '\u2026': '...',
    }))
    value = ''.join(c if ord(c) <= 255 else unicodedata.normalize('NFKD', c).encode('latin-1', 'ignore').decode('latin-1')
                    for c in value)
    value = ''.join(c for c in value if not unicodedata.category(c).startswith('C'))
    return ' '.join(value.split())[:160].strip() or 'World State'


def metadata_text(value, label, maximum, *, required=False):
    if not isinstance(value, str) or '\0' in value or len(value) > maximum or (required and not value.strip()):
        raise ValueError(f'{label} must be {"nonempty text" if required else "text"} of at most {maximum} characters, without null characters')
    try:
        value.encode('latin-1')
    except UnicodeEncodeError as error:
        raise ValueError(f'{label} contains characters Frosty cannot display. Use Latin-1 text and straight quotes or hyphens.') from error
    return value


def validate_icon(data):
    """Check supported image containers and dimensions without changing pixels."""
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_ICON_BYTES:
        raise ValueError('Choose a PNG or JPEG icon no larger than 512 KB')
    width = height = 0
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        pos, image_data, ended = 8, False, False
        while pos + 12 <= len(data):
            size = struct.unpack_from('>I', data, pos)[0]
            kind = data[pos + 4:pos + 8]
            end = pos + 12 + size
            if end > len(data):
                raise ValueError('The PNG icon is truncated')
            chunk = data[pos + 8:pos + 8 + size]
            if zlib.crc32(kind + chunk) & 0xffffffff != struct.unpack_from('>I', data, end - 4)[0]:
                raise ValueError('The PNG icon has an invalid checksum')
            if pos == 8:
                if kind != b'IHDR' or size != 13:
                    raise ValueError('The PNG icon has an invalid header')
                width, height = struct.unpack_from('>II', chunk)
            image_data |= kind == b'IDAT' and size > 0
            if kind == b'IEND':
                ended = size == 0 and end == len(data)
                break
            pos = end
        if not ended or not image_data:
            raise ValueError('The PNG icon is incomplete')
        mime = 'image/png'
    elif data.startswith(b'\xff\xd8') and data.endswith(b'\xff\xd9'):
        pos, scanned = 2, False
        sof = {0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf}
        while pos + 4 <= len(data):
            if data[pos] != 0xff:
                break
            while pos < len(data) and data[pos] == 0xff:
                pos += 1
            if pos + 3 > len(data):
                break
            marker = data[pos]
            pos += 1
            size = struct.unpack_from('>H', data, pos)[0]
            if size < 2 or pos + size > len(data):
                raise ValueError('The JPEG icon is truncated')
            if marker in sof:
                if size < 8:
                    raise ValueError('The JPEG icon has an invalid frame')
                height, width = struct.unpack_from('>HH', data, pos + 3)
            if marker == 0xda:
                scanned = True
                break
            pos += size
        if not scanned:
            raise ValueError('The JPEG icon is incomplete')
        mime = 'image/jpeg'
    else:
        raise ValueError('Choose a PNG or JPEG icon')
    if not 0 < width <= 2048 or not 0 < height <= 2048:
        raise ValueError('Icon dimensions must be between 1 and 2048 pixels')
    return mime


def image_data_url(data):
    return 'data:' + validate_icon(data) + ';base64,' + base64.b64encode(data).decode('ascii')


def decode_icon(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > MAX_ICON_BYTES * 4 // 3 + 100:
        raise ValueError('The icon is too large')
    match = re.fullmatch(r'data:(image/png|image/jpeg);base64,([A-Za-z0-9+/=]+)', value)
    if not match:
        raise ValueError('Choose a PNG or JPEG icon')
    try:
        data = base64.b64decode(match[2], validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError('The icon is not valid base64') from error
    if validate_icon(data) != match[1]:
        raise ValueError('The icon type does not match its contents')
    return data


class FbmodSettings:
    def __init__(self, path):
        self.path = Path(path)

    @staticmethod
    def validate(value):
        if not isinstance(value, dict) or set(value) != set(DEFAULT_SETTINGS):
            raise ValueError('Invalid FBMOD settings')
        metadata_text(value['author'], 'Author', 120)
        metadata_text(value['description'], 'Description', 8000)
        decode_icon(value['icon_data_url'])
        return dict(value)

    def load(self):
        if not self.path.exists():
            return dict(DEFAULT_SETTINGS)
        return self.validate(json.loads(self.path.read_text(encoding='utf8')))

    def save(self, value):
        value = self.validate(value)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix='.fbmod-settings-', dir=self.path.parent)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf8') as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return value


RESERVED_NAMES = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}


def export_filename(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise ValueError('Enter a file name of at most 160 characters')
    value = value.strip()
    if re.search(r'[<>:"/\\|?*\x00-\x1f]', value) or value.endswith(('.', ' ')):
        raise ValueError('The file name contains characters Windows cannot use')
    if not value.lower().endswith('.fbmod'):
        value += '.fbmod'
    stem = value[:-6]
    if not stem.strip(' .') or stem.endswith(('.', ' ')) or stem.split('.')[0].upper() in RESERVED_NAMES:
        raise ValueError('Choose a different file name; this name is reserved by Windows')
    return value


def suggested_filename(name):
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', name).strip(' .')[:120] or 'World State'
    if stem.split('.')[0].upper() in RESERVED_NAMES:
        stem = 'World State - ' + stem
    return export_filename(stem)


def available_export(directory, filename):
    filename = export_filename(filename)
    stem = filename[:-6]
    number = 1
    while True:
        path = Path(directory) / (filename if number == 1 else f'{stem} ({number}).fbmod')
        if not path.exists() and not path.with_suffix('.report.json').exists():
            return path
        number += 1
