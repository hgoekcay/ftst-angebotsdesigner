# Prüfliste und Übernahme

## Verbindliche Richtung

Stand aus dem bisherigen Gespräch und den Ergänzungen vom 12.09.2026:

- Billomat bleibt die kaufmännische Datenquelle; kein Odoo-Wechsel.
- Vorhandene Preise, Mengen und Steuerbeträge nicht durch KI neu berechnen.
- FTST Weiß/Rot/Schwarz; Grün für Preise und positive Status.
- A4 Hochformat, akzeptierte kompakte dreiseitige Grundstruktur erhalten.
- Editor, Rücknavigation, Speichern-Meldung; PDF in separatem Tab.
- Rauchmeldeanlage und Brandwarnanlage getrennt; Brandmeldeanlage/BMA kein angebotener Typ.
- Hub + nur Rauch/Hitze/CO/FireProtect = Rauchmeldeanlage; Einbruchkomponenten = Alarmanlage.
- Mehrere Gewerke = Kombination; manuelle gültige Auswahl hat Vorrang.
- SQLite auf persistentem App-Pfad, gemeinsame Daten für Browser/Editor/PDF.
- Firmendaten/Logo sowie echte Referenzen mit Ort, Objektart, Beschreibung und Fotos.
- Zielablauf: Sprache/Text/Merkzettelfoto → Projekt → Billomat-Artikel/Mengen → prüfbarer Entwurf → PDF.
- Spätere Kamera-/Alarmplanung: Grundriss mit Maßstab, Gerätepositionen, Legende, Komponentenliste und PDF-Anhang.

Die alte achtseitige Muster-PDF ist eine Gestaltungsvorlage, kein Stammdatennachweis: Sie enthält Platzhalter, widersprüchliche Zahlungsbedingungen und sachfremde Leistungen. Aussagen wie Zertifizierungen, Installationszahlen, Gewährleistung und Lieferfristen werden nicht ungeprüft übernommen.

## Lokale Prüfstufe 0.1.19

Ausgangsversion 0.1.18: Syntax, kritisches Lint und zwei Funktionstests bestanden.
Tests verwenden ausschließlich fiktive Daten; keine Billomat-Zugangsdaten lokal hinterlegt.
Browser: Übersicht → Angebot; Hub + 11 FireProtect als Rauchmeldeanlage; PDF erzeugt einen eigenen Tab, Angebot bleibt offen.

## Noch in Home Assistant prüfen

- Update über bestehendes Repository installieren; App-Backup vorher anlegen.
- Start, `/health`, Ingress-Links, Editor speichern, grüner Erfolgshinweis.
- Echtes Angebot mit Hub + 11 FireProtect und ein Einbruchangebot prüfen.
- PDF aus Ingress in eigenem Tab öffnen, ursprüngliche Angebotsliste erreichbar.
- Andere Browsersitzung: gespeicherte Kundendarstellung vorhanden.
- App neu starten, anschließend erneut PDF prüfen.
- App-Update und Backup/Wiederherstellung: `/data/ftst_angebotsdesigner` bleibt erhalten.
- Billomat-Livedaten: Steuern, Mengen, optionale Positionen und umfangreiche Angebote vergleichen.

## Weitere Integrationsabnahme

KI: Anbieterzugang/Abrechnung noch nicht eingerichtet. Modellzugriff, Sprache, Handschrift, Rückfragen und Preis-/Artikelzuordnung müssen mit echten freigegebenen Beispielen getestet werden.
Pläne: Grundrisse, Maßstab und konkrete Gerätedaten benötigt; keine automatische Zusicherung von Reichweiten oder Normkonformität.
Versand: E-Mail/WhatsApp nur nach gesonderter Einrichtung und ausdrücklicher Versandaktion. Keine automatische Kundenkommunikation beim Entwickeln.
