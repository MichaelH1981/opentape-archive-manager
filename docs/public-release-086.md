# Öffentliche Veröffentlichung 0.8.6

Das Repository und die Programmlizenz sind für die öffentliche Weitergabe
vorbereitet. Installationspaket und Bedienung: [Debian 13](debian-installation.md),
[Bedienungsanleitung](user-guide.md), [English quick start](getting-started-en.md).

## Ersteinrichtung

Neue Installationen haben kein Standardpasswort. Ein privater lokaler einmaliger
Einrichtungsschlüssel autorisiert die Erstellung genau eines ersten Admins.
Passwortbestätigung, PBKDF2-Salt/Hash, Origin-/Host-Prüfung, Versuchslimit,
transaktionale Parallelitätssperre und dauerhafte Sperre nach Erfolg sind getestet.
Bestehende Konten bleiben erhalten; die bestehende Bandserverinstallation wird
für diese Veröffentlichung nicht durch das Debian-Paket ersetzt.

## Prüfung vor Veröffentlichung

- 659 historische Git-Blobs nach privaten Schlüsselblöcken, GitHub- und AWS-
  Zugriffsschlüsselmustern geprüft, keine Treffer. Keine historischen
  `node.json`/`peer.key`/`.env`-Dateien oder SQLite-Laufzeitdaten gefunden.
- Aktueller Stand zusätzlich nach Zugangsdatenmustern und ignorierten Rohdaten
  geprüft. Containerkonfiguration enthält nur gekennzeichnete Platzhalter.
  Historische technische Abnahmeberichte enthalten konkrete Hardwareprofile,
  Seriennummern, private Netzwerkadressen und lokale Betriebspfade; das sind keine
  mitgelieferten Zugangsdaten und keine allgemeine Hardwarefreigabe.
- Keine bestehenden Release-Assets, Actions-Artefakte oder Issues. Die vorhandene
  PR-Beschreibung enthält Funktions-/Testdokumentation, keine Zugangsdaten.
  GitHub-Actions-Secrets: keine. Mustersuche ersetzt keine Garantie, dass beliebige
  denkbare Geheimnisformate vollständig erkannt werden.
- 279 Softwaretests mit Debian-13-Distributionsbibliotheken bestanden (99,257 s):
  FastAPI 0.115.11, Uvicorn 0.32.0, HTTPX 0.28.1. Lokal 279 mit einem Linux-Skip
  in 16,172 s. Ersteinrichtung und bestehende Konto-Migration separat geprüft.
- Debian-`all`-Paket gebaut; Paketinhalt/-abhängigkeiten/-Modi und Shellsyntax der
  vier Maintainerskripte geprüft. CLI und Web-Ersteinrichtung inklusive Anmeldung,
  Neustart und Einmaligkeit aus dem entpackten Paket mit Debian-Bibliotheken als
  Dienstkonto auf isoliertem lokalem Testzustand geprüft. Keine Installation des
  Pakets über den bestehenden `/opt/otam`-Bandserver. Ein kompletter frischer
  APT-/systemd-Installationstest ist zusätzlich als GitHub-Containerjob hinterlegt;
  der Containerjob behauptet keine Band- oder persistente Dateisystemqualifikation.
- Browseransicht der ersten Einrichtung ohne eingegebenes Passwort/Token geprüft.
  Ein dabei gefundener Darstellungsfehler (Setup-Formular im versteckten Login-
  Container) wurde korrigiert und danach sichtbar nachgeprüft.

Die bisherigen fehlgeschlagenen Hosted-CI-Läufe starteten ihre Tests nicht:
GitHub meldete fehlgeschlagene Kontozahlungen bzw. ein Ausgabenlimit. Das ist kein
fehlgeschlagener Softwaretest. Es wurden keine kostenpflichtigen Limits erhöht,
keine Zahlungsdaten geändert und keine erforderlichen Schutzregeln umgangen.
Hosted-Prüfungen müssen nach Veröffentlichung erneut kontrolliert werden.

## Grenzen

0.8.x ist eine Version vor 1.0. Physische Bandabnahme ist profilspezifisch, nicht
für jedes Laufwerk übertragbar. Die dokumentierten Datenformat-/Metadaten- und
Recovery-Grenzen bleiben gültig. Das neue Paket qualifiziert keine Hardware,
aktiviert keine Bandwrites und setzt keine produktiven Medien zurück. Lokale
Rohberichte bleiben ignoriert und werden nicht als Release-Assets veröffentlicht.
