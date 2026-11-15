# OTAM 0.9: rollierende Vollsicherungen

Status: Implementierungskandidat, noch keine physische Recyclingabnahme.
Die Liveinstallation und ihre Freigaben bleiben bis zum geprüften Deployment
unverändert. Das Konzept in `rolling-backups.md` beschreibt auch spätere Ausbaustufen.

## Enthaltener Umfang

- Neue Ansicht **Rollierende Sicherungen**, getrennt vom dauerhaften Bandarchiv.
- Pro Regel 1 bis 32 Bandsätze; spätere Erweiterung von 1 auf 2 oder 3 ohne
  Neuschreiben bestehender Generationen. Satzanzahl und erhaltene Bandstände
  sind getrennte Werte. Eine Verkleinerung bestehender Sätze wird nicht automatisch
  durchgeführt.
- Bis zu 32 registrierte Rotationskassetten pro Satz, keine gemeinsame aktive
  Nutzung derselben Kassette in mehreren Sätzen. Zusätzliche Kassetten können vor
  dem endgültigen Schreibplan aufgenommen werden, auch nach einer Kapazitätswarnung.
- Vollständige lokale Quellenaufnahme vor der Medienbindung. Jeder Lauf enthält
  den vollständigen ausgewählten Dateibestand, keine globale additive Basis.
- Explizite Wahl des Ziel-Bandsatzes; kein unbeaufsichtigter Zeitplan oder
  automatisches Überschreiben. Auswahl und Schreiben bleiben prüfbare Schritte.
- Aufbewahrungsdauer, Mindestzahl während der Erneuerung erhaltener Bandstände
  und dauerhafter manueller Schutz. Neue freie Kassetten erlauben den Erstaufbau,
  auch wenn die gewünschte Anzahl erhaltener Stände noch nicht erreicht ist.
- Separater 300-Sekunden-Review pro wiederzuverwendender Kassette, dauerhafter
  Intent vor möglichem Write, neue Medien-UUID und erhaltene Historie.
- Bekannte fremde Archivjobs auf einem zugeordneten Band bleiben gesperrt.
  Zuordnung zu einem Satz ist keine nachträgliche Löschfreigabe für alte Archive.
- Ein Medien-Childjob pro tatsächlich genutzter Kassette; bestehende Pipeline für
  Staging, vollständige Bandrücklesung und geführten Wechsel bleibt erhalten.
- Quellenaufnahme bleibt nach dem vollständigen Bandabschluss erhalten. Die
  Aktion **Lokale Quellenaufnahme bereinigen** entfernt nur diese eigene Kopie,
  nach Prüfung des verfügbaren VERIFIED-Satzes. Originalquelle unverändert.
- Gesamtrestore in ein privates Arbeitsverzeichnis, explizit je Medium fortgesetzt.
  Erst nach vollständigem Abgleich von Dateianzahl, Größen und Gesamtinventarhash
  wird ein neues Ziel veröffentlicht. Fehler behalten private Daten und Sperren.

## Grenzen dieser ersten Version

Physisches Recycling verlangt zusätzlich `physical_rotation: true` sowie die
bestehenden Freigaben für physische Archivierung und Initialisierung. Diese neue
Freigabe bleibt vor realer Hardwareabnahme false. Softwaretests mit Dateigeräten
ersetzen keine physische Abnahme. Neue freie zugeordnete Medien benutzen den
bestehenden regulären Schreibpfad.

Nach der Bindung des Schreibplans lässt sich ein laufender Satz noch nicht
umplanen. Die Oberfläche/API sperrt eine Erweiterung an dieser Stelle, auch am
Bandwechsel. Versionierte Fortsetzungspläne sind eine spätere Erweiterung des
Konzepts. Unerwartetes EOM oder Pending wird niemals automatisch umgangen.

Einzelne Dateien werden weiterhin nicht zwischen Medien geteilt. Ein
Borg-Repository als Verzeichnis braucht normalerweise keine Einzeldateisegmentierung.
OTAM erstellt noch keine Borg-Sperre oder Dateisystem-Snapshots automatisch.
Vorbereitung verlangt die ausdrückliche Bestätigung eines konsistenten, während
seiner Übernahme unveränderlichen Quellenstands. Borg-Keys/Passphrase bleiben
getrennt zu sichern; SHA-256 allein ist keine Borg-Konsistenzprüfung.

Fehlgeschlagene oder unterbrochene Wiederverwendung bleibt konservativ gesperrt;
kein allgemeiner Force-Schalter oder automatische Markerbereinigung. Nach
unterbrochenem Satz-Restore bleiben dessen Reservierungen bis zur administrativen
Klärung erhalten. Reines Warten auf das richtige Medium ist dagegen fortsetzbar.

## Format und unabhängige Recovery

Das vorhandene `otam-pax-v1`-Format bleibt bestehen; keine zusätzlichen unbekannten
Banddateien und keine Änderung der Daten/Receipt-Paarung. Jedes Datenmanifest
enthält optional `rotation` mit Format `otam-full-generation-v1`, Generation,
Regel, Satz, tatsächlichen Medien-UUIDs, Gesamtdateianzahl, Nutzbytes und SHA-256
des vollständigen Inventars. Der bestehende TAR-Hash sichert diese Metadaten mit.
Für den kleinen Descriptor wird ein zusätzlicher 10-KiB-Metadatenbudgetblock pro
TAR geplant, ohne globalen prozentualen Kapazitätsabzug.

Der Inventarhash ist SHA-256 über die kanonische JSON-Liste aller Dateieinträge,
lexikalisch nach `path` sortiert. Ein Eintrag enthält genau `path`, `size`, `sha256`.
JSON: `ensure_ascii=True`, `sort_keys=True`, Trennzeichen `(',', ':')`, UTF-8.
Alle TARs müssen denselben Descriptor tragen; Pfade dürfen nicht doppelt vorkommen.
Alle deklarierten Medien müssen vertreten sein. Gelöschte Quelldateien aus früheren
Generationen gelangen nicht in den Restore eines neuen Vollstands.

Nach dem Kopieren aller zugehörigen Daten-TARs auf Festplatte kann unabhängig von
OTAM und dessen Datenbank das Standardbibliothek-Skript verwendet werden:

```sh
python3 tools/restore_rotation.py --target /restore/neues-repository /recovery/data-*.tar
```

Optional `--expected-inventory-hash <SHA256>` aus einem getrennt vertrauenswürdig
aufbewahrten Nachweis hinzufügen. Prüfsummen schützen gegen Beschädigung, ohne
getrennten Vertrauensanker nicht gegen gezielte Manipulation aller Metadaten.
Header/Receipt-TARs werden dem Skript nicht als Daten-TAR übergeben.
Das Skript ist Komfort; die dokumentierten normalen PAX-TAR-Dateien sind auch mit
`tar` lesbar und die Dateien mit üblichen SHA-256-Werkzeugen prüfbar.

Ein gesondertes physisches Abschlussobjekt aus dem Langfristkonzept ist noch
nicht enthalten. Vollständigkeit wird durch das verteilte Dateiinventar und die
bestehenden geprüften Receipts nachgewiesen; der historische Betriebsstatus der
Gesamtgeneration bleibt Kataloginformation. Recovery ohne Katalog kann Inhalte
und Vollständigkeit selbst prüfen, ohne einen früheren Jobabschluss zu behaupten.

## Schema, Synchronisation und Update

Katalogschema 3 ergänzt Regeln, Sätze, zeitliche Mitgliedschaften, Generationen,
Generationsvolumen und Recyclingintents. `media.generation` bleibt LTO-Generation.
Überschriebene Inkarnationen sind RETIRED, betroffene Generationen UNAVAILABLE;
frühere VERIFIED-Ergebnisse bleiben als Historie erhalten. Alte Inhalte zählen
nicht als verfügbare Restorekopie oder additive Basis.

0.9 kann signierte Snapshots von Schema 2 und 3 prüfen. 0.8.9-Katalogempfänger
lehnen Schema 3 ab und müssen vor dem ersten 0.9-Push aktualisiert werden. Ein
Rückwechsel auf 0.8.9 benötigt das gesicherte Schema-2-Katalogbackup, keine
Schema-Rückkonvertierung. Nach neuen Bandwrites darf kein veraltetes Backup als
aktueller Katalog eingesetzt werden; dann ist eine kontrollierte Recovery nötig.

## Hardwareabnahme vor Aktivierung des Recycling-Gates

Benötigt wird eine ausdrücklich entbehrliche, bereits initialisierte und leere
Rotationskassette. Keine produktiven Archive werden zur Abkürzung gelöscht.
Auf diesem Medium: winzige vollständige Generation schreiben und rücklesen,
Review und neue UUID prüfen, zweite vollständige Generation schreiben/rücklesen,
Gesamtrestore und unabhängige Hashprüfung. Frische Drive-/MAM-Prüfung vor jedem
Write, gemeinsame Live-Gerätesperren/Pending und Worker-Wiederstart bleiben Pflicht.
Kein großer Vollbandtest ist hierfür erforderlich.
