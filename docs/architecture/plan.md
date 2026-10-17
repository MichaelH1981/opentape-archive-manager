# Entwicklungs- und Abnahmeplan

1. **Phase 0:** leeres Repository erfassen, Alternativen bewerten, Bandformat/Schema/Risiken festhalten. Hardware-Skripte und Linux-Inventar sind lesend erfasst. Die physische Bandintegration bleibt vorläufig.
2. **Phase 1a:** package/CLI, migrationsfähige SQLite-Datenbank, persistenter Simulator mit Lock/Medien-ID/Append, Plan mit SHA-256, PAX-TAR/Manifest.
3. **Phase 1b:** Rücklesung und Receipt, strikte VERIFIED-Regel, sicherer Restore, Fehler/Abbruch/Neustart, Katalogrekonstruktion; automatisierte Tests und unabhängiges tar-Lesen.
4. **Phase 1c (Hardware-Gate):** Skripte prüfen, lesendes Linux-Inventar, explizit benanntes entbehrliches Testband und Freigabe. Erst dann Write-Adapter mit mt-st/mbuffer entwickeln und tatsächliches Close/EOD/EOM/Filemark-Verhalten validieren. Kein produktiver Einsatz davor. Erfolgreicher Simulator ersetzt diese Abnahme nicht.
5. **Phase 2:** Medienwechsel und Mehrbandplanung, erweiterte Suche/Export/Health, Kapazitätskalibrierung, große Kataloge messen. Vier Quartalsmedien nur nach dokumentierter Retention und bewusster Wiederfreigabe.
6. **Phase 3:** Web/API, separater Worker und eigenständiger Katalogdienst mit Snapshot-Replikation sind in 0.3 implementiert; systemd-/Container-Vorlagen und lokale sichere Konfiguration liegen vor. Proxmox-/NAS-Betrieb und tatsächliche iPhone-Abnahme stehen aus.
7. **Phase 4:** System-Snapshots, Gesundheitsberichte, optional Verschlüsselung.

System-Snapshot-Workflow: ruhender Systemstand/Rescue-Boot oder atomarer Snapshot; Inventar (lsblk/blkid, Partitionstabellen, fstab/crypttab, LUKS-Metadaten, Paketliste, Bootmodus/Bootloader, Kernel/Initramfs, Mounts) mit Geheimnisprüfung; Dateisystemarchive separat; manuelle Recovery-Reihenfolge Partitionen → LUKS → Dateisysteme → Dateien → fstab/crypttab → chroot/Bootloader/Initramfs → Boot-Test in isolierter VM/Testplatte. LUKS-Header sind vertraulich. Keine automatische Partitionierung produktiver Platten. Borg-Wochenbackup bleibt unabhängig. V1-Dateiarchive sind kein vollständiger Systemstand.

Ergänzung Anforderung 20: persistentes lokales Staging, Phase INVENTORY bis STAGING_CLEANUP, konservative lokale FS-/Blockgeräteprüfung, Fehlererhalt, explizite Wiederaufnahme, Stream-Rücklesung ohne Zweit-TAR und Direct-I/O-Benchmark sind im Simulator-Kern ergänzt. Vor Phase 1c ist zusätzlich der dokumentierte lange 120-MB/s-Staging-Lesetest zu bestehen. Kurztests und bestehende /dev/null-Zuflussmessungen ersetzen diesen Nachweis nicht.
