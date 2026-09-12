# Projektassistent und weitere Fertigstellung

## Erweiterung 0.3.0

Lokaler Angebotsentwurf mit Artikelvorschlägen, Kundenauswahl, Preisgruppe, Rabatt und prüfbarer Kalkulation: siehe [ANGEBOTSENTWURF.md](ANGEBOTSENTWURF.md). Texte funktionieren auch ohne KI-Zugang. Die folgenden Abschnitte beschreiben den ursprünglichen Stand 0.2.0 und die darüber hinausgehenden Ziele.

## In 0.2.0 nutzbar

Projekte anlegen, Notizen speichern, Merkzettelfoto und Sprachnotiz hochladen. Daten bleiben lokal im persistenten App-Verzeichnis. Bilder werden normalisiert und Metadaten entfernt.

Eine ausdrückliche Aktion „Gespeicherte Eingaben analysieren“ überträgt die gespeicherten Eingaben an OpenAI. Die App fordert eine strukturierte Zusammenfassung, Komponenten, Mengen mit Beleg und Rückfragen an. Fehlende Mengen bleiben offen. API-Ausfälle und fehlende Schlüssel löschen das Projekt nicht. Ergebnisse sind Anforderungsentwürfe, keine fertigen kaufmännischen Angebote.

Ein bestehendes Billomat-Angebot kann über seine numerische ID verknüpft werden. Der kaufmännische PDF-Generator arbeitet weiter mit den Originaldaten aus Billomat. Der Projektentwurf hat einen eigenen, deutlich als Entwurf bezeichneten PDF-Export.

## Einmalige KI-Einrichtung

In Home Assistant → FTST AngebotsDesigner → Konfiguration:

- `openai_api_key`: eigener OpenAI-API-Schlüssel. Nicht in Git oder Chat ablegen.
- `openai_model`: standardmäßig `gpt-4.1`, bei Bedarf ein für den API-Account freigegebenes Modell mit Bild- und Structured-Outputs-Unterstützung.
- `openai_transcribe_model`: standardmäßig `gpt-4o-mini-transcribe`.

Der API-Zugang und die Abrechnung müssen vom Kontoinhaber eingerichtet werden. Es wurde bei der Entwicklung kein bezahlter API-Aufruf ausgeführt. `store=false` wird für Responses gesetzt; dies ist keine Zusicherung vollständiger providerseitiger Nichtaufbewahrung. Die UI informiert vor der Übertragung.

Quellen: [Bildeingaben](https://developers.openai.com/api/docs/guides/images-vision), [strukturierte Ausgaben](https://developers.openai.com/api/docs/guides/structured-outputs), [Spracherkennung](https://developers.openai.com/api/docs/guides/speech-to-text).

## Noch nicht fertig: direkt vom Merkzettel zum kalkulierten Angebot

Der nächste Schritt braucht eine Artikelzuordnung mit echten Billomat-Artikeln und einem überprüften Kunden-/Steuer-/Preisgruppenbezug. Unklare Treffer müssen zur Auswahl erscheinen. KI darf keine Preise oder IDs erfinden. Angebotserstellung in Billomat muss gegen Duplikate bei Zeitüberschreitungen geschützt werden und zunächst ausschließlich einen Entwurf erstellen. Fertigstellen oder Senden bleibt eine bewusste Aktion.

Abnahmefälle: 11 FireProtect + Hub; Kameraanzahlen innen/außen; unleserliche Menge; unbekannter Artikel; zwei mögliche Artikel; kundenspezifischer Preis; fehlende Montage; API-Zeitüberschreitung. Kein produktiver Schreibzugriff auf Billomat wurde bisher eingebaut oder ausgeführt.

## Kamera- und Alarmpläne

Vorgesehene Erweiterung am gespeicherten Projekt:

- Grundriss/Objektfoto als unverändertes Original plus bearbeitbare Planebene.
- Gebäude, Etage, Maßstab mit zwei Referenzpunkten und realer Länge.
- Kameras, Melder, Hub, Sirenen und Leitungswege mit eigener Kennung.
- Verknüpfung zur Billomat-Artikel-ID und zur Angebotsposition.
- Orientierung/Sichtwinkel/Reichweite nur aus geprüften Geräteangaben; Unbekanntes offen lassen.
- Automatische Vorschläge als Entwurf; manuelle Korrektur und Freigabestand.
- A4-Export mit Legende, Komponentenliste, Datum/Revision; optionaler Angebotsanhang.

Noch kein Planeditor und keine automatische Planfreigabe in 0.2.0. Bestehende Pläne aus anderen Gesprächen wurden nicht als vorhanden angenommen; sie müssen gezielt zugeordnet werden.

## Versand

E-Mail/WhatsApp sind weitere Integrationen. Kein Versanddienst oder öffentliches Kundenportal wurde eingerichtet. PDFs können separat geöffnet und regulär heruntergeladen werden.
