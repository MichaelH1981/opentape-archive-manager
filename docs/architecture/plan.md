# Entwicklungs- und Abnahmeplan

1. **Phase 0:** leeres Repository erfassen, Alternativen bewerten, Bandformat/Schema/Risiken festhalten. Hardware-Skripte und Linux-Inventar sind lesend erfasst. Die physische Bandintegration bleibt vorläufig.
2. **Phase 1a:** package/CLI, migrationsfähige SQLite-Datenbank, persistenter Simulator mit Lock/Medien-ID/Append, Plan mit SHA-256, PAX-TAR/Manifest.
3. **Phase 1b:** Rücklesung und Receipt, strikte VERIFIED-Regel, sicherer Restore, Fehler/Abbruch/Neustart, Katalogrekonstruktion; automatisierte Tests und unabhängiges tar-Lesen.
4. **Phase 1c (Hardware-Gate):** Skripte prüfen, lesendes Linux-Inventar, explizit benanntes entbehrliches Testband und Freigabe. Erst dann Write-Adapter mit mt-st/mbuffer entwickeln und tatsächliches Close/EOD/EOM/Filemark-Verhalten validieren. Kein produktiver Einsatz davor. Erfolgreicher Simulator ersetzt diese Abnahme nicht.
5. **Phase 2:** Medienwechsel und Mehrbandplanung, erweiterte Suche/Export/Health, Kapazitätskalibrierung, große Kataloge messen. Vier Quartalsmedien nur nach dokumentierter Retention und bewusster Wiederfreigabe.
6. **Phase 3:** Web/API, separater Worker und eigenständiger Katalogdienst mit Snapshot-Replikation sind in 0.3 implementiert; systemd-/Container-Vorlagen und lokale sichere Konfiguration liegen vor. Proxmox-/NAS-Betrieb und tatsächliche iPhone-Abnahme stehen aus.
7. **Phase 4:** System-Snapshots, Gesundheitsberichte, optional Verschlüsselung.

## Nächste Version: gezielte Quellauswahl

- Im serverseitigen Dateibrowser innerhalb freigegebener Quellbereiche einzelne reguläre Dateien und mehrere Unterverzeichnisse auswählen; eine Verzeichnisauswahl umfasst dessen Dateien rekursiv. Die bisherige Auswahl eines vollständigen Quellordners bleibt möglich.
- Die konkrete Auswahl samt relativen Pfaden und SHA-256-Planbindung persistent speichern und vor Staging erneut prüfen. Pfad-Traversal, Symlinks, Spezialdateien, geänderte Dateien sowie Wechsel des zugrunde liegenden Mounts dürfen die freigegebene Auswahl nicht umgehen. Kein Kopieren oder Löschen von Quelldaten als Voraussetzung für die Auswahl.
- Im Plan und Bestätigungsdialog Anzahl, Umfang und Archivzuordnung der ausgewählten Dateien/Ordner zeigen; Simulator-, Restore- und Berechtigungsprüfungen entsprechend erweitern. Die Auswahl muss auch nach Neustart eindeutig reproduzierbar sein.
- Mehrbandplanung und geführter Medienwechsel bleiben ein separater Phase-2-Baustein: aktuell bindet ein Job genau ein Medium und lehnt zu große Quellen vor dem Schreiben ab. Für eine spätere Mehrbandplanung dürfen TARs und Einzeldateien nicht automatisch über Bänder geteilt werden.
- Für die physische Bandabnahme die Positionierungs- und Stagingkosten von sofortiger TAR-Rücklesung gegenüber einer optionalen gebündelten Rücklesung messen. Eine spätere Batch-Variante darf kein Archiv vor echter Rücklesung als VERIFIED markieren und muss vorbereitete TARs bis dahin behalten; bei zu kleinem Staging muss die archivweise Verifikation nutzbar bleiben.

System-Snapshot-Workflow: ruhender Systemstand/Rescue-Boot oder atomarer Snapshot; Inventar (lsblk/blkid, Partitionstabellen, fstab/crypttab, LUKS-Metadaten, Paketliste, Bootmodus/Bootloader, Kernel/Initramfs, Mounts) mit Geheimnisprüfung; Dateisystemarchive separat; manuelle Recovery-Reihenfolge Partitionen → LUKS → Dateisysteme → Dateien → fstab/crypttab → chroot/Bootloader/Initramfs → Boot-Test in isolierter VM/Testplatte. LUKS-Header sind vertraulich. Keine automatische Partitionierung produktiver Platten. Borg-Wochenbackup bleibt unabhängig. V1-Dateiarchive sind kein vollständiger Systemstand.

Ergänzung Anforderung 20: persistentes lokales Staging, Phase INVENTORY bis STAGING_CLEANUP, konservative lokale FS-/Blockgeräteprüfung, Fehlererhalt, explizite Wiederaufnahme, Stream-Rücklesung ohne Zweit-TAR und Direct-I/O-Benchmark sind im Simulator-Kern ergänzt. Vor Phase 1c ist zusätzlich der dokumentierte lange 120-MB/s-Staging-Lesetest zu bestehen. Kurztests und bestehende /dev/null-Zuflussmessungen ersetzen diesen Nachweis nicht.
