"""Owned, immutable local source snapshots before any media binding.

Payload is read once from the original source. Final, medium-bound TARs are
subsequently built from this snapshot, with the recorded hashes rechecked.
"""
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from .archive import inventory, source_fd
from .common import SafetyError, encode, sync_dir
from .staging import fingerprint
from .storage import require_local
from .capture import progress_recorder


def location(staging, job):
    uuid.UUID(job)
    return staging / ('otam-source-' + job)


def validate(staging, job, capture):
    parent=location(staging,job)
    if parent.is_symlink() or parent.resolve().parent!=staging.resolve():
        raise SafetyError('Unsichere lokale Quellenkopie')
    marker=parent/'owner.json'
    if marker.is_symlink() or json.loads(marker.read_bytes())!={'format':'otam-source-capture-v1','job_id':job}:
        raise SafetyError('Eigentümer der Quellenkopie stimmt nicht überein')
    root=parent/'data'
    if root.is_symlink() or root.resolve().parent!=parent.resolve():
        raise SafetyError('Unsicheres Datenverzeichnis der Quellenkopie')
    expected=capture['entries']
    entries=inventory(root,metadata_only=True,expected=expected)
    for entry,old in zip(entries,expected):
        path=root/entry['path']
        if path.stat().st_mode & 0o222 or fingerprint(path)!=old['fingerprint']:
            raise SafetyError('Lokale Quellenkopie wurde verändert: '+entry['path'])
    return root,expected


def prepare(catalog, job, draft, staging):
    source=Path(draft['source'])
    staging=staging.resolve()
    if staging.is_relative_to(source) or source.is_relative_to(staging):
        raise SafetyError('Staging und Quelle müssen getrennt sein')
    required=draft['payload_bytes']+draft['required_estimate']
    if require_local(staging)['free'] < required:
        raise SafetyError(f'Lokale Quellenübernahme benötigt Platz für Quellkopie und TARs: {required} Byte')
    inventory(source,draft['selected_paths'],metadata_only=True,
              excluded=draft.get('excluded_paths'),expected=draft.get('inventory_entries',draft['source_entries']))
    parent=location(staging,job)
    parent.mkdir(mode=0o700,exist_ok=False)  # Never overwrite an earlier partial capture.
    with (parent/'owner.json').open('xb') as owner:
        owner.write(encode({'format':'otam-source-capture-v1','job_id':job}));owner.flush();os.fsync(owner.fileno())
    root=parent/'data';root.mkdir(mode=0o700);sync_dir(parent);sync_dir(staging)
    results=[];done=0;started=time.monotonic();progress=progress_recorder(catalog,job)
    for entry in draft['source_entries']:
        target=root/entry['path'];target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        partial=target.with_name('.otam-partial-'+str(uuid.uuid4()))
        h=hashlib.sha256()
        with os.fdopen(source_fd(source,entry['path']),'rb') as incoming,partial.open('xb') as out:
            before=os.fstat(incoming.fileno())
            actual=[before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns]
            if actual!=entry['fingerprint']:raise SafetyError('Quelle seit Planung verändert: '+entry['path'])
            while chunk:=incoming.read(1024*1024):
                out.write(chunk);h.update(chunk);done+=len(chunk)
                progress({'phase':'STAGING','bytes':done,'total_bytes':draft['payload_bytes'],'files':len(results),
                          'total_files':len(draft['source_entries']),'path':entry['path'],'elapsed_seconds':time.monotonic()-started})
            after=os.fstat(incoming.fileno())
            if [after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns]!=actual:
                raise SafetyError('Quelle während Übernahme verändert: '+entry['path'])
            if out.tell()!=entry['size']:raise SafetyError('Quelldateigröße verändert')
            out.flush();os.fsync(out.fileno())
        os.utime(partial,ns=(entry['mtime_ns'],entry['mtime_ns']));partial.chmod(0o400)
        # Exclusive publication, even if another actor created a target meanwhile.
        os.link(partial,target);partial.unlink();sync_dir(target.parent)
        results.append({**entry,'sha256':h.hexdigest(),'fingerprint':fingerprint(target)})
    sync_dir(root)
    capture={'format':'otam-source-capture-v1','entries':results,'bytes':done,'created':time.time()}
    validate(staging,job,capture)
    progress({'phase':'STAGING','bytes':done,'total_bytes':done,'files':len(results),'total_files':len(results),
              'path':'','elapsed_seconds':time.monotonic()-started,'complete':True})
    return capture


def cleanup(staging, job, capture):
    """Remove only owned source copies after all final TARs have been published."""
    root,entries=validate(staging,job,capture)
    parent=root.parent
    if {p.name for p in parent.iterdir()}!={'owner.json','data'}:
        raise SafetyError('Unbekannte Dateien im lokalen Quellenverzeichnis; keine Bereinigung')
    for entry in entries:
        (root/entry['path']).unlink()
    for base,dirs,files in os.walk(root,topdown=False,followlinks=False):
        if files:raise SafetyError('Unerwartete Dateien während Quellenbereinigung')
        Path(base).rmdir()
    (parent/'owner.json').unlink();parent.rmdir();sync_dir(staging)
