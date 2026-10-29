import pytest
import app
import document_delivery as d


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv('FTST_REQUIRE_INGRESS', raising=False)
    return app.app.test_client()


@pytest.mark.parametrize('kind,status', [('invoices','OPEN'),('invoices','PAID'),('delivery-notes','CREATED')])
def test_document_flow_uses_original_and_no_writes(client, monkeypatch, kind, status):
    spec=d.KINDS[kind]
    row={'id':'12','client_id':'7','status':status,spec[3]:'X-12','address':'<script>client</script>'}
    calls=[]
    def read(path,params=None,pdf=False):
        calls.append((path,params,pdf))
        if pdf: return b'%PDF-1.7 original'
        if path==kind: return {kind:{spec[0]:row}}
        if path=='clients/7': return {'client':{'email':'user@example.org','phone':'+491711234567'}}
        return {spec[0]:row}
    monkeypatch.setattr(d,'read',read)
    listing=client.get('/documents?kind='+kind+'&q=X-12')
    assert listing.status_code==200 and 'no-store' in listing.headers['Cache-Control']
    assert calls[0][1]['per_page']==30 and calls[0][1][spec[3]]=='X-12'
    detail=client.get('/documents/'+kind+'/12',headers={'X-Ingress-Path':'/api/hassio_ingress/test'})
    assert detail.status_code==200
    assert '<script>client' not in detail.text and '&lt;script&gt;client' in detail.text
    assert 'data-deliver="whatsapp"' in detail.text
    assert '/api/hassio_ingress/test/documents/'+kind+'/12/pdf' in detail.text
    assert 'user@example.org' in detail.text
    pdf=client.get('/documents/'+kind+'/12/pdf')
    assert pdf.data==b'%PDF-1.7 original' and pdf.mimetype=='application/pdf'
    assert client.post('/documents/'+kind+'/12').status_code==405


@pytest.mark.parametrize('status',['DRAFT','CANCELED','UNKNOWN',''])
def test_no_draft_or_canceled_pdf(client,monkeypatch,status):
    calls=[]
    def read(path,**kwargs):
        calls.append(path)
        return {'invoice':{'id':'12','status':status}}
    monkeypatch.setattr(d,'read',read)
    assert client.get('/documents/invoices/12/pdf').status_code==409
    assert calls==['invoices/12']


@pytest.mark.parametrize('path',['/documents?kind=clients','/documents?page=-1','/documents/invoices/abc/pdf','/documents/clients/12'])
def test_invalid_routes_do_not_read(client,monkeypatch,path):
    monkeypatch.setattr(d,'read',lambda *a,**k:pytest.fail('unexpected read'))
    assert client.get(path).status_code in (400,404)


def test_pdf_rechecks_changed_status(client,monkeypatch):
    monkeypatch.setattr(d,'read',lambda *a,**k:{'invoice':{'id':'99','status':'OPEN'}})
    assert client.get('/documents/invoices/12/pdf').status_code==502


def test_separate_contact_does_not_guess_main_customer_recipient(client, monkeypatch):
    calls=[]
    def read(path, **kwargs):
        calls.append(path)
        return {'invoice': {'id':'12', 'client_id':'7', 'contact_id':'9', 'status':'OPEN'}}
    monkeypatch.setattr(d, 'read', read)
    response=client.get('/documents/invoices/12')
    assert response.status_code==200
    assert calls==['invoices/12']
    assert 'id="delivery-email" type="email" value=""' in response.text


@pytest.mark.parametrize('status,content,ctype',[(302,b'%PDF-ok','application/pdf'),(401,b'key','text/plain'),(200,b'<html>','text/html'),(200,b'%PDF-ok','text/html')])
def test_transport_rejects_wrong_pdf(monkeypatch,status,content,ctype):
    class Response:
        status_code=status
        headers={'Content-Type':ctype}
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def iter_content(self,*a): yield content
    class HTTP:
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def get(self,url,**kw):
            assert kw['allow_redirects'] is False and kw['stream'] is True
            assert self.trust_env is False
            assert kw['params']['format']=='pdf'
            return Response()
    monkeypatch.setattr(d,'_configuration',lambda:('https://example.billomat.net/api',{}))
    monkeypatch.setattr(d.requests,'Session',HTTP)
    with pytest.raises(d.DocumentError): d.read('invoices/12/pdf',pdf=True)
