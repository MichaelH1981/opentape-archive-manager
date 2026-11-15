#!/usr/bin/env python3
"""Read-only live access; migrate only private SQLite backups for a 0.9 rehearsal."""
import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from otam.catalog import Catalog
from otam.web.config import WebConfig
from otam.web.control import Control
from otam.web.query import CatalogView
from otam.web.replication import validate_snapshot


def fingerprint(db,table):
    h=hashlib.sha256();count=0
    for row in db.execute(f'SELECT * FROM "{table}" ORDER BY rowid'):
        h.update(json.dumps(tuple(row),ensure_ascii=True,separators=(',',':')).encode()+b'\n');count+=1
    return {'rows':count,'sha256':h.hexdigest()}


def backup(source,target):
    src=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True);dst=sqlite3.connect(target)
    try:src.backup(dst)
    finally:dst.close();src.close()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--report-root',type=Path,required=True)
    a=p.parse_args();os.umask(0o077);cfg=WebConfig.load(a.config)
    root=a.report_root.resolve();root.mkdir(parents=True,exist_ok=False,mode=0o700)
    old=root/'catalog-schema2.sqlite';new=root/'catalog-schema3.sqlite'
    backup(cfg.catalog,old);backup(old,new)
    with sqlite3.connect(old) as db:
        if db.execute('PRAGMA user_version').fetchone()[0]!=2:raise ValueError('Expected original schema 2')
        tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        before={t:fingerprint(db,t) for t in tables}
    c=Catalog(new)
    try:
        after={t:fingerprint(c.db,t) for t in tables}
        if before!=after:raise ValueError('Existing catalogue rows changed')
        if c.db.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('Invalid references')
    finally:c.close()
    validate_snapshot(new)
    state=root/'state';state.mkdir(mode=0o700)
    backup(cfg.state/'control.sqlite',state/'control.sqlite')
    (root/'node-before.json').write_bytes(a.config.read_bytes())
    copied=replace(cfg,catalog=new,state=state)
    view=CatalogView(copied,Control(state));overview=view.overview()
    # Installed old code must still read the original backup, independent of this checkout.
    env=dict(os.environ);env.pop('PYTHONPATH',None)
    code="from pathlib import Path; import otam; from otam.catalog import Catalog; c=Catalog(Path(__import__('sys').argv[1])); assert c.db.execute('pragma user_version').fetchone()[0]==2; c.close(); print(otam.__version__)"
    old_version=subprocess.run([sys.executable,'-c',code,str(old)],cwd='/tmp',env=env,check=True,capture_output=True,text=True).stdout.strip()
    report={'state':'VERIFIED','old_version':old_version,'old_schema':2,'new_schema':3,
            'base_tables_unchanged':before==after,'tables':before,
            'snapshot_validation':'PASSED','isolated_overview_available':overview['available'],
            'rollback_backup_readable_by_old_installation':True,'live_catalog_untouched':True}
    (root/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='tables'}))

if __name__=='__main__':main()
