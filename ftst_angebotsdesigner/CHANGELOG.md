# Änderungen

## 0.3.3

- Gespeicherte, vollständig geprüfte Projektkalkulation als PDF-Entwurf im FTST-Design öffnen.
- Entwurfstatus auf jeder Seite, transparente Rabatte und Steuern sowie gespeicherte Währung.
- Export gesperrt bei offenen Positionen, veränderten Notizen, veralteter Revision oder Änderung während des Exports.
- Kein Billomat-Schreibzugriff, keine Freigabe und kein Kundenversand.

## 0.3.2

- Bildauswahl nach Bereichen mit Quellenlabels und gespeichertem/live aktualisiertem Auswahlzähler.
- Unbekannte Kundensteuerregeln sperren die Kalkulation auch bei gesetzter Steuerbestätigung.
- Individuelle Titel bleiben vollständig erhalten; lange PDF-Inhalte können umbrechen, Footer bleibt im Footerband.
- Firmenkontext und gemeinsame Automatisierungsziele dokumentiert.
- 67 Tests erfolgreich; Bildauswahl im Desktop-/Handybrowser und Muster-PDF visuell geprüft.

## 0.3.1

- PDF-Redesign anhand „FT Angebot — Muster (final).pdf“: Titelblatt, große linksbündige Typografie, ruhiger Briefkopf, grüner Preisbereich und nummerierte Abschlussseite.
- Referenzen nach Bereich gruppiert, bis zu vier Bilder je Seite; Kameradrehung wird bei der PDF-Ausgabe berücksichtigt.
- Artikelbeschreibungen vollständig statt gekürzt, wiederholte Tabellenköpfe und mehrseitige Positionen.
- App mit heller Navigation und angepasstem Desktop-/Handy-Layout.
- 58 Tests, PDF-Sichtprüfung und Browserprüfung bei 1440 und 390 Pixeln.
- Keine Änderung an Billomat-Daten oder Speicherung.

## 0.3.0

- Lokaler Angebotsentwurf aus Projektnotizen, auch ohne KI-Zugang.
- Lesender Billomat-Katalog mit Artikelvorschlägen und genauer Variantenwahl.
- Kundenauswahl, Preisgruppen, Rabatt und Nettokalkulation mit geprüften Steuersätzen.
- Offene oder widersprüchliche Angaben verhindern eine Gesamtsumme.
- Dauerhafte Entwürfe mit atomarem Schutz vor parallelem Überschreiben.
- 55 Tests; Live-Abnahme des Katalogabrufs noch ausstehend.
- Noch keine automatische Angebotsanlage in Billomat oder Entwurfs-Angebots-PDF.

- Zwölf mitgelieferte Originaldateien: vier Logos, fünf Montagefotos, zwei Symbolfotos und eine Hinweisgrafik.
- FT-Firmenlogo standardmäßig in App und PDF; vorhandene PDF-Logowahl bleibt erhalten.
- Bildauswahl mit Vorschauen, dauerhafter Speicherung und Quellenart im PDF.
- FTronics als Produktmarke hinterlegt; keine KI-Motive im festen Bildbestand.

## 0.2.0

- Firmendaten und Logo zentral speichern und im PDF verwenden.
- Eigene Fotos/Referenzen speichern und je Angebot als PDF-Seiten auswählen.
- Projekte mit Text, Merkzettelfoto und Sprachnotiz dauerhaft speichern.
- Optionaler OpenAI-Anforderungsentwurf mit Mengenbelegen und Rückfragen; eigener Entwurfs-PDF-Export.
- Noch keine automatische Billomat-Angebotsanlage, kein Planeditor und kein Versand.
- SQLite-Schema 2 migriert bestehende Präsentationen ohne Datenverlust.
- 34 lokale Tests; KI mit simulierten Antworten, kein bezahlter Live-Aufruf.

## 0.1.19

- Kundendarstellung dauerhaft in SQLite, getrennt nach Billomat-Konto und Angebot.
- Editor, Vorschau und PDF verwenden denselben gespeicherten Stand.
- Noch gültige alte Session-Daten werden einmalig übernommen; neuere Datenbankstände haben Vorrang.
- Unlesbare Datenbanken werden nicht ersetzt; Speicherfehler liefern keinen Erfolgshinweis.
- BWA als eigenständiges Kürzel und CO-Melder werden erkannt; ungültige/alte Systemtypen abgefangen.
- Gemischte Gewerke als Kombination; automatische Erkennung im Editor wieder auswählbar.
- PDF öffnet in eigenem Tab. Bestehende FTST-Gestaltung erhalten.
- Automatisierte Tests und Abnahmeprotokoll ergänzt.
