# Lesende Billomat-Belegprüfung 0.10.0

In app.py registriert und unter Billomat-Daten → Beleg-Verbindung prüfen erreichbar. Der bestehende produktive Ingress-Peer-Schutz gilt auch hier. Die lokale Implementierungsprüfung verwendet ausschließlich fiktive HTTP-Antworten; die separate Liveprüfung ist im Releaseprotokoll zu dokumentieren.

Die Schaltfläche startet höchstens zwei GET-Anfragen: erste Seite von `/api/incomings` und `/api/inbox-documents`, jeweils `per_page=5`. Ein GET auf die Prüfseite selbst startet keinen API-Aufruf. CSRF schützt die bewusste Prüfaktion. Vorhandene Umgebungsvariablen BILLOMAT_ID/BILLOMAT_API_KEY werden verwendet; der neue Leser übernimmt nicht die rohe Fehlerprotokollierung des älteren Clients.

## Schutz und Ergebnis

- Festes HTTPS-Ziel innerhalb der gültigen Billomat-Subdomain, TLS-Prüfung aktiv, keine Redirects, keine Umgebungs-Proxys.
- Connect-/Read-Timeout 5/10 Sekunden; zusätzlich Abbruch nach 20 Sekunden beim Empfang weiterer Chunks. Das ist keine harte Gesamtlaufzeitgarantie auf Betriebssystemebene: ein laufender Socket-Read kann noch bis zum Read-Timeout dauern.
- Maximal 256 KiB dekodierte Antwort pro Ressource; Content-Length ist nur eine zusätzliche Vorprüfung. Größenlimit greift auch ohne Header und nach Transport-Dekompression.
- Keine separaten Dateiabrufe, keine Nutzung von file_url, keine Weitergabe des Schlüssels an Speicheranbieter, keine Banking-Abfrage und keine schreibende HTTP-Methode.
- Ausgabe nur Erreichbarkeit, Gesamtzahl laut API und bekannte Feldnamen. Unbekannte Feldnamen werden ebenfalls nicht ausgegeben, weil auch diese vertraulichen Inhalt enthalten können. Werte, Metadateninhalte und Dateiinhalte werden nicht persistiert, protokolliert oder an eine KI gegeben. Antworten im Browser erhalten no-store.
- Bei Redirect, fehlendem Zugriff oder Rate-Limit wird keine zweite Ressource abgefragt. Kein Retry. Sperre gegen parallele Prüfung gilt pro Python-Prozess.

Eine Liste kann selbst Dateiinhalte enthalten; auch dann greift das Größenlimit. Die Prüfung bestätigt keine vollständige Belegliste, Dokumentintegrität, Banking-Aktivierung, Synchronisation oder steuerliche Buchung. Fehlende Gesamtzahl erscheint als unbekannt, nicht als null Belege. Native API-Formate müssen am realen Konto noch bestätigt werden; ungewohnte Strukturen werden als nicht prüfbar ausgewiesen.

## Quellen

- [Eingangsrechnungen](https://www.billomat.com/api/eingangsrechnungen/)
- [Beleg-Inbox](https://www.billomat.com/api/eingangsrechnungen/inbox/)
- [Lesen und Paginierung](https://www.billomat.com/api/grundlagen/daten-lesen/)
- [Aufruflimits](https://www.billomat.com/api/grundlagen/zugriffsbegrenzung/)

## Tests

`python -m pytest tests/test_billomat_receipts.py` verwendet ausschließlich gemockte HTTP-Antworten. Abgedeckt sind feste Lesziele, Redirects, TLS-/Verbindungsfehler, Timeout, Rate-Limit, fehlerhafte JSON-Strukturen, Responsegrößenlimit, sichere Mengenangaben, redigierte Sentinel-Geheimnisse, CSRF und parallele Aufrufe. Ein realer Kontotest ist ausdrücklich nicht Teil dieser Tests.
