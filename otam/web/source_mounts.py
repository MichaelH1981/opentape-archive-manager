"""Opt-in read-only source mounts via a separate, constrained root helper.

No shell commands or mount options come from the browser. SMB passwords exist
only in a private one-shot request and a root-only transient credentials file.
"""
from __future__ import annotations
import argparse
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import re
import signal
import sqlite3
import stat
import subprocess
import tempfile
import time
import uuid
from contextlib import closing
from ..common import SafetyError, encode, sync_dir
from .config import WebConfig
from .control import Control
from .power import _shared_io_lock

POLICY=Path('/etc/otam/source-mounts.json')
REGISTRY=Path('/var/lib/otam-source-mounts')
TARGETS=Path('/mnt/otam-sources')
SECRETS=Path('/run/otam-source-mounts')
USB_OPTIONS={'ext4':'noload','xfs':'norecovery','btrfs':'nologreplay','vfat':'','exfat':''}


def command(args, timeout=25):
    p=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
    try:
        out,err=p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid,signal.SIGTERM)
        try:p.communicate(timeout=3)
        except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.communicate()
        raise SafetyError('Mountaktion hat das Zeitlimit überschritten; Status vor Wiederholung prüfen')
    if p.returncode:
        raise SafetyError('Mountaktion fehlgeschlagen: '+err.strip()[:500])
    return out


def usb_devices():
    """Only unmounted supported USB filesystems on entirely unused USB disks."""
    raw=json.loads(command(['/usr/bin/lsblk','--json','-o','PATH,TYPE,FSTYPE,UUID,MOUNTPOINTS,TRAN'],10))
    result=[]
    def flatten(node):
        return [node]+[n for child in node.get('children',[]) for n in flatten(child)]
    for disk in raw.get('blockdevices',[]):
        nodes=flatten(disk)
        if disk.get('tran')!='usb' or any(any(x for x in n.get('mountpoints',[]) or []) for n in nodes):continue
        for node in nodes:
            if (node.get('uuid') and node.get('fstype') in USB_OPTIONS
                    and node.get('type') in ('disk','part') and re.fullmatch(r'/dev/[a-zA-Z0-9]+',node.get('path',''))):
                result.append({k:node[k] for k in ('path','uuid','fstype')})
    # An ambiguous UUID is not an identity.
    return [d for d in result if sum(x['uuid']==d['uuid'] for x in result)==1]


def validate(data, networks):
    if not isinstance(data,dict) or data.get('kind') not in ('nfs','smb','usb'):raise SafetyError('NFS, SMB oder USB auswählen')
    kind=data['kind']
    allowed={'kind','server','export'} if kind=='nfs' else {'kind','server','share','username','password','domain','version'} if kind=='smb' else {'kind','uuid'}
    if set(data)!=allowed:raise SafetyError('Unbekannte oder fehlende Mountparameter')
    for value in data.values():
        if not isinstance(value,str) or len(value)>1024 or any(c in value for c in ('\0','\n','\r')):raise SafetyError('Ungültiger Mountparameter')
    if kind=='usb':
        if not re.fullmatch(r'[A-Za-z0-9-]{4,128}',data['uuid']):raise SafetyError('Gültige USB-Dateisystem-UUID erforderlich')
        return
    try:address=ipaddress.IPv4Address(data['server'])
    except ValueError:raise SafetyError('Explizite NAS-IPv4-Adresse erforderlich, kein Hostname')
    if address.is_loopback or address.is_multicast or address.is_unspecified or not any(address in ipaddress.ip_network(n) for n in networks):
        raise SafetyError('NAS-Adresse liegt außerhalb der administrativ freigegebenen Netze')
    if kind=='nfs':
        value=data['export']
        if not value.startswith('/') or any(p in ('.','..') for p in value.split('/')) or '\\' in value or ',' in value:
            raise SafetyError('Absoluten NFS-Export ohne Pfadumgehung angeben')
    else:
        if not re.fullmatch(r'[A-Za-z0-9_. -]{1,100}',data['share']) or data['share'] in ('.','..'):raise SafetyError('Einfachen SMB-Freigabenamen angeben')
        if not data['username'] or data['version'] not in ('3.1.1','3.0','2.1'):raise SafetyError('SMB-Benutzer und unterstützte SMB-Version erforderlich')


def policy():
    s=POLICY.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:raise SafetyError('Unsichere administrative Mountfreigabe')
    value=json.loads(POLICY.read_text())
    if set(value)!={'allowed_networks'}:raise SafetyError('Ungültige administrative Mountfreigabe')
    for n in value['allowed_networks']:ipaddress.ip_network(n)
    return value


def unit_active():
    try:return subprocess.run(['/usr/bin/systemctl','is-active','--quiet','otam-source-mounts.path'],timeout=3).returncode==0
    except (OSError,subprocess.TimeoutExpired):return False


def listing(config, include_usb=True):
    items=[]
    try:attached={line.split()[4] for line in Path('/proc/self/mountinfo').read_text().splitlines()}
    except OSError:attached=set()
    if REGISTRY.exists():
        for p in sorted(REGISTRY.glob('*.json')):
            value=json.loads(p.read_text());value.pop('error_detail',None)
            if value.get('state')=='MOUNTED' and value.get('target') not in attached:
                value.update(state='NOT_MOUNTED',error='Dieser Mount ist im Webdienst nicht eingebunden; nach Neustart erneut einbinden')
            if value.get('state')=='RUNNING' and time.time()-value.get('time',0)>130:
                value.update(state='INTERRUPTED',error='Mounthelfer ohne Abschluss; Zustand vor Wiederholung administrativ prüfen')
            items.append(value)
    try:devices=usb_devices() if config.source_mounting and include_usb else []
    except (SafetyError,OSError):devices=[]
    return {'enabled':config.source_mounting and unit_active(),'items':items,
            'usb':devices,
            'message':'Nur lesend; NAS-Dateirechte bleiben wirksam. SMB-Passwörter werden nicht dauerhaft gespeichert.'}


def request(config, control, data, user):
    if not config.source_mounting or config.role!='archive' or not unit_active():raise SafetyError('Quellen-Mountdienst ist administrativ nicht aktiviert')
    validate(data,policy()['allowed_networks'])
    from ..storage import io_lock
    with io_lock():
        with control.connect() as db:
            if db.execute("select 1 from commands where state in ('RUNNING','QUEUED')").fetchone():raise SafetyError('Mounten erst nach Abschluss wartender und laufender Aufträge')
        key=str(uuid.uuid4());folder=config.state/'source-mount-requests'
        folder.mkdir(mode=0o700,exist_ok=True)
        if folder.is_symlink():raise SafetyError('Unsicheres Anfrageverzeichnis')
        value={'id':key,'created':time.time(),'user_id':user,'data':data}
        # A non-.json temporary name cannot trigger the helper before publication.
        fd,name=tempfile.mkstemp(prefix='.pending-',dir=folder)
        temp=Path(name)
        try:
            with os.fdopen(fd,'wb') as f:f.write(encode(value));f.flush();os.fsync(f.fileno())
            os.replace(temp,folder/(key+'.json'));sync_dir(folder)
        finally:temp.unlink(missing_ok=True)
    return {'id':key,'state':'REQUESTED'}


def publish(key,value,owner):
    REGISTRY.mkdir(mode=0o750,exist_ok=True)
    s=REGISTRY.lstat()
    if not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:raise SafetyError('Unsicheres Mountjournal')
    os.chown(REGISTRY,0,owner.pw_gid)
    fd,name=tempfile.mkstemp(prefix='.report-',dir=REGISTRY)
    temp=Path(name)
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(encode(value));f.flush();os.fsync(f.fileno());os.fchown(f.fileno(),0,owner.pw_gid);os.fchmod(f.fileno(),0o640)
        os.replace(temp,REGISTRY/(key+'.json'));sync_dir(REGISTRY)
    finally:temp.unlink(missing_ok=True)


def execute_mount(config,data,key,owner):
    validate(data,policy()['allowed_networks'])
    TARGETS.mkdir(mode=0o755,exist_ok=True)
    s=TARGETS.lstat()
    if not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:raise SafetyError('Unsicherer Mountwurzelpfad')
    target=TARGETS/key;target.mkdir(mode=0o755,exist_ok=False)
    options='ro,nosuid,nodev,noexec'
    secret=None
    try:
        if data['kind']=='nfs':
            source=data['server']+':'+data['export'];fs='nfs';options+=',vers=4.1'
        elif data['kind']=='smb':
            source='//'+data['server']+'/'+data['share'];fs='cifs'
            folder=SECRETS;folder.mkdir(mode=0o700,exist_ok=True)
            info=folder.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode&0o077:raise SafetyError('Unsicheres Passwortverzeichnis')
            fd,name=tempfile.mkstemp(prefix='credentials-',dir=folder);secret=Path(name)
            with os.fdopen(fd,'w') as f:
                f.write('username='+data['username']+'\npassword='+data['password']+'\ndomain='+data['domain']+'\n');f.flush();os.fsync(f.fileno())
            options+=f",vers={data['version']},credentials={secret},uid={owner.pw_uid},gid={owner.pw_gid},forceuid,forcegid,file_mode=0400,dir_mode=0500"
        else:
            selected=[d for d in usb_devices() if d['uuid']==data['uuid']]
            if len(selected)!=1:raise SafetyError('USB-Dateisystem nicht eindeutig, bereits eingebunden oder auf nicht freiem USB-Datenträger')
            selected=selected[0];source=selected['path'];fs=selected['fstype']
            if not stat.S_ISBLK(os.stat(source).st_mode):raise SafetyError('USB-Quelle ist kein Blockgerät')
            extra=USB_OPTIONS[fs]
            if extra:options+=','+extra
            if fs in ('vfat','exfat'):options+=f',uid={owner.pw_uid},gid={owner.pw_gid},fmask=0377,dmask=0277'
        command(['/usr/bin/mount','-t',fs,'-o',options,'--',source,str(target)])
        observed=json.loads(command(['/usr/bin/findmnt','--json','--mountpoint',str(target),'-o','TARGET,SOURCE,FSTYPE,OPTIONS,UUID']))['filesystems']
        if (len(observed)!=1 or not {'ro','nosuid','nodev','noexec'} <= set(observed[0]['options'].split(','))
                or observed[0]['target']!=str(target)
                or observed[0]['fstype'] not in (('nfs','nfs4') if data['kind']=='nfs' else (fs,))
                or (data['kind']=='usb' and str(observed[0].get('uuid','')).lower()!=data['uuid'].lower())):
            try:command(['/usr/bin/umount','--',str(target)],10)
            except (SafetyError,OSError):raise SafetyError('Unsicheres Mountergebnis; Aushängen fehlgeschlagen. Administratorprüfung erforderlich')
            raise SafetyError('Lesender Mount konnte nicht bestätigt werden; wieder ausgehängt')
        return {'id':key,'state':'MOUNTED','kind':data['kind'],'target':str(target),'source':source,'read_only':True,'time':time.time()}
    finally:
        if secret is not None:secret.unlink(missing_ok=True)


def process(config):
    if os.geteuid()!=0 or config.role!='archive':raise SafetyError('Root-Mounthelfer auf Archivnode erforderlich')
    owner=pwd.getpwnam('otam');folder=config.state/'source-mount-requests'
    if not folder.exists():return
    fd=os.open(folder,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        if info.st_uid!=owner.pw_uid or info.st_mode&0o077:raise SafetyError('Unsicheres Anfrageverzeichnis')
        for name in os.listdir(fd):
            if not re.fullmatch(r'[a-f0-9-]{36}\.json',name):continue
            key=name[:-5];uuid.UUID(key)
            # Root-owned result is also a replay guard, including previous failures.
            if (REGISTRY/(key+'.json')).exists():
                os.unlink(name,dir_fd=fd);continue
            request_fd=os.open(name,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW,dir_fd=fd)
            try:
                s=os.fstat(request_fd)
                if not stat.S_ISREG(s.st_mode) or s.st_uid!=owner.pw_uid or s.st_nlink!=1 or not 0<s.st_size<=65536 or s.st_mode&0o077:raise SafetyError('Unsichere Mountanfrage')
                value=json.loads(os.read(request_fd,65537))
            finally:os.close(request_fd)
            publish(key,{'id':key,'state':'RUNNING','time':time.time()},owner)
            os.unlink(name,dir_fd=fd);sync_dir(folder)
            public={'id':key,'state':'FAILED','time':time.time(),'target':str(TARGETS/key)}
            try:
                if not config.source_mounting:raise SafetyError('Quellen-Mountverwaltung ist administrativ deaktiviert')
                if set(value)!={'id','created','user_id','data'} or value['id']!=key or not 0<=time.time()-value['created']<=120:raise SafetyError('Mountanfrage abgelaufen oder verändert')
                publish(key,{'id':key,'state':'RUNNING','time':time.time()},owner)
                with _shared_io_lock(config,owner.pw_uid):
                    with closing(sqlite3.connect(config.state/'control.sqlite')) as db:
                        db.execute('pragma trusted_schema=OFF')
                        db.execute('pragma query_only=ON')
                        if not db.execute("select 1 from users where id=? and role='admin' and enabled=1",(value['user_id'],)).fetchone():raise SafetyError('Aktiver Administrator erforderlich')
                        if db.execute("select 1 from commands where state in ('RUNNING','QUEUED')").fetchone():raise SafetyError('Auftrag läuft; nicht während Archivarbeit mounten')
                    public=execute_mount(config,value['data'],key,owner)
            except Exception as error:public['error']=str(error)[:700]
            finally:
                value.clear();publish(key,public,owner)
    finally:os.close(fd)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);args=p.parse_args()
    process(WebConfig.load(args.config))
