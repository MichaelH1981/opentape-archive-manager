# OTAM PAX v1 – Bandlayoutentwurf

**Status:** Simulatorformat implementiert; physisches LTO-Layout noch nicht freigegeben. Keine LTFS-Annahme. Jede Banddatei ist ein eigenständiges unkomprimiertes POSIX-PAX-TAR, ohne private Binärheader. Zähler beginnen bei 0.

| Banddatei | Inhalt |
|---|---|
| 0 | media.json (format, media_id UUID, label, class, capacity, created, backend), RECOVERY.txt |
| 1 | OTAM/manifest.json, dann reguläre Dateien unter data/ |
| 2 | receipt.json mit SHA-256 und Bytezahl der gesamten Banddatei 1 |
| 3 / 4 usw. | nächste Daten-/Receipt-Paare |

Manifest: format=otam-pax-v1, media_id, archive_id UUID, created UNIX UTC, files mit path (relativ, Unicode JSON-escaped), size Bytes, mtime_ns UNIX Nanosekunden, type (Dateiendung), sha256 hex. Der Manifestpfad kollidiert nicht mit Quelldateien, da alle Nutzdaten unter data/ liegen. Keine Symlinks/Hardlink-Mitglieder, Geräte, ACLs oder Besitzerübernahme. Quell-Hardlinks werden als selbstständige reguläre Inhalte gespeichert. Maximal 32 MiB JSON pro Manifest; große Dateimengen in kleinere Archive planen.

Receipt: format, media_id, archive_id, tape_file (Datenposition), bytes, sha256, previous (SHA-256 des vorherigen Receipt-TARs; beim ersten Paar des Header-TARs). Im archivweisen Modus enthält es nach vollständiger Rücklesung `verified_at`; im verzögerten Modus wird es zunächst mit `verification: pending_readback` und `written_at` angehängt. Dieser Beleg behauptet **keine** erfolgte Rücklesung. Erst ein vollständiger Scan aller Daten-/Receipt-Paare des Mediums und Abgleich mit den lokalen Staging-Hashes setzt den Katalogstatus VERIFIED. Ein späterer unabhängiger Katalogwiederaufbau liest und prüft die Paare ebenfalls vollständig. Datenhash umfasst TAR-Header, Inhalt, Endblöcke und Padding. Hashkette erkennt inkonsistente Reihenfolgen; keine digitale Signatur, kein Schutz gegen absichtliches Neuberechnen sämtlicher Hashes.

## Unveränderliche Kataloginformationen

Der Header wird genau einmal angelegt. Archivübersicht entsteht aus aufeinanderfolgenden Manifesten/Receipts, niemals durch Zurückschreiben eines Inhaltsverzeichnisses an Bandanfang. Jedes Datenarchiv enthält sein vollständiges Dateimanifest. Neue Archive und Prüfbelege werden nur angehängt. Ein fehlender Receipt oder partieller Tail bedeutet INCOMPLETE/uncommitted; keine automatische Reparatur durch Überschreiben. Spätere Prüfresultate bleiben zunächst in SQLite/Export; zusätzliche Band-Prüfbelege benötigen eine eigene zukünftige Formatversion.

Ein erfolgreich geschriebener Receipt kann nach Stromausfall vor dem DB-Commit vorhanden sein. Der Wiederaufbau prüft Daten und Receipt erneut, statt den behaupteten Status blind zu importieren. Frühere vollständige Paare können vor einem unvollständigen Tail wiederhergestellt werden. Ein kaputtes Paar mitten im Band stoppt den konservativen Scan; Forensik/Salvage ist kein automatischer Erfolgsworkflow.

## Filemarks und reale Positionierung

Im Simulator entspricht jede nummerierte `.tar`-Datei genau einer Banddatei; `.partial` bleibt bei Fehler erhalten und blockiert Append. Der Simulator bildet keine Kernel-Blockmodi oder mechanische Bewegungen ab.

Für Linux geplant: /dev/nst* ausschließlich, passende stabile by-id-/sysfs-Zuordnung, expliziter Blockmodus, Position ausgehend von bestätigtem BOT und Banddateizahl, Header-ID prüfen, letzte vollständige Paare und EOD unabhängig bestätigen. Der `st`-Treiber kann beim Schließen Filemarks schreiben; ein zusätzliches blindes `mt weof` wäre falsch. Ein-/Zwei-Filemark-Modus, EOF-Leseposition und Verhalten nach Close sind vor Freigabe exakt zu protokollieren. `mt eod` allein ist keine Identitäts- oder Unversehrtheitsprüfung. Nie aus einer SQLite-Zahl unmittelbar eine Schreibposition ableiten.

Early EOM und hartes EOM müssen unterschieden und als Fehler behandelt werden; kein automatischer mbuffer-Mehrbandmodus, kein Archivsplit. Reservierte Restkapazität ist eine Schätzung, kein physischer Beweis. Ein abgebrochener Schreibversuch sperrt das Medium. Weder GNU-tar-Multivolume noch `mbuffer --tapeaware` unvalidiert einschalten.
