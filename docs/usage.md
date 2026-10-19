# Bedienung: vollständiger Simulatorzyklus

## Webablauf für Dateiauswahl und mehrere Medien (0.5)

Unter **Planung** eine freigegebene Quelle wählen. **Dateien und Ordner auswählen** öffnet deren serverseitigen Dateibrowser; einzelne Dateien und ganze Unterordner sind kombinierbar. Ohne Auswahl wird die ganze Quelle inventarisiert. Anschließend ein oder mehrere Simulatormedien in der angezeigten Reihenfolge wählen. Ein 100-GB-Ordner mit 75-GB-TAR-Zielgröße wird ungefähr in ein erstes TAR bis zur Zielgröße und ein weiteres TAR mit dem Rest gruppiert; Dateien werden nie geteilt. Die tatsächlichen TAR-Größen hängen von Dateigrenzen und TAR-Metadaten ab.

Bei mehr als einem Medium erstellt OTAM einen übergeordneten Plan und zeigt pro Medium einen Teilauftrag. Den Plan prüfen und für das erste Medium die vollständige Job-ID bestätigen. Nach dessen vollständiger Rücklesung erscheint **Medienwechsel erforderlich**; nun das angezeigte nächste Medium bestätigen. Erst wenn alle Mediensegmente verifiziert sind, ist der Gesamtauftrag VERIFIED. Ein einzelnes TAR oder eine einzelne Datei, die nicht vollständig auf ein verfügbares Medium passt, wird vor dem Schreiben abgelehnt.

Unter **Verifikation** ist „Nach jedem TAR zurücklesen“ die platzsparende Vorgabe. „Nach allen TARs auf diesem Medium zurücklesen“ schreibt erst alle vorbereiteten lokalen TARs eines Mediums und liest sie danach vollständig zurück, also vor dem nächsten Medium bzw. vor dem Jobabschluss. Dafür muss das Staging alle TARs dieses Mediums gleichzeitig aufnehmen. Ein Schreibabschluss allein erzeugt keinen VERIFIED-Status. Diese Abläufe sind derzeit ausschließlich am persistenten Simulator freigegeben; reale LTO-Archivierung bleibt gesperrt.

Alle Beispiele beziehen sich auf neue lokale Testverzeichnisse, nicht auf /dev/nst0. Keine Quelldatei wird gelöscht. Globales --db muss vor dem Unterbefehl stehen. Start im Projektverzeichnis; Quelle außerhalb von Datenbank, Medium und Spool.

```bash
umask 077
mkdir -p demo/source
printf 'Archivtest\n' > demo/source/beispiel.txt
python3 -m otam --db demo/catalog.sqlite init-sim demo/tape --label TEST-001
```

Die ausgegebene `media_id` als BAND_UUID übernehmen. UUIDs in den folgenden Beispielen sind Platzhalter, keine Literalwerte:

```bash
python3 -m otam --db demo/catalog.sqlite plan demo/tape demo/source --media-id BAND_UUID
```

Plan vollständig lesen: Quelle, Band-ID, Dateien, Prüfsummen, Archivgruppen, Schätzbedarf und Restkapazität. Danach die ausgegebene job_id als JOB_UUID einsetzen:

```bash
python3 -m otam --db demo/catalog.sqlite backup demo/tape JOB_UUID --confirm JOB_UUID --staging demo/staging
python3 -m otam --db demo/catalog.sqlite verify demo/tape --media-id BAND_UUID
python3 -m otam --db demo/catalog.sqlite search beispiel
python3 -m otam --db demo/catalog.sqlite restore-plan demo/tape --media-id BAND_UUID --path beispiel.txt --target demo/restored
python3 -m otam --db demo/catalog.sqlite restore demo/tape --media-id BAND_UUID --path beispiel.txt --target demo/restored
python3 -m otam --db demo/catalog.sqlite jobs
```

`restore --archive-id ARCHIV_UUID` wählt eine bestimmte Version. Ohne --path werden alle verifizierten Dateien des Mediums ausgewählt. Mehrere Versionen desselben Zielpfads führen zum Fehler, statt eine Version still auszuwählen. Mehrere --path wählen Dateien/Verzeichnisse; jeder angeforderte Pfad muss vorkommen. Restore überschreibt niemals Dateien. Auch Symlinks in übergeordneten Zielkomponenten sind verboten; auf macOS ggf. den tatsächlichen `/private/var/...`-Pfad statt `/var/...` verwenden. Das ist eine bewusste strikte Pfadprüfung.

```bash
python3 -m otam --db demo/catalog.sqlite export > demo/catalog-export.json
python3 -m otam --db demo/catalog.sqlite export --format csv --table media > demo/media.csv
python3 -m otam --db demo/catalog.sqlite export --format csv --table files > demo/files.csv
```

Vor einem weiteren Backup einen neuen Plan erstellen; erfolgreich abgeschlossene Pläne werden nie wiederholt. Fehlgeschlagene Jobs nur mit ausdrücklichem --resume nach erneuter Prüfung wiederaufnehmen. Anhängen erfordert einen vollständig lesbaren und abgeschlossenen Tail. Der Preview scannt vorher konservativ das ganze Medium; Optimierung unnötiger Rückbewegungen folgt mit dem echten Adapter, nicht anhand ungeprüfter Positionsannahmen.

Nach Prozessausfall:

```bash
python3 -m otam --db demo/catalog.sqlite recover-jobs demo/tape --media-id BAND_UUID
```

RUNNING/PLANNING wird INTERRUPTED, WRITING wird INCOMPLETE und das Medium SUSPECT. Kein automatisches Weiterschreiben. Ein voller geprüfter Daten-/Receipt-Paarabschluss kann mit `rebuild` erneut verifiziert werden. Ein partielles Ende bleibt gesperrt. Quellbestand behalten und Fehlerursache untersuchen. Niemals `.partial`-Dateien löschen, um Append zu erzwingen.

Bei Restorefehler bleiben zuvor erfolgreich erzeugte Dateien erhalten, der Gesamtjob ist FAILED. Kein Rollback-Versprechen. Ein neuer Restore erfolgt in ein neues Ziel; Quelldateien und existierende Zielinhalte werden nicht entfernt.


## Staging getrennt bedienen

Nach `plan` kann das Laufwerk ausgeschaltet bleiben:

```bash
python3 -m otam --db demo/catalog.sqlite stage JOB_UUID --staging demo/staging
python3 -m otam --db demo/catalog.sqlite staging-status --staging demo/staging --job-id JOB_UUID
python3 -m otam --db demo/catalog.sqlite backup demo/tape JOB_UUID --confirm JOB_UUID --staging demo/staging
```

Fertige READY-TARs werden erkannt und erneut geprüft; Quelldaten werden beim späteren Write nicht mehr benötigt. Ohne separaten stage-Schritt bereitet backup jeweils ein vollständiges Archiv vor, schreibt/verifiziert/bereinigt es und beginnt erst dann das nächste. Optional `backup --prepare-all`.

Nach Prozessabbruch zuerst recover-jobs ausführen, Ergebnisse und Medium untersuchen. Nur bei beweisbar sauberem Ende kann `backup ... --resume --confirm JOB_UUID --staging demo/staging` fortfahren. Ein unvollständiger Tail bleibt gesperrt; keine automatische Reparatur. Dateien im Staging nicht manuell verändern, löschen oder chmod-freigeben. Staging ersetzt keine unabhängige Sicherung. Siehe [Staging](staging.md).
