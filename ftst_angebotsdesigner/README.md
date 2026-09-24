# FTST AngebotsDesigner

Interner AngebotsDesigner für FT Sicherheitstechnik.

## Aktuelle Version

**0.20.0**

Freigegebene Angebote haben Aktionen für E-Mail und WhatsApp. Kundendaten prüfen, PDF vorbereiten und über die gewählte App senden. Empfängerlinks übertragen keine Anhänge; PDF speichern und anhängen oder natives Teilen verwenden. Kein serverseitiger Direktversand. Details: [Angebotsversand](../docs/ANGEBOTSVERSAND.md).

In Projekten zeigt **Ihr Weg zum Angebot** den gespeicherten Fortschritt und führt zum nächsten Schritt. Unter **Technikeraufnahme → Ajax-Komponente schnell ergänzen** lassen sich Bewegungsmelder, Magnetkontakte, Innen-/Außensirenen, Innen-/Außenbedienteile und Zentralen einzeln ergänzen. Menge und konkrete Variante werden anschließend eingetragen. Der optionale Raum / Montageort bleibt nach der bestätigten Übernahme in der Kalkulationsanforderung sichtbar. Details: [Technikerablauf](../docs/TECHNIKERAUFNAHME.md).

Referenzbilder sind auf insgesamt vier Motive pro Angebot begrenzt und erscheinen gemeinsam auf einer einzigen Seite. Das gilt auch für ältere Auswahlen mit mehr Bildern. Lange Bildtexte werden nur in der PDF gekürzt; die vollständigen Angaben bleiben in der Bildbibliothek erhalten.

## Firmenauftritt im Angebot

Unter **Firma** werden Inhaber, Adresse, Kontakt und Bankverbindung gepflegt. Diese Daten erscheinen in der Fußzeile jeder PDF-Seite; sie werden ausschließlich in den App-Daten gespeichert. Die IBAN-Prüfsumme und das BIC-Format werden beim Speichern geprüft. Das neue Standardlogo zeigt FT Sicherheitstechnik mit ®; bei einer früher ausdrücklich gespeicherten Logoauswahl kann es unter Firma gewählt werden.

Referenzseiten zeigen bis zu vier ausgewählte Bilder gemeinsam. Ablauf, häufige Fragen zur Sicherheitstechnik und persönlicher Kontakt ergänzen das Angebot. Die Vorlage erfindet keine Referenzzahlen, Bewertungen, Garantien oder Zahlungsfristen. Der konkret angebotene Leistungsumfang und die Konditionen bleiben maßgeblich.

Die App liest Angebote aus Billomat und stellt sie im FTST-Design dar. Angebote können als A4-PDF ausgegeben werden. Projekte, Angebotsentwürfe, Lager und lokale KI unterstützen die Vorbereitung. Die Handyansicht vermeidet seitliches Scrollen.

## Home Assistant

Die App ist als Home Assistant App aufgebaut und verwendet Ingress. Billomat-Zugangsdaten werden ausschließlich über die App-Konfiguration gesetzt und nicht im Repository gespeichert.

Billomat bleibt in dieser Phase das führende System für Kunden, Artikel, Preise und Angebote.

## Projektentwurf an Billomat übergeben

Unter **Projekte → Angebotsentwurf → Übergabe an Billomat prüfen** zunächst die aktuelle Vorschau laden. Nach Prüfung von Kunde, Texten, Positionen und Beträgen die Übernahme bestätigen. Die App legt einen Entwurf an und prüft das Ergebnis anhand der Billomat-Rückmeldung. Angebotsnummer, Freigabe und Versand folgen in Billomat; die App verschickt keine Nachricht.

Ein Projekt kann auf diesem Weg einmal übertragen werden. Bei unterbrochener Verbindung **Status in Billomat prüfen** verwenden: Dabei wird nur gelesen, kein zweites Angebot angelegt. Abweichende Rückmeldungen bleiben zur Prüfung markiert. Referenzbilder und FTST-Gestaltung werden lokal mit der Billomat-ID verknüpft und nicht als Bilder an Billomat übertragen.

In **Angebote** lassen sich Status filtern sowie Datum und interne Notiz als Wiedervorlage speichern. Die Wiedervorlage erscheint in der Übersicht, auch wenn das Angebot älter als die zwischengespeicherten 30 Einträge ist. Sie löst keinen automatischen Versand und keine Benachrichtigung aus.

Vor einem Update die App einschließlich ihrer Daten sichern. Übertragungsdatensätze nicht manuell löschen: Sie schützen vor doppelten Billomat-Angeboten. Nach einer Wiederherstellung prüft die App vor einer neuen Anlage die Projekt-Referenz in Billomat. Mehrdeutige Treffer benötigen eine Prüfung in Billomat.

## Aufnahme durch Techniker

Im Projekt **Technikeraufnahme** öffnen. Dort ein lesbares Handzettelfoto speichern oder die Komponenten direkt mit Menge und Beschreibung erfassen. Die Fotoauswertung verwendet das installierte lokale Bildmodell und läuft im Hintergrund. Sie lädt kein Modell herunter und verwendet keine Cloud-Ausweichverarbeitung.

Vor der Übernahme Originalfoto, erkannte Texte und jede Menge vergleichen. Strichlisten und unleserliche Stellen bleiben offen. Abkürzungen wie BM oder MK erst nach Bestätigung auflösen; Ajax ist als Hersteller vorgegeben, die genaue Variante wird danach im Billomat-Katalog gewählt. Kundenadresse, vorhandene Zentrale, Innen-/Außenbereich und Montageangaben ergänzen. Fehlende Angaben bleiben Rückfragen, niemals automatisch ergänzte Angebotspositionen.

Anschließend die Aufnahme bestätigen, in der Kalkulation die aktuellen Positionen übernehmen und Billomat-Artikel samt Preisen laden. Das Technikerfoto bleibt beim Projekt und wird nicht automatisch als Referenzbild in Kunden-PDFs eingefügt.

## Entwicklung

Der Antwortassistent enthält eine Mail-Arbeitsliste mit manuellem Text-/EML-Import, Originalen und Anhängen. Bearbeitung und Belegstatus bleiben getrennt. Keine automatische Postfachverbindung, kein Versand, keine OCR oder steuerliche Buchung. Billomat bleibt das führende System; die weitere Eingangsbeleg-Anbindung wird separat geprüft.

## Montageübersicht

Unter **Projekte → Projekt → Montageübersicht** stehen ausdrücklich übernommene Komponenten nach Einbauort, Mengen, Montagehinweise und offene Rückfragen. Die Übersicht lässt sich am Handy lesen und über **Übersicht drucken** ausgeben. Noch ungeprüfte Änderungen werden nicht übernommen; ein Hinweis kennzeichnet den älteren bestätigten Stand. Die Ansicht reserviert kein Material und bestätigt keine Beauftragung.

## Von der Aufnahme zur Kalkulation (0.18.0)

Die Technikeraufnahme enthält eine druckbare, ausfüllbare Ajax-Checkliste mit zwei A4-Seiten. Kundendaten können zunächst offen bleiben. Speichern hält die Aufnahme fest; erst **Geprüfte Angaben übernehmen und zur Kalkulation** übernimmt bestätigte Komponenten und öffnet den Angebotsentwurf. Dort werden der Billomat-Kunde und konkrete Artikel ausgewählt. Die Eingabe eines Namens in der Aufnahme ersetzt diese Zuordnung nicht. Eine bestehende Kalkulation wird nicht automatisch überschrieben; bei Änderungen müssen ihre Positionen bewusst neu übernommen werden. PDF-Dateiimport wird noch nicht unterstützt; für die Fotoauswertung Seite 1 fotografieren und Angaben von Seite 2 manuell ergänzen.

## Neuer Kunde direkt aus dem Angebot (0.19.0)

Im Angebotsentwurf zuerst Änderungen speichern und **Kunden suchen oder neu anlegen** öffnen. Privatpersonen mit vollständigem Namen und Anschrift manuell erfassen; Webrecherche ist für öffentliche Firmendaten vorgesehen. Nach Vorschau und ausdrücklich bestätigter Kundenanlage zeigt Billomat die neue Kundennummer. **Kunden übernehmen und zurück zum Angebot** lädt die aktuellen Stammdaten und wählt diesen Kunden im ursprünglichen Entwurf. Vorhandene Positionen bleiben erhalten. Die Preis-/Steuerprüfung muss anschließend erneut erfolgen. Zwischenzeitlich geänderte oder bereits übertragene Angebote werden nicht überschrieben. Bei unklarem Kundenanlage-Status bleibt die Übernahme gesperrt; keinen zweiten Kunden anlegen.
