"""Independent transfer safety checks: fake Billomat only, never external writes."""
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
import threading

import pytest
from werkzeug.exceptions import HTTPException

from billomat_client import OfferWriteUncertain
from quote_drafts import fingerprint
from storage import OfferStore, RecordConflict, StorageError
from test_quote_drafts import catalog, draft


class FakeBillomat:
    def __init__(self, catalog):
        self.catalog = deepcopy(catalog)
        self.posts = []
        self.searches = []
        self.reads = []
        self.offers = {}
        self.on_catalog = None
        self.on_search = None
        self.on_create = None
        self.on_verify = None
        self.search_result = None

    def draft_catalog(self):
        if self.on_catalog:
            self.on_catalog()
        return deepcopy(self.catalog)

    def find_offers_by_reference(self, marker, client_id):
        self.searches.append((marker, str(client_id)))
        if self.on_search:
            self.on_search()
        if self.search_result is not None:
            return deepcopy(self.search_result)
        return [deepcopy(offer) for offer in self.offers.values()
                if offer['label'] == marker and offer['client_id'] == str(client_id)]

    def create_offer_draft(self, payload):
        self.posts.append(deepcopy(payload))
        offer_id = str(500 + len(self.posts))
        discount = Decimal(str(payload.get('reduction', '0')).rstrip('%'))
        net = tax = Decimal('0')
        items = []
        for index, original in enumerate(payload['offer-items']['offer-item'], 1):
            row = deepcopy(original)
            line_discount = Decimal(str(row.get('reduction', '0')).rstrip('%'))
            amount = (Decimal(str(row['quantity'])) * Decimal(str(row['unit_price']))
                      * (1 - line_discount / 100) * (1 - discount / 100)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
            row_tax = (amount * Decimal(str(row['tax_rate'])) / 100).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
            row.update(id=str(1000 + index), offer_id=offer_id, position=str(index),
                       total_net=str(amount), total_gross=str(amount + row_tax))
            items.append(row)
            net += amount
            tax += row_tax
        offer = dict(deepcopy(payload), id=offer_id, status='DRAFT', items=items,
                     total_net=str(net), total_gross=str(net + tax),
                     taxes={'tax': [{'amount': str(tax)}]})
        self.offers[offer_id] = offer
        if self.on_create:
            self.on_create(offer)
        return {'id': offer_id, 'status': 'DRAFT'}

    def get_offer_for_verification(self, offer_id):
        self.reads.append(str(offer_id))
        value = deepcopy(self.offers[str(offer_id)])
        if self.on_verify:
            self.on_verify(value)
        return value


@pytest.fixture
def transfer(tmp_path, draft):
    store = OfferStore(tmp_path)
    project = dict(title='Brandwarnung Büro', notes='1 Hub + 11 FireProtect')
    quote = deepcopy(draft)
    quote.update(revision='reviewed-v1', source=fingerprint(project), reviewed=True,
                 catalog_at='2026-09-20T10:00:00+00:00')
    store.put_record('one', 'project', 'project-1', project)
    store.put_record('one', 'quote', 'project-1', quote)
    return store, project, quote, FakeBillomat(quote['catalog'])


@pytest.fixture
def implementation():
    import quote_transfer
    return quote_transfer


def prepare(module, fixture, identity='one'):
    store, _, _, api = fixture
    return module.prepare(store, identity, 'project-1', api, lambda offer: 'Rauchmeldeanlage')


def submit(module, fixture, review, identity='one'):
    store, _, _, api = fixture
    return module.submit(store, identity, 'project-1', review['token'], api)


BLOCKED = (ValueError, RuntimeError, HTTPException)


def test_prepare_is_read_only_and_submit_creates_one_verified_draft(implementation, transfer):
    store, _, _, api = transfer
    review = prepare(implementation, transfer)
    assert api.posts == []
    result = submit(implementation, transfer, review)
    assert result['status'] == 'created'
    assert len(api.posts) == 1 and api.reads
    payload = api.posts[0]
    assert payload['client_id'] == '3'
    assert payload['net_gross'] == 'NET' and payload['currency_code'] == 'EUR'
    assert payload['reduction'] == '0%'
    rows = payload['offer-items']['offer-item']
    assert len(rows) == 2
    assert [Decimal(row['quantity']) for row in rows] == [Decimal('1'), Decimal('11')]
    assert [Decimal(row['unit_price']) for row in rows] == [Decimal('80'), Decimal('10')]
    assert all(row['reduction'] == '10%' for row in rows)
    assert api.offers[api.reads[-1]]['total_gross'] == '203.49'
    assert all('status' not in posted for posted in api.posts)


@pytest.mark.parametrize('problem', ['unreviewed', 'revision', 'fingerprint', 'incomplete'])
def test_prepare_refuses_unreviewed_stale_or_incomplete_quote(implementation, transfer, problem):
    store, project, quote, api = transfer
    if problem == 'unreviewed':
        quote['reviewed'] = False
    elif problem == 'revision':
        quote['revision'] = ''
    elif problem == 'fingerprint':
        quote['source'] = 'unrelated-project'
    else:
        quote['rows'][1]['article_id'] = ''
    store.put_record('one', 'quote', 'project-1', quote)
    with pytest.raises(BLOCKED):
        prepare(implementation, transfer)
    assert api.posts == []


def test_changed_billomat_prices_block_transfer(implementation, transfer):
    _, _, _, api = transfer
    review = prepare(implementation, transfer)
    api.catalog['articles'][0]['sales_price2'] = '800'
    with pytest.raises(BLOCKED):
        submit(implementation, transfer, review)
    assert api.posts == []


def test_review_token_cannot_authorize_new_revision(implementation, transfer):
    store, _, quote, api = transfer
    review = prepare(implementation, transfer)
    store.put_record('one', 'quote', 'project-1', dict(quote, revision='reviewed-v2'))
    with pytest.raises(BLOCKED):
        submit(implementation, transfer, review)
    assert api.posts == []


def test_project_edit_during_initial_catalog_read_blocks_review(implementation, transfer):
    store, project, _, api = transfer
    api.on_catalog = lambda: store.put_record('one', 'project', 'project-1', dict(project, notes='12 Melder'))
    with pytest.raises(BLOCKED):
        prepare(implementation, transfer)
    assert api.posts == []


def test_revision_edit_during_submit_catalog_read_blocks_claim(implementation, transfer):
    store, _, quote, api = transfer
    review = prepare(implementation, transfer)
    api.on_catalog = lambda: store.put_record('one', 'quote', 'project-1', dict(quote, revision='v2'))
    with pytest.raises(BLOCKED):
        submit(implementation, transfer, review)
    assert api.posts == []


def test_project_edit_during_final_search_blocks_claim(implementation, transfer):
    store, project, _, api = transfer
    review = prepare(implementation, transfer)
    api.on_search = lambda: store.put_record('one', 'project', 'project-1', dict(project, notes='Neue Anforderungen'))
    with pytest.raises(BLOCKED):
        submit(implementation, transfer, review)
    assert api.posts == []


def test_account_isolation_before_prepare_and_submit(implementation, transfer):
    _, _, _, api = transfer
    with pytest.raises(BLOCKED):
        prepare(implementation, transfer, identity='two')
    review = prepare(implementation, transfer)
    with pytest.raises(BLOCKED):
        submit(implementation, transfer, review, identity='two')
    assert api.posts == []


def attempt(call):
    try:
        return call()
    except BLOCKED:
        return None


def test_repeated_submit_and_new_revision_never_post_another_offer(implementation, transfer):
    store, _, quote, api = transfer
    review = prepare(implementation, transfer)
    assert submit(implementation, transfer, review)['status'] == 'created'
    attempt(lambda: submit(implementation, transfer, review))
    store.put_record('one', 'quote', 'project-1', dict(quote, revision='v2'))
    second_review = attempt(lambda: prepare(implementation, transfer))
    if second_review and second_review.get('token'):
        attempt(lambda: submit(implementation, transfer, second_review))
    assert len(api.posts) == 1


def test_concurrent_double_click_has_one_post(implementation, transfer):
    _, _, _, api = transfer
    review = prepare(implementation, transfer)
    entered, release = threading.Event(), threading.Event()
    results, failures = [], []

    def pause_after_remote_creation(offer):
        entered.set()
        assert release.wait(timeout=5)

    api.on_create = pause_after_remote_creation

    def first():
        try:
            results.append(submit(implementation, transfer, review))
        except Exception as exc:
            failures.append(exc)

    worker = threading.Thread(target=first, daemon=True)
    worker.start()
    try:
        assert entered.wait(timeout=5), 'First request should reach the remote write'
        attempt(lambda: submit(implementation, transfer, review))
        assert len(api.posts) == 1
    finally:
        release.set()
        worker.join(timeout=5)
    assert not worker.is_alive() and failures == []
    assert results[0]['status'] == 'created'


def uncertain_create(offer):
    raise OfferWriteUncertain('Connection ended after remote creation')


def test_timeout_is_never_reposted_and_read_only_recovery_reuses_marker(implementation, transfer):
    store, _, _, api = transfer
    review = prepare(implementation, transfer)
    api.on_create = uncertain_create
    result = attempt(lambda: submit(implementation, transfer, review))
    assert result is None or result['status'] != 'created'
    attempt(lambda: submit(implementation, transfer, review))
    assert len(api.posts) == 1
    recovered = implementation.reconcile(store, 'one', 'project-1', api)
    assert recovered['status'] == 'created'
    assert len(api.posts) == 1
    assert api.searches[-1] == (api.posts[0]['label'], '3')


@pytest.mark.parametrize('count', [0, 2])
def test_missing_or_multiple_recovery_matches_keep_writes_blocked(implementation, transfer, count):
    store, _, _, api = transfer
    review = prepare(implementation, transfer)
    api.on_create = uncertain_create
    attempt(lambda: submit(implementation, transfer, review))
    offer = next(iter(api.offers.values()))
    api.search_result = [dict(offer, id=str(600 + index)) for index in range(count)]
    result = attempt(lambda: implementation.reconcile(store, 'one', 'project-1', api))
    assert result is None or result['status'] != 'created'
    attempt(lambda: submit(implementation, transfer, review))
    assert len(api.posts) == 1


@pytest.mark.parametrize('field', ['client', 'status', 'currency', 'net', 'gross',
                                  'quantity', 'price', 'article', 'missing_item',
                                  'tax', 'unit', 'optional', 'position', 'duplicate_position',
                                  'line_absolute_reduction', 'offer_reduction',
                                  'item_title', 'item_description'])
def test_readback_mismatch_never_marks_offer_created(implementation, transfer, field):
    _, _, _, api = transfer
    review = prepare(implementation, transfer)

    def change(offer):
        if field == 'client':
            offer['client_id'] = '99'
        elif field == 'status':
            offer['status'] = 'OPEN'
        elif field == 'currency':
            offer['currency_code'] = 'USD'
        elif field == 'net':
            offer['total_net'] = '9999'
        elif field == 'gross':
            offer['total_gross'] = '9999'
        elif field == 'quantity':
            offer['items'][0]['quantity'] = '9'
        elif field == 'price':
            offer['items'][0]['unit_price'] = '0'
        elif field == 'article':
            offer['items'][0]['article_id'] = '999'
        elif field == 'missing_item':
            offer['items'].pop()
        elif field == 'tax':
            offer['items'][0]['tax_rate'] = '7'
        elif field == 'unit':
            offer['items'][0]['unit'] = 'Stunden'
        elif field == 'optional':
            offer['items'][0]['optional'] = '1'
        elif field == 'position':
            offer['items'][0]['position'] = '0'
        elif field == 'duplicate_position':
            offer['items'][1]['position'] = '1'
        elif field == 'line_absolute_reduction':
            offer['items'][0]['reduction'] = '10'  # Billomat: absolute discount, not 10%.
        elif field == 'item_title':
            offer['items'][0]['title'] = 'Anderer Artikeltext'
        elif field == 'item_description':
            offer['items'][0]['description'] = 'Abweichender Lieferumfang'
        else:
            offer['reduction'] = '10%'

    api.on_verify = change
    result = submit(implementation, transfer, review)
    assert result['status'] == 'review'
    assert result['problems']
    attempt(lambda: submit(implementation, transfer, review))
    assert len(api.posts) == 1


def test_local_finish_failure_after_remote_write_is_not_reposted(implementation, transfer, monkeypatch):
    store, _, _, api = transfer
    review = prepare(implementation, transfer)
    transact, put = store.transact_record, store.put_record

    def fail_finish(operation):
        def guarded(*args, **kwargs):
            if api.posts:
                raise StorageError('Local finish could not be committed')
            return operation(*args, **kwargs)
        return guarded

    with monkeypatch.context() as scoped:
        scoped.setattr(store, 'transact_record', fail_finish(transact))
        scoped.setattr(store, 'put_record', fail_finish(put))
        attempt(lambda: submit(implementation, transfer, review))
    assert len(api.posts) == 1
    attempt(lambda: submit(implementation, transfer, review))
    assert len(api.posts) == 1
    recovered = implementation.reconcile(store, 'one', 'project-1', api)
    assert recovered['status'] == 'created'
    assert len(api.posts) == 1


def test_expired_review_cannot_authorize_post(implementation, transfer):
    store, _, _, api = transfer
    review = prepare(implementation, transfer)
    store.put_record('one', 'quote_transfer_review', 'project-1', dict(review, prepared_at=0))
    with pytest.raises(BLOCKED):
        submit(implementation, transfer, review)
    assert api.posts == []


def test_new_review_invalidates_old_confirmation_token(implementation, transfer):
    _, _, _, api = transfer
    old = prepare(implementation, transfer)
    new = prepare(implementation, transfer)
    assert old['token'] != new['token']
    with pytest.raises(BLOCKED):
        submit(implementation, transfer, old)
    assert api.posts == []
    assert submit(implementation, transfer, new)['status'] == 'created'
    assert len(api.posts) == 1


def test_review_replacement_during_final_search_blocks_old_claim(implementation, transfer):
    store, _, _, api = transfer
    review = prepare(implementation, transfer)
    api.on_search = lambda: store.put_record('one', 'quote_transfer_review', 'project-1', dict(review, token='new-token'))
    with pytest.raises(BLOCKED):
        submit(implementation, transfer, review)
    assert api.posts == []


def test_failed_durable_claim_prevents_post_and_allows_safe_retry(implementation, transfer, monkeypatch):
    store, _, _, api = transfer
    review = prepare(implementation, transfer)
    original = store.transact_record

    def fail_claim(account, kind, key, change):
        if kind == 'quote_transfer':
            raise StorageError('Cannot save claim')
        return original(account, kind, key, change)

    with monkeypatch.context() as scoped:
        scoped.setattr(store, 'transact_record', fail_claim)
        with pytest.raises(StorageError):
            submit(implementation, transfer, review)
    assert api.posts == []
    assert submit(implementation, transfer, review)['status'] == 'created'
    assert len(api.posts) == 1


def test_preexisting_exact_remote_marker_is_read_back_without_create(implementation, transfer):
    _, _, _, api = transfer
    review = prepare(implementation, transfer)
    # A previous remote draft exists but this SQLite has no transfer ledger.
    api.create_offer_draft(review['payload'])
    api.posts.clear()
    result = submit(implementation, transfer, review)
    assert result['status'] == 'created'
    assert api.posts == []
    assert api.reads == ['501']


def test_later_read_only_reconcile_preserves_manual_presentation_edits(implementation, transfer):
    store, _, _, api = transfer
    review = prepare(implementation, transfer)
    result = submit(implementation, transfer, review)
    oid = result['offer_id']
    store.save('one', oid, {'customer_title': 'Nachträglich bearbeitet'})
    store.put_record('one', 'offer_images', oid, {'ids': ['independent-user-image']})
    assert implementation.reconcile(store, 'one', 'project-1', api)['status'] == 'created'
    assert store.load('one', oid) == {'customer_title': 'Nachträglich bearbeitet'}
    assert store.record('one', 'offer_images', oid) == {'ids': ['independent-user-image']}
    assert len(api.posts) == 1


@pytest.mark.parametrize(('variant', 'net', 'gross'), [
    ('tax_free', '171.00', '171.00'), ('zero_price', '99.00', '117.81'),
    ('decimal_quantity', '117.00', '139.23'),
])
def test_explicit_pricing_variants_round_trip_without_invented_prices(implementation, transfer, variant, net, gross):
    store, _, quote, api = transfer
    if variant == 'tax_free':
        quote['catalog']['clients'][0]['tax_rule'] = 'NO_TAX'
    elif variant == 'zero_price':
        quote['catalog']['articles'][0]['sales_price2'] = '0'
    else:
        quote['rows'][0]['quantity'] = '0.25'
    api.catalog = deepcopy(quote['catalog'])
    store.put_record('one', 'quote', 'project-1', quote)
    review = prepare(implementation, transfer)
    result = submit(implementation, transfer, review)
    assert result['status'] == 'created'
    offer = api.offers[result['offer_id']]
    assert offer['total_net'] == net and offer['total_gross'] == gross


def test_review_token_is_bound_to_account_even_with_same_project_id(implementation, transfer):
    store, project, quote, api = transfer
    store.put_record('two', 'project', 'project-1', project)
    store.put_record('two', 'quote', 'project-1', quote)
    first = prepare(implementation, transfer)
    second = prepare(implementation, transfer, identity='two')
    assert first['token'] != second['token']
    with pytest.raises(BLOCKED):
        submit(implementation, transfer, first, identity='two')
    assert api.posts == []


def test_changed_article_description_after_review_blocks_post(implementation, transfer):
    _, _, _, api = transfer
    api.catalog['articles'][0]['description'] = 'Freigegebene Produktbeschreibung'
    review = prepare(implementation, transfer)
    api.catalog['articles'][0]['description'] = 'Nachträglich geänderte Produktbeschreibung'
    with pytest.raises(BLOCKED):
        submit(implementation, transfer, review)
    assert api.posts == []


@pytest.mark.parametrize('incoming_id', ['', '501'])
def test_stale_finish_cannot_downgrade_created_transfer(implementation, transfer, incoming_id):
    store, _, _, api = transfer
    review = prepare(implementation, transfer)
    created = submit(implementation, transfer, review)
    stale = dict(created, status='sending', offer_id=incoming_id, problems=[])
    result = implementation.finish(store, 'one', 'project-1', stale, error='Earlier request timed out')
    assert result == created
    assert store.record('one', 'quote_transfer', 'project-1') == created
    assert len(api.posts) == 1


def test_stale_finish_without_id_cannot_erase_known_review_id(implementation, transfer):
    store, _, _, api = transfer
    review = prepare(implementation, transfer)
    api.on_verify = lambda offer: offer.update(total_gross='999')
    known = submit(implementation, transfer, review)
    assert known['status'] == 'review' and known['offer_id'] == '501'
    stale = dict(known, status='sending', offer_id='', problems=[])
    result = implementation.finish(store, 'one', 'project-1', stale, error='Earlier request timed out')
    assert result == known
    assert store.record('one', 'quote_transfer', 'project-1') == known


@pytest.mark.parametrize('status', ['created', 'review'])
def test_stale_finish_with_different_known_id_conflicts_without_overwrite(implementation, transfer, status):
    store, _, _, api = transfer
    review = prepare(implementation, transfer)
    if status == 'review':
        api.on_verify = lambda offer: offer.update(total_gross='999')
    current = submit(implementation, transfer, review)
    assert current['status'] == status
    stale = dict(current, offer_id='999')
    with pytest.raises(RecordConflict):
        implementation.finish(store, 'one', 'project-1', stale, error='Different remote id')
    assert store.record('one', 'quote_transfer', 'project-1') == current
    assert len(api.posts) == 1


def test_oversized_utf8_article_payload_cannot_prepare_a_transfer(implementation, transfer):
    store, _, _, api = transfer
    # JSON escapes of non-ASCII text exceed 256 KiB even though the string is shorter.
    api.catalog['articles'][0]['description'] = 'ä' * 50_000
    with pytest.raises(ValueError):
        prepare(implementation, transfer)
    assert store.record('one', 'quote_transfer_review', 'project-1') is None
    assert store.record('one', 'quote_transfer', 'project-1') is None
    assert api.posts == []


def test_oversized_payload_at_submit_fails_before_claim_and_can_be_retried(implementation, transfer):
    store, _, _, api = transfer
    review = prepare(implementation, transfer)
    api.catalog['articles'][0]['description'] = 'a' * (256 * 1024)
    with pytest.raises(ValueError):
        submit(implementation, transfer, review)
    assert store.record('one', 'quote_transfer', 'project-1') is None
    assert api.posts == []
    api.catalog['articles'][0]['description'] = ''
    assert submit(implementation, transfer, review)['status'] == 'created'
    assert len(api.posts) == 1


def test_more_than_hundred_positions_fails_before_review_or_claim(implementation, transfer):
    store, _, quote, api = transfer
    quote['rows'] = [deepcopy(quote['rows'][0]) for _ in range(101)]
    store.put_record('one', 'quote', 'project-1', quote)
    with pytest.raises(ValueError):
        prepare(implementation, transfer)
    assert store.record('one', 'quote_transfer_review', 'project-1') is None
    assert store.record('one', 'quote_transfer', 'project-1') is None
    assert api.posts == []


def test_conflicting_project_link_during_readback_requires_review_then_recovers_read_only(implementation, transfer):
    store, project, _, api = transfer
    review = prepare(implementation, transfer)
    api.on_verify = lambda offer: store.put_record('one', 'project', 'project-1', dict(project, offer_id='999'))
    result = submit(implementation, transfer, review)
    assert result['status'] == 'review'
    assert any('Projektverknüpfung' in problem for problem in result['problems'])
    assert store.record('one', 'project', 'project-1')['offer_id'] == '999'
    assert store.load('one', result['offer_id']) == {}
    assert store.record('one', 'offer_images', result['offer_id']) is None
    assert len(api.posts) == 1
    api.on_verify = None
    store.put_record('one', 'project', 'project-1', dict(project, offer_id=''))
    recovered = implementation.reconcile(store, 'one', 'project-1', api)
    assert recovered['status'] == 'created'
    assert store.record('one', 'project', 'project-1')['offer_id'] == recovered['offer_id']
    assert store.load('one', recovered['offer_id'])['customer_title'] == project['title']
    assert store.record('one', 'offer_images', recovered['offer_id']) is not None
    assert len(api.posts) == 1
