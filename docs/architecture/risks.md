# Risiken und Freigabekriterien

| Risiko | Konsequenz | Maßnahme / offener Nachweis |
|---|---|---|
| Unbekannte Position / doppelte Filemarks | Überschreiben nachfolgender Daten | Kein realer Write-Adapter vor validiertem Close/Filemark/EOD-Verhalten; Header, Sequenz, letzte Receipts unabhängig lesen |
| Stromausfall während Write | Physisch irreversibler Teil-TAR | INCOMPLETE, Medium gesperrt; Originaldaten behalten; keine automatische Fortsetzung |
| Gebrauchte LTO-4 | EOM/Lesefehler vor nomineller Kapazität | Reserve, vollständige Rücklesung; destruktive Qualifikation separat freigeben |
| Fehlendes/falsches Medium | Falsches Ziel | Medien-ID bei jeder Operation und unter Lock prüfen; nicht Modellnummer als Medien-ID verwenden |
| Quelle verändert sich | Inkonsistenter Bestand | Hash beim Plan und TAR-Prüfung; ruhende Quellen/Snapshot; keine atomare Gesamtsicht behaupten |
| SSD zu klein/langsam | Stream stoppt, Shoe-shining | größtes Archiv spoolen, SSD-Skripte auswerten, Zielgröße begrenzen; Test mit mbuffer |
| SAS/Firmware/Kabel | Resets/Timeouts | lsscsi, sysfs, Kernelmeldungen lesen; keine unbekannten Workarounds anwenden |
| Katalogverlust | Dateien nicht auffindbar | pro TAR vollständiges Manifest und Recovery-Anleitung; Scan rekonstruiert |
| Hash im gleichen Medium | Keine Authentizität bei absichtlicher Manipulation | SHA-256 gegen zufällige Schäden; separate signierte Exporte optional später |
| Malware-TAR/Ziel-Symlink | Schreiben außerhalb Restore-Ziel | reguläre Mitglieder, relative validierte Pfade, dirfd/O_NOFOLLOW, exklusives Anlegen |
| Externe mt-/Backup-Prozesse | Lock wird umgangen | dedizierter Linux-Nutzer, systemweite Gerätesperre und organisatorische Exklusivität; fremde root-Prozesse bleiben außerhalb Garantie |
| Lange Rücklesung | Zeitbedarf | 800 GB bei 80 MB/s theoretisch 2,8 h je Durchlauf, Schreiben+Lesen mindestens 5,6 h ohne Overhead |

Offen: Linux-Distribution, mt-st-Version, Blockgröße, variable/feste Blöcke, Drive-Serial, MAM-Zugriff, TapeAlert, EOM/early warning, Hardwarekompression, tatsächlich benötigter SSD-Platz, stabile Gerätezuordnung. Keine Hardware-Lebensdauerprognose aus Fehlerzählern.
