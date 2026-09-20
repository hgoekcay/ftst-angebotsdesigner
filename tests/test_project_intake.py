import hashlib
import html
import json
import re
import threading
import time
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

import app as module
import project_intake as intake
from project_ai import AIError
from test_persistence import isolated_storage

PATH = '/projects/job-1/intake'
HEADERS = {'X-Ingress-Path': '/api/hassio_ingress/intake-test'}
SUGGESTION = {'summary': 'Handzettel mit BM und MK', 'transcript': '2 BM\nMK |||',
              'components': [{'description': 'BM', 'quantity': 2, 'evidence': '2 BM'},
                             {'description': 'MK', 'quantity': None, 'evidence': 'MK |||'}],
              'questions': ['Wie viele MK sind gemeint?'], 'provider': 'ollama', 'model': 'gemma3:4b',
              'review_required': True}


def image(color='white', format='PNG'):
    output = BytesIO()
    Image.new('RGB', (20, 20), color).save(output, format=format)
    output.seek(0)
    return output


def fields(client, **changes):
    response = client.get(PATH, headers=HEADERS)
    assert response.status_code == 200
    values = {key: html.unescape(value) for key, value in re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', response.text)
              if key in ('csrf', 'revision', 'project_revision', 'account')}
    values.update(action='upload', manufacturer='Ajax', customer_name='Firma Test', object_address='Teststraße 1',
                  central='unknown', siren='unknown', area='inside', variant='', installation='', travel='',
                  notes='2 BM und MK Strichliste', summary='', questions='', description=[''], quantity=[''], evidence=[''])
    values.update(changes)
    return values


def wait_finished(store):
    deadline = time.monotonic() + 3
    while intake.working(store, 'one', 'job-1') and time.monotonic() < deadline:
        time.sleep(.01)
    assert not intake.working(store, 'one', 'job-1')
    return store.record('one', intake.KIND, 'job-1')


@pytest.fixture
def ui(isolated_storage, monkeypatch):
    monkeypatch.setenv('BILLOMAT_ID', 'one')
    monkeypatch.setenv('FTST_REQUIRE_INGRESS', '0')
    store = module.offer_store()
    project = dict(title='Technikerprojekt', notes='Originalnotiz', analysis={}, offer_id='')
    store.put_record('one', 'project', 'job-1', project)
    model = Mock(return_value=deepcopy(SUGGESTION))
    monkeypatch.setattr(intake, 'extract_photo', model)
    return module.app.test_client(), store, model, project


def upload(ui, **extra):
    client, store, _, _ = ui
    data = fields(client, **extra)
    data['photo'] = (image(), 'notiz.png')
    response = client.post(PATH, data=data, headers=HEADERS)
    assert response.status_code == 303
    return store.record('one', intake.KIND, 'job-1')


def test_get_and_project_link_never_trigger_analysis(ui):
    client, store, model, _ = ui
    page = client.get(PATH, headers=HEADERS)
    assert page.status_code == 200 and page.headers['Cache-Control'] == 'no-store'
    assert 'name="manufacturer" maxlength="100" value="Ajax"' in page.text
    assert page.text.index('value="upload"') < page.text.index('Komponenten prüfen')
    assert '/api/hassio_ingress/intake-test/projects/job-1' in page.text
    assert '/api/hassio_ingress/intake-test/projects/job-1/intake' in client.get('/projects/job-1', headers=HEADERS).text
    assert store.record('one', intake.KIND, 'job-1') is None
    model.assert_not_called()


@pytest.mark.parametrize('csrf', [None, '', '-', 'forged', 'ungültig'])
def test_missing_or_forged_csrf_cannot_write(ui, csrf):
    client, store, model, project = ui
    values = {'action': 'apply', 'reviewed': 'yes'}
    if csrf is not None:
        values['csrf'] = csrf
    assert client.post(PATH, data=values).status_code == 400
    assert store.record('one', 'project', 'job-1') == project
    assert store.record('one', intake.KIND, 'job-1') is None
    model.assert_not_called()


def test_other_account_cannot_read_photo_or_apply_form(ui, monkeypatch):
    client, store, model, _ = ui
    upload(ui)
    values = fields(client, action='apply', reviewed='yes', description=['BM'], quantity=['2'], evidence=['2 BM'])
    monkeypatch.setenv('BILLOMAT_ID', 'two')
    assert client.get(PATH).status_code == 404
    assert client.get(PATH + '/photo').status_code == 404
    store.put_record('two', 'project', 'job-1', {'title': 'Other', 'notes': '', 'analysis': {}})
    assert client.post(PATH, data=values).status_code == 409
    assert store.record('two', intake.KIND, 'job-1') is None
    model.assert_not_called()


def test_save_photo_is_private_immutable_and_never_auto_applied(ui):
    client, store, model, project = ui
    first = upload(ui)
    path = intake.private_folder(store, 'one', 'job-1') / first['photo']['name']
    original = path.read_bytes()
    assert hashlib.sha256(original).hexdigest() == first['photo']['sha256']
    assert store.records('one', 'image') == {}
    assert store.record('one', 'project', 'job-1') == project
    assert client.get(PATH + '/photo').mimetype == 'image/jpeg'
    data = fields(client)
    data['photo'] = (image('red'), 'new.png')
    assert client.post(PATH, data=data).status_code == 303
    second = store.record('one', intake.KIND, 'job-1')
    assert first['photo']['name'] != second['photo']['name']
    assert path.read_bytes() == original
    assert second['source_changed'] is True
    model.assert_not_called()


def test_manual_components_apply_only_after_checkbox_and_keep_open_questions(ui):
    client, store, model, _ = ui
    values = fields(client, action='apply', description=['BM', 'Ajax MK'], quantity=['2', '1,5'], evidence=['2 BM', 'Technikerangabe'])
    assert client.post(PATH, data=values).status_code == 400
    assert store.record('one', 'project', 'job-1')['analysis'] == {}
    values['reviewed'] = 'yes'
    assert client.post(PATH, data=values, headers=HEADERS).status_code == 303
    project = store.record('one', 'project', 'job-1')
    assert project['customer_name'] == 'Firma Test' and project['object_address'] == 'Teststraße 1'
    assert [r['description'] for r in project['analysis']['components']] == ['Ajax BM', 'Ajax MK']
    assert [r['quantity'] for r in project['analysis']['components']] == ['2', '1.5']
    assert all(r['user_confirmed'] for r in project['analysis']['components'])
    assert len(project['analysis']['questions']) == 4
    assert 'Montage / Arbeitsumfang: Offen' in project['notes'] and 'Anfahrt / Einsatzort: Offen' in project['notes']
    assert not any('price' in row for row in project['analysis']['components'])
    assert store.record('one', intake.KIND, 'job-1')['review_required'] is False
    assert 'Kalkulation öffnen' in client.get(PATH).text
    model.assert_not_called()


@pytest.mark.parametrize('count', ['', '0', '-1', 'NaN', 'Infinity', '100001', '1.0001'])
def test_unknown_or_invalid_quantity_cannot_be_confirmed(ui, count):
    client, store, _, _ = ui
    values = fields(client, action='apply', reviewed='yes', description=['BM'], quantity=[count], evidence=['unklar'])
    assert client.post(PATH, data=values).status_code == 400
    assert store.record('one', 'project', 'job-1')['analysis'] == {}


def test_too_many_components_and_combined_questions_rejected(ui):
    client, store, _, _ = ui
    values = fields(client, description=['BM'] * 31, quantity=['1'] * 31, evidence=['Beleg'] * 31)
    assert client.post(PATH, data=values).status_code == 400
    values = fields(client, questions='\n'.join('Frage ' + str(n) for n in range(28)))
    response = client.post(PATH, data=values)
    assert response.status_code == 400 and 'Pflichtangaben' in response.text
    assert store.record('one', intake.KIND, 'job-1') is None


def test_upload_byte_and_pixel_limits_without_large_test_files(monkeypatch):
    assert intake.MAX_PHOTO_BYTES == 20 * 1024 * 1024
    monkeypatch.setattr(intake, 'MAX_PHOTO_BYTES', 32)
    with pytest.raises(ValueError, match='20 MB'):
        intake.photo_bytes(SimpleNamespace(stream=BytesIO(b'x' * 33)))
    monkeypatch.setattr(intake.Image, 'open', lambda _: SimpleNamespace(format='PNG', width=5001, height=5000))
    with pytest.raises(ValueError, match='25 Megapixel'):
        intake.photo_bytes(SimpleNamespace(stream=BytesIO(b'small-header')))


@pytest.mark.parametrize('content', [b'invalid', None])
def test_invalid_or_unsupported_photo_never_replaces_source(ui, content):
    client, store, model, _ = ui
    first = upload(ui)
    data = fields(client)
    data['photo'] = (BytesIO(content) if content is not None else image(format='GIF'), 'photo.jpg')
    assert client.post(PATH, data=data).status_code == 400
    assert store.record('one', intake.KIND, 'job-1') == first
    model.assert_not_called()


def test_photo_suggestion_is_async_and_requires_manual_review(ui):
    client, store, model, project = ui
    upload(ui)
    assert client.post(PATH, data=fields(client, action='analyze')).status_code == 303
    result = wait_finished(store)
    assert result['status'] == 'review' and result['review_required'] is True
    assert result['components'][1]['quantity'] == ''
    assert 'Zentrale' in model.call_args.args[1] and 'Montage' in model.call_args.args[1]
    assert store.record('one', 'project', 'job-1') == project
    assert len(result['questions']) == 5
    page = client.get(PATH)
    assert 'Erkannter Fototext' in page.text and 'Wie viele MK' in page.text
    assert model.call_count == 1


def test_live_refresh_disables_editing_and_duplicate_analysis(ui):
    client, store, model, _ = ui
    entered, release = threading.Event(), threading.Event()
    def paused(*args):
        entered.set()
        assert release.wait(3)
        return deepcopy(SUGGESTION)
    model.side_effect = paused
    upload(ui)
    try:
        assert client.post(PATH, data=fields(client, action='analyze')).status_code == 303
        assert entered.wait(1)
        page = client.get(PATH)
        assert 'http-equiv="refresh"' in page.text
        assert re.search(r'<fieldset[^>]* disabled>', page.text)
        assert client.post(PATH, data=fields(client, action='analyze')).status_code == 409
        assert model.call_count == 1
    finally:
        release.set()
        wait_finished(store)


def test_changed_intake_discards_late_photo_suggestion(ui):
    client, store, model, _ = ui
    entered, release = threading.Event(), threading.Event()
    def paused(*args):
        entered.set()
        assert release.wait(3)
        return deepcopy(SUGGESTION)
    model.side_effect = paused
    upload(ui)
    try:
        assert client.post(PATH, data=fields(client, action='analyze')).status_code == 303
        assert entered.wait(1)
        changed = fields(client, notes='Neuere Technikerangaben', description=['Sirene'], quantity=['1'], evidence=['Nachgetragen'])
        assert client.post(PATH, data=changed).status_code == 303
        newer = store.record('one', intake.KIND, 'job-1')
    finally:
        release.set()
        finished = wait_finished(store)
    assert finished == newer and finished['components'][0]['description'] == 'Sirene'
    assert store.record('one', 'project', 'job-1')['analysis'] == {}


def test_changed_project_discards_late_photo_suggestion(ui):
    client, store, model, project = ui
    def changed(*args):
        store.put_record('one', 'project', 'job-1', dict(project, notes='Geänderte Anforderungen'))
        return deepcopy(SUGGESTION)
    model.side_effect = changed
    upload(ui)
    assert client.post(PATH, data=fields(client, action='analyze')).status_code == 303
    result = wait_finished(store)
    assert result['status'] == 'stale' and 'verworfen' in result['error']
    assert store.record('one', 'project', 'job-1')['notes'] == 'Geänderte Anforderungen'


def test_changed_photo_hash_blocks_ai_call(ui):
    client, store, model, _ = ui
    value = upload(ui)
    (intake.private_folder(store, 'one', 'job-1') / value['photo']['name']).write_bytes(b'changed')
    assert client.post(PATH, data=fields(client, action='analyze')).status_code == 303
    result = wait_finished(store)
    assert result['status'] == 'editing' and 'Foto wurde geändert' in result['error']
    model.assert_not_called()


def test_source_text_over_limit_cannot_start_ai_but_manual_save_is_available(ui):
    client, store, model, _ = ui
    upload(ui, notes='a' * 3900)
    values = fields(client, action='analyze')
    result = client.post(PATH, data=values)
    assert result.status_code == 400 and '4000 Zeichen' in result.text
    assert store.record('one', intake.KIND, 'job-1')['status'] != 'analyzing'
    model.assert_not_called()


def test_ai_failure_keeps_photo_and_project_and_does_not_retry_on_get(ui):
    client, store, model, project = ui
    before = upload(ui)
    model.side_effect = AIError('Lokales Modell fehlt.')
    assert client.post(PATH, data=fields(client, action='analyze')).status_code == 303
    result = wait_finished(store)
    assert result['photo'] == before['photo'] and result['error'] == 'Lokales Modell fehlt.'
    assert store.record('one', 'project', 'job-1') == project
    assert 'Lokales Modell fehlt.' in client.get(PATH).text
    assert model.call_count == 1


def test_stale_apply_never_overwrites_other_edit(ui):
    client, store, _, project = ui
    values = fields(client, action='apply', reviewed='yes', description=['BM'], quantity=['2'], evidence=['2 BM'])
    store.put_record('one', 'project', 'job-1', dict(project, notes='Parallel geändert'))
    response = client.post(PATH, data=values)
    assert response.status_code == 409
    hidden = {key: html.unescape(value) for key, value in re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', response.text)
              if key in ('revision', 'project_revision')}
    assert hidden['revision'] == values['revision'] and hidden['project_revision'] == values['project_revision']
    assert client.post(PATH, data=dict(values, **hidden)).status_code == 409
    assert store.record('one', 'project', 'job-1')['notes'] == 'Parallel geändert'
    assert store.record('one', 'project', 'job-1')['analysis'] == {}


def test_invalid_quantity_form_keeps_unsaved_description_and_value(ui):
    client, store, _, _ = ui
    values = fields(client, action='apply', reviewed='yes', description=['Meine neue Zeile'], quantity=['0'], evidence=['Neue Ergänzung'])
    response = client.post(PATH, data=values)
    assert response.status_code == 400
    assert 'value="Meine neue Zeile"' in response.text and 'value="Neue Ergänzung"' in response.text
    assert 'name="quantity" maxlength="20" value="0"' in response.text
    assert store.record('one', intake.KIND, 'job-1') is None


def test_source_change_preserves_components_but_marks_them_for_review(ui):
    client, store, _, _ = ui
    upload(ui)
    assert client.post(PATH, data=fields(client, action='analyze')).status_code == 303
    result = wait_finished(store)
    data = fields(client, notes='Neuere Angaben', description=[r['description'] for r in result['components']],
                  quantity=[r['quantity'] for r in result['components']], evidence=[r['evidence'] for r in result['components']])
    assert client.post(PATH, data=data).status_code == 303
    assert store.record('one', intake.KIND, 'job-1')['source_changed'] is True
    assert 'Vorhandene Komponenten erneut prüfen' in client.get(PATH).text


def test_file_written_before_conflicting_transaction_is_cleaned_up(ui, monkeypatch):
    client, store, _, project = ui
    original = type(store).transact_record
    def race(self, identity, kind, key, change):
        if kind == intake.KIND:
            self.put_record(identity, 'project', key, dict(project, notes='Zeitgleiche Änderung'))
        return original(self, identity, kind, key, change)
    monkeypatch.setattr(type(store), 'transact_record', race)
    data = fields(client)
    data['photo'] = (image(), 'photo.png')
    assert client.post(PATH, data=data).status_code == 409
    assert not list(intake.private_folder(store, 'one', 'job-1').glob('*.jpg'))
    assert store.record('one', intake.KIND, 'job-1') is None
