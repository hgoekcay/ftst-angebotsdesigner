## 0.3.1
- Interner Belegimport unterstützt vollständige MIME-Nachrichten bis 32 MiB, bei 40 MiB pro Batch. Die Dokumentgrenze im empfangenden ATLAS bleibt separat begrenzt.
- Abgelehnte Anmeldung, zu große Nachricht und Transportlimits werden als feste Fehlercodes gemeldet, ohne Serverantworten oder Zugangsdaten offenzulegen.
- Nachrichten über der Grenze bleiben sichtbar blockiert; kein Überspringen und keine Cursorbestätigung bei Fehlern.

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
