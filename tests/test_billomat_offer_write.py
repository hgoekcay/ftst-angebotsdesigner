"""Synthetic transport tests: never contact Billomat."""
import json

import pytest
import requests

from billomat_client import BillomatClient, OfferReadError, OfferWriteUncertain


class Response:
    def __init__(self, data, status=200):
        self.status_code = status
        self.content = data if isinstance(data, bytes) else json.dumps(data).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, size):
        for offset in range(0, len(self.content), size):
            yield self.content[offset:offset + size]


@pytest.fixture
def wire(monkeypatch):
    replies, calls, sessions = [], [], []
    class Session:
        def __enter__(self):
            sessions.append(self)
            return self

        def __exit__(self, *args):
            pass

        def request(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            reply = replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply
    monkeypatch.setattr(requests, 'Session', Session)
    return replies, calls, sessions


@pytest.fixture
def payload():
    return dict(client_id='3', label='FTST-' + 'a' * 32, title='Testangebot',
                currency_code='EUR', net_gross='NET', reduction='0%', **{
        'offer-items': {'offer-item': [dict(article_id='7', title='Testkamera',
            unit='Stück', quantity='2', unit_price='90.00', tax_rate='19', reduction='10%')]}})


def test_create_one_draft_request_and_empty_number(wire, payload):
    replies, calls, sessions = wire
    replies.append(Response({'offer': {'id': '12', 'status': 'DRAFT', 'offer_number': ''}}, 201))
    result = BillomatClient('test', 'not-a-secret').create_offer_draft(payload)
    assert result['id'] == '12' and result['offer_number'] == ''
    assert len(calls) == 1
    method, url, options = calls[0]
    assert method == 'POST' and url == 'https://test.billomat.net/api/offers'
    assert options['json'] == {'offer': payload}
    assert options['allow_redirects'] is False and options['verify'] is True
    assert options['timeout'] == (5, 30) and sessions[0].trust_env is False
    assert 'status' not in options['json']['offer']


@pytest.mark.parametrize('response', [
    Response(b'secret-body', 302), Response(b'secret-body', 400),
    Response(b'secret-body', 500), Response(b'not json', 201),
    Response({'offer': {}}, 201), Response({'offer': {'id': '12', 'status': 'OPEN'}}, 201),
    requests.Timeout('secret-credential'), Response(b'x' * (2 * 1024 * 1024 + 1), 201),
])
def test_uncertain_write_never_retried_or_leaks_body(wire, payload, response):
    replies, calls, _ = wire
    replies.append(response)
    with pytest.raises(OfferWriteUncertain) as failure:
        BillomatClient('test', 'not-a-secret').create_offer_draft(payload)
    assert len(calls) == 1
    assert 'secret' not in str(failure.value)


def test_sparse_response_requires_later_verification(wire, payload):
    wire[0].append(Response({'offer': {'id': '12'}}, 201))
    assert BillomatClient('test', 'key').create_offer_draft(payload) == {'id': '12'}


@pytest.mark.parametrize('field,value', [('status', 'OPEN'), ('net_gross', 'GROSS'),
    ('currency_code', ''), ('client_id', '../3'), ('offer-items', {'offer-item': []})])
def test_invalid_payload_makes_no_request(wire, payload, field, value):
    payload[field] = value
    with pytest.raises(ValueError):
        BillomatClient('test', 'key').create_offer_draft(payload)
    assert not wire[1]


def test_verification_reads_full_offer_and_items(wire):
    replies, calls, _ = wire
    replies.extend([Response({'offer': {'id': '12', 'status': 'DRAFT', 'total_net': '162'}}),
        Response({'offer-items': {'@total': '1', 'offer-item': {'id': '8', 'offer_id': '12'}}})])
    result = BillomatClient('test', 'key').get_offer_for_verification('12')
    assert result['total_net'] == '162' and result['items'][0]['id'] == '8'
    assert all(method == 'GET' for method, *_ in calls)


@pytest.mark.parametrize('data', [
    {'offer-items': {'@total': '2', 'offer-item': []}},
    {'offer-items': {'@total': '1', 'offer-item': {'id': '8', 'offer_id': '999'}}},
    {'unexpected': []},
])
def test_verification_rejects_incomplete_or_foreign_items(wire, data):
    wire[0].extend([Response({'offer': {'id': '12'}}), Response(data)])
    with pytest.raises(OfferReadError):
        BillomatClient('test', 'key').get_offer_for_verification('12')


def test_reconcile_exact_reference_all_status_and_no_write(wire):
    marker = 'FTST-' + 'a' * 32
    wire[0].append(Response({'offers': {'@total': 3, 'offer': [
        {'id': '12', 'client_id': '3', 'label': marker, 'status': 'OPEN'},
        {'id': '13', 'client_id': '3', 'label': marker + '-other'},
        {'id': '14', 'client_id': '4', 'label': marker}]}}))
    result = BillomatClient('test', 'key').find_offers_by_reference(marker, '3')
    assert [row['id'] for row in result] == ['12']
    method, _, options = wire[1][0]
    assert method == 'GET' and 'status' not in options['params']


def test_status_filter_is_optional_and_validated(monkeypatch):
    client = BillomatClient('test', 'key')
    seen = []
    monkeypatch.setattr(client, '_get', lambda path, params: (seen.append(params) or {'offers': []}))
    client.list_offers()
    client.list_offers(status='WON')
    assert 'status' not in seen[0] and seen[1]['status'] == 'WON'
    with pytest.raises(ValueError):
        client.list_offers(status='UNEXPECTED')
    assert len(seen) == 2


def test_invalid_host_and_ids_never_contact_network(wire, payload):
    with pytest.raises(ValueError):
        BillomatClient('test.example/other', 'key').create_offer_draft(payload)
    with pytest.raises(ValueError):
        BillomatClient('test', 'key').get_offer_for_verification('../12')
    assert not wire[1]


def test_reconcile_reads_next_page_and_rejects_duplicate_ids(wire):
    marker = 'FTST-' + 'a' * 32
    batch = [{'id': str(n), 'client_id': '3', 'label': 'other'} for n in range(1, 101)]
    wire[0].extend([Response({'offers': {'offer': batch}}),
                    Response({'offers': {'offer': [{'id': '1', 'label': marker, 'client_id': '3'}]}})])
    with pytest.raises(OfferReadError):
        BillomatClient('test', 'key').find_offers_by_reference(marker, '3')
    assert [c[2]['params']['page'] for c in wire[1]] == [1, 2]


def test_malformed_collection_is_not_reported_empty(wire):
    wire[0].append(Response({'offers': {'error': 'unexpected'}}))
    with pytest.raises(OfferReadError):
        BillomatClient('test', 'key').find_offers_by_reference('FTST-test', '3')


def test_payload_preflight_is_pure_and_detached(wire, payload):
    body = BillomatClient.validate_offer_payload(payload)
    assert body == {'offer': payload}
    payload['offer-items']['offer-item'][0]['title'] = 'Changed after validation'
    assert body['offer']['offer-items']['offer-item'][0]['title'] == 'Testkamera'
    assert not wire[1]


@pytest.mark.parametrize('problem', ['oversized', 'nan', 'unknown_field'])
def test_preflight_and_create_apply_same_rejection_before_network(wire, payload, problem):
    if problem == 'oversized':
        payload['note'] = 'x' * (256 * 1024)
    elif problem == 'nan':
        payload['offer-items']['offer-item'][0]['quantity'] = float('nan')
    else:
        payload['complete'] = True
    with pytest.raises(ValueError) as preflight:
        BillomatClient.validate_offer_payload(payload)
    with pytest.raises(ValueError) as creation:
        BillomatClient('test', 'key').create_offer_draft(payload)
    assert str(creation.value) == str(preflight.value)
    assert not wire[1]
