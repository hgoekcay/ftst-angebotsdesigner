from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from io import BytesIO
import json
import pytest
from PIL import Image
from storage import OfferStore
import portal_product_photos as photos
from website_portal import snapshot
from website_portal_client import PortalClient


def source():
    today=date.today()
    return dict(id='42', title='Synthetisches System', date=str(today), validity_date=str(today+timedelta(days=7)), status='OPEN',
        total_net='300.00', total_gross='357.00', client={'name':'Test'}, items=[
            dict(title='FTronics FC-8D-PRO Kamera', description='Rein synthetisch', quantity=1, unit='Stück', unit_price='100.00', total_net='100.00'),
            dict(title='Türsprechanlage ohne Modellcode', description='Rein synthetisch', quantity=1, unit='Stück', unit_price='100.00', total_net='100.00'),
            dict(title='Montage und Inbetriebnahme', description='', quantity=1, unit='Pauschale', unit_price='100.00', total_net='100.00')])


def library(tmp_path, identity='account-a'):
    store=OfferStore(tmp_path)
    path=Path(tmp_path)/'images';path.mkdir(exist_ok=True)
    key='test-product'
    exif=Image.Exif();exif[270]='PRIVATE-METADATA-MUST-NOT-LEAVE'
    Image.new('RGB',(1600,1600),'red').save(path/(key+'.png'),exif=exif)
    store.put_record(identity,'image',key,{'title':'Internal library caption secret','description':'Internal project note secret','category':'Türsprechanlage'})
    return store,key


def test_manual_product_selection_freezes_only_public_identity_without_price_change(tmp_path):
    store,key=library(tmp_path);offer=source();original=deepcopy(offer)
    s=snapshot(offer,1,['position-1'])
    original_totals=deepcopy(s['totals'])
    content,binding=photos.apply(store,'account-a',offer,s,{'position-1':key,'position-2':key},lambda title:'Montage' in title)
    assert s['lines'][0]['options'][0]['product_photo_id']=='product-1'
    assert 'product_image_id' not in s['lines'][0]['options'][0]
    assert s['lines'][1]['product_photo_id']=='product-2'
    assert len(s['product_images'])==2 and len(content)==2
    assert s['product_images'][1]['caption']=='Freigegebenes Produktbild: Türsprechanlage ohne Modellcode'
    assert 'Internal' not in json.dumps(s)
    assert s['totals']==original_totals and offer==original
    assert binding['position-1']['asset_id']==key
    assert max(map(len,content.values()))<=128*1024
    picture=Image.open(BytesIO(content['product-1']))
    assert not picture.getexif()
    assert b'PRIVATE-METADATA-MUST-NOT-LEAVE' not in content['product-1']


def test_selection_is_account_offer_and_exact_product_bound(tmp_path):
    store,key=library(tmp_path);o=source();s=snapshot(o,1,[])
    _,binding=photos.apply(store,'account-a',o,s,{'position-2':key},lambda title:'Montage' in title)
    store.put_record('account-a',photos.KIND,'42',binding)
    assert photos.remembered(store,'account-a',o)=={'position-2':key}
    assert photos.remembered(store,'account-b',o)=={}
    changed=deepcopy(o);changed['items'][1]['quantity']=2
    assert photos.remembered(store,'account-a',changed)=={'position-2':key}
    changed['items'][1]['description']='Anderes Produktmodell'
    assert photos.remembered(store,'account-a',changed)=={}
    assert photos.remembered(store,'account-a',dict(o,id='43'))=={}


@pytest.mark.parametrize('choices',[{'position-3':'test-product'},{'position-99':'test-product'},{'position-1':'unknown-asset'},{'position-1':'builtin-ftst-registered'}])
def test_unknown_foreign_logo_and_service_choices_rejected(tmp_path,choices):
    store,_=library(tmp_path);o=source();s=snapshot(o,1,[])
    with pytest.raises(ValueError):photos.apply(store,'account-a',o,s,choices,lambda title:'Montage' in title)
    with pytest.raises(ValueError):photos.apply(store,'account-b',o,s,{'position-1':'test-product'},lambda title:False)


def test_transport_exact_product_descriptors_and_global_budget_before_http():
    transport=PortalClient('https://portal.example','x'*32)
    calls=[]
    transport._request=lambda *args,**kwargs:calls.append(kwargs) or {'saved':True}
    s={'schema_version':'ftst.customer-proposal.v1','approved_for_customer':True,'images':[],
       'product_images':[{'id':'product-1','caption':'Freigegebenes Produktbild: Synthetisches Produkt'}]}
    image=b'\x89PNG\r\n\x1a\n'+b'synthetic'
    transport.publish(s,b'%PDF-synthetic',product_images={'product-1':image})
    assert calls[0]['files'][1][0]=='product:product-1'
    with pytest.raises(ValueError):transport.publish(s,b'%PDF-synthetic',product_images={})
    huge={'schema_version':'ftst.customer-proposal.v1','approved_for_customer':True,
          'images':[{'id':'reference-'+str(n)} for n in range(4)],
          'product_images':[{'id':'product-'+str(n)} for n in range(3)]}
    before=len(calls)
    with pytest.raises(ValueError,match='18-MiB'):
        transport.publish(huge,b'%PDF-'+b'x'*(8*1024*1024-5),
                          images={'reference-'+str(n):b'x'*(2*1024*1024) for n in range(4)},
                          product_images={'product-'+str(n):b'x'*(2*1024*1024) for n in range(3)})
    assert len(calls)==before


def test_old_transport_without_product_images_unchanged():
    client=PortalClient('https://portal.example','x'*32)
    captured=[];client._request=lambda *args,**kwargs:captured.append(kwargs) or {}
    client.publish({'schema_version':'ftst.customer-proposal.v1','approved_for_customer':True,'images':[]},b'%PDF-test')
    assert len(captured[0]['files'])==1


def test_release_ui_product_choice_requires_existing_csrf_and_employee_approval(tmp_path,monkeypatch):
    import html,re
    from flask import Flask
    from uuid import uuid4
    import website_portal
    store,key=library(tmp_path,'test');o=source();app=Flask(__name__);app.secret_key='synthetic-test-secret'
    monkeypatch.setenv('BILLOMAT_ID','test');monkeypatch.setenv('WEBSITE_PORTAL_ENABLED','true')
    monkeypatch.setenv('WEBSITE_PORTAL_URL','https://portal.example')
    monkeypatch.setattr(website_portal,'read_catalog',lambda:{})
    pid=str(uuid4());published=[]
    class Transport:
        def publish(self,snap,pdf,images,product_images=None):
            published.append((snap,product_images));return {'proposal_id':pid}
        def create_link(self,proposal_id):
            return {'customer_url':'https://portal.example/angebot/'+pid+'#'+'a'*43,'expires_at':'2099-01-01T00:00:00Z','link_id':'a'*64}
    monkeypatch.setattr(website_portal,'client',lambda:Transport())
    website_portal.register(app,lambda title,body:body,lambda path:'/'+path,html.escape,
                           lambda:store,lambda oid:o,lambda offer:BytesIO(b'%PDF-synthetic'))
    c=app.test_client();page=c.get('/offer/42/portal');assert page.status_code==200
    assert 'name="product_photo:position-1"' in page.text
    assert 'name="product_photo:position-2"' in page.text
    assert 'name="product_photo:position-3"' not in page.text
    csrf=re.search(r'name="csrf" value="([^"]+)"',page.text).group(1)
    values=dict(csrf=csrf,account='test',digest=website_portal.fingerprint(o),**{'product_photo:position-2':key})
    assert c.post('/offer/42/portal',data=values).status_code==400 and not published
    values['approved']='yes'
    result=c.post('/offer/42/portal',data=values)
    assert result.status_code==302 and len(published)==1
    assert published[0][0]['lines'][1]['product_photo_id']=='product-1'
    assert set(published[0][1])=={'product-1'}
    assert store.record('test',photos.KIND,'42')['position-2']['asset_id']==key
