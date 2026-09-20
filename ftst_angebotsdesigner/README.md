# FTST AngebotsDesigner

Interner AngebotsDesigner für FT Sicherheitstechnik.

## Aktuelle Version

**0.14.0**

Die App liest Angebote aus Billomat und stellt sie im FTST-Design dar. Angebote können als A4-PDF ausgegeben werden. Projekte, Angebotsentwürfe, Lager und lokale KI unterstützen die Vorbereitung. Die Handyansicht vermeidet seitliches Scrollen.

## Home Assistant

Die App ist als Home Assistant App aufgebaut und verwendet Ingress. Billomat-Zugangsdaten werden ausschließlich über die App-Konfiguration gesetzt und nicht im Repository gespeichert.

Billomat bleibt in dieser Phase das führende System für Kunden, Artikel, Preise und Angebote.

## Projektentwurf an Billomat übergeben

Unter **Projekte → Angebotsentwurf → Übergabe an Billomat prüfen** zunächst die aktuelle Vorschau laden. Nach Prüfung von Kunde, Texten, Positionen und Beträgen die Übernahme bestätigen. Die App legt einen Entwurf an und prüft das Ergebnis anhand der Billomat-Rückmeldung. Angebotsnummer, Freigabe und Versand folgen in Billomat; die App verschickt keine Nachricht.

Ein Projekt kann auf diesem Weg einmal übertragen werden. Bei unterbrochener Verbindung **Status in Billomat prüfen** verwenden: Dabei wird nur gelesen, kein zweites Angebot angelegt. Abweichende Rückmeldungen bleiben zur Prüfung markiert. Referenzbilder und FTST-Gestaltung werden lokal mit der Billomat-ID verknüpft und nicht als Bilder an Billomat übertragen.

In **Angebote** lassen sich Status filtern sowie Datum und interne Notiz als Wiedervorlage speichern. Die Wiedervorlage erscheint in der Übersicht, auch wenn das Angebot älter als die zwischengespeicherten 30 Einträge ist. Sie löst keinen automatischen Versand und keine Benachrichtigung aus.

Vor einem Update die App einschließlich ihrer Daten sichern. Übertragungsdatensätze nicht manuell löschen: Sie schützen vor doppelten Billomat-Angeboten. Nach einer Wiederherstellung prüft die App vor einer neuen Anlage die Projekt-Referenz in Billomat. Mehrdeutige Treffer benötigen eine Prüfung in Billomat.

## Entwicklung

Der Antwortassistent enthält eine Mail-Arbeitsliste mit manuellem Text-/EML-Import, Originalen und Anhängen. Bearbeitung und Belegstatus bleiben getrennt. Keine automatische Postfachverbindung, kein Versand, keine OCR oder steuerliche Buchung. Billomat bleibt das führende System; die weitere Eingangsbeleg-Anbindung wird separat geprüft.
