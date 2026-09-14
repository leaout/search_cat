"""Static, read-only inspection of QQSG's 32-bit DataBin.dll."""
import argparse
import json
import struct
from pathlib import Path


class PE32:
    def __init__(self, path: Path):
        self.data = path.read_bytes()
        pe = struct.unpack_from('<I', self.data, 0x3c)[0]
        self.image_base = struct.unpack_from('<I', self.data, pe + 52)[0]
        count = struct.unpack_from('<H', self.data, pe + 6)[0]
        optional_size = struct.unpack_from('<H', self.data, pe + 20)[0]
        self.optional = pe + 24
        table = self.optional + optional_size
        self.sections = []
        for index in range(count):
            offset = table + index * 40
            name = self.data[offset:offset + 8].split(b'\0')[0].decode('ascii')
            virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from('<4I', self.data, offset + 8)
            self.sections.append((name, virtual_address, max(virtual_size, raw_size), raw_offset, raw_size))

    def offset(self, rva: int) -> int:
        for _, address, size, raw, _ in self.sections:
            if address <= rva < address + size:
                return raw + rva - address
        raise ValueError(f'RVA {rva:#x} is outside sections')

    def rva(self, offset: int) -> int:
        for _, address, _, raw, raw_size in self.sections:
            if raw <= offset < raw + raw_size:
                return address + offset - raw
        raise ValueError(f'offset {offset:#x} is outside sections')

    def exports(self) -> dict[str, int]:
        export_rva = struct.unpack_from('<I', self.data, self.optional + 96)[0]
        cursor = self.offset(export_rva)
        values = struct.unpack_from('<IIHHIIIIIII', self.data, cursor)
        function_count, name_count, functions_rva, names_rva, ordinals_rva = values[6:]
        functions = struct.unpack_from(f'<{function_count}I', self.data, self.offset(functions_rva))
        names = struct.unpack_from(f'<{name_count}I', self.data, self.offset(names_rva))
        ordinals = struct.unpack_from(f'<{name_count}H', self.data, self.offset(ordinals_rva))
        result = {}
        for name_rva, ordinal in zip(names, ordinals):
            start = self.offset(name_rva)
            end = self.data.index(0, start)
            result[self.data[start:end].decode('ascii')] = functions[ordinal]
        return result

    def code(self):
        section = next(item for item in self.sections if item[0] == '.text')
        return section, self.data[section[3]:section[3] + section[4]]

    def call_xrefs(self, target_rva: int) -> list[int]:
        section, code = self.code()
        refs = []
        for index in range(len(code) - 5):
            if code[index] != 0xE8:
                continue
            source_rva = section[1] + index
            relative = struct.unpack_from('<i', code, index + 1)[0]
            if source_rva + 5 + relative == target_rva:
                refs.append(source_rva)
        return refs

    def immediate_xrefs(self, target_rva: int) -> list[int]:
        target = struct.pack('<I', self.image_base + target_rva)
        section, code = self.code()
        return [section[1] + index for index in range(len(code)) if code.startswith(target, index)]

    def find_bytes(self, value: bytes) -> int:
        return self.rva(self.data.index(value))

    def hex_near(self, rva: int, before=32, after=96) -> str:
        start = max(0, self.offset(rva) - before)
        return self.data[start:start + before + after].hex(' ')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('dll', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    pe = PE32(args.dll)
    exports = pe.exports()
    wanted = {
        name: rva for name, rva in exports.items()
        if any(token in name for token in ('GetNPCOnMap', 'AddEmptyNpcData', 'CreateDataBinMgr'))
    }
    report = {'dll': str(args.dll), 'image_base': pe.image_base, 'exports': {}, 'strings': {}}
    for name, rva in wanted.items():
        report['exports'][name] = {
            'rva': rva, 'direct_call_xrefs': pe.call_xrefs(rva),
            'hex': pe.hex_near(rva, before=0),
        }
    for value in (b'public/npc/NPCData.txt', b'Public/NPC/DynNPCData.txt'):
        rva = pe.find_bytes(value)
        report['strings'][value.decode()] = {'rva': rva, 'immediate_xrefs': pe.immediate_xrefs(rva)}
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
