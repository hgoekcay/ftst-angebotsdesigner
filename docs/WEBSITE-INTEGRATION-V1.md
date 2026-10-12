# Website und AngebotsDesigner: Schnittstellenentwurf v1

Stand: 09.10.2026. Status: Abstimmungsentwurf, noch keine implementierte API.
Verantwortung: Website-Chat erstellt Konfigurator und Portal; AngebotsDesigner-Chat betreut interne Aufnahme, Prüfung und Versandintegration.
Es werden keine Produktionsrouten oder Zugriffsrechte durch dieses Dokument eingerichtet.

## Zwei getrennte Abläufe
1. Konfiguratoranfrage: Kundenauswahl wird zur ungeprüften internen Aufnahme. Keine automatische Beauftragung, Billomat-Anlage, Kundenanlage oder Versendung.
2. Kundenansicht: Ein ausdrücklich freigegebener Leistungsvorschlag wird als feste Revision angezeigt. Die spätere Bearbeitung eines internen Entwurfs ändert diese Revision nicht stillschweigend.

## Konfiguratoranfrage v1
Beispiel ausschließlich mit synthetischen Daten:

```json
{
  "schema_version": "ftst.configuration.v1",
  "request_id": "example-0001",
  "created_at": "2026-10-09T10:00:00Z",
  "system_type": "alarm",
  "customer": {
    "name": "Testkunde",
    "email": "test@example.com",
    "phone": "",
    "object_address": ""
  },
  "components": [{
    "manufacturer": "Ajax",
    "supplier_sku": "example-sku",
    "title": "Beispielgerät",
    "quantity": "2",
    "variant": "",
    "color": "white",
    "unit_net": "100.00"
  }],
  "price_source": "EPS_UVP",
  "catalog_at": "2026-10-09",
  "currency": "EUR",
  "vat_rate": "19",
  "notes": ""
}
```

Die Beispielpreise und SKU sind keine Produktdaten.
- Hersteller und SKU identifizieren nur einen Vorschlag. Lieferanten-SKU ist keine Billomat-Artikel-ID.
- EPS-UVP sind laut Nutzer netto; 19 Prozent Mehrwertsteuer. Billomat-Verkaufspreise bleiben die bestehende interne Preisbasis. Abweichungen sichtbar prüfen, niemals still überschreiben.
- Browserpreise, Namen und Mengen sind nicht vertrauenswürdig. Die empfangende Seite validiert gegen ihren Katalog. Vom Kunden übermittelte Preise sind nur Referenzwerte und werden nicht automatisch kalkuliert.
- Dezimalwerte als Strings, keine Fließkommaarithmetik. Endliche positive Mengen, maximal 100000 und drei Nachkommastellen; Preise endlich, nicht negativ. Grenzen für Texte und maximal 30 Komponenten müssen mit der bestehenden Aufnahme übereinstimmen.
- Pflicht: Schema, Anfrage-ID, Zeitpunkt, Systemart, Komponenten. Kontakt-/Objektangaben dürfen für einen manuellen Import fehlen; der Website-Sendeablauf darf für die gewünschte Rückmeldung notwendige Felder verlangen.
- Gleiches Quellsystem + request_id + gleicher Inhalt liefert denselben Import. Geänderter Inhalt unter gleicher ID wird als Konflikt behandelt. Atomare Speicherung verhindert doppelte Projekte bei Wiederholung.
- Import speichert Quelle, Preisstand und Originalbezeichnungen; alle Artikel bleiben unbestätigt. Kunden dürfen später zugeordnet werden.
- Kein Geheimnis im Browser. Eine spätere automatische Übertragung benötigt authentifizierten Server-zu-Server-Zugang, Ratenbegrenzung und Größenlimits. Öffentliche Formulare benötigen ebenfalls Missbrauchsschutz.
- Erster integrationsfähiger Schritt kann ein manueller JSON-Export und interner Import sein. Bis Authentifizierung und Hosting feststehen, keine neue öffentliche HA-Schreibroute.

## Freigegebener Kundensnapshot
Eigenes Schema ftst.customer-proposal.v1, getrennt vom Konfigurator:
- Dokument-ID, feste Revision, Leistungsvorschlagsnummer, Ausstellungsdatum und Gültigkeit.
- Nur ausdrücklich freigegebene Kundendarstellung und Firmendaten.
- Positionen: Bezeichnung, öffentliche Leistungsbeschreibung, Menge, Einheit, Einzelpreis netto, Positionssumme netto, Steuersatz.
- Netto-, Steuer- und Bruttosumme sowie EUR aus der geprüften serverseitigen Kalkulation; keine Neuberechnung im Browser als verbindliche Quelle.
- Höchstens vier freigegebene Referenzbilder. Bildbeschriftungen ebenfalls prüfen.
- PDF und Webansicht verwenden denselben Snapshot und dieselbe Revision.
- Keine internen Projektnotizen, Fotoanalysen, EK-Preise, vollständigen Kataloge, Zugangsdaten oder internen Kunden-/Benutzerlisten.

Wichtiger Bestandsbefund: quote_export.py erzeugt interne Entwürfe und fügt project.notes in project_summary ein. Diesen Export nicht unverändert veröffentlichen. Öffentliche Daten über eine ausdrückliche Feldfreigabe aufbauen.

## Kundenlink und Lebenszyklus
- Zuerst intern prüfen, Vorschau zeigen und ausdrücklich für Kundenansicht freigeben.
- Stark zufälliger Linkschlüssel (mindestens 256 Bit), serverseitig nur Hash speichern; zeitlich begrenzt und widerrufbar.
- Linkschlüssel ist ein Zugang: keine Rohwerte in Logs, Analysewerkzeugen oder Referrer-Weitergabe. HTTPS, Cache-Control: no-store, Referrer-Policy: no-referrer, noindex.
- HTML, PDF und Bilder müssen dieselbe Zugriffsprüfung verwenden. Kein öffentliches Medienverzeichnis als Umgehung.
- Kein HA-Ingress-Link für Kunden. Öffentliche Website und interne Anwendung bleiben getrennte Zugänge.
- Abgelaufener oder widerrufener Link liefert keine Kundendaten mehr. Eine bereits heruntergeladene PDF lässt sich nicht zurückrufen.
- Öffnen ist keine Annahme, kein verlässlicher menschlicher Lesenachweis und keine Versandbestätigung. Kein automatischer Billomat-Statuswechsel durch GET-Aufruf.
- Erste Version nur ansehen und PDF herunterladen. Beauftragung, Signatur und Zahlung sind separate spätere Funktionen.
- E-Mail/WhatsApp übernehmen nach Freigabe den Kundenlink; bestehender PDF-Versand bleibt verfügbar. Keine Links zu ungeprüften Entwürfen automatisch versenden.

## Abnahme mit synthetischen Daten
1. Import, Wiederholung und paralleler Import erzeugen genau eine Aufnahme.
2. Manipulierte Preise, negative Mengen, unbekannte SKU und zu lange Daten werden sicher behandelt.
3. Lieferantenartikel werden nicht ungeprüft Billomat-Artikeln zugeordnet.
4. Öffentlicher Snapshot enthält keine internen Notizen, Einkaufspreise oder Geheimnisse.
5. Falscher, abgelaufener und widerrufener Schlüssel sperrt HTML, PDF und Bilder gleichermaßen.
6. Eine interne Änderung überschreibt eine bereits freigegebene Revision nicht.
7. Webansicht und PDF zeigen identische Positionen, Summen und Revision.
8. Linkaufrufe lösen keine Annahme und keinen Kundenversand aus.

## Noch technisch abzustimmen
Website-URL, Backend/Datenspeicher, Hosting, authentifizierter Transport und Revisionserzeugung sind vom Website-Chat zu bestätigen. Echte Kundendaten erst nach implementierter Zugriffskontrolle und gemeinsamen Tests veröffentlichen.
