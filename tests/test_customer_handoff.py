import re
from copy import deepcopy
from unittest.mock import Mock

import pytest
import app as module
import customers
from customer_handoff import context, select_created
from quote_drafts import fingerprint
from storage import RecordConflict
from test_customers import client, token, FIELDS
from test_persistence import isolated_storage
from test_quote_drafts import catalog


@pytest.fixture
def setup(client, catalog, monkeypatch):
    store = module.offer_store()
    project = dict(title='Testangebot', notes='2 Hub', analysis={}, customer_name='Erika Muster')
    store.put_record('test', 'project', 'p1', project)
    draft = dict(rows=[dict(description='Hub', quantity='2', article_id='1')], source=fingerprint(project),
                 revision='q1', client_id='old', reviewed=True, tax_confirmed='yes', presentation={'title':'Eigener Text'})
    store.put_record('test', 'quote', 'p1', draft)
    remote = Mock()
    remote.collection.return_value = []
    remote.create_client.return_value = dict(id='3', client_number='1003')
    remote.draft_catalog.return_value = catalog
    monkeypatch.setattr(customers, 'api', lambda: remote)
    return store, project, draft, remote


def created(store):
    customer = dict(fields=deepcopy(FIELDS), quote_context=context(store, 'test', 'p1'), revision='c1', ready=True)
    result = dict(status='created', fields=deepcopy(FIELDS), client_id='3', client_number='1003')
    return customer, result


def test_complete_manual_flow_selects_created_customer_with_no_second_create(client, setup):
    store, project, old, remote = setup
    csrf = token(client)
    response = client.post('/customers', data=dict(csrf=csrf, action='manual', project='p1'))
    path = response.location
    key = path.rsplit('/',1)[-1]
    customer = store.record('test','customer_draft',key)
    assert customer['fields']['name'] == 'Erika Muster'
    assert customer['fields']['country_code'] == 'DE'
    assert 'Vollständiger Name / Firmenname' in client.get(path).text
    client.post(path, data=dict(FIELDS,csrf=csrf,revision=customer['revision'],action='prepare'))
    customer = store.record('test','customer_draft',key)
    response = client.post(path, data=dict(csrf=csrf,revision=customer['revision'],action='create',confirmed='yes'))
    assert 'Kunden übernehmen und zurück zum Angebot' in response.text
    assert store.record('test','quote','p1') == old
    data = dict(csrf=csrf,revision=customer['revision'],action='use',client_id='evil',project='other')
    response = client.post(path,data=data)
    assert response.status_code == 303 and '/projects/p1/quote?customer_selected=1' in response.location
    new = store.record('test','quote','p1')
    assert new['client_id']=='3' and new['rows']==old['rows'] and new['presentation']==old['presentation']
    assert not new['reviewed'] and new['tax_confirmed']=='' and new['revision']!='q1'
    remote.create_client.assert_called_once_with(FIELDS)
    assert client.post(path,data=data).status_code==409
    assert store.record('test','quote','p1')==new


@pytest.mark.parametrize('change',['project','quote','transfer','offer'])
def test_stale_context_never_overwrites_work(setup,change):
    store,project,old,remote=setup
    customer,result=created(store)
    if change=='project': store.put_record('test','project','p1',dict(project,notes='Changed'))
    if change=='quote': store.put_record('test','quote','p1',dict(old,revision='q2'))
    if change=='transfer': store.put_record('test','quote_transfer','p1',dict(status='unknown'))
    if change=='offer': store.put_record('test','project','p1',dict(project,offer_id='123'))
    before=store.record('test','quote','p1')
    with pytest.raises(RecordConflict): select_created(store,'test',customer,result,remote)
    assert store.record('test','quote','p1')==before
    remote.draft_catalog.assert_not_called()


def test_concurrent_edit_during_catalog_loading_is_rejected(setup):
    store,project,old,remote=setup
    customer,result=created(store)
    catalog=remote.draft_catalog.return_value
    def edit():
        store.put_record('test','project','p1',dict(project,notes='Concurrent edit'))
        return catalog
    remote.draft_catalog.side_effect=edit
    with pytest.raises(RecordConflict): select_created(store,'test',customer,result,remote)
    assert store.record('test','quote','p1')==old


@pytest.mark.parametrize('change',['unknown','wrong_fields','archived','absent','network'])
def test_unconfirmed_or_unavailable_customer_keeps_quote(setup,change):
    store,project,old,remote=setup
    customer,result=created(store)
    if change=='unknown': result['status']='unknown'
    if change=='wrong_fields': result['fields']=dict(FIELDS,name='Different')
    if change=='archived': remote.draft_catalog.return_value['clients'][0]['archived']='1'
    if change=='absent': remote.draft_catalog.return_value['clients']=[]
    if change=='network': remote.draft_catalog.side_effect=RuntimeError('Offline')
    with pytest.raises((ValueError,RuntimeError)): select_created(store,'test',customer,result,remote)
    assert store.record('test','quote','p1')==old


def test_first_quote_is_prepared_with_existing_requirements(client,setup):
    store,project,old,remote=setup
    store.put_record('test','project','new',project)
    customer,result=created(store)
    customer['quote_context']=context(store,'test','new')
    assert select_created(store,'test',customer,result,remote)=='new'
    new=store.record('test','quote','new')
    assert new['rows'][0]['quantity']=='2' and new['client_id']=='3'


def test_csrf_account_and_invalid_return_target(client,setup,monkeypatch):
    store,project,old,remote=setup
    customer,result=created(store)
    store.put_record('test','customer_draft','one',customer)
    assert client.post('/customers/one',data=dict(action='use',revision='c1')).status_code==400
    assert client.get('/customers?project=https://evil.test').status_code==404
    monkeypatch.setenv('BILLOMAT_ID','other')
    assert client.get('/customers?project=p1').status_code==404
    assert client.get('/customers/one').status_code==404
    remote.draft_catalog.assert_not_called()


def test_search_context_survives_selection_without_private_data_in_web_query(client,setup,monkeypatch):
    store,project,old,remote=setup
    research=Mock(return_value=[dict(FIELDS,source_url='https://example.org',source_title='Quelle',hint='Prüfen')])
    monkeypatch.setattr(customers,'research',research)
    csrf=token(client)
    response=client.post('/customers',data=dict(csrf=csrf,project='p1',action='web',query='Public GmbH'))
    search=re.search('name="search" value="([^"]+)"',response.text).group(1)
    selected=client.post('/customers/select',data=dict(csrf=csrf,search=search,index='0'))
    draft=store.record('test','customer_draft',selected.location.rsplit('/',1)[-1])
    assert draft['quote_context']['project']=='p1'
    research.assert_called_once_with('Public GmbH')


def test_private_person_existing_first_last_name_blocks_duplicate_creation():
    assert customers.duplicates(dict(FIELDS,name='Erika Muster'),[dict(id='7',first_name='Erika',last_name='Muster')])
