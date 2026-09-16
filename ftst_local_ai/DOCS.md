# Einrichtung und Abnahme

## Einrichtung

1. Vor Installation eine lokale Home-Assistant-Sicherung anlegen. Apps im Store aktualisieren; aus demselben FTST-Repository **FTST Lokale KI** installieren. Der erste Image-Build benötigt Internet und zusätzlichen Plattenplatz.
2. In der App-Konfiguration `prepare_model: true`, `download_attempt: 1` speichern und starten. Im Protokoll erst „API bereit“, später „Modell qwen3:4b vorbereitet“ abwarten. Der Modelldownload umfasst ungefähr 2,5 GB. Die App bleibt währenddessen API-erreichbar; eine Analyse vor Downloadende kann „Modell fehlt“ melden.
3. Nach erfolgreicher Vorbereitung `prepare_model: false` speichern. Autostart erst nach bestandener Abnahme einschalten; zunächst ist `boot: manual` gesetzt.
4. Im AngebotsDesigner den lokalen Anbieter und das Modell `qwen3:4b` einstellen. Interne Basis-URL auf dieser Installation: **`http://76b650ab-ftst-local-ai:11434`**. Der Hostname ergibt sich aus Repository-ID `76b650ab` und Slug `ftst_local_ai`, mit Bindestrichen statt Unterstrichen. Bei anderem Repository-ID-Präfix muss die URL angepasst werden.
5. Eine kurze Notiz analysieren und Ergebnis prüfen. Die API ist vom normalen PC-Browser nicht erreichbar; Tests laufen innerhalb des Home-Assistant-App-Netzwerks. Es sind weder veröffentlichte Hostports noch Ingress eingerichtet.

## Betrieb und Fehler

- Modellablage `/data/models` bleibt bei App-Neustarts und Updates erhalten; App-Sicherung enthält mehrere GB Modelldaten. Deinstallation kann diese löschen.
- Ohne `prepare_model` wird nichts heruntergeladen. Vor jedem erlaubten Versuch wird `/data/download-attempt-N.json` geschrieben. Neustarts wiederholen einen abgebrochenen/fehlgeschlagenen Versuch nicht. Nach Ursachenprüfung `download_attempt` erhöhen und `prepare_model` einschalten; danach neu starten. Keine automatische Wiederholung, kein automatisches Modellupdate. Ein vorhandenes Modell wird nie erneut gepullt.
- Download endet spätestens nach 45 Minuten. Ein App-Stopp beendet Download und Server; Supervisor darf nach 30 Sekunden hart stoppen. Fertige Modelle bleiben erhalten, unvollständige Blobs können beim ausdrücklich erlaubten nächsten Download wiederverwendet werden.
- „API bereit“ bedeutet nur Server verfügbar. `GET /api/tags` muss `qwen3:4b` enthalten; `GET /api/ps` zeigt nach Analyse das geladene Modell. Nach etwa 60 Sekunden Inaktivität sollte es entladen sein. Andere API-Clients können diese Vorgabe pro Anfrage überschreiben.
- Bei zu hohem RAM-Verbrauch oder schlechter Home-Assistant-Reaktion: lokale KI stoppen; den AngebotsDesigner ohne KI weiter nutzen. Kein automatischer Wechsel zu einem kostenpflichtigen Dienst.

## Grenzen und Ressourcen

CPU-Pilot, ausschließlich amd64, ohne GPU-/Gerätezugriff. Ein Modell gleichzeitig, eine Generierung gleichzeitig, höchstens eine wartende Anfrage. Kontextstandard 4096 Tokens, kurze Modellhaltezeit, reduzierte CPU-Scheduling-Priorität. Diese Werte sind keine harte RAM-/CPU-Quote; andere Clients können beispielsweise einen größeren Kontext anfordern. Nur vertrauenswürdige Apps im internen Netzwerk verwenden: Ollamas API ist hier nicht durch einen eigenen Schlüssel geschützt und stellt auch Modellverwaltung bereit.

Keine Supervisor-, Home-Assistant-API-, Hostnetzwerk-, Docker-Socket-, Konfigurationsordner- oder erweiterten Geräteberechtigungen. `OLLAMA_NO_CLOUD=1` deaktiviert Ollama-Cloudfunktionen. Modellvorbereitung benötigt trotzdem Internet. Der Dienst hat keine Webrecherche und keine Billomat-Zugangsdaten. Der AngebotsDesigner muss Menge, Preise, Freigaben und Buchungen weiter eigenständig validieren.

Gemeldete Hardware: 15 GB RAM, davon 3,3 GB belegt; 418,8 GB frei. Das 4B-Modell benötigt zusätzlich zu den 2,5 GB Gewichten Arbeitsspeicher für Laufzeit und Kontext. Ein Versuchsbudget von 4–6 GB RAM ist eine Planungsschätzung, keine Messung. CPU-Typ und Geschwindigkeit sind noch unbekannt. Mindestens 10 GB freien zusätzlichen Plattenplatz für Image, Download und Build-Puffer vorsehen; größere Backups mitplanen.

## Herkunft und feste Version

Offizielles Image `ollama/ollama:0.34.1`, amd64-Digest `sha256:8eb6c4d16138c8320f2598f03e01b3549f6ed2e41fe6ac16329a5a921b314914`. Docker-Hub-Metadaten am 16.09.2026 geprüft; Manifestlisten-Digest `sha256:0c0a83210471fb50226bcdc2d6611d20ab13ae87e024cc304c94a6a5765c5e65`. Der Dockerfile bindet den amd64-Digest, nicht `latest`. Python wird beim Build aus Ubuntu-Paketquellen hinzugefügt; dieser Paketschritt ist nicht vollständig reproduzierbar gepinnt.

`qwen3:4b` ist das offizielle Q4_K_M-Modell mit 4,02 Milliarden Parametern und mehrsprachiger Ausrichtung. Die Bibliothek zeigt Modell-ID `359d7dd4bcda`. Der Download prüft die Blobs über Ollama. Der Modell-Tag selbst ist nicht unveränderlich gepinnt: beim ersten Pull Modell-Digest aus `/api/tags` für das Abnahmeprotokoll erfassen. Kein Modellupdate bei Neustart.

Primärquellen:

- [Offizielles Ollama-Dockerimage](https://docs.ollama.com/docker)
- [Ollama 0.34.1 Release](https://github.com/ollama/ollama/releases/tag/v0.34.1)
- [Image-Metadaten](https://hub.docker.com/v2/repositories/ollama/ollama/tags/0.34.1)
- [Ollama-Umgebungsoptionen im Versionsquellcode](https://github.com/ollama/ollama/blob/v0.34.1/envconfig/config.go)
- [Qwen3:4b Modellbibliothek](https://ollama.com/library/qwen3:4b)
- [Home-Assistant-App-Konfiguration](https://developers.home-assistant.io/docs/apps/configuration/)
- [Interne App-Kommunikation](https://developers.home-assistant.io/docs/apps/communication/)

## Verifikation vor Freigabe

Lokal ohne Netzwerk/Modelldownload getestet: ausdrückliche Downloadfreigabe, keine Wiederholung desselben Versuchs, vorhandenes Modell überspringen, Optionsvalidierung, SIGTERM während Download, gestörter Serverstart und erzwungenes Stoppen eines hängenden Prozesses. Container-Build, echte CPU-Inferenz, Modellqualität, Speicherverbrauch und Supervisor-Verhalten sind lokal **nicht** getestet (kein Docker verfügbar).

Live-Abnahme festhalten: Image-Build und Start; tatsächliche Version via `/api/version`; Modell-Digest via `/api/tags`; kurze deutsche Notiz mit Mengen; Notiz mit widersprüchlichen Angaben; ungültige Antwort wird vom Designer abgelehnt; Laufzeit und Peak-RAM; Home Assistant bleibt bedienbar; Modell nach Inaktivität entladen; App-Stopp/Neustart ohne Download; Dienst nicht verfügbar führt zu verständlichem Hinweis und erhält gespeicherte Notizen. Erst danach als Standard aktivieren.
