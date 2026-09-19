# FTST Lokale KI

Separater CPU-Pilot für deutsche Projektnotizen. Installiert Ollama 0.34.1 und bereitet auf ausdrückliche Anforderung `qwen3:4b` vor. Keine externe KI und kein Cloud-Fallback. Noch keine Garantie für fachliche Richtigkeit oder ausreichende Geschwindigkeit: Vorschläge müssen geprüft werden.

Ab Version 0.1.1 kann zusätzlich `gemma3:4b` für die lokale Erkennung von Referenzfotos vorbereitet werden. In **Konfiguration** „Bildmodell einmalig vorbereiten“ einschalten, speichern und die App neu starten. Der optionale Download umfasst etwa 3,3 GB; er beginnt nur mit mindestens 6 GiB freiem Speicher. Das Textmodell bleibt erhalten. Nach erfolgreicher Vorbereitung den Schalter wieder ausschalten. Die Bilderkennung im AngebotsDesigner kann danach Kategorien vorschlagen; unsichere Ergebnisse bleiben zur Prüfung offen.

Siehe [Einrichtung und Abnahme](DOCS.md). Die Home-Assistant-Ollama-Integration ist für den direkten Zugriff des AngebotsDesigners nicht erforderlich.
