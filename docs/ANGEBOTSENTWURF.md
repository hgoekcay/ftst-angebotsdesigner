# Angebotsentwurf 0.3.0

## Ablauf

Im Projekt „Angebotsentwurf vorbereiten“ öffnen. Die vorhandene KI-Komponentenliste wird übernommen, sofern vorhanden. Ohne KI werden Textzeilen, Semikolon, „ + “ und „ und “ getrennt; nur eine vorangestellte Zahl wird als Menge übernommen. Beispiel: `1 Hub + 11 FireProtect`. Freie Prosa und fehlende Mengen bleiben zur manuellen Prüfung sichtbar.

„Artikel und Kunden aus Billomat laden“ liest den vollständigen Artikel-/Kundenkatalog, Steuersätze, Einheiten und die benötigten Kontoeinstellungen. Die Übernahme erfolgt erst nach vollständigem Abruf. Der Datenstand wird angezeigt. Es werden nur benötigte Felder gespeichert, keine Bankverbindungen oder API-Schlüssel.

Kunden auswählen, Artikelvorschläge prüfen und genaue Variante wählen. Eine unklare oder auch einzelne Fundstelle wird nicht automatisch als fachlich richtig bestätigt. Suchbegriffe lassen sich ändern und speichern. Die letzte leere Zeile dient zum Ergänzen von Montage, Anfahrt oder Zubehör. Alle Felder einer Zeile leeren, um sie zu entfernen.

Der gespeicherte Entwurf bleibt nach Browserwechsel und Neustart vorhanden. Atomarer Versionsvergleich schützt vor Überschreiben eines inzwischen geänderten Entwurfs. Geänderte Projektanforderungen machen die Summe ungültig, bis die Positionen neu übernommen und zugeordnet wurden.

## Kalkulationsgrenzen

- Preisgruppen 1–5: fehlender Gruppenpreis verwendet den Standardpreis; ein expliziter Nullpreis bleibt null.
- Kundenrabatt `reduction` wird berücksichtigt. Skonto `discount_rate` wird nicht abgezogen.
- Der erste geprüfte Ablauf unterstützt Nettopreise und gleiche Währungen. Bruttopreisbasis, abweichende Kundenpreisbasis und Währungsumrechnung bleiben gesperrt.
- Steuerregel TAX nutzt Artikelsteuer bzw. einen eindeutig vorhandenen Standardsteuersatz. NO_TAX setzt die Steuer auf null. COUNTRY erfordert die ausdrückliche fachliche Bestätigung der Artikelsteuersätze; es findet keine automatische Bewertung von Lieferort oder Steuerbefreiungen statt.
- Fehlende Einheit, Menge, Preis, Steuer oder Artikel verhindern eine Gesamtsumme. Keine Teilkalkulation als Gesamtpreis.
- Decimal-Arithmetik; kaufmännische Cent-Rundung nach Rabatt je Position, anschließend Steuer je Position. Endsumme muss bei späterer Billomat-Übernahme gegen dessen Ergebnis geprüft werden.
- Die Katalogpreise sind ein Snapshot. Vor späterer Übertragung müssen Artikel und Kunden neu geladen werden. Ein Neuladen entfernt vorhandene Prüfbestätigungen.

## Betrieb und Abnahme

Keine neuen HA-Konfigurationsfelder. Dieselben Billomat-Zugangsdaten werden für ausschließlich lesende API-Aufrufe verwendet. Keine neue Datenbankmigration: Entwürfe liegen kontogetrennt als eigener Datensatztyp im Schema 2.

50 automatisierte Tests insgesamt, einschließlich Preisgruppe, Rabatt/Skonto, Nullpreis, fehlende Mengen, Währung, Steuer, Varianten, paginierte Kataloge, Verbindungsfehler, Kontotrennung und atomarem Versionsvergleich. Lokaler Browserdurchlauf mit fiktiven Artikeln: 1 Hub zu Gruppenpreis 80,00 plus 11 FireProtect zu 10,00; nach 10 % Rabatt 171,00 netto, 32,49 Steuer, 203,49 brutto.

Noch ausstehend: Live-Abnahme des neuen Katalogabrufs in HA und Vergleich eines internen Testentwurfs mit Billomat. Version 0.2.0 bleibt bis zur Installation dieser Erweiterung der produktive Stand. Automatische Anlage eines Angebots in Billomat, Angebots-PDF aus diesem Entwurf, Planeditor und Versand sind eigene nächste Schritte. Der vorhandene PDF-Export von Billomat-Angeboten bleibt unverändert.

## Dokumentierte Schnittstellen

- https://www.billomat.com/api/artikel/
- https://www.billomat.com/api/kunden/
- https://www.billomat.com/api/einstellungen/
- https://www.billomat.com/api/einstellungen/steuersaetze/
- https://www.billomat.com/api/einstellungen/einheiten/
