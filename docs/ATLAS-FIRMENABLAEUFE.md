# ATLAS als Firmenassistenz

Stand 03.11.2026. ATLAS bleibt die zentrale Oberfläche für Gespräch, Wissen,
Aufgaben, E-Mails, Termine und Buchhaltung. Hermes ist auf Wunsch des Inhabers
kein aktueller Ausbaupfad. Dieses Dokument ist der verbindliche Arbeitsplan,
keine Bestätigung neuer installierter Funktionen.

## Nachweisstand und Priorität

Priorität ist die Vorbereitung der Oktober-Buchhaltung. Der letzte dokumentierte
Produktionsstand ist ATLAS 0.9.5 vom 02.11.2026 mit erfolgreich durchgelaufener
Monatsvorbereitung und mehrteiligen Exporten. Eine erneute Live-Prüfung fand bei
dieser Konzeptaktualisierung nicht statt. OpenAI-Text und Webrecherche wurden im
vorherigen Arbeitsabschnitt erfolgreich getestet. Die direkte Google-Verbindung
und ein vollständiges Gespräch auf dem tatsächlichen iPhone bleiben unbestätigt.

Ein Kontoauszug wurde außerhalb von ATLAS ausgewertet und gegen Rechnungsdaten
geprüft. Diese Auswertung ist noch kein eingebauter Bankimport, kein persistenter
Zahlungsabgleich und kein fertiges Buchungsjournal. Private Beträge, Dokumente und
Kontoverbindungen gehören nicht in dieses öffentliche Projektprotokoll.

## Gemeinsames Bedienkonzept

Der Nutzer formuliert einen Auftrag im Gespräch oder per Text. ATLAS zeigt,
welchen Ablauf es startet, welche Quellen verfügbar sind und welche Angaben fehlen.
Ein angenommener Auftrag bleibt nach Navigation oder Neustart nachvollziehbar.
Die Antwort unterscheidet erledigte Arbeit, Vorschläge und noch offene Klärungen.
Eine gespeicherte Aufgabe allein ist keine ausgeführte Aktion.

Die Ansichten bleiben Gespräch, Wissen, Aufgaben, E-Mails, Belege und System.
Für die Buchhaltung erhält Belege einen Monatsarbeitsplatz mit Quellenstatus,
Kontoauszügen, Zuordnungsvorschlägen, Klärungen und Export. Derselbe Monatsstand
soll später über Sprache und Telegram abrufbar sein.

## Nächster Lieferumfang – Bankabgleich in ATLAS

| Schritt | Verhalten | Abnahme |
| --- | --- | --- |
| Original übernehmen | Besitzer lädt Auszug hoch, Original und SHA-256 bleiben erhalten. Quelle, Konto, Währung und Zeitraum werden separat geführt. | Erneuter Upload derselben Datei erzeugt keine zusätzlichen Transaktionen. Ein anderer Besitzer kann weder Original noch Buchungen abrufen. |
| Auszug prüfen | Zunächst ausdrücklich unterstütztes Revolut-EUR-PDF und ein dokumentiertes CSV-Format. Giro und Unterkonten bleiben getrennt. Unlesbare oder widersprüchliche Daten bleiben im Prüfstatus. | Anfangssaldo plus Eingänge minus Ausgänge entspricht Endsaldo je Konto. Transaktionssaldo und Summen werden geprüft. Keine stille Teilübernahme. |
| Zahlungen vorschlagen | Rechnungsreferenz, Betrag, Währung und Richtung begründen den Vorschlag. Vollständiger Verwendungszweck einschließlich Folgezeilen wird berücksichtigt. | Gleicher Betrag allein bestätigt keine Zuordnung. Testfälle umfassen Teilzahlung, Sammelzahlung, Gutschrift, Bankgebühr und Umbuchung. |
| Entscheidung speichern | Nutzer bestätigt oder verwirft Vorschlag. Zuordnung speichert Betrag, Transaktion, Rechnung, Entscheider und Zeitpunkt. Korrekturen bleiben nachvollziehbar. | Eine Zahlung kann nur bis zu ihrem verfügbaren Betrag zugeordnet werden. Wiederholte Bestätigung erzeugt keine Doppelzuordnung. Billomat-Status bleibt unverändert. |
| Klärungen anzeigen | Nicht zugeordnete Zahlungen, fehlende Belege, Widersprüche und unvollständige Quellen stehen in einer gemeinsamen Liste. | „Kein Treffer“ wird nicht als „unbezahlt“ ausgegeben. Aktueller Quellstatus wird vom historischen Monatsstichtag unterschieden. |
| Monat exportieren | Originale, geprüfte Transaktionsliste, bestätigte Zuordnungen, Vorschläge und Klärungen werden getrennt exportiert. | Jeder Datensatz ist zur Quelle rückverfolgbar. Alle Exportteile sind vollständig herunterladbar und anhand des Verzeichnisses prüfbar. |

Implementierungsreihenfolge im bestehenden Projekt
1. Besitzergebundene Datenhaltung, Originalspeicher und Importvalidierung.
2. Deterministischer Abgleich mit synthetischen Sonderfällen.
3. HTTP-Routen mit bestehendem Besitzer-/CSRF-Schutz und Monatsoberfläche.
4. Ergänzung des bestehenden Monatsablaufs und Exports.
5. Gezielte Tests, unabhängige Prüfung, Release-CI und Installation mit Backup.
6. Abnahme mit einem realen Monat ohne automatische finanzielle Entscheidungen.

Keine Modellantwort schreibt direkt Buchungen. Ein zukünftiges Beancount-Journal
benötigt bestätigte Stammdaten, Kontenrahmen, Steuerlogik und Anfangsbestände.
Diese Voraussetzungen sind ein separates Arbeitspaket nach dem Zahlungsabgleich.

## Folgepakete in Reihenfolge

| Paket | Ergebnis | Abschlussnachweis |
| --- | --- | --- |
| Belege nachfordern | Konkrete Klärung mit zugehörigem Uploadzugang über Telegram an den eingerichteten Inhaber. Mitarbeiterzugänge bleiben auf Einreichen begrenzt. | Upload beantwortet genau eine Klärung. Widerruf sperrt Zugang. Versand und Fehler sind nachvollziehbar und werden nicht doppelt ausgelöst. |
| Natürliches Gespräch | Allgemeine ATLAS-Fragen, Aufgaben erstellen und abfragen, danach automatisch weiter zuhören. | Drei aufeinanderfolgende Runden am echten iPhone, Unterbrechung, Sprechpause, Stop und Verbindungsverlust geprüft. Keine doppelten Aktionen. |
| Mailassistenz | Quelle, Zusammenfassung und dauerhaft bearbeitbarer Antwortentwurf pro Vorgang. | Entwurf bleibt nach Neustart erhalten. Versand ist eine gesonderte ausdrücklich beauftragte Aktion mit prüfbarem Ergebnis. |
| Kalender | Direkte Google-Anbindung und Buchung nach Bestätigung der endgültigen Details. | OAuth, freie Zeiten, konkurrierender Termin und eindeutige Speicherung getestet. Unklarer Schreibausgang wird nicht blind wiederholt. |
| Firmenwissen | Bestätigte Fakten mit Herkunft, Änderungshistorie und Verbindungen zu Vorgängen. | Korrektur ersetzt veraltete Aussagen im aktuellen Kontext. Eingehende Dokumente werden nicht ungeprüft zu gültigen Firmenregeln. |
| Vertrieb und Technik | Geprüfte Übergaben zum AngebotsDesigner, Montagevorbereitung und Wartung. | Ein vollständiger Testvorgang mit echten Datenquellen und nachvollziehbaren Übergaben. |

## Protokoll und Fertigstellungsmaßstab

Für jedes Paket werden geplant, implementiert, getestet, veröffentlicht und
installiert getrennt festgehalten. Ein Release ist erst im Alltag abgenommen,
wenn der beschriebene Nutzerablauf am Zielgerät funktioniert. Tests ersetzen weder
eine reale Quellenverbindung noch vollständige Monatsdaten.

Nächster konkreter Entwicklungsschritt ist das Datenmodell samt Importprüfung
für Kontoauszüge. Anschließend folgen Zuordnung und Monatsoberfläche. Bestehende
Buchhaltungssynchronisation, Originale und Besitzergrenzen müssen erhalten bleiben.
Weitere Funktionen werden nicht als aktiv bezeichnet, bevor ihre Abnahme erfolgt.
