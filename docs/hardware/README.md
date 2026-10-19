# Hardware-Abnahme und lokale Diagnosen

Die Softwaretests verwenden den persistenten Bandsimulator. Der reguläre Linux-Tape-Adapter ist bis zur Abnahme eines vollständigen OTAM-Archivierungs- und Restore-Zyklus weiterhin deaktiviert. Kein automatisierter Softwaretest darf ein physisches Band verändern. Gesondert freigegebene Hardware-Wartungstests haben die Kassette `HC4BELa904` vollständig mit rekonstruierbaren Daten beschrieben und zurückgelesen; diese Abnahme ersetzt den fehlenden regulären Archivpfad nicht. Aktueller Status: [Produktionsfreigabe](../production-readiness.md).

Vorhandene Hardware-Testskripte wurden lesend untersucht und nicht verändert. Die lokalen Diagnoseberichte und Messrohdaten enthalten interne Netzwerkadressen, Benutzerpfade und Geräteseriennummern. Sie bleiben auf dem Entwicklungsrechner erhalten und sind über `.gitignore` vom Repository ausgeschlossen.

## Bisherige Erkenntnisse

- Linux erkennt den Intel-Onboard-SATA-Controller und den separaten IBM/LSI-SAS-HBA. Die System-SSD hängt am Onboard-SATA-Controller.
- Das IBM ULT3580-HH4 wurde erkannt und mit der ausdrücklich freigegebenen Kassette in getrennten Wartungsläufen geprüft. Der vollständige Vollbandlauf erreichte das erste ENOSPC/Frühwarn-Bandende und bestand die SHA-256-Rücklesung.
- Die interne SSD bestand kurze und lange SMART-Selbsttests, zeigte aber im 30-Minuten-Lesetest erhebliche Durchsatzschwankungen. Ein Kabel-, SSD- oder Controllerdefekt ist damit nicht eindeutig bestimmt.
- Eine andere, externe HDD wurde über USB 3 rein lesend in drei Bereichen je zehn Minuten geprüft. Durchschnitt außen/Mitte/innen: 149,59 / 138,60 / 88,45 MB/s; drei Transport-Resets verursachten lange Lesepausen.
- Die später intern per SATA eingebaute Seagate-ST2000DM001-HDD bestand einen 30-Minuten-O_DIRECT-Test und fünf ausschließlich lesende Zonenmessungen bis 1,6 TB nach dem 120-MB/s-FIFO-Puffermodell. Sie ist nach einem kontrollierten Neustart als optionales ext4-Staging verfügbar. Quellen bleiben erhalten; der Staging-Puffer ist keine unabhängige Sicherung.

Verbindliches weiteres Verfahren: [Staging](../staging.md), [Test- und Abnahmeplan](../testing.md), [Risiken](../architecture/risks.md). Physische Schreibtests ausschließlich mit ausdrücklich freigegebenem entbehrlichem Testband. Keine automatische Übernahme destruktiver Funktionen aus Diagnoseskripten. Der lokale, nicht auf GitHub veröffentlichte Rohdatenordner `docs/hardware/testdaten-2026-10-19/` enthält eine ausführliche Messübersicht.
