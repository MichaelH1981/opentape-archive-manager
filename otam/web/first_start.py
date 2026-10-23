"""One-use first administrator enrollment, bound to a local private setup token."""
import hashlib
import hmac
import os
import stat
import time
import uuid
from fastapi import HTTPException
from .accounts import USERNAME
from .config import password_hash


def required(config, control):
    if config.setup_token_file is None:
        return False
    with control.connect() as db:
        return not db.execute('SELECT 1 FROM users LIMIT 1').fetchone() and not db.execute(
            "SELECT 1 FROM settings WHERE key='first_start_completed'").fetchone()


def enroll(config, control, username, password, confirmation, token, ip):
    if not required(config,control):
        raise HTTPException(409,'Ersteinrichtung ist nicht verfügbar')
    # Count rejected enrollment attempts before any expensive password hash.
    now=time.time();key='first-start:'+ip
    with control.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('DELETE FROM attempts WHERE time<?',(now-900,))
        if db.execute('SELECT count(*) FROM attempts WHERE ip=?',(key,)).fetchone()[0]>=10:
            raise HTTPException(429,'Zu viele Versuche; nach 15 Minuten erneut versuchen')
        db.execute('INSERT INTO attempts VALUES(?,?)',(key,now))
    path=config.setup_token_file
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise HTTPException(409,'Einrichtungsschlüssel benötigt eine private reguläre Datei')
        expected=stream.read(257).strip()
    if not 32<=len(expected)<=256 or not hmac.compare_digest(hashlib.sha256(token.encode()).digest(),hashlib.sha256(expected).digest()):
        raise HTTPException(403,'Einrichtungsschlüssel ungültig')
    if not USERNAME.fullmatch(username) or password!=confirmation:
        raise HTTPException(400,'Benutzername ungültig oder Passwörter stimmen nicht überein')
    encoded=password_hash(password)
    with control.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM users LIMIT 1').fetchone() or db.execute(
                "SELECT 1 FROM settings WHERE key='first_start_completed'").fetchone():
            raise HTTPException(409,'Ersteinrichtung wurde bereits abgeschlossen')
        db.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?,?,?)',
                   (str(uuid.uuid4()),username,encoded,'admin',1,'de','disabled',now,now))
        db.execute("INSERT INTO settings(key,value) VALUES('first_start_completed','true')")
        db.execute('DELETE FROM attempts WHERE ip=?',(key,))
    # The DB transaction permanently closes enrollment, even if cleanup fails.
    try:
        current=path.lstat()
        if (current.st_dev,current.st_ino)==(info.st_dev,info.st_ino):path.unlink()
    except OSError:
        pass
    return {'state':'CONFIGURED','username':username}
