# PDF-Angebotsentwurf 0.3.3

Auf der Projektkalkulation erscheint „PDF-Entwurf öffnen“, sobald eine Gesamtsumme berechnet werden kann und der Leistungsumfang als geprüft gespeichert ist. Das ist eine interne Prüfung, keine Angebotsfreigabe. Die PDF öffnet in einem eigenen Tab.

Route: /projects/<key>/quote/pdf?revision=<gespeicherte Revision>. Export nur im richtigen Billomat-Konto. Fehlender Entwurf: 404. Fehlende/falsche Revision, offene Angaben, ungeprüfter Umfang oder veraltete Notizen: 409. Nach der PDF-Erzeugung werden Projekt und Entwurf erneut gelesen; konkurrierende Änderungen verhindern die Auslieferung. Cache-Control: no-store.

Die gespeicherte Währung, Preisgruppe, Rabatt, Steuersätze, Mengen und Summen werden verwendet. Einzelpreise vor Rabatt und Positionssummen nach Rabatt sind erläutert. Logo und Firmendaten stammen aus dem vorhandenen Profil. Interne Projekt-ID wird nicht als Angebotsnummer dargestellt. Datum auf dem Deckblatt bezeichnet den Katalogstand, keine erfundene Ausstellung/Gültigkeit. Keine externen API-Aufrufe oder Änderungen beim Export.

Tests decken Export, Rabattsummen, Status je Seite, Währung, Kontentrennung, fehlende Revision, ungeprüfte/unvollständige/veraltete Daten und konkurrierende Änderung ab. Beispiel mit ausschließlich Testdaten als vierseitige PDF gerendert und visuell geprüft.

Weiter offen: explizite revisionsgebundene Freigabe, Übernahme in Billomat, Live-Abgleich der Rundung/Preisgruppen und HA-Installation. Git-Schreibanmeldung weiter nicht vorhanden; kein erneuter identischer Push-Versuch.
