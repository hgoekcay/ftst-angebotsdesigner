"""Exercise ingress, CSRF, the actual packaged Hermes CLI and model result."""
import json
import urllib.request

BASE = "http://172.30.32.3:8099"
HEADERS = {"X-Remote-User-Id": "a" * 32}
with urllib.request.urlopen(urllib.request.Request(BASE + "/state", headers=HEADERS), timeout=10) as r:
    csrf = json.load(r)["csrf"]
for question in ("Antworte mit dem Testtext.", "Wiederhole die Antwort."):
    request = urllib.request.Request(
        BASE + "/turn", json.dumps({"message": question}).encode(),
        headers={**HEADERS, "X-FTST-CSRF": csrf, "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=190) as r:
        assert "Hermes-Modelltest erfolgreich." in json.load(r)["reply"]
