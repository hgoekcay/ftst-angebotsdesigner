"""Real HTTP framing and owner scope for explicitly activated voice turns."""
import json
import test_voice_http

server = test_voice_http.server
request = test_voice_http.request


def call(server, **kwargs):
    body = json.dumps({'message': 'Aufgabe anlegen: Test', 'request_id': 'turn-0123456789012345'}).encode()
    return request(server, '/api/voice/turn', body, extra={'Content-Type': 'application/json'}, **kwargs)


def test_authorized_turn_and_csrf(server):
    app, _ = server
    assert call(server, csrf=False)[0] == 403
    assert call(server, user='other')[0] == 403
    assert app.jobs.list('owner') == []
    code, _, raw = call(server)
    assert code == 202
    first = json.loads(raw)
    assert call(server)[0] == 202
    assert len(app.jobs.list('owner')) == 1
    app.jobs._process_one()
    assert app.jobs.get('owner', first['id'])['result']['action'] == 'task_created'


def test_owner_checked_before_large_body_and_no_streaming(server):
    code, _, _ = request(server, '/api/voice/turn', body=b'', user='other', extra={'Content-Length': '50000'})
    assert code == 403
    assert request(server, '/api/voice/turn', body=b'', extra={'Content-Length': '50000'})[0] == 413
    assert request(server, '/api/voice/turn', body=b'', extra={'Transfer-Encoding': 'chunked'})[0] == 400
