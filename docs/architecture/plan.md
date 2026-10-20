# Entwicklungs- und Abnahmeplan

## TODO für Version 0.8: gemessene Platznutzung und Kapazitätsprognosen

Aufgenommen am 20.10.2026 auf Nutzerwunsch; Umsetzung erst ab Version 0.8.

- [ ] Pro Archiv und Medium geplante Bytes, tatsächliche Nutz-/TAR-/Receiptbytes, Header und Filemarks sowie Laufwerks-/Medienprofil und Komprimierungsmodus dauerhaft erfassen. Verifizierte Ergebnisse von abgebrochenen oder unbestätigten Writes trennen.
- [ ] Physische Belegung und verbleibende Kapazität aus geeigneten Laufwerks-/Medienzählern erfassen, soweit belastbar verfügbar. Hostseitig übertragene Bytes sind nicht automatisch physisch belegte Bandbytes; nicht verfügbare Werte ausdrücklich als unbekannt führen. Keine zusätzlichen Banddurchläufe nur für Statistik.
- [ ] Prognose und tatsächliches Ergebnis gegenüberstellen; Schätzfehler, Format-Overhead und beobachtetes Bandende nach Profil auswerten. Merkmale wie Dateigrößenverteilung und Dateitypen aggregiert sammeln, ohne Dateiinhalte oder vollständige Quellpfade als Trainingsdaten zu benötigen. Daten bleiben zunächst lokal; kein automatischer Upload.
- [ ] Zuerst einfache empirische/statistische Kalibrierung als Vergleichsbasis prüfen. Anschließend evaluieren, ob maschinelles Lernen oder ein trainiertes Modell nachweislich bessere Vorhersagen liefert; ML ist eine Option, keine bereits festgelegte Voraussetzung.
- [ ] Prognosen mit Unsicherheit, Datenbasis und Modell-/Kalibrierungsversion anzeigen; auf unabhängigen späteren Jobs prüfen. Bei unbekannten Profilen oder zu wenigen Messungen auf native Kapazität und Formatabschätzung zurückfallen. Gelernte Prognosen dürfen Identitäts-, Schreib- und EOM-/Tail-Sperren nicht umgehen oder unbelegte Komprimierungsgewinne als garantierte Kapazität ausweisen.

Die aktuelle Version erhält hierfür weder neue Datensammlung noch ein Modell.

1. **Phase 0:** leeres Repository erfassen, Alternativen bewerten, Bandformat/Schema/Risiken festhalten. Hardware-Skripte und Linux-Inventar sind lesend erfasst. Die physische Bandintegration bleibt vorläufig.
2. **Phase 1a:** package/CLI, migrationsfähige SQLite-Datenbank, persistenter Simulator mit Lock/Medien-ID/Append, Plan mit SHA-256, PAX-TAR/Manifest.
3. **Phase 1b:** Rücklesung und Receipt, strikte VERIFIED-Regel, sicherer Restore, Fehler/Abbruch/Neustart, Katalogrekonstruktion; automatisierte Tests und unabhängiges tar-Lesen.
4. **Phase 1c (Hardware-Gate):** Skripte prüfen, lesendes Linux-Inventar, explizit benanntes entbehrliches Testband und Freigabe. Erst dann Write-Adapter mit mt-st/mbuffer entwickeln und tatsächliches Close/EOD/EOM/Filemark-Verhalten validieren. Kein produktiver Einsatz davor. Erfolgreicher Simulator ersetzt diese Abnahme nicht.
5. **Phase 2:** Medienwechsel und Mehrbandplanung, erweiterte Suche/Export/Health, Kapazitätskalibrierung, große Kataloge messen. Vier Quartalsmedien nur nach dokumentierter Retention und bewusster Wiederfreigabe.
6. **Phase 3:** Web/API, separater Worker und eigenständiger Katalogdienst mit Snapshot-Replikation sind in 0.3 implementiert; systemd-/Container-Vorlagen und lokale sichere Konfiguration liegen vor. Proxmox-/NAS-Betrieb und tatsächliche iPhone-Abnahme stehen aus.
7. **Phase 4:** System-Snapshots, Gesundheitsberichte, optional Verschlüsselung.

## Version 0.5: Quellauswahl und Mehrbandjobs im Simulator

- Ein serverseitiger Dateibrowser listet reguläre Dateien und Unterverzeichnisse nur innerhalb freigegebener Quellen. Eine Auswahl kann mehrere Dateien/Ordner umfassen; gewählte Ordner werden rekursiv inventarisiert. Relative Auswahlpfade sind im gehashten, persistenten Plan enthalten. Symlinks, Spezialdateien, Pfad-Traversal und geänderte Quelldaten werden abgelehnt. Quelldaten werden nicht gelöscht.
- Mehrere ausgewählte Simulatormedien bilden einen übergeordneten Job mit unabhängigen Mediensegmenten. Vollständige TARs werden konservativ auf die Medien verteilt, ohne Datei oder TAR zu teilen. Nach jedem erfolgreich verifizierten Medium fordert `WAITING_MEDIA` die nächste ausdrückliche Bestätigung. Damit sind Quellen über der Kapazität eines einzelnen Mediums planbar.
- Wahlweise wird jedes TAR sofort zurückgelesen oder werden alle TARs eines Mediums zuerst geschrieben und dann vollständig geprüft. Im zweiten Modus bleiben alle TARs bis zur Verifikation lokal im Staging; vor dem Schreiben wird der Platz dafür geprüft. Kein Archiv erhält vorher den Status VERIFIED. Ein unerwartetes Bandende wird nicht automatisch auf ein neues Medium fortgesetzt.
- Offen für die physische Abnahme: Mountidentität über den gesamten Quelljob absichern, die Positionierungs-/Stagingkosten beider Verifikationsarten messen, Dateimengen im Millionenbereich profilieren und den geführten Wechsel auf realen LTO-Medien beweisen. Bis dahin bleiben reale Archivierungswrites gesperrt.

System-Snapshot-Workflow: ruhender Systemstand/Rescue-Boot oder atomarer Snapshot; Inventar (lsblk/blkid, Partitionstabellen, fstab/crypttab, LUKS-Metadaten, Paketliste, Bootmodus/Bootloader, Kernel/Initramfs, Mounts) mit Geheimnisprüfung; Dateisystemarchive separat; manuelle Recovery-Reihenfolge Partitionen → LUKS → Dateisysteme → Dateien → fstab/crypttab → chroot/Bootloader/Initramfs → Boot-Test in isolierter VM/Testplatte. LUKS-Header sind vertraulich. Keine automatische Partitionierung produktiver Platten. Borg-Wochenbackup bleibt unabhängig. V1-Dateiarchive sind kein vollständiger Systemstand.

Ergänzung Anforderung 20: persistentes lokales Staging, Phase INVENTORY bis STAGING_CLEANUP, konservative lokale FS-/Blockgeräteprüfung, Fehlererhalt, explizite Wiederaufnahme, Stream-Rücklesung ohne Zweit-TAR und Direct-I/O-Benchmark sind im Simulator-Kern ergänzt. Vor Phase 1c ist zusätzlich der dokumentierte lange 120-MB/s-Staging-Lesetest zu bestehen. Kurztests und bestehende /dev/null-Zuflussmessungen ersetzen diesen Nachweis nicht.
