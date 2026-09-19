## 0.3.0
- Bis zu 20 weitere Postfächer mit getrennten IDs und Prozess-Zugangsdaten; bestehendes Hauptpostfach unverändert.
- Interne lesende Verbindung zum AngebotsDesigner, separat authentifiziert.
- Aktivierungscheckpoint, UIDVALIDITY-Prüfung und begrenzte vollständige EML-Batches.
- Nur interner Host; öffentliche OAuth-Routen unverändert. Standardmäßig deaktiviert.

# Änderungen

## 0.2.0

- Eigenständige Home-Assistant-App für amd64 auf Port 8098.
- Hintergrundabruf mit dauerhaftem Zustand im eigenen Datenverzeichnis.
- OAuth-geschützter HTTP-MCP-Zugang.
- Gesundheitsprüfung für Supervisor-Watchdog und Docker.
- Installation mit Sicherung vorhandener App-Quelldateien.
