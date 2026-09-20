## 0.15.1

- Maximal vier Referenzbilder insgesamt pro Angebot und Projektentwurf, immer gemeinsam auf einer einzigen Seite im 2×2-Raster.
- Ältere Auswahlen mit mehr Bildern verwenden die ersten vier gültigen Motive. Die Bildbibliothek und gespeicherte Altbestände bleiben erhalten.
- Lange Bildtexte werden für die feste Referenzseite lesbar gekürzt. Die vollständigen Angaben bleiben in der Bildbibliothek gespeichert.
- Bildauswahl mit Vierergrenze im Formular und serverseitiger Prüfung.

## 0.15.0
- Größeres originales FT-Sicherheitstechnik-Logo mit ® im Appkopf und in der PDF.
- Firmenadresse, Inhaber, Kontakt und Bankverbindung in einer dreispaltigen Fußzeile auf jeder PDF-Seite; Angaben werden unter Firma gepflegt. IBAN-Prüfsumme und BIC-Format werden vor dem Speichern geprüft.
- Vier Referenzbilder unterschiedlicher Sicherheitsbereiche gemeinsam auf einer Seite; Bildherkunft bleibt gekennzeichnet.
- Ablaufseite sowie häufige Fragen zur Sicherheitstechnik mit persönlichem Kontakt und Angebotsgültigkeit. Keine fremden Kennzahlen, Garantien oder Zahlungszusagen aus Mustervorlagen.
- Firmendatenformular schützt Änderungen mit einem Sitzungstoken; fehlerhafte Angaben überschreiben keine gespeicherten Daten.

## 0.14.0

- Technikeraufnahme am Handy: Handzettelfoto hochladen und lokal auswerten oder eine strukturierte Liste erfassen. Originalfoto, Transkript und Positionen bleiben zur Prüfung sichtbar; erst bestätigte Mengen und Beschreibungen gehen in die Projektkalkulation ein.
- Ajax als Vorgabe für die Aufnahme und gezielte Artikelvorschläge für Bewegungsmelder, Magnetkontakte, Sirenen und Bedienteile. Die konkrete Billomat-Variante wird weiterhin ausgewählt; unklare Strichlisten, Zentrale und Montage werden nicht ergänzt.
- Geprüfte Projektkalkulationen nach Vorschau und ausdrücklicher Bestätigung als Billomat-Angebotsentwurf anlegen. Kundenkonditionen werden vor der Übergabe erneut geladen; Kunde, Texte, Positionen und Beträge anschließend aus Billomat zurückgelesen und verglichen.
- Dauerhaft gespeicherter Übertragungsstand verhindert doppelte Anlage bei Doppelklick, Zeitüberschreitung und Neustart. Unklare Ergebnisse ausschließlich über „Status in Billomat prüfen“ klären; kein automatischer erneuter Schreibversuch.
- Kundendarstellung und gewählte Referenzbilder bleiben mit dem erzeugten Angebot in der FTST-App verbunden. Billomat-Entwürfe werden auch in der PDF als Entwurf gekennzeichnet. Keine Freigabe und kein Versand an Kunden.
- Angebotsübersicht mit Billomat-Statusfilter sowie lokalen Wiedervorlagen und Notizen. Die letzten 30 Angebote bleiben zwischengespeichert; ältere Wiedervorlagen sind separat sichtbar.

## 0.13.1

- Bildaufträge warten im Hintergrund bis zu 150 Sekunden auf eine bereits laufende lokale Textauswertung, statt sofort auf manuelle Zuordnung zurückzufallen.
- Türstationen mit Klingeltasten werden bei der Bildbeschreibung ausdrücklich der Türsprechanlage zugeordnet.

## 0.13.0

- Bis zu 20 Referenzfotos gemeinsam auswählen, einzeln übertragen und gesammelt prüfen/speichern. Fortschritt pro Bild, Wiederaufnahme und Schutz vor doppeltem Speichern.
- Lokale Bilderkennung mit gemma3:4b schlägt Titel, Beschreibung und Kategorie vor. Unsichere Zuordnungen bleiben offen. Keine Cloud-Bildübertragung.
- Benötigt FTST Lokale KI 0.1.1 mit vorbereitetem Bildmodell. Bei fehlender Erkennung bleibt manuelle Zuordnung möglich.

## 0.12.2

- Automatisch bis zu vier passende Originalreferenzen nach Angebotsart in Billomat-Angebote aufnehmen; manuelle Auswahl hat Vorrang. Bildvorschläge bleiben änderbar, Rückkehr zur Automatik möglich.
- Keine bezahlten KI-Aufrufe für die Bildauswahl; fehlende passende Motive werden angezeigt.

## 0.12.1

- PDF in der angemeldeten App abrufen; anschließend speichern oder auf unterstützten Handys teilen, ohne geschützte Download-Adresse im externen Browser zu öffnen.
- PDF-Antworten prüfen und Anmeldefehler verständlich anzeigen.
- Die letzten 30 Angebote lokal zwischenspeichern und im Hintergrund aktualisieren; weitere Angebote seitenweise laden.

## 0.11.0

- Optionaler STRATO-Lesepilot für info@ftst.eu: Startpunkt bewusst setzen, neue Nachrichten begrenzt und schreibgeschützt in die Mail-Arbeitsliste übernehmen. Standardmäßig deaktiviert; Passwort direkt in der Home-Assistant-Konfiguration hinterlegen.
- Originale und Anhänge bleiben erhalten; Duplikatschutz und atomarer Abrufstand. Kein Versand, Löschen, Verschieben oder automatischer KI-Aufruf.
- Projektentwürfe erhalten bearbeitbare Kundentexte und eine eigene Fotowahl für die PDF-Ausgabe.
- Artikelvorschläge ignorieren Mengen und Füllwörter; deutsche Wortformen werden besser gefunden.
- Offene Artikelzuordnungen werden auch bei fehlender Steuerbestätigung angezeigt. Verständlicher Rückweg bei veralteten Entwürfen.
- Preise und Entwurfkennzeichnung bleiben erhalten; Darstellungsänderungen erzeugen eine neue Revision.

# 0.10.0

- Bewusste, rein lesende Billomat-Belegprüfung unter Billomat-Daten → Beleg-Verbindung prüfen.
- Begrenzte Stichprobe von Eingangsrechnungen und Beleg-Inbox; nur Erreichbarkeit, Gesamtzahl und bekannte Feldnamen sichtbar.
- Keine Beleganlage, Dateiübertragung, Banking-Abfrage oder Buchung; TLS, Redirect-Sperre, Zeit-/Größenlimit und redigierte Fehler.

# 0.9.0

- Barcodegestützte Lagerentnahme: Auftrag wählen, Code erfassen, Menge prüfen und ausdrücklich bestätigen.
- Bestätigte Einzel-/Verpackungszuordnung mit führenden Nullen, Hauptlager und bestehenden Reservierungs-/Doppelbuchungssperren.
- Kamera-Decoder lokal gebündelt, alternativ Hardware-Scanner oder Texteingabe; unklare Übertragung über dieselbe Vorgangs-ID prüfen.
- Handyansicht geprüft; tatsächlicher iPhone-/Home-Assistant-Kameratest noch offen. Vor Rückkehr zu älterer Version Sicherung des Lagerjournals beachten.
# 0.8.0

- Mail-Arbeitsliste mit Mehrfachkategorien, Verantwortlichem, Wiedervorlage und separatem Bearbeitungs-/Beleg-/Zahlungsstatus.
- Begrenzter EML-Import: unverändertes Original und Anhänge, atomarer Duplikatschutz, sichtbare ungeprüfte Anhänge und Analysegrenzen.
- Manuelle Belegangaben mit Originalbezug und Bestätigungsverlauf; kein Postfachzugriff, OCR, Versand oder Buchhaltungsexport.
- Produktiver Ingress-Zugriffsschutz und Handyansichten; Datenbankschema 3 (Rollback benötigt Sicherung der Vorversion).
# 0.7.0

- Lokaler Antwortassistent für manuell eingefügte Kundenanfragen: belegte Textausschnitte, offene Angaben und bearbeitbare Antwortentwürfe.
- Feste Antwortbausteine ohne Preis-, Verfügbarkeits- oder Terminzusagen; Kopieren statt Versand.
- Persistente Entwürfe, Wiederverwendung unveränderter Auswertungen, Schutz manueller und paralleler Änderungen; Handyansicht.
- Noch kein Postfachzugriff, EML-Import oder Belegworkflow.

# 0.6.1

- Handyansichten ohne seitliches Scrollen: Tabellen werden als beschriftete Positionen untereinander angezeigt.
- Größere Bedienelemente, umbrochene Schaltflächen und Navigation; Dezimaltastatur für Angebotsmengen.
- Gilt für Angebotsentwürfe, Angebote, Projektanalyse, Lager und Materialplanung.

# 0.6.0

- Lokale Textanalyse mit separater FTST Lokale KI App (Ollama): keine automatische Cloud-Ausweichverarbeitung.
- Nur eine lokale Analyse gleichzeitig, begrenzte Eingabe und Ausgabe, validierte Quellenbelege.
- Gespeicherte lokale Ergebnisse bei unveränderten Eingaben wiederverwenden; bewusste Neuanalyse möglich.
- KI-Status und Funktionstest mit Beispieldaten. Gleichzeitige Projektänderungen werden nicht von Analyseergebnissen überschrieben.
- Lokaler Pilot unterstützt zunächst Text. Anhänge werden nicht stillschweigend ausgelassen. Web-Firmensuche bleibt eine separate Online-Funktion.

# 0.5.0

- Kundenassistent: bestehende Billomat-Kunden suchen, öffentliche Firmen mit Quellen recherchieren und Kundendaten vor der Anlage prüfen.
- Neue Billomat-Kunden erst nach ausdrücklicher Bestätigung; Dublettenprüfung und dauerhafter Schutz gegen doppelte Übertragung.
- Zentrale Billomat-Stammdaten laden, für neue Entwürfe und Lager verwenden.
- Sichtbarer Hinweis, wenn der OpenAI-API-Schlüssel für Websuche fehlt.

# 0.4.0

- Hauptlager mit unbekannten/gezählten Beständen, Eingängen, Auftragsentnahmen, Rückgaben, Korrekturen und nachvollziehbaren Gegenbuchungen.
- Materialreservierung aus tatsächlich beauftragten, geprüften Projektentwürfen; Schutz gegen Doppelbuchungen, fremde Reservierungen und veraltete Formulare.
- Einkaufsprüfliste mit getrennten physischen Fehlmengen, offenen externen Bestellungen und verbleibendem Beschaffungsbedarf.
- Erfassung vorhandener Lieferantenbestellungen, Teillieferungen und bestätigter Reststornierungen. Kein externer Bestellversand.
- Interne Terminvorschläge anhand gedeckten Materials, geprüfter freier Zeiten, Teamgröße, Fähigkeiten sowie Fahrt-/Rüstpuffer. Keine verbindliche Kalenderbuchung.
- 104 Tests erfolgreich; lokale Browserprüfung von Lager, Reservierung, Planung, Bestellerfassung und Teillieferung.

# 0.3.4

- Optionale Billomat-Positionen in Angebotsansicht und PDF ausdrücklich als nicht im Gesamtpreis enthalten kennzeichnen.
- Positions- und Angebotsrabatte mit Prozent-/Betragsangabe darstellen; Originalbeträge bleiben unverändert.
- Einzelpreise je nach Billomat-Preisbasis als netto oder brutto beschriften.

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
# 0.12.0 – Lokale Mail-Verbindung

- Import über die separate STRATO-Mail-App, ohne das Postfachpasswort zu kopieren.
- Aktivierung mit Startpunkt ab jetzt; vorhandene Mails bleiben ausgeschlossen.
- Optionaler Hintergrundabruf und lokale KI-Vorschläge; kein Versand und keine automatische Übernahme von Kategorien oder Antworten.
- Atomarer Import, Duplikaterkennung und Schutz gleichzeitiger manueller Änderungen.
- Bestehender direkter STRATO-Lesepilot bleibt verfügbar, ohne automatischen Anbieterwechsel.
