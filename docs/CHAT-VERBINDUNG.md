# FTST Chat-Verbindung — vorbereitete Lesestufe

Stand 2026-11-09: Implementierung hinter `connect_enabled: false`. Nicht installiert,
nicht öffentlich erreichbar und nicht im ChatGPT-Konto verbunden. Keine erneute
Anmeldung für einzelne API-Aufrufe nötig, sobald die Verbindung einmal eingerichtet
ist; OAuth-Grants laufen nach 30 Tagen aus und können widerrufen werden.

## Was diese Stufe kann

- Angebote, Kunden und Artikel aus dem konfigurierten Billomat-Konto lesen
  (ein Datensatz oder höchstens 30 Einträge pro Seite).
- Titel, Notizen und Angebotszuordnung eines bekannten Designer-Projekts lesen.
- Vorhandene `billomat_id`/`billomat_api_key` nutzen. Keine Ausgabe von Schlüsseln.
- OAuth mit PKCE, exakter Rücksprungadresse und Ressourcenbindung, kurzen Access-
  Tokens, persistenten gehashten Tokens, Rotation und Wiederverwendungserkennung.

Keine allgemeinen Home-Assistant-Dienste, keine Konfigurations-/Secret-Abfragen,
keine Schreib-, Abschluss- oder Versandtools. Der vorhandene Browser-/Designer-
Angebotsablauf bleibt dafür nötig. Dies ist ausdrücklich noch kein vollständiger
API-Ersatz für den Plan–Angebot–Versand-Skill.

## Aktivierung nach Freigabe

1. Aktuelle installierte Designer-Version prüfen, Backup erstellen, diese Änderung
   prüfen und als eigene Releaseversion installieren. Keine Installation als gleich
   nummerierte 0.27.10-Version; Releaseversion erst bei Freigabe festlegen.
2. Eine separate HTTPS-Origin festlegen, z.B. eine vom Betreiber verwaltete
   Connect-Subdomain. `connect_public_url` muss exakt diese Origin ohne Pfad sein.
3. Ein separates Verbindungspasswort (mindestens 24 Zeichen) über die geschützten
   HA-App-Optionen setzen, nie im Chat, Git oder Screenshot. Es ist nicht das HA-
   oder Billomat-Passwort. Bestehende Secrets nicht kopieren oder rotieren.
4. Erst nach Freigabe des Zugriffs `connect_enabled` aktivieren. Der OAuth-Dienst
   hört app-intern auf 8100; es gibt kein veröffentlichtes Host-Port-Mapping.
   Ein autorisierter TLS-Reverse-Proxy muss den korrekten Host erhalten und auf den
   internen Dienst zeigen. Designer-UI 8099 bleibt ausschließlich HA Ingress.
   Keine öffentliche Weiterleitung auf UI, Supervisor oder Home-Assistant-API.
5. In ChatGPT eine benutzerdefinierte MCP-Verbindung mit OAuth auf der festgelegten
   HTTPS-Origin plus `/mcp` hinzufügen und auf der Einwilligungsseite einmal anmelden.
   Die Verfügbarkeit dieses Menüs im persönlichen Konto ist separat zu prüfen.
6. Unauthentifizierten MCP-Aufruf (401), fremden Host (421), Discovery, Zustimmung,
   Tools-Liste und genau einen lesenden Billomat-Aufruf prüfen. App neu starten und
   erneuten Zugriff mit erneuertem Token prüfen. Keine Test-Angebote versenden.
7. Rücknahme: `connect_enabled` aus, Proxyroute entfernen, Verbindung in ChatGPT
   trennen. Vorhandene Angebote und der normale Designer bleiben unverändert.

## Kameraplanung

Die geprüfte öffentliche Dokumentation unter https://docs.cctvdesigntool.com/
beschreibt Planung, lokale/Cloud-Projekte und Exporte, aber lieferte keinen Beleg
für eine öffentlich nutzbare Projektbearbeitungs-API. Deshalb keine erfundene
API-Anbindung oder Ausleitung gespeicherter Browser-Cookies implementiert.
Vorläufig Browseranmeldung verwenden und Projekt/PDF dauerhaft speichern.
Eine dauerhafte Anmeldung kann der Anbieter jederzeit beenden.

## Quellen und Grenzen

- https://developers.openai.com/plugins/build/auth
- https://developers.openai.com/plugins/build/app-quickstart
- https://www.billomat.com/api/grundlagen/authentifizierung/

`connect_http.py` ist eine isolierte Ableitung des bereits vorhandenen
`ftst_strato_mail/app/strato_http.py`, mit eigenem Scope, Cookie, Datenverzeichnis
und sachlich passendem Zustimmungsdialog. Änderungen am Maildienst sind vermieden;
Sicherheitskorrekturen beider Transportmodule künftig gemeinsam prüfen.
