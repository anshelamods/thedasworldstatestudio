"""Runtime EBX/CAS reading primitives, separated from development inspection tools."""
from pathlib import Path
import struct
import sys
import zlib

if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent /
        'assessment/reference/DAI_Exporter'))
from ebx_parser import EbxParser


class Reader:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def take(self, count):
        assert 0 <= count <= len(self.data) - self.pos
        result = self.data[self.pos:self.pos + count]
        self.pos += count
        return result

    def num(self, fmt):
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))[0]

    def string(self):
        end = self.data.index(0, self.pos)
        return self.take(end - self.pos + 1)[:-1].decode('utf-8')


def lz4_block(data):
    reader, output = Reader(data), bytearray()
    def length(initial):
        total = initial
        if initial == 15:
            while True:
                extra = reader.num('B')
                total += extra
                if extra != 255:
                    break
        return total
    while reader.pos < len(data):
        token = reader.num('B')
        output.extend(reader.take(length(token >> 4)))
        if reader.pos == len(data):
            break
        distance = reader.num('<H')
        assert 0 < distance <= len(output)
        for _ in range(length(token & 15) + 4):
            output.append(output[-distance])
    return bytes(output)


def decode_cas(data):
    reader, output, types = Reader(data), bytearray(), []
    while reader.pos < len(data):
        size = reader.num('>I') & 0xffffff
        compression = reader.num('<H')
        packed_size = reader.num('>H') | (((compression >> 8) & 15) << 16)
        block = reader.take(packed_size)
        kind = compression & 0x7f
        if kind == 0:
            decoded = block
        elif kind == 2:
            decoded = zlib.decompress(block)
        elif kind == 9:
            decoded = lz4_block(block)
        else:
            raise ValueError(f'Unsupported compression {kind}')
        assert len(decoded) == size
        types.append(kind)
        output.extend(decoded)
    return bytes(output), types
