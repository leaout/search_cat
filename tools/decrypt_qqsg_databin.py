"""Read-only experiment for QQSG DataBin text protection.

The TEA block and chaining rules mirror the routines statically identified in
DataBin.dll.  The command never modifies the installed client or its package.
"""
import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugin_platform.qqsg_data import QQSGPackage


MASK32 = 0xFFFFFFFF
DELTA = 0x9E3779B9
DEFAULT_KEY = b'pleasebecareful0'


def tea_decrypt(block: bytes, key: bytes) -> bytes:
    """Decrypt one big-endian TEA block with a 128-bit key."""
    if len(block) != 8 or len(key) != 16:
        raise ValueError('TEA requires an 8-byte block and a 16-byte key')
    left, right = struct.unpack('>2I', block)
    words = struct.unpack('>4I', key)
    total = (DELTA * 16) & MASK32
    for _ in range(16):
        right = (right - (((left << 4) + words[2]) ^ (left + total) ^ ((left >> 5) + words[3]))) & MASK32
        left = (left - (((right << 4) + words[0]) ^ (right + total) ^ ((right >> 5) + words[1]))) & MASK32
        total = (total - DELTA) & MASK32
    return struct.pack('>2I', left, right)


def xor(left: bytes, right: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(left, right))


def qqtea_decrypt(payload: bytes, key: bytes = DEFAULT_KEY) -> bytes:
    """Decrypt Tencent's chained TEA envelope and validate its zero trailer."""
    if len(payload) < 16 or len(payload) % 8:
        raise ValueError('encrypted payload length must be a multiple of 8 and at least 16')
    previous_cipher = payload[:8]
    previous_plain = tea_decrypt(previous_cipher, key)
    clear = bytearray(previous_plain)
    for offset in range(8, len(payload), 8):
        current_cipher = payload[offset:offset + 8]
        current_plain = xor(tea_decrypt(xor(current_cipher, previous_plain), key), previous_cipher)
        # The next TEA input is the pre-encryption block (plain XOR previous cipher).
        previous_plain = xor(current_plain, previous_cipher)
        previous_cipher = current_cipher
        clear.extend(current_plain)
    padding = clear[0] & 7
    start = padding + 3
    if len(clear) - start < 7 or clear[-7:] != b'\0' * 7:
        raise ValueError('QQ TEA trailer validation failed')
    return bytes(clear[start:-7])


def text_quality(payload: bytes) -> tuple[str, float, str]:
    best = ('', 0.0, '')
    for encoding in ('gb18030', 'utf-8', 'utf-16-le'):
        try:
            value = payload.decode(encoding)
        except UnicodeDecodeError:
            continue
        printable = sum(character.isprintable() or character in '\r\n\t' for character in value)
        score = printable / max(1, len(value))
        if score > best[1]:
            best = (encoding, score, value[:240].replace('\r', '\\r').replace('\n', '\\n'))
    return best


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('package', type=Path)
    parser.add_argument('names', nargs='*', default=[
        'res/Txt/Public/NPC/NPCData.txt',
        'res/Txt/Public/Task/TaskDesc.txt',
        'res/Txt/Public/Item/ItemData.txt',
    ])
    args = parser.parse_args()
    package = QQSGPackage(args.package)
    for name in args.names:
        try:
            raw = package.read(name)
        except (FileNotFoundError, ValueError) as error:
            print(f'{name}: {error}')
            continue
        print(f'{name}: size={len(raw)}, magic={raw[:4].hex(" ")}')
        attempts = [('after-header', raw[4:]), ('whole-file', raw)]
        for label, encrypted in attempts:
            try:
                clear = qqtea_decrypt(encrypted)
                encoding, quality, preview = text_quality(clear)
                print(f'  {label}: OK, clear={len(clear)}, encoding={encoding or "?"}, quality={quality:.3f}')
                print(f'    {preview!r}')
            except ValueError as error:
                print(f'  {label}: {error}')


if __name__ == '__main__':
    main()
