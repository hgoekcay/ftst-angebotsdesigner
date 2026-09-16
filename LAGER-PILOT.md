# Lager, Einkauf und interne Terminplanung – erste Ausbaustufe

Release 0.4.0: geprüfte erste Ausbaustufe für das Hauptlager. Die Installation allein legt keine Artikel, Bestände oder Aufträge an. Erst reale Artikel auswählen und tatsächlich zählen.

## Bedienung

1. Im bestehenden Projekt einen Billomat-Katalog laden, Materialpositionen zuordnen und den Angebotsentwurf prüfen/speichern.
2. Unter **Lager** die gewünschten Billomat-Artikel aufnehmen. Lagereinheit ausdrücklich zuordnen: ganze Stück oder Meter mit bis zu drei Nachkommastellen. Dienstleistungen bleiben außerhalb des Lagers. Noch ungezählte Artikel zeigen **Unbekannt**.
3. Tatsächlich zählen und **Anfangsbestand gezählt** buchen. Anschließend Eingänge, auftragsbezogene Entnahmen, verwendbare Rückgaben und begründete Zählkorrekturen erfassen.
4. Im Projekt **Material & Termine** öffnen, tatsächlich beauftragte Materialpositionen auswählen und einen Auftragsnachweis eintragen. Nur diese Bestätigung reserviert vorhandenes Material. Der geprüfte Angebotsstand wird festgehalten.
5. Die Einkaufsliste zeigt ungedeckten Bedarf. Unbekannte Bestände müssen zuerst gezählt werden. Nach Wareneingang **Freies Material erneut zuordnen** betätigen; der Benutzer bestimmt damit die Auftragspriorität.
6. Für interne Terminvorschläge Montagezeit, Teamgröße, Fahrt-/Rüstpuffer, erforderliche Fähigkeiten und je Mitarbeiter manuell geprüfte freie Zeitfenster eintragen. Kalenderprüfung darf höchstens 24 Stunden alt sein. Alle benötigten Personen müssen gleichzeitig frei sein und die angegebenen Fähigkeiten besitzen. Vorschläge setzen gedeckten Materialbedarf voraus.

Die CSV-Einkaufsprüfliste ist **unbestellt**. Bereits extern aufgegebene Bestellungen können mit Lieferant, eindeutiger Bestellposition, Menge und optionalem Lieferdatum dokumentiert werden. Offene Bestellmengen reduzieren den zusätzlichen Beschaffungsvorschlag, niemals den physischen Fehlbestand. Tatsächliche Teillieferungen einzeln buchen; nur diese erhöhen den Bestand. Extern bestätigte Stornierungen der Restmenge gesondert dokumentieren. Doppelte Lieferanten-Bestellpositionen werden abgewiesen. Lieferant, Einkaufspreis und nicht erfasste externe Bestellungen bleiben vor einer neuen Bestellung abzugleichen. Die Funktion bestellt nichts und beansprucht keine Lieferfähigkeit. Google Kalender und Craftnote werden nicht angebunden oder verändert. Termine sind interne Vorschläge, keine Kundenbestätigungen und keine Kalenderreservierungen.

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

Für den kleinen Pilotbetrieb wird das gesamte Journal pro Zugriff projiziert. Vor großflächiger Nutzung sind normalisierte Tabellen bzw. überprüfbare Projektionen und Lasttests erforderlich. Es gibt noch keine Fahrzeuglager, Sperrlager, Seriennummern, Barcodekamera, Offlinebuchungen, Lieferantenkataloge, automatischen Bestellversand oder automatische Kalenderabfragen. Erfasste Lieferdaten sind manuelle Momentaufnahmen, keine laufende Lieferantenabfrage. Auftragsstorno storniert keine Lieferantenbestellung; offene Mengen bleiben sichtbar. Überfällige Lieferdaten und überschüssige offene Mengen werden in der Auftragsansicht markiert. Stunden-/Dienstleistungspositionen sind nicht lagerfähig. Personal und Arbeitszeiten werden nicht vorausgefüllt oder erfunden.

Terminvorschläge nutzen `Europe/Berlin`; mehrdeutige oder nicht existierende Zeiten bei Sommerzeitwechsel benötigen einen expliziten Offset. Eine fehlende Materialfreigabe liefert eine konkrete Aufgabe statt eines vermeintlich gesicherten Termins. Jeder Vorschlag ist eine Momentaufnahme; vor externer Zusage erneut prüfen.

## Validierung

- 104 Tests erfolgreich, einschließlich 26 neuer Lager-/Planungstests. Offene Bestellungen, Teillieferungen, Reststornierungen und Bestelleingangs-Gegenbuchungen zusätzlich geprüft.
- Gleichzeitige letzte Entnahme, konkurrierende Reservierungen, Teilreservierungen, fremde Reservierungen, Rückgabe, Storno, Bedarfsänderung, Gegenbuchung, Wiederholung und Kontotrennung geprüft.
- Unbekannte Bestände, Dezimalmengen, fehlerhafte Formulare, CSRF-Prüfung, veraltete Angebotsstände und CSV-Formelpräfixe geprüft.
- Material-, Team-, Fähigkeits-, Puffer- und Aktualitätsregeln sowie Sommerzeitwechsel geprüft.
- Browserablauf mit isolierten, eindeutig als Vorschau gekennzeichneten Daten: Eingang von zwei Stück, Zuordnung zum Auftrag, Fehlmenge von zwei auf null, gemeinsames Zeitfenster für zwei Personen. Keine Produktionsdaten dafür geändert.
- Syntaxprüfung und kritische Ruff-Regeln erfolgreich.

- Ergänzender Browsertest: externe Testbestellung mit 4 Stück dokumentiert; 1 Stück eingegangen, 3 offen; Bestand nur um 1 erhöht. Alle Daten ausschließlich im lokalen Vorschaubereich.
- Journalprojektion mit 10.002 synthetischen Vorgängen: 0,038 Sekunden auf dem Entwicklungs-PC. Kein Ersatz für einen vollständigen Mehrbenutzer-Lasttest.
