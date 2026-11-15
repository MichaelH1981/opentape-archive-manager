#!/usr/bin/env python3
"""Standalone recovery of OTAM full-generation PAX TARs. Standard library only.

First copy the data TAR tape files to disk using the medium's RECOVERY.txt.
Supply every DATA TAR of one generation; omit headers and receipt TARs.
No OTAM installation, catalog or Borg installation is needed for reconstruction.
Borg keys and a subsequent Borg check are separate requirements.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tarfile
import tempfile


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode()


def recover(archives, target, expected_hash=None):
    target = Path(target).absolute()
    if target.exists() or target.is_symlink():
        raise ValueError('Output must be a new directory')
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.otam-recovery-', dir=target.parent))
    descriptor = None; files = {}; seen_archives = set(); media = set()
    # On failure retain the private directory for inspection; never publish as complete.
    for path in archives:
        with tarfile.open(path, mode='r|') as tar:
            payloads = iter(tar)
            first = next(payloads, None)
            if not first or first.name != 'OTAM/manifest.json' or not first.isfile() or first.size > 32*1024**2:
                raise ValueError('Not an OTAM data TAR')
            manifest = json.load(tar.extractfile(first))
            context = manifest.get('rotation')
            if not context or context.get('format') != 'otam-full-generation-v1':
                raise ValueError('Missing supported generation descriptor')
            if descriptor is not None and descriptor != context:
                raise ValueError('Mixed generations or changed descriptors')
            descriptor = context
            if manifest['archive_id'] in seen_archives:
                raise ValueError('Duplicate archive')
            seen_archives.add(manifest['archive_id']); media.add(manifest['media_id'])
            entries = manifest['files']
            for entry in entries:
                name = entry['path']; parts = PurePosixPath(name).parts
                if (not parts or name.startswith('/') or '\\' in name
                        or any(x in ('', '.', '..') for x in name.split('/')) or name in files):
                    raise ValueError('Unsafe or duplicate payload path')
                member = next(payloads, None)
                if (not member or not member.isfile() or member.name != 'data/' + name or member.size != entry['size']):
                    raise ValueError('TAR payload differs from manifest')
                output = temporary.joinpath(*parts); output.parent.mkdir(parents=True, exist_ok=True)
                h = hashlib.sha256(); count = 0
                with output.open('xb') as out, tar.extractfile(member) as source:
                    while block := source.read(1024*1024):
                        out.write(block); h.update(block); count += len(block)
                    out.flush(); os.fsync(out.fileno())
                if count != entry['size'] or h.hexdigest() != entry['sha256']:
                    raise ValueError('Payload hash/size mismatch: ' + name)
                os.utime(output, ns=(entry['mtime_ns'], entry['mtime_ns']))
                files[name] = {k:entry[k] for k in ('path', 'size', 'sha256')}
            if next(payloads, None) is not None:
                raise ValueError('Unexpected extra TAR member')
    inventory = [files[name] for name in sorted(files)]
    checksum = hashlib.sha256(canonical(inventory)).hexdigest()
    if (not descriptor or set(descriptor['media_ids']) != media
            or descriptor['file_count'] != len(files)
            or descriptor['payload_bytes'] != sum(x['size'] for x in inventory)
            or descriptor['inventory_sha256'] != checksum
            or (expected_hash is not None and expected_hash != checksum)):
        raise ValueError('Incomplete generation or inventory checksum mismatch')
    target.mkdir(mode=0o700, exist_ok=False)
    for name in files:
        dest = target / name; dest.parent.mkdir(parents=True, exist_ok=True)
        os.link(temporary / name, dest)
    # All sources are owned files; keep no redundant payload after successful publication.
    for name in files:
        (temporary / name).unlink()
    for folder in sorted(temporary.rglob('*'), key=lambda p:len(p.parts), reverse=True):
        folder.rmdir()
    temporary.rmdir()
    return checksum


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True)
    parser.add_argument('--expected-inventory-hash', help='Optional separately trusted SHA-256')
    parser.add_argument('archives', nargs='+')
    args = parser.parse_args()
    try:
        print('VERIFIED', recover(args.archives, args.target, args.expected_inventory_hash))
    except (ValueError, OSError, KeyError, tarfile.TarError) as error:
        parser.exit(1, 'Recovery failed; private partial data retained: ' + str(error) + '\n')
