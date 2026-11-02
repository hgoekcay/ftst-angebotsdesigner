"""Drive the Hermes chat into one real MCP task write and independently verify SQLite via ATLAS."""
import json
from urllib.request import Request, urlopen

url = 'http://172.30.32.3:8099'
headers = {'X-Remote-User-Id': 'a' * 32}
with urlopen(Request(url + '/state', headers=headers), timeout=10) as r:
    state = json.load(r)
assert state['tasks']
headers.update({'Content-Type': 'application/json', 'X-FTST-CSRF': state['csrf']})
data = json.dumps({'message': 'ATLAS-Testaufgabe speichern.'}).encode()
with urlopen(Request(url + '/turn', data, headers), timeout=190) as r:
    assert 'ATLAS-Testaufgabe gespeichert.' in json.load(r)['reply']
with urlopen(Request('http://local-ftst-atlas:8102/tasks', headers={'Authorization':'Bearer ' + 'x' * 43})) as r:
    actual = json.load(r)['tasks']
assert len(actual) == 1 and actual[0]['title'] == 'ATLAS Integrationstest' and not actual[0]['done']
