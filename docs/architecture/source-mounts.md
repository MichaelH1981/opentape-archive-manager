# Lesende Quellen-Mounts (0.9.1)

Unter Planung gibt es getrennte Aktionen für Quellenregistrierung/-abmeldung und
für das Einbinden von NFS, SMB und unterstützten USB-Dateisystemen. Abmelden löscht
keine Dateien, verändert keine Bandarchive und hängt keinen Datenträger aus.
Laufende/eingereihte Aufträge, aktive Archivpläne und Referenzen aus
Rotationsregeln verhindern die Abmeldung. Fehlgeschlagene reine Inventarisierungen
ohne fertige Quellenaufnahme oder Stagingeinträge verhindern sie nicht dauerhaft.

## Privilegiengrenze

`source_mounting` ist standardmäßig false. Ein separat installierter Root-Dienst
verarbeitet ausschließlich private, authentifizierte Administratoranfragen; Web
und Bandworker behalten ihre bisherigen Sandboxes und benötigen kein sudo.
Servernetze sind zusätzlich in der root-eigenen Datei
`/etc/otam/source-mounts.json` freigegeben, beispielsweise:

```json
{"allowed_networks": ["192.168.1.120/32"]}
```

Die Datei muss root gehören und darf nicht gruppen-/weltweit schreibbar sein.
Keine Hostnamen, beliebigen Mountoptionen, Shellbefehle, freien Zielpfade,
Formatierung, Zwangs-Unmounts oder Änderungen an `/etc/fstab`. Jeder Mount erhält
sein eigenes Ziel unter `/mnt/otam-sources/<UUID>`; existierende Mounts bleiben
unverändert. Freigabe und Ausführung benutzen dieselbe Eingabevalidierung.
Alle Ziele werden mit `ro,nosuid,nodev,noexec` eingebunden und das Ergebnis geprüft.
Mountaktionen sind bei laufenden/wartenden Aufträgen beziehungsweise belegter
I/O-Sperre gesperrt. Fehler werden nicht automatisch wiederholt.

Root-eigene Status-/Replayjournale liegen unter `/var/lib/otam-source-mounts`.
Anfragen liegen kurzzeitig unter `<state>/source-mount-requests`, Modus 0600 in
privatem Verzeichnis. Die Verbraucher prüfen Eigentümer, Dateityp, Größe, Alter,
Linkanzahl und Administratorrolle erneut. Root-Sicherheitsjournale bleiben nach
Fehlern erhalten. Der Mountdienst muss im Host-Mountnamespace laufen: Optionen wie
PrivateTmp oder ProtectSystem würden seine Mounts vom Host isolieren. Diese
Einschränkung gilt nur für den eng begrenzten Mounthelfer, nicht für Web/Worker.

## Protokolle und Zugangsdaten

NFS nutzt explizite NAS-IPv4-Adresse und absoluten Export, Version 4.1. Numerische
UID-/GID-/ACL-Rechte am NAS bleiben wirksam. Root-eigene Dateien mit Modus 0600 sind
für den normalen OTAM-Benutzer über NFS weiterhin nicht lesbar. OTAM verändert
weder diese Rechte noch läuft der Archivworker als root. Für Borg ist ein
konsistenter, lesbarer Repository-Stand beziehungsweise eine passende NAS-Leseidentität
bereitzustellen; index-/hints-Dateien werden nicht ungeprüft ausgeschlossen.

SMB nutzt eine eigene NAS-Leseidentität, Version 3.1.1, 3.0 oder ausdrücklich 2.1;
SMB1 ist ausgeschlossen. Der Browser zeigt Passwortfelder nur über HTTPS oder
localhost/SSH-Tunnel, das Backend prüft den Transport ebenfalls. Passwörter
erscheinen nicht in Kommandozeilen, Control-Queue, Statusantworten oder dauerhaften
Konfigurationsdateien. Ein root-exklusives temporäres Credentialsfile unter `/run`
wird nach Erfolg/Fehler entfernt. NAS-Zugriff bleibt von den Rechten des gewählten
SMB-Kontos abhängig. Anfragen sind kurzzeitig als private 0600-Datei vorhanden;
der Mount verwendet anschließend die normale Kernel-Sitzung. Kein automatisches
Wiedereinbinden nach Neustart, kein dauerhaft gespeichertes NAS-Passwort.

USB unterstützt ext4, XFS, Btrfs, FAT und exFAT. Es werden nur eindeutig identifizierte
Dateisystem-UUIDs auf vollständig unbenutzten USB-Datenträgern angeboten. Sobald
irgendeine Partition eines solchen Datenträgers eingebunden ist, wird der ganze
Datenträger ausgeschlossen; ebenso SATA-/System-/Stagingdatenträger, doppelte UUIDs
und unbekannte Dateisysteme. Vor und nach Mount werden Identität und Lesemodus
geprüft. Für ext4 `noload`, XFS `norecovery`, Btrfs `nologreplay`, damit ein als
lesend angeforderter Mount keine Journalwiederholung auslöst. Verschlüsselte,
mehrteilige RAID-/LVM- und NTFS-/APFS-Dateisysteme werden nicht implizit entsperrt
oder durch unsichere Force-Optionen eingebunden.

## Installation

Benötigt werden die passenden Distributionswerkzeuge (`nfs-common`, `cifs-utils`
und für die jeweiligen USB-Dateisysteme vorhandene Kernel-/Mountunterstützung).
Systemd-Beispiele liegen in `packaging/systemd/otam-source-mounts.*`. Nur nach
bewusster administrativer Einrichtung aktivieren:

1. Getestetes OTAM installieren; Root-Mountpolicy mit konkreten NAS-Adressen anlegen.
2. `<state>/source-mount-requests` als otam:otam 0700 anlegen, Root-Journal
   `/var/lib/otam-source-mounts` als root:otam 0750, Zielwurzel als root:root 0755.
3. Path-/Service-Units nach `/etc/systemd/system` kopieren; TMPDIR und Statepfad
   müssen mit Web/Worker übereinstimmen. Beim Debian-Paket den dort mitgelieferten
   Helfer mit `/usr/bin/python3` verwenden; die Repository-Vorlage verwendet die
   Wheel-Installation unter `/opt/otam/venv`.
4. `source_mounting: true` in der geschützten Nodekonfiguration setzen, Units prüfen,
   daemon-reload und `otam-source-mounts.path` starten; Web im Leerlauf neu laden.
5. Zunächst einen eigenen lesenden Mount testen und seine Sichtbarkeit im
   Dienstnamespace prüfen. Erst danach als Quelle registrieren.

Status zeigt die Mounttabelle des Webdienstes; er behauptet keine vollständige
NAS-Erreichbarkeit oder Lesbarkeit aller Dateien. Nach einem Neustart verschwundene
Mounts werden als nicht eingebunden dargestellt. Bestehende andere Mounts werden
weder ersetzt noch automatisch umkonfiguriert. Das Aushängen und eine automatische
Bootverwaltung sind nicht Bestandteil dieses ersten Umfangs.

## Technische Referenzen

- [Kernel: ext4 – ro allein kann Journalreplay ausführen](https://docs.kernel.org/admin-guide/ext4.html)
- [Btrfs: Mountoptionen und nologreplay](https://btrfs.readthedocs.io/en/stable/btrfs-man5.html)
- [systemd: Mountnamespace und Propagation](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html)
