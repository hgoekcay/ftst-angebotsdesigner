# Persönliche Angebotslinks und bestätigte Kundenauswahl

Dieses Feature bleibt standardmäßig deaktiviert. Es verschickt keine E-Mail, erstellt keine Bestellung und verändert kein Billomat-Angebot. Es erweitert den bestehenden ausdrücklich geprüften E-Mail-/WhatsApp-Versand.

## Ablauf

1. Freigegebenen Billomat-Leistungsvorschlag öffnen, „Persönlichen Kundenlink vorbereiten“ wählen. Darstellung, Auswahlgrenzen und Preise ausdrücklich freigeben. Montage/Inbetriebnahme bleiben fest. Home Assistant/Software kann als 0/1-Pauschale freigegeben werden.
2. Ausgewählte vorhandene Positionen werden mengenveränderbar. Zusätzlich können passende Ajax-Kameras, Außenbewegungsmelder, Außenschutz und Außensirenen aus dem vollständigen Billomat-Katalog freigegeben werden. Diese starten mit Menge 0. Browserwerte enthalten nur IDs; Preise kommen beim Veröffentlichen erneut aus Billomat. NET/EUR und normaler `sales_price` plus 19 % sind erforderlich. Es werden keine EPS-UVP mit Billomat-Preisen vermischt.
3. Ein unveränderlicher, öffentlicher Allowlist-Snapshot wird zusammen mit der Original-PDF und maximal vier dafür ausgewählten Referenzbildern hochgeladen. Interne Projektnotizen, Gesamtkatalog, Einkaufspreise und Zugangsdaten bleiben intern. Der persönliche widerrufbare Link erscheint in E-Mail- und WhatsApp-Texten. Der bisherige Versand bleibt ausdrücklich bestätigt; der Link ist auch Bestandteil der eingefrorenen E-Mail.
4. Kunde wählt selbst innerhalb freigegebener Optionen/Mengen, sieht den berechneten Endpreis und bestätigt gegebenenfalls mit gezeichneter Unterschrift. Eine Bestätigung ist keine ungeprüfte Änderungsanfrage. Fragen bleiben möglich. Das Portal erlaubt nur eine endgültige Bestätigung pro Vorschlag.
5. Ein serverseitiger Abgleich läuft bei aktivierter Integration alle 60 Sekunden; zusätzlich ist manueller Abruf verfügbar. Nur `customer_confirmed` der passenden Quellrevision wird angenommen. Jede Auswahl und alle Netto-/Steuer-/Bruttosummen werden unabhängig aus dem gespeicherten Snapshot nachgerechnet. Manipulierte Browserpreise und Titel werden ignoriert.
6. Die bestätigte Auswahl wird als separater lokaler Datensatz gespeichert. Das ursprüngliche Billomat-Angebot wird nicht überschrieben. Die bestehende `offer_design`-PDF-Erstellung erzeugt die bestätigte Auswahl im FTST-Design. PDF-Bytes werden dauerhaft und mit privaten Dateirechten gespeichert, damit Wiederholungen exakt dieselbe Datei hochladen. Portal stellt diese Datei dem Kunden separat bereit; ursprüngliche PDF bleibt unverändert.

## HA-Konfiguration

- `website_portal_enabled`: standardmäßig false.
- `website_portal_url`: HTTPS-Origin des Kundenportals.
- `website_portal_secret`: mindestens 32 Zeichen, identisch zu serverseitigem `PORTAL_PUBLISH_SECRET`.
- `website_portal_site_token`: optionaler serverseitiger Sites-Dispatch-Zugang. Dieser ersetzt keinen Kundenzugang.

Die drei Geheimnisse werden nur serverseitig aus HA-Optionen an Umgebungsvariablen übergeben und niemals in Formulare/URLs/JavaScript eingebaut. Keine automatischen Netzwerk-Retries für Veröffentlichung/Link-Erstellung. Abgleich wiederholt im Fehlerfall mit unverändertem Cursor und identischen finalen PDF-Bytes.

**Noch nicht produktiv aktiv:** Diese Änderung muss mit dem anderen App-Verantwortlichen geprüft werden. Server-Publish-Secret und zugängliches Kundenportal müssen eingerichtet werden. Ein derzeit nur für den Eigentümer sichtbarer Site-Zugang funktioniert nicht für Kunden. Hier wurden keine echten Kundendaten veröffentlicht und keine Nachrichten versendet.

## Schnittstelle

Bestehende PR50/51 bleiben Vorarbeiten; diese Implementierung übernimmt den Transport direkt und ergänzt die aktiven App-Hooks. Nicht doppelt denselben Client parallel mergen.

- POST `/api/internal/proposals`: multipart `snapshot`, `pdf`, optional `image:<id>`.
- POST `/api/internal/proposals/{id}/links`: Laufzeit 7 Tage, serverseitig auf Angebotsgültigkeit begrenzt.
- POST `/api/internal/links/{hash}/revoke`.
- GET `/api/internal/responses?after={cursor}`: `responses`, `next_cursor`.
- POST `/api/internal/proposals/{id}/responses/{request_id}/pdf`: multipart `pdf`, identische Bytes idempotent.

Bestätigungsdatensatz: `kind=approval`, `status=customer_confirmed`, `confirmed=true`, Quell-`document_id`/`revision`, alle editierbaren `selections`, `preview_totals` und identische `final_totals`; optional `ftst.drawn-signature.v1`. Fragen sind `question_received` und werden als Frage gespeichert, nicht angenommen.

## Grenzen

- Vorhandene Billomat-Positionen bieten aktuell ihre Originalvariante und freigegebene Mengen. Neue Varianten können über zusätzliche ausdrücklich freigegebene Katalogartikel angeboten werden; automatische SKU-Zuordnung zwischen Billomat und EPS findet nicht statt.
- Nur centgenau nachrechenbare Positionen und 19%-Angebote. Abweichende Gesamt-/Steuer-/Rabattberechnungen, andere Währungen, abgelaufene Angebote und ungenaue effektive Einzelpreise brechen die Veröffentlichung ab.
- Zusätzliche Produktbilder werden nur bei eindeutigem Modell und Farbe hinterlegt. Ähnliche MotionCam-/MotionProtect- oder Kameraauflösungsvarianten bekommen kein geratenes Bild.
- Publizierte Referenzbilder sind genau die bereits für die Kunden-PDF ausgewählten Bilder. Die komplette interne Bilderbibliothek wird niemals hochgeladen.
- Geschäftliche Bestellung/Billomat-Annahme ist eine spätere eigene Schnittstelle. `customer_confirmed` dokumentiert hier die endgültige Kundenauswahl mit Endpreis; es gibt keinen zusätzlichen Prüf-/Änderungsantrag.
