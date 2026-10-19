# Produktionsfreigabe: Stand 19.10.2026

**Status: NICHT FREIGEGEBEN.** Die installierte Version 0.5.0 ist für Simulatorbetrieb, Katalogsuche und ausdrücklich bestätigte physische Wartung geeignet. Der reguläre Archivdienst sperrt physische Bandzugriffe in `LinuxTape` weiterhin absichtlich. Ein bestandener Wartungstest darf diese Sperre nicht umgehen.

| Abnahme | Befund | Status |
| --- | --- | --- |
| Automatisierte Softwaretests auf Debian-Bandserver | 114 Tests bestanden; temporäre Testdaten auf `/var/tmp` | Bestanden |
| Reale Laufwerks-/Medienerkennung | IBM ULT3580-HH4 und eindeutig identifiziertes eingelegtes Testmedium; keine aktive TapeAlert-Warnung beim letzten Scan | Bestanden, Momentaufnahme |
| Reales PAX-TAR-/Filemark-/Append-Layout | Fünf Banddateien; alle vor und nach Append zurückgelesen und gehasht | Bestanden im kleinen Testlayout |
| Unabhängige Wiederherstellung ohne OTAM-Installation | Zwei bereits vom Testband zurückgelesene Daten-/Receipt-Paare mit `tools/recover_tar.py` unter isoliertem Python 3 wiederhergestellt: je zwei Dateien, inklusive Archiv- und Ziel-Hashprüfung; temporäre Ziele entfernt | Bestanden für diese Testarchive |
| 256-GiB-Medientest | Vollständiger Schreib-/Rücklesezyklus mit SHA-256; kein echtes Bandende erreicht | Teilabnahme |
| Volles Band bis EOM und vollständig zurücklesen | Nutzerfreigabe für die eingelegte Testkassette erteilt. Dauerhaft protokollierter OTAM-Wartungsauftrag am 19.10.2026 mit erneut geprüfter Medienidentität gestartet; Ergebnis erst nach vollständigem Rücklesen bewerten | Läuft |
| Kontrollierter Abbruch, Neustart und Medienwechsel an echter Hardware | Position, Tail und Identität müssen vor jedem weiteren Write unabhängig geprüft werden | Offen |
| Reguläre OTAM-Pipeline auf `/dev/nst*` | Backend fehlt; `LinuxTape` löst absichtlich `SafetyError` aus. Inklusive `mbuffer`, Staging, Receipt, Scan, gezieltem Restore und vollständiger Rückleseprüfung zu implementieren und separat abzunehmen | Sperrend |
| Wiederherstellung eines regulär durch OTAM erzeugten physischen Archivs nach Verlust von Installation und Katalog | Testlayout-Wiederherstellung ersetzt diesen End-to-End-Test nicht | Offen |
| Eigenständiger Katalog auf Proxmox und NAS-Katalogsicherung | Zieladresse/Zugang beziehungsweise Backup-Pfad sind noch nicht konfiguriert | Offen für verteilten Betrieb |
| Staging-HDD | USB-HDD bisher mit 10-Minuten-Zonentests und Transport-Resets; interner SATA-Einbau und 30-Minuten-O_DIRECT-Test am endgültigen Staging-Dateisystem stehen aus. Gemäß Nutzerwunsch als letzter Hardware-Schritt | Sperrend |

Eine Freigabe erfordert einen bestandenen echten OTAM-Zyklus **Planung → vollständiges lokales Staging → Band-Write → vollständige physische Rücklesung → SHA-256-Verifikation → gezielter Restore**, eine konservative und nach Neustart sichere Positionierung, einen bestandenen langen Staging-Test am endgültigen Einbauort sowie dokumentierte Fehlerfälle. Bandqualifikation und Testlayout dürfen nur auf einem ausdrücklich für den jeweiligen destruktiven Umfang freigegebenen Medium laufen. Keine der noch offenen Prüfungen darf durch Simulatorergebnisse als bestanden gelten.

Die Staging-HDD wird wie vereinbart erst nach den übrigen verfügbaren Prüfungen am endgültigen Anschluss bewertet. Solange ihre Qualifikation fehlt, bleibt der physische Archivierungsbetrieb gesperrt, auch wenn die übrigen Tests bestehen.
