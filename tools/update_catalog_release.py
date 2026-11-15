#!/usr/bin/env python3
"""Update ONLY the standalone catalog node; retain private backups and rollback.

Run as root on the catalog server with an explicitly checked release wheel hash.
Never changes users, LAN binding, configuration or physical workflow gates.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time
import urllib.request


def run(*args,**kwargs):
    return subprocess.run(list(args),check=True,**kwargs)


def file_hash(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while block:=f.read(1024*1024):h.update(block)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--wheel',required=True,type=Path)
    p.add_argument('--sha256',required=True)
    a=p.parse_args()
    if os.geteuid()!=0:raise SystemExit('Run with sudo on the catalog server')
    os.umask(0o077)
    cfg_file=Path('/etc/otam/node.json');cfg=json.loads(cfg_file.read_text())
    if cfg.get('role')!='catalog':raise SystemExit('Refusing to update an archive node')
    if len(a.sha256)!=64 or file_hash(a.wheel)!=a.sha256:raise SystemExit('Release wheel SHA-256 mismatch')
    root=Path('/var/lib/otam/reports')/('catalog-update-090-'+time.strftime('%Y%m%d-%H%M%S',time.gmtime()))
    root.mkdir(parents=True,mode=0o700,exist_ok=False)
    wheel=root/a.wheel.name;shutil.copyfile(a.wheel,wheel)
    if file_hash(wheel)!=a.sha256:raise SystemExit('Copied release wheel SHA-256 mismatch')
    if not wheel.name.endswith('.whl') or '/' in wheel.name:raise SystemExit('Wheel required')
    venv=Path('/opt/otam/venv');saved=root/'venv-before'
    report={'state':'PREPARING','wheel_sha256':a.sha256,'version':'0.9.0'}
    def save():
        (root/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    save();stopped=False;backed_up=False
    try:
        run('systemctl','stop','otam-web.service');stopped=True
        shutil.copytree(venv,saved,symlinks=True);backed_up=True
        shutil.copy2(cfg_file,root/'node-before.json')
        src=sqlite3.connect('file:'+str(Path(cfg['state'])/'control.sqlite')+'?mode=ro',uri=True)
        dst=sqlite3.connect(root/'control-before.sqlite')
        try:src.backup(dst)
        finally:dst.close();src.close()
        # Backups stay private; installed program files must remain readable by the service account.
        old_mask=os.umask(0o022)
        try:run(str(venv/'bin/python'),'-m','pip','install','--no-index','--no-deps',str(wheel))
        finally:os.umask(old_mask)
        run('runuser','-u','otam','--',str(venv/'bin/python'),'-c',"import otam; from otam.web.app import create_app; assert otam.__version__=='0.9.0'")
        run('systemctl','start','otam-web.service');stopped=False
        host=cfg.get('host','127.0.0.1')
        if host in ('0.0.0.0','::'):host='127.0.0.1'
        if ':' in host:host='['+host+']'
        url='http://'+host+':'+str(cfg.get('port',8765))+'/healthz'
        error=None
        for _ in range(20):
            try:
                with urllib.request.urlopen(url,timeout=2) as response:body=json.load(response)
                if body.get('status')!='ok' or body.get('role')!='catalog':raise ValueError('Wrong health result')
                error=None;break
            except Exception as exc:error=exc;time.sleep(.5)
        if error:raise error
        if cfg_file.read_bytes()!=(root/'node-before.json').read_bytes():raise ValueError('Configuration changed')
        report.update(state='VERIFIED',health=body,configuration_unchanged=True);save()
        print('VERIFIED: catalog 0.9.0; backup '+str(root))
    except BaseException as exc:
        report.update(state='FAILED',error=str(exc));save()
        if backed_up:
            run('systemctl','stop','otam-web.service');stopped=True
            failed=venv.with_name('venv-failed-090-'+str(int(time.time())))
            os.rename(venv,failed)
            shutil.copytree(saved,venv,symlinks=True)
            report.update(rollback='previous venv restored',failed_venv=str(failed));save()
        if stopped:run('systemctl','start','otam-web.service')
        raise

if __name__=='__main__':main()
