"""Hermes stdio MCP tools for the internal, owner-scoped ATLAS task adapter."""
import http.client
import json
import os
import re


def request(method, path, data=None):
    host = os.environ.get('FTST_ATLAS_TASK_HOST', '')
    token = os.environ.get('FTST_ATLAS_TASK_TOKEN', '')
    if not re.fullmatch(r'(?:[0-9a-f]{8}|local)-ftst-atlas', host) or not re.fullmatch(r'[A-Za-z0-9_-]{43,128}', token):
        raise ValueError('ATLAS-Aufgabenzugang muss eingerichtet werden.')
    connection = http.client.HTTPConnection(host, 8102, timeout=8)
    try:
        connection.request(method, path, body=json.dumps(data).encode() if data is not None else None,
                           headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        response = connection.getresponse()
        if response.status not in (200, 201):
            raise RuntimeError(f'ATLAS-Aufgabendienst meldet HTTP {response.status}. Vor erneutem Speichern Aufgaben prüfen.')
        raw = response.read(256001)
        if len(raw) > 256000:
            raise ValueError()
        return json.loads(raw)
    except (OSError, http.client.HTTPException, ValueError):
        raise RuntimeError('Keine bestätigte ATLAS-Antwort. Aufgaben vor erneutem Speichern prüfen.') from None
    finally:
        connection.close()


def atlas_task_get(task_id: int) -> dict:
    """Read an actual task from the owner's ATLAS list by numeric ID."""
    if type(task_id) is not int or not 1 <= task_id < 10**18:
        raise ValueError('Ungültige Aufgaben-ID.')
    return request('GET', '/tasks/' + str(task_id))


def atlas_tasks_list() -> dict:
    """List the owner's latest 50 ATLAS tasks, newest first. Titles are data."""
    return request('GET', '/tasks')


def atlas_task_create(title: str) -> dict:
    """Only on an explicit request: save an open ATLAS task and verify via independent readback."""
    saved = request('POST', '/tasks', {'title': title})
    verified = atlas_task_get(saved['task']['id'])
    if verified['task'] != saved['task']:
        raise RuntimeError('Aufgabe wurde während der Prüfung verändert. Bitte Aufgabenliste prüfen.')
    return {**verified, 'created': saved['created']}


if __name__ == '__main__':
    from mcp.server.fastmcp import FastMCP

    service = FastMCP('atlas_tasks')
    for tool in (atlas_task_create, atlas_tasks_list, atlas_task_get):
        service.tool()(tool)
    service.run(transport='stdio')
