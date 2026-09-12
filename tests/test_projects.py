import json
from io import BytesIO
from unittest.mock import Mock
from pypdf import PdfReader
import pytest
import app as module
import project_ai
from test_persistence import isolated_storage


def test_project_survives_missing_ai_key(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    client=module.app.test_client()
    response=client.post('/projects',data={'title':'Testprojekt','notes':'11 FireProtect und ein Hub'})
    location=response.headers['Location']
    assert client.post(location+'/analyze').status_code==302
    page=module.app.test_client().get(location)
    assert '11 FireProtect' in page.text
    assert 'KI noch nicht eingerichtet' in page.text
    pdf=PdfReader(BytesIO(client.get(location+'/pdf').data))
    assert 'Kein freigegebenes Angebot' in pdf.pages[0].extract_text()


def test_ai_extract_and_provider_payload(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-only')
    value={'summary':'Rauchmelderlösung','components':[{'description':'FireProtect','quantity':11,'evidence':'11 FireProtect'}], 'questions':['Objektgröße?']}
    response=Mock(ok=True)
    response.json.return_value={'status':'completed','output':[{'content':[{'type':'output_text','text':json.dumps(value)}]}]}
    post=Mock(return_value=response)
    monkeypatch.setattr(project_ai.requests,'post',post)
    result=project_ai.extract('11 FireProtect')
    assert result['components'][0]['quantity']==11
    payload=post.call_args.kwargs['json']
    assert payload['store'] is False
    assert payload['text']['format']['strict'] is True
    assert 'tools' not in payload


def test_refusal_and_invalid_quantity_fail_closed(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-only')
    response=Mock(ok=True)
    response.json.return_value={'status':'completed','output':[{'content':[{'type':'refusal','refusal':'No'}]}]}
    monkeypatch.setattr(project_ai.requests,'post',Mock(return_value=response))
    with pytest.raises(project_ai.AIError):
        project_ai.extract('test')


def test_other_account_cannot_read_project(monkeypatch):
    client=module.app.test_client()
    monkeypatch.setenv('BILLOMAT_ID','one')
    location=client.post('/projects',data={'title':'Test'}).headers['Location']
    monkeypatch.setenv('BILLOMAT_ID','two')
    assert client.get(location).status_code==404
