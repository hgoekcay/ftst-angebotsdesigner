from copy import deepcopy

import pytest

import app as module
from project_intake import fingerprint as intake_fingerprint
from project_workflow import progress
from quote_drafts import fingerprint
from test_persistence import isolated_storage
from test_quote_drafts import catalog, draft


def project():
    return dict(title='Testprojekt', notes='', analysis={}, offer_id='')


def test_empty_project_starts_with_intake_and_never_claims_completion():
    state = progress(project())
    assert state['next_index'] == 0
    assert state['steps'][0]['state'] == 'Offen'
    assert state['steps'][3]['path'] == 'quote'


def test_intake_edits_are_not_shown_as_confirmed():
    p = project()
    p['analysis'] = {'user_confirmed': True, 'components': [{'description': 'BM'}]}
    intake = dict(status='editing', review_required=True, components=[{'description': 'MK'}], questions=['Welche Variante?'])
    state = progress(p, intake)
    assert state['next_index'] == 0
    assert state['steps'][0]['state'] != 'Angaben übernommen'
    assert state['questions'] == ['Welche Variante?']


def test_accepted_intake_with_project_link_change_is_described_neutrally():
    p = project()
    p['analysis'] = {'user_confirmed': True, 'components': [{'description': 'BM'}]}
    intake = dict(status='applied', review_required=False, source_changed=False, source_project=intake_fingerprint(p))
    p['offer_id'] = '123'
    state = progress(p, intake)
    assert state['steps'][0]['state'] == 'Angaben übernommen'
    assert 'danach geändert' in state['steps'][0]['text']
    assert state['steps'][3]['state'] == 'Angebot verknüpft'
    assert state['steps'][3]['offer_id'] == '123'


@pytest.mark.parametrize('change', ['valid', 'stale', 'not_reviewed', 'bad_catalog', 'no_revision'])
def test_quote_readiness_respects_saved_revision_source_and_commercial_checks(draft, change):
    p = project()
    p['notes'] = 'Aufnahme'
    draft.update(revision='v1', source=fingerprint(p), reviewed=True)
    if change == 'stale':
        p['notes'] = 'Neue Aufnahme'
    elif change == 'not_reviewed':
        draft['reviewed'] = False
    elif change == 'bad_catalog':
        draft['catalog']['settings'] = None
    elif change == 'no_revision':
        draft['revision'] = ''
    state = progress(p, draft=draft)
    assert (state['steps'][1]['state'] == 'Lokal geprüft') == (change == 'valid')
    assert (state['next_index'] == 3) == (change == 'valid')


@pytest.mark.parametrize('status', ['sending', 'unknown', 'review', 'created'])
def test_existing_transfer_always_takes_priority_and_cannot_offer_new_creation(draft, status):
    p = project()
    draft.update(revision='v1', source=fingerprint(p), reviewed=True)
    transfer = dict(status=status, draft=deepcopy(draft), project=deepcopy(p), offer_id='123')
    p['offer_id'] = '123'
    state = progress(p, draft=draft, transfer=transfer)
    assert state['next_index'] == 3
    assert state['steps'][3]['path'] == 'quote/transfer'
    assert 'Übergabe' not in state['steps'][3]['action']
    assert state['steps'][3]['state'] == ('Entwurf angelegt' if status == 'created' else 'Status prüfen')


def test_created_transfer_does_not_claim_later_local_edits_were_transferred(draft):
    p = project()
    draft.update(revision='v1', source=fingerprint(p), reviewed=True)
    transfer = dict(status='created', draft=deepcopy(draft), project=deepcopy(p))
    p['notes'] = 'Neue Komponenten'
    state = progress(p, draft=draft, transfer=transfer)
    assert state['steps'][3]['state'] == 'Früherer Stand übertragen'
    assert 'kein zweites' in state['steps'][3]['text']


def test_saved_intake_edits_take_priority_over_previous_ready_quote(draft):
    p = project()
    draft.update(revision='v1', source=fingerprint(p), reviewed=True)
    state = progress(p, intake=dict(status='editing', review_required=True), draft=draft)
    assert state['next_index'] == 0


def test_workflow_get_is_read_only_account_scoped_and_escaped(isolated_storage, monkeypatch, draft):
    monkeypatch.setenv('BILLOMAT_ID', 'test')
    monkeypatch.setenv('FTST_REQUIRE_INGRESS', '0')
    store = module.offer_store()
    p = project()
    store.put_record('test', 'project', 'one', p)
    store.put_record('other', 'quote_transfer', 'one', dict(status='created'))
    store.put_record('test', 'project_intake', 'one', dict(status='editing', questions=['<script>bad()</script>']))
    before = {kind: store.record('test', kind, 'one') for kind in ('project', 'project_intake', 'quote', 'quote_transfer')}
    monkeypatch.setattr(module.BillomatClient, 'draft_catalog', lambda *a: pytest.fail('GET must not call Billomat'))
    client = module.app.test_client()
    response = client.get('/projects/one', headers={'X-Ingress-Path': '/ingress/test'})
    assert response.status_code == 200
    assert 'Ihr Weg zum Angebot' in response.text
    assert '/ingress/test/projects/one/intake' in response.text
    assert '&lt;script&gt;bad()&lt;/script&gt;' in response.text
    assert 'Entwurf angelegt' not in response.text
    assert before == {kind: store.record('test', kind, 'one') for kind in before}
    assert client.get('/projects/one/pdf').status_code == 200
