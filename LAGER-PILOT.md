# Lager, Einkauf und interne Terminplanung – erste Ausbaustufe

Entwicklungszweig `codex/lager-planung`, noch nicht produktiv installiert. Die HA-Version bleibt 0.3.4, bis eine eigene Release-Abnahme erfolgt.

## Bedienung

1. Im bestehenden Projekt einen Billomat-Katalog laden, Materialpositionen zuordnen und den Angebotsentwurf prüfen/speichern.
2. Unter **Lager** die gewünschten Billomat-Artikel aufnehmen. Lagereinheit ausdrücklich zuordnen: ganze Stück oder Meter mit bis zu drei Nachkommastellen. Dienstleistungen bleiben außerhalb des Lagers. Noch ungezählte Artikel zeigen **Unbekannt**.
3. Tatsächlich zählen und **Anfangsbestand gezählt** buchen. Anschließend Eingänge, auftragsbezogene Entnahmen, verwendbare Rückgaben und begründete Zählkorrekturen erfassen.
4. Im Projekt **Material & Termine** öffnen, tatsächlich beauftragte Materialpositionen auswählen und einen Auftragsnachweis eintragen. Nur diese Bestätigung reserviert vorhandenes Material. Der geprüfte Angebotsstand wird festgehalten.
5. Die Einkaufsliste zeigt ungedeckten Bedarf. Unbekannte Bestände müssen zuerst gezählt werden. Nach Wareneingang **Freies Material erneut zuordnen** betätigen; der Benutzer bestimmt damit die Auftragspriorität.
6. Für interne Terminvorschläge Montagezeit, Teamgröße, Fahrt-/Rüstpuffer, erforderliche Fähigkeiten und je Mitarbeiter manuell geprüfte freie Zeitfenster eintragen. Kalenderprüfung darf höchstens 24 Stunden alt sein. Alle benötigten Personen müssen gleichzeitig frei sein und die angegebenen Fähigkeiten besitzen. Vorschläge setzen gedeckten Materialbedarf voraus.

Die CSV-Einkaufsprüfliste ist **unbestellt**. Lieferant, Einkaufspreis, Liefertermin und extern bereits bestellte Mengen bleiben ausdrücklich offen. Vor einer Bestellung diese Angaben abgleichen. Die Funktion bestellt nichts und beansprucht keine Lieferfähigkeit. Google Kalender und Craftnote werden nicht angebunden oder verändert. Termine sind interne Vorschläge, keine Kundenbestätigungen und keine Kalenderreservierungen.

## Buchungsregeln und Wiederherstellung

- Hauptlager als einziger verfügbarer Lagerort. Keine erfundenen Startmengen, Fahrzeuge oder Lieferanten.
- Physischer Bestand und Reservierungen getrennt; fremde Reservierungen sind vor Entnahmen geschützt.
- Entnahme reduziert eigene Reservierung und offenen Bedarf gemeinsam. Rückgabe erhöht Bestand, reserviert ihn jedoch nicht automatisch erneut.
- Bedarfsänderungen sind begründet und dürfen bereits entnommene Mengen nicht unterschreiten. Storno gibt offene Reservierungen frei; tatsächliche Entnahmen bleiben erhalten. Rückgaben nach Storno bleiben möglich.
- Eingang, Entnahme und Rückgabe können einmalig mit Bezug auf die ursprüngliche Vorgangs-ID gegengebucht werden, soweit spätere Bewegungen/Reservierungen dies zulassen. Zählungen werden durch eine neue begründete Zählung korrigiert. Kein Journalvorgang wird gelöscht oder überschrieben.
- Zählkorrekturen unter reservierte Mengen erfordern vorherige Freigabe/Prüfung der betroffenen Reservierungen. Gesperrte oder defekte Ware wird in dieser ersten Stufe nicht als verfügbar zurückgebucht.
- Name des Buchenden ist eine Pflichtangabe, jedoch eine Selbstauskunft und keine personenscharfe Authentifizierung. Zugriff erfolgt über die bestehende HA-App. Kein öffentliches Deployment ohne eigene Authentifizierung.
- Schutz gegen doppelte Übertragung per Vorgangs-ID und Nutzdatenvergleich; veraltete Formulare führen zu Konflikt statt Überschreiben. Nach einem Verbindungsabbruch dieselbe Übertragung wiederholen oder Journal prüfen, nicht einen neuen Vorgang blind buchen.

## Speicherung und technische Grenzen

Das kontogetrennte, append-only Lagerjournal liegt in der vorhandenen `offers.sqlite3`, Datensatzart `inventory`, Schlüssel `main`. Der Bestand wird deterministisch aus dem Journal rekonstruiert. Validierung, Reservierungsänderung und Journaleintrag laufen unter derselben SQLite-Schreibtransaktion. Bei Auftragsübernahme werden Projekt und Angebotsrevision innerhalb dieser Transaktion erneut geprüft. Ein bestehendes HA-App-Backup enthält damit auch die Lagerdaten; kein zusätzlicher Speicherort ist notwendig.

Für den kleinen Pilotbetrieb wird das gesamte Journal pro Zugriff projiziert. Vor großflächiger Nutzung sind normalisierte Tabellen bzw. überprüfbare Projektionen und Lasttests erforderlich. Es gibt noch keine Fahrzeuglager, Sperrlager, Seriennummern, Barcodekamera, Offlinebuchungen, Lieferantenkataloge, Bestellverwaltung, Lieferterminverwaltung oder automatische Kalenderabfragen. Stunden-/Dienstleistungspositionen sind nicht lagerfähig. Personal und Arbeitszeiten werden nicht vorausgefüllt oder erfunden.

Terminvorschläge nutzen `Europe/Berlin`; mehrdeutige oder nicht existierende Zeiten bei Sommerzeitwechsel benötigen einen expliziten Offset. Eine fehlende Materialfreigabe liefert eine konkrete Aufgabe statt eines vermeintlich gesicherten Termins. Jeder Vorschlag ist eine Momentaufnahme; vor externer Zusage erneut prüfen.

## Validierung

- 99 Tests erfolgreich, einschließlich 21 neuer Lager-/Planungstests.
- Gleichzeitige letzte Entnahme, konkurrierende Reservierungen, Teilreservierungen, fremde Reservierungen, Rückgabe, Storno, Bedarfsänderung, Gegenbuchung, Wiederholung und Kontotrennung geprüft.
- Unbekannte Bestände, Dezimalmengen, fehlerhafte Formulare, CSRF-Prüfung, veraltete Angebotsstände und CSV-Formelpräfixe geprüft.
- Material-, Team-, Fähigkeits-, Puffer- und Aktualitätsregeln sowie Sommerzeitwechsel geprüft.
- Browserablauf mit isolierten, eindeutig als Vorschau gekennzeichneten Daten: Eingang von zwei Stück, Zuordnung zum Auftrag, Fehlmenge von zwei auf null, gemeinsames Zeitfenster für zwei Personen. Keine Produktionsdaten dafür geändert.
- Syntaxprüfung und kritische Ruff-Regeln erfolgreich.
