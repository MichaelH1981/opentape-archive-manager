# Additive Ordnerarchivierung

Unter **Neue Archivierung planen → Sicherungsumfang → Additiv: nur neue Dateien**
wird die rekursive Auswahl vor dem Hashen mit dem lokalen Katalog verglichen.
Zielmedien werden wie bisher erst nach der Quellenplanung ausgewählt. Neue TARs
können an ein bereits beschriebenes, ausreichend freies Medium angehängt werden.
Die vorhandenen Prüfungen für Identität, Pending, Bandende und Belegkette gelten
weiterhin. Diese Funktion verändert keine alten Archive oder Quelldateien.

## Quellenzuordnung und Vertrauensbasis

Die Zuordnung besteht aus der konfigurierten Quellen-ID und ihrem aufgelösten
absoluten Wurzelverzeichnis im lokalen Katalog. Unterschiedliche Quellen-IDs oder
Wurzelverzeichnisse werden nicht vermischt. Der Betreiber muss dieselbe logische
Quelle unter dieser Zuordnung behalten; ein ausgetauschtes NAS unter demselben
Pfad wird nicht automatisch als neue Quelle erkannt. Dafür eine neue Quelle
registrieren oder ausdrücklich vollständig sichern.

Nur Dateien in VERIFIED-Archiven nicht als SUSPECT/RETIRED geführter Medien
zählen. Simulator- und physische Sicherungen sind getrennt. Die Herkunft muss
über einen abgeschlossenen, versiegelten Quellenplan und dessen gebundenen
Archivjob beziehungsweise Mehrband-Kindjobs nachvollziehbar sein. Vorhandene
Quellenpläne älterer Versionen sind damit nutzbar, ohne Schemaänderung oder
rückwirkende Manipulation ihrer Hashes. Archive ohne diese Zuordnung, etwa nach
reiner Bandrekonstruktion oder aus älteren direkten Plan-Aufrufen, werden
konservativ nicht als Basis benutzt. Ohne zuordenbare Basis werden alle Dateien
aufgenommen. Das ist keine globale Deduplizierung nach Dateinamen oder SHA-256.

## Dateivergleich

Verglichen werden relativer Pfad, Größe und Änderungszeit in Nanosekunden mit
der neuesten zugeordneten verifizierten Version. Bekannte Dateiinhalte werden
weder ins Staging kopiert noch erneut gehasht. Das Verzeichnis muss weiterhin
rekursiv inventarisiert werden; dabei entstehen Metadatenzugriffe und sichere
Dateiöffnungen. Eine neue oder umbenannte Datei gilt als neu.

Abweichende Größe oder Änderungszeit führt zu **geändert**. Die Vorgabe ist
**Anzeigen und überspringen**; alternativ kann der Benutzer **Als neue Version
sichern** wählen. Die Vorschau nennt neue, unveränderte und geänderte Dateien
sowie bis zu 100 geänderte Pfade. Metadatenvergleich beweist keine Inhaltsgleichheit:
Inhaltsänderungen mit gleicher Größe und wiederhergestellter Änderungszeit werden
nicht erkannt. Dafür die vollständige Sicherung wählen; sie liest und hasht alle
ausgewählten Dateien erneut. Übersprungene Dateien erhalten keinen neuen
Integritätsnachweis oder Verifikationszeitpunkt.

Neue und ausdrücklich eingeschlossene geänderte Dateien durchlaufen unverändert
SHA-256, TAR-Prüfung und vollständige Band-Rücklesung im gewählten Prüfmodus.
Gelöschte Quelldateien bleiben archiviert. Mehrere Versionen desselben Pfads
bleiben separate Archivkopien; für einen Restore die gewünschte Kopie auswählen.

## Persistenz und Änderungen zwischen den Phasen

Der versiegelte Quellenplan enthält die ursprüngliche Metadatenauswahl, die
Auswahl der zu übernehmenden Dateien, die Betriebsart und das Vergleichsergebnis.
Vor Medienbindung werden die vollständige ursprüngliche Auswahl und die aktuelle
Katalogbasis erneut geprüft. Änderungen verlangen einen neuen Quellenplan statt
stillschweigend eine andere Auswahl zu sichern. Die reguläre Übernahme prüft die
Fingerprints jeder ausgewählten Datei weiterhin vor und nach dem Lesen.

Ohne zu übernehmende Dateien endet der Quellenjob erfolgreich mit dem Ergebnis
NO_CHANGES. Es werden weder Medien angefordert noch leere TARs geschrieben.
Die API-Detailansicht liefert die Zusammenfassung, nicht die vollständigen privaten
Inventar- und Fingerprintlisten. Bestehende Vollpläne und Planhashes bleiben
unverändert; der Standardmodus ist weiterhin die vollständige Auswahl.

## Queue-API

`plan-source` akzeptiert zusätzlich `backup_mode: "full" | "additive"` und
`changed_policy: "skip" | "include"`. Die Felder sind optional und haben die
Vorgaben `full` und `skip`. Die spätere Medienbindung verwendet ausschließlich
den gespeicherten Quellenplan und seinen Hash. Eine Änderung des Modus oder der
Dateiauswahl während der Medienbindung ist nicht zulässig.
