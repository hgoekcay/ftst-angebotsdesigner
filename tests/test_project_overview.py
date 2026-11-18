import pytest
import app as module
from test_persistence import isolated_storage


def test_overview_empty_read_only_and_no_cache(isolated_storage, monkeypatch):
    monkeypatch.setenv('BILLOMAT_ID', 'overview')
    response = module.app.test_client().get('/projects')
    assert response.status_code == 200
    assert 'Noch keine Projekte vorhanden' in response.text
    assert response.headers['Cache-Control'] == 'no-store'
    assert module.offer_store().records('overview', 'project') == {}


def test_saved_evidence_links_and_account_isolation(isolated_storage, monkeypatch):
    monkeypatch.setenv('BILLOMAT_ID', 'overview')
    store = module.offer_store()
    p = dict(title='<script>unsafe</script>', notes='', analysis={}, offer_id='')
    store.put_record('overview', 'project', 'one', p)
    store.put_record('other', 'project', 'secret', dict(title='PRIVATE'))
    store.put_record('other', 'quote_transfer', 'one', dict(status='created'))
    store.put_record('overview', 'project_intake', 'one', dict(status='editing', questions=['Variant?']))
    before = {kind: store.records('overview', kind) for kind in ('project', 'project_intake', 'quote', 'quote_transfer')}
    monkeypatch.setattr(module.BillomatClient, 'get_full_offer', lambda *a: pytest.fail('No external lookup'))
    response = module.app.test_client().get('/projects', headers={'X-Ingress-Path': '/ingress/test'})
    assert response.status_code == 200
    assert '&lt;script&gt;unsafe&lt;/script&gt;' in response.text
    assert 'PRIVATE' not in response.text and 'Entwurf angelegt' not in response.text
    assert 'Offene Rückfragen: 1' in response.text
    assert '/ingress/test/projects/one/intake' in response.text
    assert '/ingress/test/projects/one/montage' in response.text
    assert 'Neuere Aufnahme noch nicht übernommen' in response.text
    assert before == {kind: store.records('overview', kind) for kind in before}


@pytest.mark.parametrize('status', ['sending', 'unknown', 'review', 'created'])
def test_existing_transfer_never_offers_new_creation(isolated_storage, monkeypatch, status):
    monkeypatch.setenv('BILLOMAT_ID', 'overview')
    store = module.offer_store()
    store.put_record('overview', 'project', 'one', dict(title='Test', notes='', analysis={}, offer_id='123'))
    store.put_record('overview', 'quote_transfer', 'one', dict(status=status))
    response = module.app.test_client().get('/projects')
    assert '/projects/one/quote/transfer' in response.text
    assert 'keine Beauftragung' in response.text
    assert 'Bestätigte Komponenten fehlen' in response.text


def test_reviewed_components_and_pending_edit_are_distinguished(isolated_storage, monkeypatch):
    monkeypatch.setenv('BILLOMAT_ID', 'overview')
    store = module.offer_store()
    p = dict(title='Test', notes='', analysis=dict(provider='technician-reviewed', user_confirmed=True,
        components=[dict(description='Camera', quantity=2, user_confirmed=True)]), offer_id='')
    store.put_record('overview', 'project', 'one', p)
    store.put_record('overview', 'project_intake', 'one', dict(status='editing', review_required=True))
    client = module.app.test_client()
    for _ in range(2):
        response = client.get('/projects')
        assert response.status_code == 200
        assert 'Bestätigte Komponenten vorhanden' in response.text
        assert 'Neuere Aufnahme noch nicht übernommen' in response.text
        assert '1 Position(en) ohne Einbauort' in response.text
    assert store.record('overview', 'project', 'one') == p


def test_overview_retains_ingress_security(isolated_storage, monkeypatch):
    monkeypatch.setenv('FTST_REQUIRE_INGRESS', '1')
    assert module.app.test_client().get('/projects').status_code == 403
