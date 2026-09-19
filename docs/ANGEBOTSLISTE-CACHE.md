# Schnelle Angebotsliste

Lokale Entwicklung nach Version 0.11.0; noch nicht veröffentlicht/installiert.

Die erste Angebotsseite zeigt die letzten 30 Angebotszusammenfassungen aus SQLite. Ein einzelner Hintergrundthread lädt diese beim Produktionsstart vor und aktualisiert sie alle fünf Minuten, auch wenn kein Browser offen ist. Daten bleiben über Neustarts erhalten und sind nach Billomat-Konto getrennt. Gespeichert werden nur ID, Nummer, Datum, Titel und Bruttobetrag, keine Schlüssel oder vollständigen Angebotsinhalte.

Der erste Aufruf ohne gespeicherten Stand zeigt einen Ladehinweis und lädt die Seite nach zehn Sekunden neu. Bei API-Fehlern bleibt der letzte erfolgreiche Stand mit Zeitstempel und Warnung erhalten; nächster Versuch nach einer Minute. Die Standardliste führt keinen synchronen Billomat-Aufruf aus. Ein einzelner Abruf fragt höchstens 30 Einträge ab. Die vorhandene Billomat-Transportfunktion hat weiterhin ein Socket-Timeout, jedoch kein hartes Gesamtzeit-/Antwortgrößenlimit.

Weitere Seiten werden bewusst mit „Weitere 30 Angebote“ direkt aus Billomat nachgeladen. Angebotsnummernsuche bleibt serverseitig möglich. Neuere Änderungen können bis zur nächsten Aktualisierung fehlen; bei Änderungen während des Blätterns ist die API-Seiteneinteilung kein unveränderlicher Snapshot. Einzelangebote und PDFs werden weiterhin frisch geladen; der Listencache verändert keine Preise in PDF-Ausgaben und löst den gemeldeten PDF-Fehler nicht automatisch.

Prüfung: API-Seitengröße/-parameter, dauerhafter Cache und Kontotrennung, Ausfall mit unveränderten Daten, nicht blockierender Hintergrundstart ohne doppelte Threads, Route ohne synchronen API-Aufruf, Seiten-/Suchnavigation. Browser mit fiktiven Daten bei 320 und 390 Pixeln ohne horizontalen Überlauf; Seite 2 zeigt Einträge 31–60. Vollständiges Testergebnis im übergeordneten Arbeitsstand.

API-Referenz: https://www.billomat.com/api/grundlagen/daten-lesen/ und https://www.billomat.com/api/angebote/
