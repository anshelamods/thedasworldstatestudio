"""Bounded, lazy PC GFF4 save reader. There is no save-writing API.

Field layouts follow the reader in the sibling TLKEdit project. Lazy lists let
the importer inspect plot/player data without decoding inventories or morphs.
"""
from __future__ import annotations

import struct

MAX_SAVE_BYTES = 32 * 1024 * 1024
NULL = 0xFFFFFFFF
LIST, STRUCT, REFERENCE = 0x8000, 0x4000, 0x2000
FORMATS = {0: 'B', 1: 'b', 2: 'H', 3: 'h', 4: 'I', 5: 'i', 6: 'Q', 7: 'q',
           8: 'f', 9: 'd', 10: '3f', 12: '4f', 13: '4f', 15: '4f', 16: '16f'}


class SaveFormatError(ValueError):
    pass


class Node:
    def __init__(self, reader, kind, offset):
        self.reader, self.kind, self.offset = reader, kind, offset
        reader.require(offset, reader.definition(kind)[0])

    def get(self, label, default=None):
        field = self.reader.definition(self.kind)[1].get(label)
        if field is None:
            return default
        kind, flags, offset = field
        width = (4 if flags & LIST else (8 if kind == 0xFFFF else 4) if flags & REFERENCE
                 else self.reader.definition(kind)[0] if flags & STRUCT else self.reader.size(kind))
        if offset + width > self.reader.definition(self.kind)[0]:
            raise SaveFormatError('A save field extends beyond its structure.')
        return self.reader.value(kind, flags, self.offset + offset)


class ListView:
    def __init__(self, reader, kind, flags, offset):
        self.reader, self.kind, self.flags = reader, kind, flags
        self.offset = offset + 4
        self.count = reader.unpack('I', offset)[0]
        if self.count > 1_000_000:
            raise SaveFormatError('A save list exceeds the supported size.')
        self.stride = (8 if kind == 0xFFFF else 4) if flags & REFERENCE else (
            reader.definition(kind)[0] if flags & STRUCT else reader.size(kind))
        if self.count and not self.stride:
            raise SaveFormatError('A save list has an invalid element size.')
        reader.require(self.offset, self.count * self.stride)

    def __len__(self):
        return self.count

    def __getitem__(self, index):
        if type(index) is not int or not 0 <= index < self.count:
            raise IndexError(index)
        return self.reader.value(self.kind, self.flags & ~LIST, self.offset + index * self.stride)

    def __iter__(self):
        return (self[i] for i in range(self.count))


class SaveReader:
    def __init__(self, payload, *, game='da2'):
        if game not in ('dao', 'da2'):
            raise SaveFormatError('Unsupported save game.')
        minimum = 28 if game == 'dao' else 36
        if not isinstance(payload, bytes) or not minimum <= len(payload) <= MAX_SAVE_BYTES:
            raise SaveFormatError('Choose a complete ' + game.upper() + ' .das save no larger than 32 MB.')
        self.payload = payload
        if payload[:4] != b'GFF ':
            raise SaveFormatError('Choose the .das save itself, rather than its ZIP, picture or metadata file.')
        self.version = payload[4:8]
        expected = (b'V4.0', b'SAVEV1.1') if game == 'dao' else (b'V4.1', b'SAVEV2.0')
        if (self.version, payload[12:20]) != expected or payload[8:12] != b'PC  ':
            raise SaveFormatError('Choose a supported PC ' + ('Dragon Age: Origins' if game == 'dao' else 'Dragon Age II') + ' save.')
        if game == 'dao':
            structures, self.data_offset = self.unpack('II', 20)
            strings, string_offset = 0, self.data_offset
        else:
            structures, strings, string_offset, self.data_offset = self.unpack('IIII', 20)
        if not 1 <= structures <= 4096 or strings > 1_000_000:
            raise SaveFormatError('Unsupported save schema size.')
        if not minimum + structures * 16 <= string_offset <= self.data_offset <= len(payload):
            raise SaveFormatError('Invalid save header offsets.')
        self.definitions = []
        total_fields = 0
        for index in range(structures):
            _, count, fields_offset, size = self.unpack('4sIII', minimum + index * 16)
            total_fields += count
            if total_fields > 65536:
                raise SaveFormatError('Unsupported number of save fields.')
            self.require(fields_offset, count * 12)
            if fields_offset < minimum + structures * 16 or fields_offset + count * 12 > string_offset:
                raise SaveFormatError('Save fields overlap the string table.')
            fields = {}
            for i in range(count):
                label, encoded, offset = self.unpack('III', fields_offset + i * 12)
                if label in fields or offset >= size:
                    raise SaveFormatError('Invalid or duplicate save field definition.')
                if (encoded >> 16) & ~(LIST | STRUCT | REFERENCE):
                    raise SaveFormatError('Unsupported save field flags.')
                fields[label] = (encoded & 0xFFFF, encoded >> 16, offset)
            self.definitions.append((size, fields))
        self.strings = []
        cursor = string_offset
        for _ in range(strings):
            end = payload.find(b'\0', cursor, self.data_offset)
            if end < 0:
                raise SaveFormatError('The save string table is incomplete.')
            self.strings.append((cursor, end))
            cursor = end + 1
        self.root = Node(self, 0, self.data_offset)

    def require(self, offset, length):
        if offset < 0 or length < 0 or offset + length > len(self.payload):
            raise SaveFormatError('The save is incomplete or has an invalid data offset.')

    def unpack(self, fmt, offset):
        self.require(offset, struct.calcsize('<' + fmt))
        return struct.unpack_from('<' + fmt, self.payload, offset)

    def definition(self, kind):
        if not 0 <= kind < len(self.definitions):
            raise SaveFormatError('Invalid save structure type.')
        return self.definitions[kind]

    def size(self, kind):
        if kind in (14,):
            return 4
        if kind in (17, 0xFFFF):
            return 8
        if kind not in FORMATS:
            raise SaveFormatError('Unsupported save field type.')
        return struct.calcsize('<' + FORMATS[kind])

    def string(self, index):
        if index == NULL:
            return None
        if self.version == b'V4.0':
            address = self.data_offset + index
            length = self.unpack('I', address)[0]
            if length > 1_000_000:
                raise SaveFormatError('Save text exceeds the supported size.')
            self.require(address + 4, length * 2)
            try:
                return self.payload[address + 4:address + 4 + length * 2].decode('utf-16le').rstrip('\0')
            except UnicodeError as error:
                raise SaveFormatError('Invalid text in the save.') from error
        if not 0 <= index < len(self.strings):
            raise SaveFormatError('Invalid save string reference.')
        start, end = self.strings[index]
        try:
            return self.payload[start:end].decode('utf-8')
        except UnicodeError as error:
            raise SaveFormatError('Invalid text in the save.') from error

    def value(self, kind, flags, offset, depth=0):
        if depth > 16:
            raise SaveFormatError('Save references are nested too deeply.')
        if flags & LIST:
            address = self.unpack('I', offset)[0]
            return () if address == NULL else ListView(self, kind, flags, self.data_offset + address)
        if flags & REFERENCE:
            if kind == 0xFFFF:
                encoded, address = self.unpack('II', offset)
                if address == NULL:
                    return None
                target_kind, target_flags = encoded & 0xFFFF, encoded >> 16
                target = self.data_offset + address
                if target_flags & LIST:
                    return ListView(self, target_kind, target_flags, target)
                return self.value(target_kind, target_flags & ~REFERENCE, target, depth + 1)
            address = self.unpack('I', offset)[0]
            return None if address == NULL else self.value(kind, flags & ~REFERENCE,
                                                         self.data_offset + address, depth + 1)
        if flags & STRUCT:
            return Node(self, kind, offset)
        if kind == 14:
            return self.string(self.unpack('I', offset)[0])
        if kind == 17:
            _, index = self.unpack('II', offset)
            if self.version == b'V4.0' and index == 0:
                return None  # No literal text; only the game's TLK reference.
            return self.string(index)
        if kind not in FORMATS:
            raise SaveFormatError('Unsupported save field type.')
        values = self.unpack(FORMATS[kind], offset)
        return values[0] if len(values) == 1 else values

    def get(self, path, default=None):
        current = self.root
        for label in path:
            if not isinstance(current, Node):
                return default
            current = current.get(label)
            if current is None:
                return default
        return current
