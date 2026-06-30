#!/usr/bin/env python3
"""
Dixell XWEB Library Unpacker
Handles both formats:

  XWEB EVO (.zip):  XOR key = filename[i % min(20,len)] ^ 0xA1, cycling period 20
  XWEB 500 (.xw5):  XOR key = 0xA7 (constant), gzip-compressed XWEB500UF text protocol

Usage:
  python3 xweb_evo_unpack.py <file.zip>           # XWEB EVO ZIP package
  python3 xweb_evo_unpack.py <file.xw5>           # XWEB 500 single library
  python3 xweb_evo_unpack.py <encrypted> <fname_key> [outdir]  # raw EVO file
"""

import sys
import os
import io
import gzip
import tarfile
import zipfile
import argparse


def make_key(filename: str, period: int = 20) -> bytes:
    """Build the period-20 XOR key from the bare filename (no path)."""
    fname = os.path.basename(filename).encode()
    n = min(len(fname), period)
    base = bytearray(period)
    for i in range(n):
        base[i] = fname[i] ^ 0xA1
    for i in range(n, period):
        base[i] = 0xA1  # fname[i] == 0x00, 0x00 ^ 0xA1 = 0xA1
    return bytes(base)


def decrypt(data: bytes, key: bytes) -> bytes:
    period = len(key)
    return bytes(data[i] ^ key[i % period] for i in range(len(data)))


def detect_and_extract(decrypted: bytes, name: str, outdir: str) -> list[str]:
    """
    Detect the format of decrypted bytes and extract/write to outdir.
    Returns list of files written.
    """
    written = []

    # gzip (.tar.gz or .gz)
    if decrypted[:2] == b'\x1f\x8b':
        try:
            raw = gzip.decompress(decrypted)
        except Exception as e:
            print(f"    [!] gzip decompress failed: {e}")
            _write(decrypted, outdir, name + '.dec')
            return [os.path.join(outdir, name + '.dec')]

        # Try as tar archive
        try:
            with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
                tf.extractall(outdir)
                written = [m.name for m in tf.getmembers() if not m.isdir()]
                print(f"    Extracted tar: {len(written)} file(s)")
                return written
        except tarfile.TarError:
            pass

        # Plain gzip (not tar)
        bare = name
        for ext in ('.tar.gz', '.tgz', '.gz'):
            if bare.endswith(ext):
                bare = bare[: -len(ext)]
                break
        dest = _write(raw, outdir, bare)
        return [dest]

    # ZIP
    if decrypted[:4] == b'PK\x03\x04':
        dest = _write(decrypted, outdir, name)
        print(f"    Wrote ZIP: {dest}")
        return [dest]

    # Plain text / XML / shell script — write as-is
    dest = _write(decrypted, outdir, name)
    try:
        preview = decrypted[:80].decode('utf-8').replace('\n', ' ')
    except UnicodeDecodeError:
        preview = decrypted[:20].hex()
    print(f"    Wrote: {dest}  ({preview!r})")
    return [dest]


def _write(data: bytes, outdir: str, name: str) -> str:
    dest = os.path.join(outdir, os.path.basename(name))
    os.makedirs(os.path.dirname(dest) if os.path.dirname(dest) else outdir, exist_ok=True)
    with open(dest, 'wb') as f:
        f.write(data)
    return dest


def unpack_zip(zippath: str, outdir: str) -> None:
    os.makedirs(outdir, exist_ok=True)
    with zipfile.ZipFile(zippath) as zf:
        names = zf.namelist()
        print(f"ZIP contains {len(names)} file(s):")
        for name in names:
            raw = zf.read(name)
            bare = os.path.basename(name)
            key = make_key(bare)
            dec = decrypt(raw, key)
            print(f"  {name}  ({len(raw)} bytes)")
            detect_and_extract(dec, bare, outdir)


def unpack_file(filepath: str, key_name: str, outdir: str) -> None:
    os.makedirs(outdir, exist_ok=True)
    with open(filepath, 'rb') as f:
        raw = f.read()
    key = make_key(key_name)
    dec = decrypt(raw, key)
    print(f"File: {filepath}  ({len(raw)} bytes), key from: {key_name!r}")
    detect_and_extract(dec, os.path.basename(filepath), outdir)


def unpack_xw5(filepath: str, outdir: str) -> None:
    """Decrypt and extract a XWEB 500 .xw5 library file."""
    os.makedirs(outdir, exist_ok=True)
    with open(filepath, 'rb') as f:
        raw = f.read()

    dec = bytes(b ^ 0xA7 for b in raw)

    if dec[:2] != b'\x1f\x8b':
        print(f"[!] Not a valid .xw5 file (expected gzip after XOR 0xA7)")
        return

    content = gzip.decompress(dec).decode('latin-1')

    # Parse XWEB500UF protocol: space-delimited commands
    # GETFILE|path|size\ndata...  embeds files inline
    tokens = content.split(' ')
    i = 0
    files_written = []
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith('GETFILE|'):
            parts = tok.split('|')
            fpath = parts[1]
            size = int(parts[2]) if len(parts) > 2 else 0
            # Remaining content after this token is the file data (space-joined)
            remainder = ' '.join(tokens[i + 1:])
            file_data = remainder[:size].encode('latin-1')
            dest = _write(file_data, outdir, fpath)
            files_written.append(dest)
            print(f"  Extracted: {fpath}  ({size} bytes)")
            # Advance past the file data
            consumed = len(file_data.decode('latin-1').split(' '))
            i += consumed + 1
        else:
            i += 1

    if not files_written:
        # Fallback: write the raw decompressed text
        dest = _write(content.encode('latin-1'), outdir,
                      os.path.splitext(os.path.basename(filepath))[0] + '.txt')
        print(f"  Wrote decompressed text: {dest}")
        files_written.append(dest)

    print(f"  {len(files_written)} file(s) extracted")


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Decrypt and extract Dixell XWEB / XWEB EVO library packages'
    )
    parser.add_argument('input', help='.zip (EVO), .xw5 (XWEB 500), or raw encrypted file')
    parser.add_argument('arg2', nargs='?', help='Output directory (ZIP/.xw5) or key filename (raw file)')
    parser.add_argument('arg3', nargs='?', help='Output directory (raw file mode)')
    args = parser.parse_args()

    # XWEB 500 format
    if args.input.endswith('.xw5'):
        outdir = args.arg2 or (os.path.splitext(args.input)[0] + '_unpacked')
        print(f"Mode: XWEB 500 .xw5  →  {outdir}/")
        unpack_xw5(args.input, outdir)
    # XWEB EVO ZIP
    elif zipfile.is_zipfile(args.input):
        outdir = args.arg2 or (os.path.splitext(args.input)[0] + '_unpacked')
        print(f"Mode: XWEB EVO ZIP  →  {outdir}/")
        unpack_zip(args.input, outdir)
    # Raw EVO encrypted file
    else:
        if not args.arg2:
            parser.error("Raw file mode requires the key filename as second argument")
        key_name = args.arg2
        outdir = args.arg3 or (os.path.splitext(args.input)[0] + '_unpacked')
        print(f"Mode: raw EVO file  →  {outdir}/")
        unpack_file(args.input, key_name, outdir)

    print("Done.")


if __name__ == '__main__':
    main()
