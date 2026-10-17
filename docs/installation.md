# Installation

Preview für Phase 1, ausschließlich Simulator. Linux ist Zielplattform; Entwicklung zusätzlich auf macOS. Python >=3.11 und dessen sqlite3-Modul erforderlich. Keine Laufzeit-PyPI-Abhängigkeiten und kein Internet im Betrieb.

Offline direkt aus dem Quellverzeichnis:

```bash
python3 -m otam --help
python3 -m unittest discover -v
python3 -m otam doctor
```

Optional Paketinstallation in eine eigene Umgebung (Build-Backend ist in pyproject.toml auf setuptools 80.9.0 festgelegt):

```bash
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/otam --help
```

Für reproduzierbare Offline-Paketinstallation das gepinnte Build-Backend und das erzeugte OTAM-Wheel vorab bereitstellen und per `pip --no-index --find-links ...` installieren. Der direkte Modulstart benötigt kein Build-Backend. Python-/Distributionsversion mit dem Installationsinventar dokumentieren. Mindestversion 3.11 ist die deklarierte API-Untergrenze; bisher getestete Versionen siehe Testplan.

Später auf Debian für reale Integration: GNU tar, mt-st, mbuffer, sg3-utils/lsscsi; Installation und Geräteberechtigungen bewusst administrieren. Der vorhandene Server besitzt diese Kernwerkzeuge bereits; es wurden keine Pakete installiert. Kein root-Dauerprozess, kein automatisches sudo, keine fremden Bandprogramme parallel. Web-/systemd-Service wird in Phase 3 implementiert; derzeit wird keiner installiert oder gestartet.
