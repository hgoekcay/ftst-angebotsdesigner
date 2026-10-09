# Kundenportal: getesteter Transport, noch keine aktivierte HA-Integration

Hüseyin hat den Ablauf präzisiert: AngebotsDesigner erstellt und prüft das Angebot; Kunde erhält Original-PDF plus persönlichen Link, sieht sein Projekt mit Vorher/Nachher und kann Änderungen, Rückfragen oder eine aktive Freigaberückmeldung abgeben.

Website: https://alarmanlagen-angebotskonfigurator.hg-51d7.chatgpt.site

Der separate Website-Stand besitzt nun Worker-/D1-/R2-Backend, unveränderliche `ftst.customer-proposal.v1`-Revisionen, Original-PDF-Ablage, höchstens vier geschützte Bilder, 256-Bit-Linkschlüssel als Hash, kurzlebige Cookies, Ablauf/Widerruf, serverseitig geprüfte Varianten und `ftst.customer-response.v1`-Rückmeldungen. Startseite und Demo-PDF verwenden nur synthetische Daten. Site bleibt Eigentümer-privat. Keine echte HA-Anbindung und kein öffentlicher Kundenversand aktiviert.

Dieser PR ergänzt ausschließlich einen getesteten, eigenständigen Python-Transportbaustein. Keine bestehenden Produktionsdateien, HA-Optionen, Flask-Routen, Billomat-Schreibaktionen oder Versandfunktionen werden verändert. Er ergänzt PR 50; dessen interner Konfigurator-Import bleibt ein eigener Ablauf.

## Transport

`website_portal_client.PortalClient(base_url, publish_secret, site_service_token=...)`:

- `publish(snapshot, original_pdf, images)` → proposal_id. Multipart `/api/internal/proposals`, snapshot JSON + unveränderte PDF-Bytes + explizit freigegebene Bilddateien. Dokument-ID/Revision sind unveränderlich und idempotent. Server prüft Allowlist und Summen.
- `create_link(proposal_id, expires_in_days=7)` → customer_url, link_id, revision, expires_at. Link mit maximal 30 Tagen, durch Angebotsgültigkeit begrenzt. Rohschlüssel nur einmal zurückgegeben; keine automatische Wiederholung bei unklarem Transportergebnis.
- `revoke(link_id)` → bestehende Sitzungen, PDF und Bilder dieses Links gesperrt.
- `responses(after=sequence)` → maximal 100 Rückmeldungen, next_cursor. Vor Cursorfortschreibung intern atomar/idempotent nach proposal_id/request_id speichern.

Publishing-Secret nur in geschützten HA-Optionen und als Sites-Secret, niemals Browser/Git/Versandtext. Im privaten Sites-Modus ist außerdem der getrennte Dispatch-Servicezugang nötig. Ohne konfiguriertes Publishing-Secret sind interne Endpunkte gesperrt. Ein Kundenlink hebt die derzeitige private Sites-Zugangsgrenze nicht auf.

Vollständiger Website-Vertrag/Fixture: lokale Website-Dateien `docs/PORTAL-HANDOFF.md`, `fixtures/demo-proposal.json`, `server/validation.js`. Die Website verwendet `effective_unit_net` nur für intern freigegebene Änderungsoptionen; keine automatische EPS-zu-Billomat-Preisübernahme. Nicht verlustfrei abbildbare Rabatt-/Brutto-/Optionalpositionen zunächst unveränderlich anzeigen oder Vertrag gemeinsam erweitern.

## Nächster Einbau durch AngebotsDesigner-Verantwortlichen

1. Frischen Billomat-Status und Konto prüfen. Öffentlich erlaubten Snapshot mit festen Positions-/Steuersummen, Ausstellungsdatum/Gültigkeit, Firma, höchstens vier freigegebenen Bildern und einer neuen festen Revision erzeugen. Kein `quote_export.build`: enthält interne Notizen und ungeprüfte Entwürfe. Fachlich geprüfte Änderungsvarianten/Mengengrenzen gesondert freigeben.
2. Snapshot und PDF aus demselben eingefrorenen Stand erzeugen. Portal-Vorschau intern prüfen und ausdrückliche Veröffentlichung auslösen. Der Portalupload darf keine eigene Freigabeentscheidung treffen.
3. Den zu genau dieser Revision gehörenden Kundenlink zusammen mit der unveränderten PDF in der bestehenden Versandvorschau speichern. Bestehende bestätigte E-Mail-/WhatsApp-Aktion sendet PDF plus Link. Kein Versand beim GET oder beim Linkanlegen.
4. Rückmeldungen als ungeprüfte interne Aufgaben/Änderungsentwürfe aufnehmen. `approval` verlangt auf Website eine aktive Bestätigung des unveränderten Angebots; Portal setzt keinen Billomat-Status. Die tatsächliche Beauftragung/Auftragsbestätigung bleibt beim internen Workflow.
5. Gemeinsam mit synthetischen Daten prüfen und passenden externen Portal-Zugang festlegen. Erst danach echte Kunden freischalten.

## Validierung

5 unabhängige Unit-Tests für unveränderte PDF/Snapshot-Übertragung, Freigabesperre vor Netzaufruf, getrennte Link-/Widerruf-/Polling-Aktionen, keine Redirects oder automatischen Wiederholungen und ausschließlich explizit freigegebene Bilder. Website separat mit 8 Worker-/D1-/R2-Tests geprüft. Kein Update der laufenden HA-App durch diesen Draft-PR.
