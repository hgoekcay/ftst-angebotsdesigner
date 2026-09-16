import json
from unittest.mock import Mock
import pytest
import requests
import app as module
import local_ai
import project_ai
import projects
from test_persistence import isolated_storage

NOTES='4 Kameras und 2 Bewegungsmelder'
VALUE={'summary':'Vier Kameras und zwei Bewegungsmelder.','components':[{'description':'Kameras','quantity':4,'evidence':'4 Kameras'},{'description':'Bewegungsmelder','quantity':2,'evidence':'2 Bewegungsmelder'}],'questions':['Montage?']}


@pytest.fixture
def local(monkeypatch):
    monkeypatch.setenv('AI_PROVIDER','ollama')
    monkeypatch.setenv('OPENAI_API_KEY','must-not-use')
    monkeypatch.delenv('OLLAMA_URL',raising=False)
    response=Mock(status_code=200)
    response.json.return_value={'done':True,'done_reason':'stop','message':{'content':json.dumps(VALUE)}}
    post=Mock(return_value=response)
    monkeypatch.setattr(local_ai._http,'post',post)
    tags=Mock(status_code=200)
    tags.json.return_value={'models':[{'name':local_ai.MODEL,'digest':'model-version-1'}]}
    monkeypatch.setattr(local_ai._http,'get',Mock(return_value=tags))
    return post


def test_local_payload_no_cloud_and_limits(local):
    value=project_ai.extract(NOTES)
    assert value['provider']=='ollama' and value['components'][0]['quantity']==4
    assert local.call_count==1
    assert local.call_args.args[0]=='http://76b650ab-ftst-local-ai:11434/api/chat'
    kw=local.call_args.kwargs
    assert 'headers' not in kw and kw['allow_redirects'] is False
    assert kw['json']['stream'] is False and kw['json']['think'] is False
    assert kw['json']['options']['num_thread']==2
    assert 'tools' not in kw['json']
    assert 'must-not-use' not in json.dumps(kw)


@pytest.mark.parametrize('media',[{'image':b'png'},{'audio':('x.wav',b'voice')}])
def test_attachments_never_silently_ignored(local,media):
    with pytest.raises(project_ai.AIError,match='nur Text'): project_ai.extract(NOTES,**media)
    local.assert_not_called()


def test_timeout_no_fallback_and_releases_lock(local):
    local.side_effect=requests.Timeout()
    with pytest.raises(project_ai.AIError,match='kein Cloud-Aufruf'): project_ai.extract(NOTES)
    assert local.call_count==1
    assert local_ai._busy.acquire(blocking=False)
    local_ai._busy.release()


def test_concurrency_rejects_second(local):
    with local_ai._busy:
        with pytest.raises(project_ai.AIError,match='bereits'): project_ai.extract(NOTES)
    local.assert_not_called()


@pytest.mark.parametrize('url',['https://api.openai.com','http://example.org','http://169.254.169.254','http://76b650ab-ftst-local-ai:11434/redirect','http://user:secret@localhost:11434'])
def test_local_endpoint_rejects_public_redirect_and_credentials(local,monkeypatch,url):
    monkeypatch.setenv('OLLAMA_URL',url)
    with pytest.raises(project_ai.AIError): project_ai.extract(NOTES)
    local.assert_not_called()


@pytest.mark.parametrize('payload',[{'done':False}, {'done':True,'done_reason':'length','message':{'content':json.dumps(VALUE)}}, {'done':True,'done_reason':'stop','message':{'content':'{}'}}, {'done':True,'done_reason':'stop','message':{'content':json.dumps(dict(VALUE,components=[dict(description='Invented',quantity=2,evidence='not in notes')]))}}])
def test_incomplete_or_unsubstantiated_output_rejected(local,payload):
    local.return_value.json.return_value=payload
    with pytest.raises(project_ai.AIError): project_ai.extract(NOTES)


def test_input_limit_no_hidden_truncation(local):
    with pytest.raises(project_ai.AIError): project_ai.extract('a'*4001)
    local.assert_not_called()


def test_cache_reuses_and_force_refreshes(local):
    client=module.app.test_client()
    path=client.post('/projects',data={'title':'Local test','notes':NOTES}).location
    client.post(path+'/analyze'); client.post(path+'/analyze')
    assert local.call_count==1
    client.post(path+'/analyze',data={'force':'yes'})
    assert local.call_count==2
    client.post(path,data={'notes':NOTES+' Montage offen'})
    client.post(path+'/analyze')
    assert local.call_count==3


def test_analysis_does_not_overwrite_concurrent_edit(local,monkeypatch):
    monkeypatch.setenv('BILLOMAT_ID','test')
    client=module.app.test_client()
    path=client.post('/projects',data={'title':'Local test','notes':NOTES}).location
    key=path.rsplit('/',1)[1]
    def changed(*args,**kwargs):
        saved=module.offer_store().record('test','project',key)
        saved['notes']='new notes'
        module.offer_store().put_record('test','project',key,saved)
        return VALUE
    monkeypatch.setattr(projects,'extract',changed)
    assert client.post(path+'/analyze').status_code==409
    assert module.offer_store().record('test','project',key)['notes']=='new notes'


def test_status_and_explicit_sample(local,monkeypatch):
    response=Mock(status_code=200)
    response.json.return_value={'models':[{'name':'qwen3:4b'}]}
    monkeypatch.setattr(local_ai._http,'get',Mock(return_value=response))
    client=module.app.test_client()
    assert 'ist installiert' in client.get('/ai').text
    local.assert_not_called()
    assert client.post('/ai').status_code==400
    with client.session_transaction() as session: token=session['ai_csrf']
    assert 'Lokaler Test abgeschlossen' in client.post('/ai',data={'csrf':token}).text
    assert local.call_count==1


def test_proxy_environment_disabled():
    assert local_ai._http.trust_env is False


def test_model_change_invalidates_cache(local):
    client=module.app.test_client()
    path=client.post('/projects',data={'title':'Local test','notes':NOTES}).location
    client.post(path+'/analyze')
    local_ai._http.get.return_value.json.return_value={'models':[{'name':local_ai.MODEL,'digest':'model-version-2'}]}
    client.post(path+'/analyze')
    assert local.call_count==2


def test_quantity_must_appear_in_evidence():
    value=json.loads(json.dumps(VALUE))
    value['components'][0]['quantity']=400
    with pytest.raises(ValueError): local_ai.validate(value,NOTES)
