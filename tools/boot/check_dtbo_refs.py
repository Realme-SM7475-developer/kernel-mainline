#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check stock Android DTBO external references against a mainline base DTB.

Reads a selected, uncompressed Android DT table entry. Never modifies inputs.
Passing this check establishes reference availability only, not merge validity
or bootability. Requires fdtget from dtc.
"""

import argparse
from pathlib import Path
import struct
import subprocess
import tempfile


def extract_entry(data, index):
    if len(data) < 32:
        raise ValueError('truncated DT table header')
    magic, total, header, entry_size, count, offset, page, version = struct.unpack_from('>8I', data)
    if magic != 0xd7b7ab1e or version != 0:
        raise ValueError('expected an uncompressed Android DT table v0')
    if not 32 <= header <= total <= len(data) or entry_size < 32:
        raise ValueError('invalid DT table sizes')
    if offset < header or offset + entry_size * count > total:
        raise ValueError('DT entry table outside image')
    if not 0 <= index < count:
        raise ValueError('DTBO index outside table')
    size, start = struct.unpack_from('>2I', data, offset + index * entry_size)
    if start < offset + entry_size * count or size < 40 or start + size > total:
        raise ValueError('DTBO payload outside image')
    blob = data[start:start + size]
    if struct.unpack_from('>2I', blob) != (0xd00dfeed, size):
        raise ValueError('entry is not one complete uncompressed FDT')
    return blob


def missing_references(base, overlay):
    result = subprocess.run(['fdtget', '-p', str(overlay), '/__fixups__'],
                            capture_output=True, text=True)
    # Check existence separately: absence is valid for a self-contained overlay.
    nodes = subprocess.run(['fdtget', '-l', str(overlay), '/'],
                           capture_output=True, text=True, check=True).stdout.split()
    if '__fixups__' not in nodes:
        return []
    if result.returncode:
        raise ValueError(result.stderr.strip())
    missing = []
    for name in result.stdout.split():
        target = subprocess.run(['fdtget', '-t', 's', str(base), '/__symbols__', name],
                                capture_output=True, text=True)
        if target.returncode:
            missing.append(name)
            continue
        phandle = subprocess.run(['fdtget', '-t', 'x', str(base), target.stdout.strip(), 'phandle'],
                                 capture_output=True, text=True)
        if phandle.returncode or phandle.stdout.strip() in ('0', 'ffffffff'):
            missing.append(name)
    return missing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dtb', type=Path, required=True)
    parser.add_argument('--stock-dtbo', type=Path, required=True)
    parser.add_argument('--index', type=int, required=True,
                        help='entry selected by the installed ABL; see its log')
    args = parser.parse_args()
    try:
        blob = extract_entry(args.stock_dtbo.read_bytes(), args.index)
        with tempfile.TemporaryDirectory() as directory:
            overlay = Path(directory) / 'overlay.dtbo'
            overlay.write_bytes(blob)
            missing = missing_references(args.dtb, overlay)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(2, f'{error}\n')
    if missing:
        parser.exit(1, f'DTBO entry {args.index}: {len(missing)} unresolved base references:\n'
                    + '\n'.join(missing) + '\n')
    print('External references resolve; overlay merge and bootability are unverified.')


if __name__ == '__main__':
    main()
