from copy import deepcopy
import re
import pytest
import app as module
from billomat_client import BillomatClient
from quote_drafts import calculate, components, candidates, catalog_snapshot
from test_persistence import isolated_storage


@pytest.fixture
def catalog():
    return dict(articles=[dict(id='1', article_number='ART-1', title='Hub', sales_price='100', sales_price2='80', currency_code='EUR', tax_id='1', unit_id='1'), dict(id='2', title='FireProtect RB', sales_price='10', currency_code='EUR', tax_id='1', unit_id='1')], clients=[dict(id='3', name='Testkunde', price_group='2', reduction='10', net_gross='SETTINGS', tax_rule='TAX')], taxes=[dict(id='1', rate='19', is_default='1')], units=[dict(id='1', name='Stück')], settings=dict(net_gross='NET',currency_code='EUR'))


@pytest.fixture
def draft(catalog):
    return dict(catalog=catalog, client_id='3', rows=[dict(description='Hub',article_id='1',quantity='1'), dict(description='FireProtect',article_id='2',quantity='11')])


def test_price_group_fallback_reduction_not_skonto(draft):
    draft['catalog']['clients'][0]['discount_rate']='99'
    value=calculate(draft)
    assert value['total']==dict(net='171.00', tax='32.49', gross='203.49')
    assert [x['price_field'] for x in value['lines']]==['sales_price2','sales_price']


def test_zero_group_price_is_not_missing(draft):
    draft['catalog']['articles'][0]['sales_price2']='0'
    assert calculate(draft)['lines'][0]['price']=='0'


@pytest.mark.parametrize('quantity',['','0','-1','NaN','Infinity','1000001'])
def test_invalid_quantity_never_produces_partial_total(draft,quantity):
    draft['rows'][0]['quantity']=quantity
    assert calculate(draft)['total'] is None


def test_currency_and_unknown_article_fail_closed(draft):
    draft['catalog']['articles'][0]['currency_code']='USD'
    assert calculate(draft)['total'] is None
    draft['rows'][0]['article_id']='invented'
    assert calculate(draft)['total'] is None


def test_country_rule_requires_review_and_gross_is_not_net(draft):
    draft['catalog']['clients'][0]['tax_rule']='COUNTRY'
    assert calculate(draft)['total'] is None
    draft['tax_confirmed']='yes'
    assert calculate(draft)['total']
    draft['catalog']['settings']['net_gross']='GROSS'
    assert calculate(draft)['lines']==[]


def test_tax_free_and_ambiguous_default(draft):
    draft['catalog']['clients'][0]['tax_rule']='NO_TAX'
    assert calculate(draft)['total']['tax']=='0.00'
    draft['catalog']['clients'][0]['tax_rule']='TAX'
    draft['catalog']['articles'][0]['tax_id']=None
    draft['catalog']['taxes'].append(dict(id='2',rate='7',is_default='1'))
    assert calculate(draft)['total'] is None


@pytest.mark.parametrize('tax_rule', [None, '', 'UNKNOWN'])
def test_unknown_tax_rule_cannot_be_confirmed_as_country(draft, tax_rule):
    draft['catalog']['clients'][0]['tax_rule'] = tax_rule
    draft['tax_confirmed'] = 'yes'
    result = calculate(draft)
    assert result['total'] is None
    assert result['lines'] == []
    assert 'Unbekannte oder fehlende Steuerregel' in result['problems'][0]


def test_plain_notes_and_ambiguous_variants(catalog):
    result=components({'notes':'1 Hub + 11 FireProtect\nMontage offen'})
    assert [x['quantity'] for x in result]==['1','11','']
    catalog['articles'].append(dict(id='4',title='FireProtect SB'))
    matches=candidates('FireProtect',catalog['articles'])
    assert {x['id'] for x in matches}=={'2','4'}
    assert all('article_id' not in row for row in result)
    assert candidates('Unbekannt',catalog['articles'])==[]


def test_sensitive_client_fields_not_persisted(catalog):
    catalog['clients'][0]['bank_iban']='private'
    catalog['settings']['default_email_sender']='private'
    assert 'bank_iban' not in catalog_snapshot(catalog)['clients'][0]
    assert 'default_email_sender' not in catalog_snapshot(catalog)['settings']


def test_catalog_pagination_and_repeated_page(monkeypatch):
    api=BillomatClient('test','test')
    calls=[]
    def get(path,params):
        calls.append(params['page'])
        return {'articles':{'article': {'id':str(params['page'])}}} if params['page']<3 else {'articles':{}}
    monkeypatch.setattr(api,'_get',get)
    assert len(api.collection('articles','article'))==2
    assert calls==[1,2,3]
    monkeypatch.setattr(api,'_get',lambda *a: {'articles':{'article':{'id':'1'}}})
    with pytest.raises(RuntimeError):
        api.collection('articles','article')


def test_atomic_revision_prevents_overwrite(tmp_path):
    from storage import OfferStore, RecordConflict
    first, second = OfferStore(tmp_path), OfferStore(tmp_path)
    first.put_revision('test','quote','one',{'revision':'a'},'')
    with pytest.raises(RecordConflict):
        second.put_revision('test','quote','one',{'revision':'b'},'')
    assert first.record('test','quote','one')['revision']=='a'


def test_draft_browser_persistence_stale_notes_and_failed_refresh(monkeypatch,catalog):
    monkeypatch.setenv('BILLOMAT_ID','test')
    monkeypatch.setenv('BILLOMAT_API_KEY','test-only')
    monkeypatch.setattr(BillomatClient,'draft_catalog',lambda self:deepcopy(catalog))
    client=module.app.test_client()
    location=client.post('/projects',data={'title':'Test','notes':'1 Hub + 11 FireProtect'}).headers['Location']
    url=location+'/quote'
    def revision():
        return re.search(r'name="revision" value="([^"]*)"',client.get(url).text)[1]
    assert client.post(url,data={'action':'catalog','revision':revision()}).status_code==302
    old=revision()
    from werkzeug.datastructures import MultiDict
    payload=MultiDict([('action','save'),('revision',old),('client_id','3'),('description','Hub'),('quantity','1'),('article_id','1'),('description','FireProtect'),('quantity','11'),('article_id','2')])
    assert client.post(url,data=payload).status_code==302
    assert '203,49' in module.app.test_client().get(url).text
    assert client.post(url,data=payload).status_code==409
    def fail(self):
        raise RuntimeError('timeout')
    monkeypatch.setattr(BillomatClient,'draft_catalog',fail)
    assert client.post(url,data={'action':'catalog','revision':revision()}).status_code==503
    assert '203,49' in client.get(url).text
    client.post(location,data={'notes':'12 FireProtect'})
    page=client.get(url).text
    assert 'Projektnotizen wurden geändert' in page
    assert 'Entwurf: Netto' not in page
    monkeypatch.setenv('BILLOMAT_ID','other')
    assert client.get(url).status_code==404


def test_search_ignores_quantity_and_matches_german_product_words():
    articles = [dict(id='1', title='4 Kanal Rekorder'),
                dict(id='2', title='Funk-Bewegungsmelder PIR'),
                dict(id='3', title='Alarmzentrale'),
                dict(id='4', title='8MP Domekamera', article_number='ART-954')]
    assert {a['id'] for a in candidates('alarm mit 4 bewegungsmeldern', articles)} == {'2', '3'}
    assert candidates('4 mit und', articles) == []
    assert candidates('Domekameras', articles)[0]['id'] == '4'
    assert candidates('ART-954', articles)[0]['id'] == '4'


def test_tax_confirmation_does_not_hide_missing_article_selections(draft):
    draft['catalog']['clients'][0]['tax_rule'] = 'COUNTRY'
    draft['rows'][0]['article_id'] = ''
    result = calculate(draft)
    assert result['total'] is None
    assert any('Steuerregel' in p for p in result['problems'])
    assert 'Position 1: Artikel auswählen.' in result['problems']
