"""Explicit node configuration. No runtime discovery of writable source paths."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from ..common import SafetyError


def password_hash(password: str) -> str:
    if len(password) < 12:
        raise SafetyError("Das Passwort muss mindestens 12 Zeichen enthalten")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 600_000
    ).hex()
    return f"pbkdf2_sha256$600000${salt}${digest}"


def password_matches(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or not 100_000 <= int(rounds) <= 2_000_000:
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), int(rounds)
        ).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


@dataclass(frozen=True)
class Resource:
    id: str
    label: str
    path: Path


@dataclass(frozen=True)
class WebConfig:
    node_id: str
    name: str
    role: str
    state: Path
    catalog: Path
    staging: Path
    media_root: Path
    restore_root: Path
    password: str
    username: str = "admin"
    host: str = "127.0.0.1"
    port: int = 8765
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost", "[::1]")
    sources: tuple[Resource, ...] = ()
    directory_roots: tuple[Path, ...] = ()
    physical_maintenance: bool = False
    physical_archiving: bool = False
    peer_url: str = ""
    peer_key_file: Path | None = None
    publisher_id: str = ""
    allow_http_peer: bool = False
    sync_interval: int = 300
    nas_backup: Path | None = None
    max_snapshot_bytes: int = 1024**3
    session_seconds: int = 8 * 3600
    secure_cookie: bool = False
    trusted_proxy_ips: tuple[str, ...] = ()
    allow_host_shutdown: bool = False
    physical_multivolume: bool = False
    physical_initialization: bool = False
    physical_reset: bool = False
    physical_reinitialization: bool = False

    def validate(self) -> None:
        uuid.UUID(self.node_id)
        if self.role not in {"archive", "catalog"}:
            raise SafetyError("Unbekannte Node-Rolle")
        if not self.password.startswith("pbkdf2_sha256$"):
            raise SafetyError("Passwort-Hash fehlt")
        for path in (
            self.state,
            self.catalog,
            self.staging,
            self.media_root,
            self.restore_root,
        ):
            if not path.is_absolute():
                raise SafetyError("Node-Pfade müssen absolut sein")
        if self.catalog.is_relative_to(self.staging) or self.catalog.is_relative_to(
            self.media_root
        ):
            raise SafetyError("Katalog und temporäre Daten müssen getrennt liegen")
        if not self.allowed_hosts or "*" in self.allowed_hosts:
            raise SafetyError("Explizite Host-Allowlist erforderlich")
        import ipaddress

        for proxy in self.trusted_proxy_ips:
            ipaddress.ip_address(proxy)
        if not 300 <= self.session_seconds <= 86400:
            raise SafetyError(
                "Sitzungsdauer muss zwischen 5 Minuten und 24 Stunden liegen"
            )
        if self.role == "catalog" and self.publisher_id:
            uuid.UUID(self.publisher_id)
        if self.nas_backup is not None:
            if not self.nas_backup.is_absolute() or self.peer_key_file is None:
                raise SafetyError(
                    "NAS-Export benötigt absolutes Ziel und Peer-Schlüsseldatei"
                )
        if self.peer_key_file is not None and not self.peer_key_file.is_absolute():
            raise SafetyError("Peer-Schlüsselpfad muss absolut sein")
        if self.peer_url:
            parsed = urlsplit(self.peer_url)
            if (
                parsed.scheme != "https"
                and not (self.allow_http_peer and parsed.scheme == "http")
            ) or not parsed.hostname:
                raise SafetyError(
                    "Peer benötigt HTTPS oder ausdrücklich erlaubtes internes HTTP"
                )
            if (
                parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or parsed.path not in ("", "/")
            ):
                raise SafetyError(
                    "Peer-URL muss eine feste Basisadresse ohne Zugangsdaten sein"
                )
            if not self.peer_key_file:
                raise SafetyError("Peer-Schlüsseldatei fehlt")
        if not 30 <= self.sync_interval <= 86400 or not 1 <= self.port <= 65535:
            raise SafetyError("Ungültiges Intervall oder Port")
        if not 1024 <= self.max_snapshot_bytes <= 100 * 1024**3:
            raise SafetyError("Ungültiges Snapshot-Limit")
        if type(self.physical_maintenance) is not bool or any(
            not p.is_absolute() for p in self.directory_roots
        ):
            raise SafetyError("Ungültige Verzeichnisfreigaben oder Hardwarefreigabe")
        if type(self.allow_host_shutdown) is not bool:
            raise SafetyError("Ungültige Shutdown-Freigabe")
        if (type(self.physical_archiving) is not bool
                or (self.physical_archiving and (not self.physical_maintenance or self.role != "archive"))):
            raise SafetyError("Physische Archivierung benötigt einen administrativ freigegebenen Archivnode")
        if (type(self.physical_multivolume) is not bool
                or (self.physical_multivolume and not self.physical_archiving)):
            raise SafetyError("Physischer Mehrbandbetrieb benötigt die separate administrative Workflow-Abnahme")
        if (type(self.physical_initialization) is not bool
                or (self.physical_initialization and not self.physical_archiving)):
            raise SafetyError("Physische Initialisierung benötigt eine separate administrative Freigabe")
        if (type(self.physical_reset) is not bool
                or (self.physical_reset and not self.physical_initialization)):
            raise SafetyError("Physisches Zurücksetzen benötigt eine separate administrative Freigabe")
        if (type(self.physical_reinitialization) is not bool
                or (self.physical_reinitialization and not self.physical_initialization)):
            raise SafetyError('Physische Neuinitialisierung benötigt eine separate administrative Freigabe')
        ids = [s.id for s in self.sources]
        if len(set(ids)) != len(ids) or any(
            not s.path.is_absolute() for s in self.sources
        ):
            raise SafetyError("Quellen benötigen eindeutige IDs und absolute Pfade")
        for s in self.sources:
            private_paths = (
                self.state,
                self.catalog,
                self.staging,
                self.media_root,
                self.restore_root,
            )
            if self.nas_backup is not None:
                private_paths += (self.nas_backup,)
            for private in private_paths:
                if private.resolve().is_relative_to(
                    s.path.resolve()
                ) or s.path.resolve().is_relative_to(private.resolve()):
                    raise SafetyError("Quellen und Node-Daten müssen getrennt liegen")

    def peer_key(self) -> bytes:
        if self.peer_key_file is None:
            raise SafetyError("Kein Synchronisationsschlüssel konfiguriert")
        if self.peer_key_file.is_symlink() or self.peer_key_file.stat().st_mode & 0o077:
            raise SafetyError(
                "Peer-Schlüssel benötigt Modus 0600 und darf kein Symlink sein"
            )
        key = self.peer_key_file.read_bytes().strip()
        if len(key) < 32 or len(key) > 1024 or not all(33 <= c <= 126 for c in key):
            raise SafetyError(
                "Peer-Schlüssel benötigt 32–1024 druckbare ASCII-Bytes ohne Leerzeichen"
            )
        return key

    @classmethod
    def load(cls, path: Path) -> WebConfig:
        data = json.loads(path.read_text())
        for k in (
            "state",
            "catalog",
            "staging",
            "media_root",
            "restore_root",
            "peer_key_file",
            "nas_backup",
        ):
            if data.get(k) is not None:
                data[k] = Path(data[k])
        data["directory_roots"] = tuple(
            Path(p) for p in data.get("directory_roots", [])
        )
        data["sources"] = tuple(
            Resource(s["id"], s["label"], Path(s["path"]))
            for s in data.get("sources", [])
        )
        for k in ("allowed_hosts", "trusted_proxy_ips"):
            if k in data:
                data[k] = tuple(data[k])
        config = cls(**data)
        config.validate()
        return config


def initialize(
    path: Path, root: Path, role: str, password: str, sources: list[Path] | None = None
) -> None:
    """Create a new private configuration; never overwrite an existing installation."""
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = {
        "node_id": str(uuid.uuid4()),
        "name": "OTAM Bandserver" if role == "archive" else "OTAM Katalog",
        "role": role,
        "state": str(root / "state"),
        "catalog": str(root / "catalog.sqlite"),
        "staging": str(root / "staging"),
        "media_root": str(root / "media"),
        "restore_root": str(root / "restores"),
        "password": password_hash(password),
        "sources": [
            {
                "id": f"source-{i+1}",
                "label": source.name or "Quelle",
                "path": str(source.resolve()),
            }
            for i, source in enumerate(sources or [])
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(data, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    WebConfig.load(path)
