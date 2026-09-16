import json
import re
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import requests
import app as module
import customers
import company_search
from billomat_client import BillomatClient, CustomerWriteUncertain
from storage import OfferStore, RecordConflict
from test_persistence import isolated_storage
from test_quote_drafts import catalog


FIELDS = dict(name='Beispiel GmbH', street='Testweg 1', zip='12345', city='Teststadt', country_code='DE', www='https://example.org')


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('BILLOMAT_ID', 'test')
    monkeypatch.setenv('BILLOMAT_API_KEY', 'fake')
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    return module.app.test_client()


def token(client):
    client.get('/customers')
    with client.session_transaction() as session:
        return session['customers_csrf']


def seed(store, key='one', fields=None):
    store.put_record('test','customer_draft',key,dict(fields=fields or FIELDS, revision='r1', ready=True))


def test_explicit_confirmation_csrf_and_saved_revision(client, monkeypatch):
    seed(module.offer_store())
    remote=Mock()
    remote.collection.return_value=[]
    remote.create_client.return_value={'id':'123','client_number':'456'}
    monkeypatch.setattr(customers,'api',lambda:remote)
    csrf=token(client)
    data=dict(action='create', revision='r1', csrf=csrf)
    assert client.post('/customers/one',data=data).status_code==400
    assert client.post('/customers/one',data=dict(data,confirmed='yes',csrf='wrong')).status_code==400
    assert client.post('/customers/one',data=dict(data,confirmed='yes',revision='old')).status_code==409
    remote.create_client.assert_not_called()
    response=client.post('/customers/one',data=dict(data,confirmed='yes',name='Tampered'))
    assert response.status_code==200 and 'Kunde in Billomat angelegt' in response.text
    remote.create_client.assert_called_once_with(FIELDS)
    client.post('/customers/one',data=dict(data,confirmed='yes'))
    client.get('/customers/one')
    assert remote.create_client.call_count==1


def test_existing_including_archived_blocks_create(tmp_path):
    store=OfferStore(tmp_path); seed(store)
    remote=Mock()
    remote.collection.return_value=[dict(FIELDS,id='2',archived='1')]
    assert customers.submit(store,'test','one','r1',remote)['status']=='duplicate'
    remote.create_client.assert_not_called()


def test_unknown_write_never_retried_after_restart(tmp_path):
    store=OfferStore(tmp_path); seed(store)
    remote=Mock()
    remote.collection.return_value=[]
    remote.create_client.side_effect=CustomerWriteUncertain()
    assert customers.submit(store,'test','one','r1',remote)['status']=='unknown'
    assert customers.submit(OfferStore(tmp_path),'test','one','r1',remote)['status']=='unknown'
    seed(store,'two',dict(FIELDS,street='Different 2'))
    with pytest.raises(RecordConflict):
        customers.submit(store,'test','two','r1',remote)
    assert remote.create_client.call_count==1


def test_concurrent_drafts_only_write_once(tmp_path):
    store=OfferStore(tmp_path); seed(store); seed(store,'two')
    barrier=Barrier(2)
    remote=Mock()
    def read(*args):
        barrier.wait(timeout=5)
        return []
    remote.collection.side_effect=read
    remote.create_client.return_value={'id':'9'}
    def run(key):
        try: return customers.submit(OfferStore(tmp_path),'test',key,'r1',remote)['status']
        except RecordConflict: return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses=list(pool.map(run,['one','two']))
    assert sorted(statuses)==['conflict','created']
    assert remote.create_client.call_count==1


@pytest.mark.parametrize('response',[SimpleNamespace(status_code=500),SimpleNamespace(status_code=302),SimpleNamespace(status_code=201,json=lambda:{}),SimpleNamespace(status_code=201,json=lambda:{'client':{'id':'oops'}})])
def test_remote_unconfirmed_responses_no_retry(monkeypatch,response):
    post=Mock(return_value=response)
    monkeypatch.setattr('billomat_client.requests.post',post)
    with pytest.raises(CustomerWriteUncertain):
        BillomatClient('test','secret').create_client(FIELDS)
    assert post.call_count==1
    assert post.call_args.kwargs['allow_redirects'] is False


def test_billomat_post_contract_and_timeout(monkeypatch):
    post=Mock(return_value=SimpleNamespace(status_code=201,json=lambda:{'client':{'id':'12'}}))
    monkeypatch.setattr('billomat_client.requests.post',post)
    api=BillomatClient('test','secret')
    assert api.create_client(FIELDS)['id']=='12'
    assert post.call_args.args==('https://test.billomat.net/api/clients',)
    assert post.call_args.kwargs['json']=={'client':FIELDS}
    assert post.call_args.kwargs['headers']['X-BillomatApiKey']=='secret'
    post.side_effect=requests.Timeout()
    with pytest.raises(CustomerWriteUncertain): api.create_client(FIELDS)


def test_web_requires_key_and_manual_remains_available(client):
    csrf=token(client)
    response=client.post('/customers',data=dict(csrf=csrf,action='web',query='Beispiel GmbH'))
    assert 'OpenAI-API-Schlüssel' in response.text
    response=client.post('/customers',data=dict(csrf=csrf,action='manual'))
    assert response.status_code==302
    preview=client.get(response.location)
    assert 'Daten prüfen und Vorschau speichern' in preview.text
    assert 'Bestätigten Kunden in Billomat anlegen' not in preview.text


def test_research_citations_and_private_data_boundary(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-secret')
    source='https://example.org/impressum'
    company=dict(FIELDS,source_url=source,hint='Anschrift prüfen')
    responses=[{'status':'completed','output':[{'content':[{'type':'output_text','text':'Public research','annotations':[{'type':'url_citation','url':source,'title':'Impressum'}]}]}]},
               {'status':'completed','output':[{'content':[{'type':'output_text','text':json.dumps({'companies':[company,dict(company,source_url='https://invented.org')]})}]}]}]
    post=Mock(side_effect=[SimpleNamespace(ok=True,json=lambda data=data:data) for data in responses])
    monkeypatch.setattr(company_search.requests,'post',post)
    result=company_search.research('Beispiel GmbH')
    assert len(result)==1 and result[0]['source_title']=='Impressum'
    first=post.call_args_list[0].kwargs['json']
    assert first['input']=='Beispiel GmbH' and first['store'] is False
    assert first['tools']==[{'type':'web_search'}]
    assert 'test-secret' not in json.dumps(first)


def test_search_selection_stays_local_until_review(client,monkeypatch):
    company=dict(FIELDS,source_url='https://example.org',source_title='Quelle',hint='Prüfen')
    monkeypatch.setattr(customers,'research',lambda query:[company])
    remote=Mock(); monkeypatch.setattr(customers,'api',lambda:remote)
    csrf=token(client)
    result=client.post('/customers',data=dict(csrf=csrf,action='web',query='Beispiel GmbH'))
    search=re.search('name="search" value="([^"]+)"',result.text).group(1)
    selected=client.post('/customers/select',data=dict(csrf=csrf,search=search,index='0'))
    assert selected.status_code==302
    review=client.get(selected.location)
    assert 'Beispiel GmbH' in review.text and 'https://example.org' in review.text
    remote.create_client.assert_not_called()
    draft=module.offer_store().record('test','customer_draft',selected.location.rsplit('/',1)[1])
    response=client.post(selected.location,data=dict(FIELDS,csrf=csrf,action='prepare',revision=draft['revision']))
    assert response.status_code==302
    assert 'Bestätigten Kunden in Billomat anlegen' in client.get(selected.location).text
    remote.create_client.assert_not_called()


def test_shared_catalog_loading_failure_and_new_drafts(client,monkeypatch,catalog):
    remote=Mock(); remote.draft_catalog.return_value=catalog
    monkeypatch.setattr(customers,'api',lambda:remote)
    csrf=token(client)
    assert client.post('/billomat',data=dict(csrf=csrf)).status_code==200
    saved=module.offer_store().record('test','catalog','shared')
    remote.draft_catalog.side_effect=RuntimeError('SECRET')
    failed=client.post('/billomat',data=dict(csrf=csrf))
    assert failed.status_code==503 and 'SECRET' not in failed.text
    assert module.offer_store().record('test','catalog','shared')==saved
    module.offer_store().put_record('test','project','new',dict(title='Test',notes='1 Hub'))
    assert 'Testkunde' in client.get('/projects/new/quote').text
    assert 'ART-1' in client.get('/inventory').text


@pytest.mark.parametrize('changes',[dict(www='javascript:alert(1)'),dict(city=''),dict(country_code='Germany')])
def test_invalid_customer_fields(changes):
    with pytest.raises(ValueError): customers.customer_fields(dict(FIELDS,**changes))
