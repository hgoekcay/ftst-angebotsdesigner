"""Flask integration checks with isolated SQLite and a fake Billomat only."""
import html
import re
from copy import deepcopy
from io import BytesIO
from unittest.mock import Mock

import pytest
from pypdf import PdfReader

import app as module
import quote_transfer
from test_baseline import raw
from test_persistence import isolated_storage
from test_quote_drafts import catalog, draft
from test_quote_transfer import transfer

PATH = '/projects/project-1/quote/transfer'
INGRESS = '/api/hassio_ingress/test-transfer'
HEADERS = {'X-Ingress-Path': INGRESS}


def hidden(response, name):
    match = re.search(r'<input[^>]*name="' + name + r'"[^>]*value="([^"]*)"', response.text)
    assert match, f'Missing field {name}'
    return html.unescape(match.group(1))


@pytest.fixture
def routes(transfer, isolated_storage, monkeypatch):
    monkeypatch.setenv('BILLOMAT_ID', 'one')
    monkeypatch.setenv('BILLOMAT_API_KEY', 'test-only-never-send')
    monkeypatch.setenv('FTST_REQUIRE_INGRESS', '0')
    store, project, quote, fake = transfer
    api = Mock(return_value=fake)
    monkeypatch.setattr(quote_transfer, 'api', api)
    return module.app.test_client(), store, project, quote, fake, api


def preview(routes):
    client, store, _, _, _, _ = routes
    csrf = hidden(client.get(PATH, headers=HEADERS), 'csrf')
    result = client.post(PATH, headers=HEADERS, data={'csrf': csrf, 'action': 'prepare'})
    assert result.status_code == 302
    assert result.headers['Location'] == INGRESS + PATH
    page = client.get(PATH, headers=HEADERS)
    assert page.status_code == 200 and 'Übernahme prüfen' in page.text
    return csrf, hidden(page, 'review'), page


@pytest.mark.parametrize('action', ['prepare', 'confirm', 'reconcile'])
@pytest.mark.parametrize('csrf', [None, '', '-', 'forged', 'ungültig'])
def test_uninitialized_or_forged_csrf_never_reaches_api(routes, action, csrf):
    client, store, _, _, fake, api = routes
    values = {'action': action, 'confirm': 'yes', 'review': 'forged-review'}
    if csrf is not None:
        values['csrf'] = csrf
    result = client.post(PATH, headers=HEADERS, data=values)
    assert result.status_code == 400
    api.assert_not_called()
    assert fake.posts == [] and fake.searches == [] and fake.reads == []
    assert store.record('one', 'quote_transfer', 'project-1') is None
    assert store.record('one', 'quote_transfer_review', 'project-1') is None


def test_existing_session_rejects_another_csrf_and_preserves_review(routes):
    client, store, _, _, fake, api = routes
    _, token, _ = preview(routes)
    before = store.record('one', 'quote_transfer_review', 'project-1')
    api.reset_mock()
    result = client.post(PATH, data={'csrf': '-', 'action': 'confirm', 'confirm': 'yes', 'review': token})
    assert result.status_code == 400
    api.assert_not_called()
    assert store.record('one', 'quote_transfer_review', 'project-1') == before
    assert fake.posts == []


@pytest.mark.parametrize('confirmation', [None, '', 'true', '1', 'no'])
def test_create_requires_explicit_checkbox_without_api_access(routes, confirmation):
    client, store, _, _, fake, api = routes
    csrf, token, _ = preview(routes)
    api.reset_mock()
    values = {'csrf': csrf, 'action': 'confirm', 'review': token}
    if confirmation is not None:
        values['confirm'] = confirmation
    result = client.post(PATH, data=values, headers=HEADERS)
    assert result.status_code == 409
    assert 'ausdrücklich bestätigen' in result.text
    api.assert_not_called()
    assert fake.posts == []
    assert store.record('one', 'quote_transfer', 'project-1') is None


def test_get_pages_are_read_only_no_store_and_keep_ingress_links(routes):
    client, store, _, _, fake, api = routes
    first = client.get(PATH, headers=HEADERS)
    assert first.status_code == 200 and first.headers['Cache-Control'] == 'no-store'
    assert INGRESS + '/projects/project-1/quote' in first.text
    assert 'href="/projects/' not in first.text
    api.assert_not_called()
    _, _, reviewed = preview(routes)
    assert reviewed.headers['Cache-Control'] == 'no-store'
    assert 'type="checkbox" name="confirm" value="yes" required' in reviewed.text
    assert fake.posts == []
    store.put_record('one', 'quote_transfer', 'project-1', {
        'status': 'created', 'offer_id': '501', 'offer_number': '', 'problems': [],
    })
    api.reset_mock()
    completed = client.get(PATH, headers=HEADERS)
    assert completed.status_code == 200 and completed.headers['Cache-Control'] == 'no-store'
    assert INGRESS + '/offer/501' in completed.text
    assert 'Noch nicht vergeben (Entwurf)' in completed.text
    assert 'name="action" value="confirm"' not in completed.text
    api.assert_not_called()


@pytest.mark.parametrize('change', ['expired', 'project', 'draft'])
def test_stale_review_hides_confirmation_and_blocks_old_form(routes, change):
    client, store, project, quote, fake, api = routes
    csrf, token, _ = preview(routes)
    if change == 'expired':
        review = store.record('one', 'quote_transfer_review', 'project-1')
        store.put_record('one', 'quote_transfer_review', 'project-1', dict(review, prepared_at=0))
    elif change == 'project':
        store.put_record('one', 'project', 'project-1', dict(project, notes='Anforderungen geändert'))
    else:
        store.put_record('one', 'quote', 'project-1', dict(quote, revision='new-revision'))
    api.reset_mock()
    page = client.get(PATH, headers=HEADERS)
    assert page.status_code == 200 and page.headers['Cache-Control'] == 'no-store'
    assert 'name="action" value="confirm"' not in page.text
    assert 'name="action" value="prepare"' in page.text
    api.assert_not_called()
    result = client.post(PATH, data={'csrf': csrf, 'action': 'confirm', 'confirm': 'yes', 'review': token}, headers=HEADERS)
    assert result.status_code == 409 and 'role="alert"' in result.text
    assert fake.posts == []
    assert store.record('one', 'quote_transfer', 'project-1') is None


def test_confirmed_route_creates_one_draft_and_repeated_form_does_not_repost(routes):
    client, store, _, _, fake, _ = routes
    csrf, token, _ = preview(routes)
    values = {'csrf': csrf, 'action': 'confirm', 'confirm': 'yes', 'review': token}
    result = client.post(PATH, data=values, headers=HEADERS)
    assert result.status_code == 302 and result.headers['Location'] == INGRESS + PATH
    saved = store.record('one', 'quote_transfer', 'project-1')
    assert saved['status'] == 'created' and saved['offer_id'] == '501'
    assert len(fake.posts) == 1
    assert client.post(PATH, data=values, headers=HEADERS).status_code == 302
    assert len(fake.posts) == 1


@pytest.mark.parametrize('status,expected', [('DRAFT', True), ('OPEN', False), ('WON', False), (None, False)])
def test_billomat_status_controls_normalized_draft_flag(raw, status, expected):
    source = dict(deepcopy(raw), status=status)
    value = module.normalize(source)
    assert value['is_draft'] is expected
    assert 'is_draft' not in source


def test_pdf_route_keeps_billomat_draft_visibly_unreleased(routes, raw, monkeypatch):
    client, _, _, _, _, _ = routes
    source = dict(deepcopy(raw), status='DRAFT', offer_number='')
    monkeypatch.setattr(module.BillomatClient, 'get_full_offer', lambda self, oid: deepcopy(source))
    response = client.get('/offer/42/pdf', headers=HEADERS)
    assert response.status_code == 200 and response.mimetype == 'application/pdf'
    text = '\n'.join(page.extract_text() for page in PdfReader(BytesIO(response.data)).pages)
    assert 'ENTWURF / NICHT FREIGEGEBEN' in text
    assert 'Keine Angebotsfreigabe, kein Kundenversand.' in text
