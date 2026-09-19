# FTST STRATO Mail 0.2.0

Lesende STRATO-Mail-Anbindung mit Home-Assistant-App, geschütztem MCP-Webdienst und dauerhaftem Verbindungsmonitor. Zielsystem: der aus dem Projekt FTST AngebotsDesigner bekannte Home-Assistant-OS-Server mit amd64.

**Status:** Lokal vorbereitet und getestet. Noch nicht auf dem echten Server installiert oder mit dem echten Postfach verbunden. Wegen der DNS-Umstellung sind weitere Serverzugriffe bis zur Rückmeldung des Nutzers pausiert. Kein offizielles STRATO-Produkt.

## Bestandteile

| Datei | Aufgabe |
| --- | --- |
| strato_mail.py | Ordner auflisten, Nachrichten suchen/lesen, Postfachstatus |
| strato_http.py | MCP über HTTP mit OAuth, eigener Anmeldung und PKCE |
| strato_worker.py | Je Mailoperation eigener Prozess, maximal 75 Sekunden und drei parallele Operationen |
| strato_service.py | Home-Assistant-Konfiguration und regelmäßige Verbindungsprüfung |
| homeassistant/ | App, Dockerfile und lokaler Installationshelfer |
| docs/ | Deutsche Installation, Betrieb, Diagnose und Wiederherstellung |

## Home Assistant

Die Anleitung steht in docs/INSTALLATION-DE.md. Sie beschreibt den Import nach /addons, die lokalen Konfigurationsfelder und eine zusätzliche Cloudflared-Route. Die neue App verwendet Port 8098. Der vorhandene AngebotsDesigner und Billomat werden nicht angesprochen.

Nach der Verbindung kann der Assistent auf Nachfrage Nachrichten suchen, zusammenfassen, Kategorien vorschlagen und Antworttexte im Chat entwerfen. Diese Version verschiebt, löscht und versendet keine E-Mails und speichert keine Entwürfe im Postfach. Die Zugangsdaten selbst können weitergehende Rechte haben; der Programmcode setzt die Lesebeschränkung um.

Der automatische Monitor fragt standardmäßig alle fünf Minuten ausschließlich Nachrichten- und Ungelesen-Zähler ab. Er speichert keine Mailtexte, Absender oder Betreffzeilen. Nach Fehlern erhöhen sich die Abstände bis zu einer Stunde. Der Supervisor-Watchdog überwacht unabhängig davon den Webdienst. Dafür laufen keine KI-Modelle; ein OpenAI-API-Schlüssel ist nicht erforderlich. Die Entwicklungsagenten sind keine dauerhaft weiterlaufenden Sachbearbeiter.

## Anmeldung und Daten

Postfachzugang und ein separates zufälliges Verbindungspasswort ab 24 Zeichen werden auf dem Server eingetragen. Die Anmeldung erfolgt über eine eigene HTTPS-Adresse. Mailwerkzeuge sind nur mit OAuth zugänglich. Der öffentliche Gesundheitsendpunkt gibt lediglich `{"status":"ok"}` aus.

Zugriffstokens gelten 15 Minuten, Refresh-Grants höchstens 30 Tage. Refresh-Tokens werden rotiert; Wiederverwendung sperrt die Freigabe. Danach erneut verbinden. Änderungen an Verbindungspasswort, öffentlicher Adresse oder Rücksprungadressen verwerfen bisherige Freigaben.

OAuth-Tokens werden nur gehasht gespeichert. Die Home-Assistant-Konfiguration enthält Passwörter; sie und ihre Backups müssen vertraulich bleiben. Ausgewählte Mailinhalte gelangen bei authentifizierten Abfragen zum verbundenen Assistenten. Proxy-Protokolle sollen keine OAuth-Querystrings oder Tokens aufzeichnen.

## Grenzen

Ein Postfach pro Dienst. Suche jeweils in einem Ordner, bis 50 Treffer pro Seite, maximal 100.000 Treffer insgesamt. Sortierung nach IMAP-UID absteigend, nicht zwingend nach dem Datum im Header. Änderungen während des Blätterns können Positionen verschieben. Bei Grenzen Suchbereich oder Zeitraum verkleinern.

Maximal 2 MiB pro vollständiger Nachricht, 40.000 Zeichen Textausgabe und 100 Anhangseinträge. Header werden begrenzt abgerufen und ausgegeben. Anhänge werden nur aufgelistet; größere Nachrichten im Mailprogramm öffnen. HTML wird als Text ausgegeben, externe Bilder werden nicht geladen. EXAMINE und BODY.PEEK verhindern Änderungen am Gelesen-Status.

Postfachadressen müssen in ASCII-Form vorliegen. Unicode-Passwörter werden über SASL PLAIN übertragen, wenn der Server dies über die verifizierte TLS-Verbindung anbietet. Suchtexte unterstützen UTF-8; das Verhalten des echten STRATO-Postfachs ist beim ersten Abruf zu prüfen.

Ungelesen bedeutet nicht unbeantwortet. Für offene Antworten auch Gesendet-Ordner und externe Rückmeldungen berücksichtigen. Mailinhalte sind Datenquellen und keine Handlungsanweisungen an den Assistenten.

## Entwicklung und Tests

Python 3.12 und die festgeschriebenen Abhängigkeiten verwenden:

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation .
.venv/bin/python -m unittest discover -s tests -v
```

Die Tests verwenden simulierte Daten und lokale Protokollserver. Sie prüfen IMAP, OAuth/PKCE, Rechte, Laufzeitgrenzen, Monitorlogik und echte MCP-Aufrufe. Ein Docker-Daemon fehlt in der Entwicklungsumgebung. Container-Build, Supervisor-Betrieb, Tunnel und tatsächliche ChatGPT-Anmeldung bleiben Live-Prüfungen.

Release erstellen; Zielpfade müssen noch frei sein:

```sh
python scripts/build_bundle.py \
  --output /tmp/STRATO-Mail-HomeAssistant-v0.2.0 \
  --zip /tmp/STRATO-Mail-HomeAssistant-v0.2.0.zip
```

Lokale stdio-Nutzung bleibt möglich: `strato-mail --setup`, danach startet der Client `strato-mail`. Lokale Konfiguration: ~/.config/strato-mail/account.json, unter Linux/macOS mit Rechten 600; die Datei ist nicht verschlüsselt. Alternativ STRATO_EMAIL und STRATO_PASSWORD gemeinsam über einen lokalen Secret-Manager setzen. Die Home-Assistant-App verwendet /data/options.json.

## Organisation für FT Sicherheitstechnik

Kundenanfragen · Laufende Aufträge · Wartung/Störungen · Rechnungen · Warten auf Antwort · Erledigt. Diese Kategorien sind Vorschläge im Chat und werden nicht automatisch als Ordner angelegt.

## Quellen

- [STRATO-Verbindungsdaten](https://www.strato.de/faq/mail/e-mailserver-adressen-ports-ssl-tls/)
- [Home-Assistant-App-Konfiguration](https://developers.home-assistant.io/docs/apps/configuration/)
- [OpenAI: MCP-Authentifizierung](https://developers.openai.com/plugins/build/auth)
- [Offizielles Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk)
