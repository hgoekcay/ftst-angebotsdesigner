# Speicherung und Betrieb

Home Assistant setzt `FTST_DATA_DIR=/data/ftst_angebotsdesigner`.
Die Datei `offers.sqlite3` enthält Kundendarstellungen; Billomat bleibt Quelle für kaufmännische Daten.
Lokal kann `FTST_DATA_DIR` auf einen absoluten dauerhaften Ordner gesetzt werden. Ohne Einstellung wird `ftst_angebotsdesigner/instance` verwendet. Kein temporärer Fallback.

SQLite verwendet Transaktionen und fünf Sekunden Wartezeit bei konkurrierenden Zugriffen. Schemaänderungen sind über `PRAGMA user_version` versioniert. Ein neueres oder beschädigtes Schema wird nicht gelöscht, zurückgesetzt oder durch eine leere Datenbank ersetzt. Ein Speicherfehler ergibt HTTP 503 und keine grüne Speichern-Bestätigung.

Vorhandene, noch signaturgültige Flask-Cookies werden beim Öffnen des jeweiligen Angebots übernommen. Anschließend wird der betreffende Cookie-Eintrag entfernt. Bereits in SQLite gespeicherte Bearbeitungen haben Vorrang. Cookies mit einem nach Neustart ungültigen alten Zufallsschlüssel sind technisch nicht wiederherstellbar. Vor dem ersten Update wichtige Bearbeitungen sichern; ein vorhandenes festes `flask_secret` beibehalten.

Sicherung: Home-Assistant-App-Backup einschließlich `/data` verwenden. Für manuelle Dateikopien App vorher stoppen; den gesamten Datenordner sichern. Restore bei gestoppter App durchführen und `/health` sowie ein gespeichertes Angebot prüfen. Keinen Datenordner aus einer neueren Version mit einer älteren App öffnen.

Lokale Entwicklung: `python -m venv .venv`, dann `python -m pip install -r requirements-dev.txt`. Tests mit `python -m pytest`; kritisches Lint mit `python -m ruff check --select E9,F63,F7,F82 ftst_angebotsdesigner tests`; Syntax mit `python -m compileall -q ftst_angebotsdesigner`.

Die App ist für den authentifizierten Home-Assistant-Ingress bestimmt. Eine direkte öffentliche Freigabe ohne separate Anmeldung ist nicht vorgesehen.
