# Parallele Rückleseprüfung ab 0.8.9

Ziel ist CPU-Reserve bei gleichem vollständigem Integritätsnachweis und einem
sequenziellen Bandlesepass. Der vorhandene Prefetch-Produzent berechnet den
SHA-256 des vollständigen TAR-Stroms aus seinen unveränderlichen Records.
Der Konsument prüft gleichzeitig TAR-Struktur, Manifest und sämtliche Datei-Hashes.
Keine zweite Queue, kein neuer Prozess, keine zusätzlichen Nutzdatenkopien für die
Hashübergabe und keine Vergrößerung des bestehenden Puffers.

## Sicherheitsgrenzen

- Der Produzent bleibt alleiniger Geräte-Leser; die erste Dateimarke ist weiterhin
  verriegelt. Er liest keinen Record nach dem ersten EOF.
- Der TAR-Hash umfasst auch Endblöcke und Padding bis zur physischen Dateimarke.
- Das Digest wird nur nach erfolgreichem Produzentenabschluss und vollständiger
  Konsumierung exakt aller empfangenen Bytes herausgegeben. Frühes Schließen,
  Lesefehler und Bytezahldifferenzen bleiben Fehler.
- Der volle TAR-Hash, die Dateihashes und die bestehende Receipt-Kette bleiben
  erforderlich. Keine Veröffentlichung von Restore-Dateien oder VERIFIED vor dem
  Abschluss aller Prüfungen. Das Bandformat und bestehende Pläne ändern sich nicht.
- Ohne Prefetch, etwa bei zu wenig verfügbarem RAM, bleibt der synchrone vollständige
  Prüfer erhalten. `archive_hash_mode=producer` kennzeichnet den neuen Pfad in den
  vorhandenen Fortschrittsereignissen; es ist kein eigener Integritätsnachweis.

## Konkurrierende Last

Die häufig abgefragte Jobliste lädt nur Eltern-/Kindverknüpfungen aus Plan-JSON in
Python. Große historische Datei-/Inventarlisten werden nicht mehr für jede
Listenaktualisierung materialisiert; die Jobdetails und verbindlichen Pläne bleiben
unverändert. Die normale systemd-Unit verwendet `CPUWeight=200`. Auf dem Bandserver
wurde dies als getrennt gesicherter Drop-in installiert und der wirksame Kernelwert
200 geprüft. Es ist eine relative Bevorzugung unter Konkurrenz, keine exklusive
Kernreservierung, keine Echtzeitpriorität und kein Schutz vor thermischem Drosseln.

## Messung und Abnahme

Auf dem Celeron J4005 am 29.10.2026: sechs abwechselnde RAM-only-TAR-Prüfungen mit je
64 MiB Nutzdaten, ohne Band-, NAS- oder Staging-Payloadzugriff. Beide Varianten
prüften identische Archiv- und Dateihashes. Mediane:

| Messung | Bisher | Produzenten-Hash |
| --- | ---: | ---: |
| Durchsatz des RAM-Prüfers | 107,20 MB/s | 135,28 MB/s |
| CPU-Zeit des Hauptthreads je TAR | 0,594 s | 0,494 s |
| CPU-Zeit des Produzenten je TAR | 0,037 s | 0,127 s |
| Gesamte Prozess-CPU-Zeit je TAR | 0,635 s | 0,621 s |

Das entspricht rund 26 % mehr Prüfdurchsatz und 17 % weniger Hauptthread-CPU-Zeit
für dieselben Daten. Die sehr kurzen RAM-Läufe sind kein thermischer Dauertest,
kein Nachweis einer bestimmten Bandrate und keine Garantie gegen Lesepausen.
Im ungedrosselten Benchmark läuft der Hauptthread weiterhin nahe einem vollen
Kern; die nutzbare Reserve ergibt sich aus der höheren Kapazität bei begrenzter
realer Leserate, nicht aus einem behaupteten niedrigen Benchmark-CPU-Prozentwert.

323 lokale Softwaretests mit einem Skip und 323/323 Debian-Tests bestanden.
Neue Tests prüfen Threadzuständigkeit, exakt einen Pass/erste Dateimarke, Padding,
frühen Abschluss, Fehler nach TAR-Ende, weiterhin getrennt erforderliche TAR-/Datei-
Hashprüfung sowie die schlanke Joblistenprojektion. Bestehende Linux-Adaptertests
prüfen den normalen Pipelinepfad. Kein zusätzlicher physischer Bandlauf.

0.8.9 wurde nach vollständigem VERIFIED-Abschluss des Multimedia-Jobs und bei leerer
Queue installiert. Paket, Konfiguration und beide Datenbanken gesichert; globale
I/O-/Workersperre, Dienstkontoimport, Gesundheitsprüfung, frische Telemetrie und
Katalog-/Bindungsfingerprints geprüft. Kein Job gestartet oder erneut gelesen.
