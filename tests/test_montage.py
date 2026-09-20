from copy import deepcopy

import pytest

import app as module
from montage import overview
from test_persistence import isolated_storage


def project():
    return dict(title='Montagetest', notes='', offer_id='', intake_fields=dict(
        customer_name='Bestätigter Kunde', object_address='Teststraße 1', manufacturer='Ajax',
        installation='Leitungsweg prüfen', central='no'), analysis=dict(
        provider='technician-reviewed', user_confirmed=True, questions=['Welche Farbe?'], components=[
            dict(description='Ajax Bewegungsmelder · Raum / Montageort: Flur', source_description='Bewegungsmelder',
                 quantity='2', location='Flur', user_confirmed=True, evidence='Vor Ort'),
            dict(description='Ajax Magnetkontakt', quantity='1', user_confirmed=True),
        ]))


@pytest.fixture
def ui(isolated_storage, monkeypatch):
    monkeypatch.setenv('BILLOMAT_ID', 'test')
    monkeypatch.setenv('FTST_REQUIRE_INGRESS', '0')
    store = module.offer_store()
    store.put_record('test', 'project', 'one', project())
    return module.app.test_client(), store


def test_groups_keep_confirmed_locations_and_legacy_rows():
    value = overview(project())
    assert value['accepted']
    assert list(value['groups']) == ['Flur', '']
    assert value['groups']['Flur'][0]['description'] == 'Bewegungsmelder'
    assert value['groups'][''][0]['description'] == 'Ajax Magnetkontakt'
    assert value['missing_locations'] == 1


@pytest.mark.parametrize('change', ['provider', 'confirmation', 'row', 'zero', 'nan', 'empty'])
def test_unconfirmed_or_invalid_analysis_never_exposes_a_partial_list(change):
    p = project()
    a = p['analysis']
    if change == 'provider':
        a['provider'] = 'ollama'
    elif change == 'confirmation':
        a['user_confirmed'] = False
    elif change == 'row':
        a['components'][1]['user_confirmed'] = False
    elif change in ('zero', 'nan'):
        a['components'][1]['quantity'] = '0' if change == 'zero' else 'NaN'
    else:
        a['components'] = []
    value = overview(p)
    assert not value['accepted']
    assert not value['groups'] and not value['fields']


def test_pending_intake_never_leaks_unconfirmed_edits_or_prices(ui):
    client, store = ui
    store.put_record('test', 'project_intake', 'one', dict(status='editing', review_required=True,
        fields=dict(customer_name='UNBESTÄTIGTER KUNDE'), components=[dict(description='UNBESTÄTIGTES GERÄT')]))
    store.put_record('test', 'quote', 'one', dict(rows=[dict(price='GEHEIMER PREIS')]))
    before = {kind: store.record('test', kind, 'one') for kind in ('project', 'project_intake', 'quote')}
    response = client.get('/projects/one/montage', headers={'X-Ingress-Path': '/ingress/test'})
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-store'
    for text in ('Neuere Aufnahme noch nicht übernommen', 'Bestätigter Kunde', '2 × Bewegungsmelder',
                 'Einbauort offen', 'Welche Farbe?', '/ingress/test/projects/one/intake'):
        assert text in response.text
    assert 'UNBESTÄTIGT' not in response.text and 'GEHEIMER PREIS' not in response.text
    assert before == {kind: store.record('test', kind, 'one') for kind in before}
    assert client.post('/projects/one/montage').status_code in (400, 405)


def test_empty_state_and_account_isolation(ui, monkeypatch):
    client, store = ui
    p = project()
    p['analysis'] = {}
    store.put_record('test', 'project', 'one', p)
    response = client.get('/projects/one/montage')
    assert 'Noch keine bestätigte Komponentenliste' in response.text
    assert 'montage-print"' not in response.text
    monkeypatch.setenv('BILLOMAT_ID', 'other')
    assert client.get('/projects/one/montage').status_code == 404


def test_all_free_text_is_escaped_and_no_external_requests(ui, monkeypatch):
    client, store = ui
    p = project()
    payload = '<script>alert(1)</script>'
    p['title'] = payload
    p['analysis']['components'][0].update(source_description=payload, location=payload, evidence=payload)
    p['analysis']['questions'] = [payload]
    p['intake_fields']['notes'] = payload
    store.put_record('test', 'project', 'one', p)
    import requests
    monkeypatch.setattr(requests.sessions.Session, 'request', lambda *a, **k: pytest.fail('No network on montage GET'))
    response = client.get('/projects/one/montage')
    assert response.status_code == 200
    assert payload not in response.text
    assert response.text.count('&lt;script&gt;alert(1)&lt;/script&gt;') >= 6


def test_change_while_rendering_returns_conflict(ui, monkeypatch):
    client, store = ui
    record = type(store).record
    calls = []
    def changing(self, account, kind, key):
        result = record(self, account, kind, key)
        if kind == 'project':
            calls.append(kind)
            if len(calls) > 1:
                result = deepcopy(result)
                result['title'] = 'Changed'
        return result
    monkeypatch.setattr(type(store), 'record', changing)
    assert client.get('/projects/one/montage').status_code == 409


def test_navigation_exposes_montage_without_marking_order_as_confirmed(ui):
    client, store = ui
    assert '/projects/one/montage' in client.get('/projects/one').text
    assert '/projects/one/montage' in client.get('/projects/one/operations').text
    assert store.record('test', 'project', 'one').get('offer_id') == ''
