"""Drop ancillary PNG chunks with a bad CRC (some community hair ships a broken iCCP profile, which
browsers and Pillow reject outright). Pixels are untouched.

    .venv/bin/python fix_pngs.py assets_src
"""
import struct
import sys
import zlib
from pathlib import Path


def fix(path: Path) -> bool:
    b = path.read_bytes()
    if b[:8] != b"\x89PNG\r\n\x1a\n":
        return False
    out, i, dropped = [b[:8]], 8, False
    while i + 12 <= len(b):
        (n,) = struct.unpack(">I", b[i:i + 4])
        kind, chunk = b[i + 4:i + 8], b[i:i + 12 + n]
        (crc,) = struct.unpack(">I", b[i + 8 + n:i + 12 + n])
        if zlib.crc32(b[i + 4:i + 8 + n]) & 0xFFFFFFFF != crc and kind[0] & 0x20:  # lowercase first letter = ancillary
            dropped = True
        else:
            out.append(chunk)
        i += 12 + n
    if dropped:
        path.write_bytes(b"".join(out))
    return dropped


if __name__ == "__main__":
    fixed = [p for p in Path(sys.argv[1]).rglob("*.png") if fix(p)]
    print(f"fixed {len(fixed)} png", *[str(p) for p in fixed], sep="\n  ")
