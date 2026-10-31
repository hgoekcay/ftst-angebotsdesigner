# ATLAS als Firmenassistenz

Stand: 31.10.2026. Ziel ist eine gemeinsame Assistenz für FT Sicherheitstechnik:
sprechen, nachfragen, Wissen wiederfinden und nachvollziehbare Arbeitsaufträge
bearbeiten. Dieses Dokument beschreibt den Ausbau. Es bestätigt weder eine
vollständige Automatisierung noch die Installation eines Updates. Maßgeblich für
Release- und Testnachweise ist [ATLAS-STATUS.md](ATLAS-STATUS.md).

## Sechs Bausteine

Die gezeigte JARVIS-Vorlage verbindet Steuerung, Wissensablage, Sprache und
Oberfläche. Für den Firmenbetrieb ergänzen wir Quellenanbindungen und eine
überprüfbare Auftragsausführung:

| Baustein | ATLAS-Ziel | Aktueller Stand |
| --- | --- | --- |
| Steuerung | Frage beantworten oder passenden Ablauf starten | Lokales Modell, optionale Online-Beratung und fest definierte Abläufe vorhanden; kein beliebiger autonomer Werkzeugplaner. Online-Zugang benötigt Konfiguration. |
| Firmenwissen | Herkunft, Änderungen und Verbindungen zwischen Kundenprojekten, Verfahren und Entscheidungen nachvollziehen | Profil, gespeicherte Notizen, Suche, Fassungen und Aufgabenverknüpfungen vorhanden. Obsidian ist keine nachgewiesene installierte Voraussetzung. Ein Markdown-Export wäre ein zusätzlicher Zugang. |
| Sprache | Einmal starten, zuhören, antworten, erneut zuhören | Dialog implementiert. Erkennung und gespeicherte Antworten beobachtet; durchgängiger Betrieb auf dem tatsächlichen iPhone bleibt zu prüfen. |
| Oberfläche | Gespräch plus Wissen, Aufgaben, E-Mails und Belege an einem Ort | Gemeinsame Weboberfläche vorhanden. Anzeigen müssen echte Ausführungszustände zeigen; eine Animation beweist keine erledigte Arbeit. |
| Quellen | Freigegebene Postfächer, Billomat und Mitarbeiterbelege zusammenführen | Anbindungen und Import vorhanden, aber Quellenabdeckung unvollständig. Ein Postfach meldet abgewiesene Anmeldung; Mitarbeiterzugang benötigt geprüfte separate HTTPS-Erreichbarkeit. |
| Ausführung | Aufträge dauerhaft annehmen, Ergebnisse nachvollziehbar ablegen, Fehler erkennen | Hintergrundaufträge, Tagesüberblick und Monatsvorbereitung vorhanden. Eine gespeicherte Aufgabe ist ein offener Listeneintrag, keine bereits ausgeführte Firmenaktion. |

## Abteilungen und konkrete Ergebnisse

„Vorhanden“ bezeichnet implementierte Funktionen, nicht automatisch einen
vollständig eingerichteten oder im Alltag abgenommenen Ablauf.

| Bereich | Eingaben | Konkrete Ergebnisse | Umsetzungsstand |
| --- | --- | --- | --- |
| Leitung | Firmenprofil, freigegebenes Wissen, Aufgaben, verfügbarer Belegstand | Tagesüberblick mit offenen Punkten und erkennbaren Datenlücken | Fester Briefing-Ablauf vorhanden. Automatische Zustellung und verlässliche Terminüberwachung sind separat zu ergänzen und abzunehmen. |
| Büro | Freigegebene E-Mail-Postfächer, Gesprächsaufträge, Rückfragen | Mailzusammenfassungen, Antwortentwürfe, offene Aufgaben | Lesen und Entwürfe vorhanden. Dauerhaft verwaltete Mailentwürfe, Zuordnung zu Vorgängen und Versandablauf sind nächste Ausbauschritte. |
| Vertrieb | Kundenanfrage, geprüfte Artikel und Preise, Projektwissen | Angebotsentwurf, fehlende Angaben, nächste Vertriebsaufgabe | AngebotsDesigner ist ein bestehendes separates Modul. Ein durchgängiger ATLAS-Vertriebsablauf mit geprüften Übergaben ist noch abzunehmen; automatischer Angebotsversand ist kein vorhandener Standardablauf. |
| Technik | Freigegebenes Angebot, Projektunterlagen, Fotos, Wartungshinweise | Montagevorbereitung, Materialentwurf, Prüf- und Wartungslisten | Als Ziel beschrieben. Eine verlässliche vollständige Projektkette mit Nachweisen und Rückmeldungen ist noch aufzubauen. |
| Buchhaltung | Eingangsbelege, Billomat-Ausgangsrechnungen, später Bankdaten | Geprüftes Monatspaket, fehlende Belegangaben, nachvollziehbare offene Posten | Import, Belegprüfung, Export und Monatsvorbereitung vorhanden. Bankabgleich, vollständiges Buchungsjournal und belastbare OP-Liste fehlen. Der Billomat-Zahlungsstatus ersetzt keinen Bankabgleich. |
| Marketing | Freigegebene Referenzen, Leistungsbeschreibung, Bildmaterial | Beitragsentwürfe und Redaktionsvorschläge | Geplanter Ablauf. Ein anderer verfügbarer Connector bedeutet noch keine in ATLAS eingerichtete oder getestete Veröffentlichung. |

## Buchhaltung: vom Dokument zum geprüften Monat

Der Zielweg lautet: Original übernehmen, Dokumentart bestimmen, Angaben mit
Quelle auslesen, Dubletten oder Korrekturen zuordnen, Rechnung prüfen, Zahlung
abgleichen und einen überprüfbaren Export vorbereiten.

Der heutige Import erledigt davon nur Teile. Ein E-Mail-Anhang ist nicht automatisch
eine Rechnung; ein unbekannter Zahlungsstatus ist kein Nachweis einer offenen
Forderung. Unvollständige Quellen dürfen keinen scheinbar vollständigen Bericht
ergeben. Ein zukünftiges Buchungsjournal, etwa mit Beancount, benötigt ausdrücklich
festgelegte Konten, Perioden, Korrekturregeln und Abnahmetests. Der vorhandene
Buchhaltungs-Skill allein stellt diese Integration nicht her.

Die gewünschte Telegram-Liste soll konkrete Rückfragen enthalten: welcher Beleg
fehlt, zu welchem Vorgang er gehört und wie er nachgereicht werden kann. Dafür
müssen zunächst Rechnungsart und Zahlungsabgleich verlässlich sein. Mitarbeiter
sollen Belege über einen begrenzten Uploadzugang einreichen können; dieser Zugang
soll keine Firmenpostfächer oder fremden Unterlagen offenlegen.

## Nächste Meilensteine und Abnahme

| Reihenfolge | Arbeitspaket | Nachprüfbare Abnahme |
| --- | --- | --- |
| 1 | Dialog stabilisieren und Update verifizieren | Installierte Version festhalten. Drei gesprochene Fragen nacheinander liefern Text und Ton; nach jeder Antwort hört ATLAS wieder zu. Stop beendet Audio und Mikrofon. Bereits angenommene Aufträge erscheinen höchstens einmal und starten keine zweite Aktion. Test auf dem tatsächlichen iPhone. |
| 2 | Quellen vollständig anbinden | Jedes vorgesehene Postfach besteht einen Lese-Test. Billomat-Abdeckung und Importfehler sind sichtbar. Zugangsdaten werden sicher konfiguriert; ein fehlender API-Schlüssel wird als offen ausgewiesen. |
| 3 | Dokumenteingang und Mitarbeiterupload abnehmen | Testfälle für Rechnung, sonstiges Dokument, Dublette und Korrektur bleiben unterscheidbar. Originale bleiben erhalten. Upload von außerhalb funktioniert über HTTPS; gesperrter Zugang wird abgewiesen. |
| 4 | Mailassistenz als Arbeitsablauf | Ein Testvorgang enthält Quelle, Zusammenfassung und gespeicherten bearbeitbaren Entwurf. Der Status unterscheidet „Entwurf“ und „gesendet“. Eine ausdrückliche Versandaktion erzeugt höchstens einen Versand. |
| 5 | Bankabgleich und Buchungsentwürfe | Testmonat mit Teilzahlung, Gutschrift, fehlendem Beleg und Dublette wird korrekt zugeordnet. Unklare Fälle bleiben offen. Summen und Herkunft sind prüfbar; Wiederholung erzeugt keine doppelten Buchungen. |
| 6 | Firmenabläufe und Telegram-Berichte | Tagesüberblick und Monatsvorbereitung enthalten nachvollziehbare Quellen und Lücken. Eine freigegebene Telegram-Rückfrage lässt sich durch Upload beantworten. Jede automatisierte Aktion hat Ergebnis, Fehlerstatus und Schutz vor Wiederholung. |

Erst nach diesen Nachweisen werden weitere automatische Aktionen einzeln
freigeschaltet. Neue Quellen und Berechtigungen werden je Ablauf dokumentiert.
Zahlungen, Steuerübermittlungen und verbindlicher Kundenversand sind eigene
Integrationen mit eigenen Prüfungen, keine Nebenwirkung einer Chatantwort.

Dieses Konzept ergänzt die laufenden Fehlerkorrekturen. Es ersetzt weder deren
Installation noch die praktische Abnahme des Gesprächsmodus.
