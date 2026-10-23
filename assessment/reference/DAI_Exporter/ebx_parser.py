"""Small Frostbite EBX v2/v4 reader from DAI Exporter."""

from __future__ import annotations

import struct
import uuid


TYPE_NAMES = {
    0x00: "Inherited", 0x01: "DbObject", 0x02: "Struct",
    0x03: "Pointer", 0x04: "Array", 0x06: "String",
    0x07: "CString", 0x08: "Enum", 0x09: "FileRef",
    0x0A: "Boolean", 0x0B: "Int8", 0x0C: "UInt8",
    0x0D: "Int16", 0x0E: "UInt16", 0x0F: "Int32",
    0x10: "UInt32", 0x11: "UInt64", 0x12: "Int64",
    0x13: "Float32", 0x14: "Float64", 0x15: "Guid",
    0x16: "Sha1", 0x17: "ResourceRef", 0x18: "Delegate",
    0x19: "TypeRef", 0x1A: "BoxedValueRef",
}


def ebx_hash(text: str) -> int:
    value = 5381
    for character in text:
        value = ((value * 33) ^ (ord(character) & 0xFF)) & 0xFFFFFFFF
    return value


class EbxParser:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def unpack(self, fmt):
        size = struct.calcsize("<" + fmt)
        values = struct.unpack_from("<" + fmt, self.data, self.pos)
        self.pos += size
        return values[0] if len(values) == 1 else values

    def align(self, alignment):
        if alignment:
            self.pos = (self.pos + alignment - 1) // alignment * alignment

    def guid(self):
        raw = self.data[self.pos:self.pos + 16]
        self.pos += 16
        return str(uuid.UUID(bytes_le=raw))

    def cstring_at(self, offset):
        if offset == 0xFFFFFFFF:
            return ""
        start = self.strings_offset + offset
        end = self.data.index(0, start)
        return self.data[start:end].decode("utf-8", errors="replace")

    def parse(self):
        magic = self.unpack("I")
        if magic not in (0x0FB2D1CE, 0x0FB4D1CE):
            raise ValueError("Unsupported EBX magic: 0x%08X" % magic)
        self.magic = magic
        self.strings_offset = self.unpack("I")
        strings_and_data_len = self.unpack("I")
        guid_count = self.unpack("I")
        instance_count, exported_count, unique_class_count = self.unpack("HHH")
        class_count, field_count, type_names_len = self.unpack("HHH")
        strings_len, array_count, data_len = self.unpack("III")
        self.strings_len = strings_len
        self.arrays_offset = self.strings_offset + strings_len + data_len
        file_guid = self.guid()
        if magic == 0x0FB4D1CE:
            boxed_count, boxed_offset = self.unpack("II")
        else:
            boxed_count, boxed_offset = 0, 0
            self.align(16)

        self.imports = [
            {"file_guid": self.guid(), "class_guid": self.guid()}
            for _ in range(guid_count)
        ]

        names_start = self.pos
        names = {}
        while self.pos - names_start < type_names_len:
            end = self.data.index(0, self.pos)
            name = self.data[self.pos:end].decode("utf-8", errors="replace")
            self.pos = end + 1
            names[ebx_hash(name)] = name

        fields = []
        for index in range(field_count):
            name_hash, type_word, class_ref, data_offset, second_offset = self.unpack("IHHII")
            type_id = (type_word >> 4) & 0x1F
            fields.append({
                "index": index,
                "name": names.get(name_hash, "hash_%08X" % name_hash),
                "type": TYPE_NAMES.get(type_id, "Unknown_%02X" % type_id),
                "type_id": type_id,
                "class_ref": class_ref,
                "data_offset": data_offset,
                "second_offset": second_offset,
            })
        self.fields = fields

        classes = []
        for index in range(class_count):
            name_hash, field_index = self.unpack("Ii")
            field_num, alignment, type_word, size, second_size = self.unpack("BBHHH")
            type_id = (type_word >> 4) & 0x1F
            classes.append({
                "index": index,
                "name": names.get(name_hash, "hash_%08X" % name_hash),
                "field_index": field_index,
                "field_count": field_num,
                "alignment": alignment,
                "type": TYPE_NAMES.get(type_id, "Unknown_%02X" % type_id),
                "type_id": type_id,
                "size": size,
                "second_size": second_size,
            })
        self.classes = classes

        instances = []
        remaining_exported = exported_count
        for _ in range(instance_count):
            class_ref, count = self.unpack("HH")
            instances.append({
                "class_ref": class_ref,
                "class": classes[class_ref]["name"],
                "count": count,
                "exported": remaining_exported > 0,
            })
            if remaining_exported:
                remaining_exported -= 1
        self.instances = instances
        self.align(16)

        arrays = []
        for index in range(array_count):
            offset, count, class_ref = self.unpack("IIi")
            arrays.append({
                "index": index,
                "offset": offset,
                "count": count,
                "class_ref": class_ref,
                "class": classes[class_ref]["name"],
            })
        self.arrays = arrays
        self.align(16)

        self.pos = self.strings_offset + strings_len
        objects = []
        object_id = 0
        for group in instances:
            cls = classes[group["class_ref"]]
            for _ in range(group["count"]):
                self.align(cls["alignment"])
                instance_guid = self.guid() if group["exported"] else None
                if cls["alignment"] != 4:
                    self.pos += 8
                value = self.read_class(cls)
                objects.append({
                    "object_id": object_id,
                    "instance_guid": instance_guid,
                    "class": cls["name"],
                    "value": value,
                })
                object_id += 1

        return {
            "version": 2 if magic == 0x0FB2D1CE else 4,
            "header": {
                "file_guid": file_guid,
                "file_size": len(self.data),
                "strings_and_data_len": strings_and_data_len,
                "unique_class_count": unique_class_count,
                "boxed_value_count": boxed_count,
                "boxed_value_offset": boxed_offset,
            },
            "imports": self.imports,
            "objects": objects,
        }

    def read_class(self, cls):
        result = {}
        for field_index in range(cls["field_index"], cls["field_index"] + cls["field_count"]):
            field = self.fields[field_index]
            if field["type_id"] == 0x00:
                result.update(self.read_class(self.classes[field["class_ref"]]))
                continue
            if field["type_id"] in (0x11, 0x12, 0x14, 0x17, 0x19, 0x09, 0x1A):
                self.align(8)
            elif field["type_id"] in (0x03, 0x04):
                self.align(4)
            if field["type_id"] == 0x04:
                array_index = self.unpack("i")
                saved = self.pos
                descriptor = self.arrays[array_index]
                self.pos = self.arrays_offset + descriptor["offset"]
                wrapper = self.classes[descriptor["class_ref"]]
                item_field = self.fields[wrapper["field_index"]]
                items = [self.read_field(item_field) for _ in range(descriptor["count"])]
                self.pos = saved
                result[field["name"]] = items
            else:
                result[field["name"]] = self.read_field(field)
        self.align(cls["alignment"])
        return result

    def read_field(self, field):
        type_id = field["type_id"]
        scalar_formats = {
            0x0A: "?", 0x0B: "b", 0x0C: "B", 0x0D: "h", 0x0E: "H",
            0x0F: "i", 0x10: "I", 0x11: "Q", 0x12: "q",
            0x13: "f", 0x14: "d", 0x08: "i",
        }
        if type_id in scalar_formats:
            return self.unpack(scalar_formats[type_id])
        if type_id == 0x15:
            return self.guid()
        if type_id == 0x17:
            return "0x%016X" % self.unpack("Q")
        if type_id == 0x16:
            raw = self.data[self.pos:self.pos + 20]
            self.pos += 20
            return raw.hex()
        if type_id == 0x06:
            raw = self.data[self.pos:self.pos + 32]
            self.pos += 32
            return raw.split(b"\0", 1)[0].decode("utf-8", errors="replace")
        if type_id == 0x07:
            return self.cstring_at(self.unpack("I"))
        if type_id in (0x09, 0x19):
            offset = self.unpack("I")
            self.pos += 4
            return self.cstring_at(offset)
        if type_id == 0x03:
            raw = self.unpack("I")
            if raw == 0:
                return {"kind": "null"}
            if raw & 0x80000000:
                index = raw & 0x7FFFFFFF
                return {"kind": "external", "import_index": index, **self.imports[index]}
            return {"kind": "internal", "object_id": raw - 1}
        if type_id == 0x02:
            cls = self.classes[field["class_ref"]]
            self.align(cls["alignment"])
            return self.read_class(cls)
        raise ValueError("Unsupported EBX field type %s at 0x%X" % (field["type"], self.pos))
