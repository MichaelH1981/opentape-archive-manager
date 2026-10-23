# Fotos-Master: Laufanalyse 0.8.4, 23.10.2026

Auswertung bestehender SQLite-Ereignisse, acht mbuffer-Datenlogs und gefilterter
Journale. Keine Geräteabfrage, kein neuer Lese-/Schreibtest, keine Änderung am Job.
Rohdaten ausschließlich lokal ignoriert in
`docs/hardware/testdaten-2026-10-19/fotos-performance-20261023/` mit SHA256SUMS.

## Ergebnis und Zeitbezug

Job `6af984e9-e3a6-4237-9444-490453573c3c` ist VERIFIED, alle acht Archive und
acht Verifikationsdatensätze VERIFIED; Staging vollständig bereinigt.
61.034 Dateien, 525.066.858.862 Nutzbytes, 525.188.792.320 TAR-Bytes.
Medienmodus `media`, Batchvorbereitung, Transferlimit 120.000.000 Byte/s,
2.368 MiB Schreibpuffer und 90 Prozent Vorfüllung. Medienseriennummer laut
Transferpolicy HC4ALJqA70, Drive 1K10112224. Installation laut Dienstimport 0.8.4.

Alle Zeitangaben Europe/Berlin (MESZ):

- Metadatenplanung 22.10. 17:43:37–17:52:37: 9m00s.
- Medienbindung/Inhaltshashing 22.10. 20:06:43–23:34:15: 3h27m33s;
  schließt Vorprüfung ein. Dieser Auftrag bildet einen eigenen Quelldurchgang.
- Backupauftrag 23.10. 08:44:29–16:13:30: 7h29m02s.
- Die Lücken zwischen diesen Aufträgen sind keine gemessene Bearbeitungszeit.

| Teil des Backupauftrags | Gemessene Dauer | Bezug |
|---|---:|---|
| TAR-Erstellung aus NAS-Quelle | 2h55m01s | acht STAGING-Intervalle, ca. 50,0 MB/s Nutzdaten effektiv |
| Lokale vollständige Validierung | 1h53m09s | 16 Intervalle, zwei Passagen über acht TARs |
| Schreibphase | 1h22m23s | acht TAPE_WRITE-Intervalle einschließlich Receiptabschluss |
| Rücklesephase | 1h16m23s | acht TAPE_READBACK-Intervalle |
| Cleanup | 3s | eigene registrierte Stagingartefakte |

Aus letzten Byte-/Ratensamples berechnete eigentliche Datenstromdauer:
Schreiben 4.665,79s (1h17m46s), 112,56 MB/s; Rücklesen 4.569,38s
(1h16m09s), 114,94 MB/s. Phasenzeiten und Datenstromzeiten sind verschiedene
Bezugsgrößen und werden nicht addiert. Schreibdatenstrom plus Rücklesen
umfassen jeweils genau die Gesamtgröße der acht TARs. Acht TARs bedeuten acht
Teile eines vollständigen Rücklesedurchgangs, nicht acht Vollbandprüfungen.

## Bandbewegung und Puffer

Hostkommandos sind kumulativ innerhalb der exklusiven Sitzung:
Beim letzten Datenwrite EOD=16, Rewind=1; bei sämtlichen acht Datenreadbacks
konstant EOD=17, Rewind=2, FSF=1. Damit keine zusätzlichen Positionierungskommandos
zwischen den acht Rücklesungen. Der Code erzwingt vor jedem Payload- und
Receipt-Append frisches EOD/Dateizahl/Identität: 16 Appends plus eine initiale
EOD-Zählung erklären die 17 EOD-Kommandos. Diese Kommandos sind weder ein
Beleg für 17 große Fahrten noch ein Maß interner Laufwerksbewegungen.
Interne Backhitches/Stopps werden durch diese Telemetrie nicht gezählt.

Die sieben großen TARs schreiben mit 109,46–115,33 MB/s; das letzte 1,83-GB-TAR
mit 60,77 MB/s einschließlich fester Vorfüll-/Startkosten. Schreibpuffermedian
100 Prozent bei allen großen TARs, kein beobachteter Nullstand. Werte unter
10 Prozent erst ab 99,72 Prozent übergebener TAR-Bytes; beim kleinen Rest-TAR
ab 90,97 Prozent. Das passt zum normalen Leerlaufen am Ende. Abtastraten
beweisen nicht die Abwesenheit sehr kurzer Unterversorgungen. Größte Abstände
zwischen Samples bei den großen TARs 4,13–15,45s, ohne daraus mechanische Stopps
oder deren Ursachen abzuleiten. Acht originale Daten-mbuffer-Logs gesichert;
keine expliziten Fehler darin gefunden.

Lesepuffer: 64 MiB Budget, maximal 34.078.720 Byte beobachtet, somit nicht
vollständig ausgeschöpft. Gemessene Readback-Raten 108,74–118,09 MB/s.
Producer-Thread-CPU zusammen 273,20s, Consumer-Thread-CPU 3.085,93s;
Consumer umfasst TAR-/Datei-/Archivprüfung, nicht ausschließlich SHA-256.
Zeit in Geräte-Reads 4.526,15s überlappt mit Verarbeitung, darf nicht zur
Consumer-CPU oder Gesamtzeit addiert werden. Der bisherige serielle Engpass
ist deutlich reduziert: LP unter 0.8.2 ca. 52,97 MB/s, jetzt 114,94 MB/s
(Faktor 2,17). Verschiedene Daten und Medien, kein kontrollierter A/B-Test.

Keine WARNING/ERROR-Katalogereignisse für diese beiden Jobs. Im abgefragten
Kerneljournal 22.10. 17:00–23.10. 16:20 keine passenden Reset-/NFS-/Timeout-/
Gerätefehler, kein Worker-Warnjournal. Dienstkonto-CPU 4h23m17s und MemoryPeak
5,34 GB sind kumulative Workerwerte, keine isolierten Jobstatistiken;
Dateicache/Kindprozesse können enthalten sein. IOAccounting weiterhin aus.
Web, Worker und Katalogtunnel nach Analyse aktiv. Reinigung wurde nicht geprüft
oder als erledigt angenommen.

## Priorisierte Optimierungen

1. Quellenübernahme, Datei-SHA und TAR-Erstellung verbinden: einen NAS-Inhaltsread
   sparen. Aktuell erst Hashing bei Bindung, dann erneutes Lesen für TARs.
   Metadatenvorprüfung/Kapazitätsprüfung und Änderungsnachweis erhalten. Manifest
   am TAR-Anfang enthält Dateihashes und Medien-ID; privates Zwischenartefakt
   muss vor unveränderlicher Publikation sicher finalisiert werden. Kein bloßes
   Zusammenlegen zweier Funktionen und kein neuer Formatclaim.
2. TAR-Gesamthash während Erstellung bestimmen und doppelte lokale Vollprüfung
   durch einen unabhängigen vollständigen Prüfdurchgang plus unveränderliche
   Identitätsprüfung vor Write ersetzen. Änderungen/Prozessverlust weiterhin
   konservativ behandeln. Potenzial ungefähr eine jetzige lokale Passage,
   ca. 56 Minuten, unter vergleichbaren Bedingungen; nicht beide Prüfungen löschen.
3. EOD-Kontrollen nur nach gezieltem Software-/Sicherheitsnachweis reduzieren:
   bestätigte Position nach eigenem Filemark könnte unnötige EOD-Kommandos
   vermeiden. Identitäts-/Tail-/Pending-Prüfungen behalten. Hier nur wenige
   Minuten möglicher Gewinn, keine belegte stundenlange Spulschleife.
4. Für die nächste reguläre Sitzung saubere sitzungsbezogene CPU-/IO-Statistik
   und explizite Bewegungsereignisse mit Dauer statt nur kumulativer Zähler.
   Geräteinterne Backhitch-Zähler nur nutzen, wenn tatsächlich unterstützt und
   sicher außerhalb laufender Gerätearbeit lesbar.

Kein Anlass, den RAM-Lesepuffer zu entfernen oder SHA-/Bandverifikation zu
verkürzen. Das NAS muss den Banddatenstrom nicht live versorgen: das lokale
Staging entkoppelt beide. Die zuvor beobachteten ca. 44,6 MB/s NFS waren eine
kurze Zählerprobe (geteilte Exportzähler, nicht pro Mount addieren), kein
Maximalbenchmark. Kopierphase hier effektiv ca. 50 MB/s. Zusammenführen kann
mehrere Stunden sparen, ohne einen konkreten zukünftigen Laufzeitgewinn zu
garantieren. Diese Analyse installiert oder implementiert keine Änderungen.
