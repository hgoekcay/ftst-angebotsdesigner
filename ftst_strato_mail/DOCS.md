# FTST STRATO Mail einrichten

1. In der Konfiguration die vollständige STRATO-E-Mail-Adresse und das
   Postfach-Passwort eingeben. Das Passwort gehört nur in diese lokale Einstellung.
2. `public_url` auf die gewählte externe HTTPS-Adresse setzen, ohne `/mcp`,
   beispielsweise `https://mail-assistent.ftsicherheit.org`. Dieser Name ist nur
   ein Vorschlag und wird durch die App nicht angelegt.
3. Ein eigenes, zufälliges `login_password` mit mindestens 24 Zeichen vergeben.
   Dieses Passwort ist für die Anmeldung des Assistenten bestimmt; es muss sich
   vom Postfach-Passwort unterscheiden.
4. `folder: INBOX` und `poll_interval_seconds: 300` als Startwerte verwenden.
5. Speichern, starten sowie „Beim Booten starten“ und „Watchdog“ aktivieren.
6. Die getrennte Installation-/Tunnelanleitung im Paket abschließen.

| Option | Bedeutung |
| --- | --- |
| `email` | Vollständige STRATO-Postfachadresse |
| `password` | Passwort dieses Postfachs |
| `public_url` | Externe HTTPS-Basisadresse, ohne Pfad oder abschließendes `/mcp` |
| `login_password` | Eigenes zufälliges Passwort für die OAuth-Anmeldung, mindestens 24 Zeichen |
| `folder` | Ordner für den regelmäßigen Hintergrundabruf |
| `poll_interval_seconds` | Abrufabstand, standardmäßig 300 Sekunden |
| `allowed_redirect_uris` | Exakte erlaubte Rücksprungadressen des MCP-Clients |

Die Oberfläche der App ist keine Mail-Weboberfläche. `/healthz` zeigt nur, ob der
Webdienst erreichbar ist; den letzten erfolgreichen Mailabruf zeigt das
authentifizierte MCP-Werkzeug `service_status`.

Die technische Überwachung läuft unabhängig von der Anmeldung im Chat. Für den
Chat-Zugang gelten Zugriffstokens 15 Minuten und OAuth-Freigaben höchstens 30 Tage;
danach ist eine erneute Anmeldung nötig. Ein Wechsel des Anmeldepassworts, der
öffentlichen URL oder der erlaubten Rücksprungadressen verwirft beim nächsten
Dienststart bisherige Freigaben und Tokens.

Im Hintergrund werden die Erreichbarkeit und die Anzahl vorhandener/ungelesener
Nachrichten geprüft. Inhalte liest der verbundene Assistent erst bei einem
Werkzeugaufruf. Zusammenfassungen, Ordnungsvorschläge und Antwortentwürfe entstehen
im Chat. Die App verschiebt, löscht und versendet keine E-Mails. Das Angebotsprogramm
und Billomat werden nicht angesprochen. SMTP und ein Home-Assistant-API-Zugang sind
nicht nötig.

Port 8098 bleibt im lokalen Netz. Für den Zugang aus ChatGPT wird ein eigener
Cloudflare-Tunnel-Hostname ergänzt. Die schon vorhandenen Tunnelrouten bleiben
erhalten. Die genaue Anleitung liegt im Paket.


## Interne AngebotsDesigner-Verbindung (0.3.0)

`bridge_token` aktiviert die lokale Verbindung. Das separate zufällige Token
(mindestens 32 Zufallsbytes, URL-sicher kodiert, 43–128 Zeichen) wird direkt auf
dem Server erzeugt und beiden Apps lokal bereitgestellt. Niemals ins Chatfenster
oder in Protokolle kopieren. Leer lässt die Brücke deaktiviert.

Die Verbindung akzeptiert ausschließlich den Host `local-ftst-strato-mail:8098`,
einen passenden Bearer-Token und Anfragen ohne Origin. Sie ist für Docker-DNS im
Supervisor-Netz bestimmt. Den Cloudflare-Tunnel nicht auf diesen Host-Header
umschreiben und keine öffentliche Route zu `/internal/` anlegen. Hostprüfung ist
keine Netzwerk-Firewall; das zufällige Token ist die Authentifizierung.

Das bestehende Hauptpostfach bleibt unverändert und hat die ID `primary`.
Unter `accounts` können bis zu 20 zusätzliche STRATO-Postfächer eingetragen werden:

```yaml
accounts:
  - id: vertrieb
    email: vertrieb@example.de
    password: HIER_LOKAL_EINTRAGEN
    folder: INBOX
    enabled: true
```

IDs müssen eindeutig sein und aus 1–40 Kleinbuchstaben, Ziffern, Unterstrichen oder
Bindestrichen bestehen. `primary` ist reserviert. `folder` ist optional (INBOX),
`enabled` ist optional (true). Doppelte Kombinationen aus Mailadresse und Ordner
werden abgewiesen. Änderungen lokal speichern und die App neu starten. Deaktivierte
Postfächer sind über die Brücke nicht abrufbar. Zugangsdaten werden ausschließlich
im jeweiligen kurzlebigen Abrufprozess ausgewählt; parallele Abrufe verwenden keine
wechselnden gemeinsamen Zugangsdaten. Bestehende öffentliche OAuth/MCP-Funktionen
verwenden weiterhin nur das Hauptpostfach.

GET `/internal/mail/accounts` liefert ausschließlich IDs, Adressen und Ordner der
aktiven Postfächer. POST `/internal/mail/checkpoint` mit `account_id` wählt das
Postfach für einen neuen Aktivierungscheckpoint. POST `/internal/mail/batch`
akzeptiert zusätzlich `account_id`; ohne Angabe bleibt das Hauptpostfach gewählt.
Unbekannte oder deaktivierte IDs liefern HTTP 404 `account_not_found`. UID und
UIDVALIDITY sind nur innerhalb eines Postfachs eindeutig: Der Empfänger muss Cursor,
Originale und Verarbeitung stets zusammen mit der `account_id` speichern. GET `/internal/mail/checkpoint` liefert UIDVALIDITY und UIDNEXT−1.
POST `/internal/mail/batch` erwartet `uidvalidity`, `after_uid`, `since`
(YYYY-MM-DD). Antworten enthalten höchstens zehn vollständige EML-Nachrichten,
je höchstens 8 MiB und insgesamt höchstens 20 MiB, als Base64. Fehler bestätigen
keinen Cursor. UIDVALIDITY-Wechsel ergeben HTTP 409. EXAMINE und BODY.PEEK
verändern keine Gelesen-Markierung. Es gibt keinen Versand und keine Löschfunktion.


Für sichere Quellenbindung sendet der AngebotsDesigner bei jedem POST-Checkpoint
und Batch zusätzlich `expected_email` und `expected_folder` aus der zuvor gelesenen
Kontoliste. Beide Angaben sind gemeinsam optional für ältere Clients. Stimmen sie
nicht exakt mit der aktiven Konfiguration überein, antwortet die Brücke vor jedem
Postfachabruf mit HTTP 409 `source_changed`. Damit wird eine zwischenzeitlich neu
zugeordnete Konto-ID nicht mit dem Cursor des bisherigen Postfachs gelesen. Eine
neue Zuordnung benötigt eine erneute Aktivierung mit eigenem Checkpoint.
