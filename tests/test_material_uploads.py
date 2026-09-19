import io
import queue
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

from flask import Flask, request
from PIL import Image
import pytest

import image_classification
import material_uploads as module
from storage import OfferStore, StorageError


TOKEN = 'a' * 32
TOKEN2 = 'b' * 32
BATCH = 'c' * 32
CATEGORIES = ('Alarmanlage', 'Videoüberwachung')
SUGGESTION = dict(title='Domekamera', category='Videoüberwachung', description='Kamera innen')


def photo(color='white'):
    target = io.BytesIO()
    Image.new('RGB', (12, 18), color).save(target, format='JPEG')
    return target.getvalue()


@pytest.fixture
def service(tmp_path, monkeypatch):
    store = OfferStore(tmp_path)
    app = Flask(__name__)
    app.config['TESTING'] = True
    module.register(app, lambda: store, lambda: request.headers.get('Account', 'one'), CATEGORIES)
    # Exercise the real worker deterministically, without daemon races or network.
    work = queue.Queue(maxsize=20)
    monkeypatch.setattr(module, '_jobs', work)
    monkeypatch.setattr(module, '_pending', set())
    monkeypatch.setattr(module, '_worker', SimpleNamespace(is_alive=lambda: True))
    classifier = Mock(return_value=SUGGESTION)
    monkeypatch.setattr(module.image_classification, 'classify', classifier)
    return SimpleNamespace(store=store, app=app, client=app.test_client(), queue=work, classifier=classifier)


def prepare(service, token=TOKEN, content=None, account='one'):
    return service.client.post('/materials/batch/prepare', headers={'Account': account},
                               data={'token': token, 'image': (io.BytesIO(content if content is not None else photo()), 'Kamera.jpg')})


def run_jobs(service, monkeypatch):
    class StopWorker(BaseException):
        pass

    original_get = service.queue.get

    def get():
        if service.queue.empty():
            raise StopWorker()
        return original_get()

    with monkeypatch.context() as scoped:
        scoped.setattr(service.queue, 'get', get)
        with pytest.raises(StopWorker):
            module._run()


def commit(service, items=None, account='one', batch=BATCH):
    return service.client.post('/materials/batch/commit', headers={'Account': account},
                               json={'batch': batch, 'items': items if items is not None else [dict(token=TOKEN, **SUGGESTION)]})


def test_prepare_many_remains_staged_until_atomic_commit(service, monkeypatch):
    for token in (TOKEN, TOKEN2):
        response = prepare(service, token)
        assert response.status_code == 202 and response.json['status'] == 'queued'
    assert service.store.records('one', 'image') == {}
    assert service.queue.qsize() == 2
    run_jobs(service, monkeypatch)
    assert service.classifier.call_count == 2
    assert module._pending == set()
    assert service.queue.unfinished_tasks == 0
    for token in (TOKEN, TOKEN2):
        status = service.client.get('/materials/batch/' + token)
        assert status.json['status'] == 'ready' and status.json['category'] == 'Videoüberwachung'
        assert set(status.json) == {'token', 'title', 'category', 'description', 'status', 'message'}
    saved = commit(service, [dict(token=TOKEN, **SUGGESTION), dict(token=TOKEN2, **SUGGESTION)])
    assert saved.status_code == 200 and saved.json['count'] == 2
    assert set(service.store.records('one', 'image')) == {TOKEN, TOKEN2}


def test_invalid_second_item_rolls_back_entire_batch(service, monkeypatch):
    prepare(service)
    run_jobs(service, monkeypatch)
    result = commit(service, [dict(token=TOKEN, **SUGGESTION), dict(token=TOKEN2, **SUGGESTION)])
    assert result.status_code == 409
    assert service.store.records('one', 'image') == {}
    assert service.store.record('one', 'image_upload', TOKEN)['status'] == 'ready'
    assert service.store.record('one', 'image_upload_batch', BATCH) is None


@pytest.mark.parametrize('content', [b'', b'not an image', b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'])
def test_invalid_image_never_creates_rows_or_files(service, content):
    assert prepare(service, content=content).status_code == 400
    assert service.store.records('one', 'image_upload') == {}
    assert not (service.store.directory / 'images' / (TOKEN + '.png')).exists()
    service.classifier.assert_not_called()


@pytest.mark.parametrize('token', ['../secret', 'A' * 32, '', '123'])
def test_invalid_tokens_are_rejected_before_writing(service, token):
    assert prepare(service, token=token).status_code == 400
    assert service.store.records('one', 'image_upload') == {}


@pytest.mark.parametrize('changes', [{'category': 'Brandmeldeanlage'}, {'category': ''}, {'category': None},
                                    {'title': ''}, {'title': 'a' * 201}, {'description': 'a' * 2001},
                                    {'title': 42}])
def test_invalid_commit_fields_do_not_publish(service, monkeypatch, changes):
    prepare(service)
    run_jobs(service, monkeypatch)
    result = commit(service, [dict(token=TOKEN, **(SUGGESTION | changes))])
    assert result.status_code == 400
    assert service.store.records('one', 'image') == {}


def test_prepare_and_commit_retry_are_idempotent(service, monkeypatch):
    assert prepare(service).status_code == 202
    assert prepare(service).status_code == 200
    assert service.queue.qsize() == 1
    run_jobs(service, monkeypatch)
    for _ in range(2):
        assert commit(service).json == {'count': 1}
    assert len(service.store.records('one', 'image')) == 1
    assert service.store.record('one', 'image_upload', TOKEN)['status'] == 'committed'
    assert prepare(service).json['status'] == 'committed'
    assert service.classifier.call_count == 1


def test_changed_committed_metadata_is_not_silently_ignored(service, monkeypatch):
    prepare(service)
    run_jobs(service, monkeypatch)
    assert commit(service).status_code == 200
    changed = dict(SUGGESTION, title='Neuer Titel')
    assert commit(service, [dict(token=TOKEN, **changed)]).status_code == 409
    assert service.store.record('one', 'image', TOKEN) == SUGGESTION


def test_token_cannot_be_reused_for_another_photo(service):
    prepare(service)
    assert prepare(service, content=photo('red')).status_code == 409
    assert service.queue.qsize() == 1


def test_other_account_cannot_preview_read_or_commit_upload(service, monkeypatch):
    prepare(service)
    run_jobs(service, monkeypatch)
    assert service.client.get('/materials/batch/' + TOKEN, headers={'Account': 'two'}).status_code == 404
    assert service.client.get('/materials/batch/' + TOKEN + '/preview', headers={'Account': 'two'}).status_code == 404
    assert commit(service, account='two').status_code == 409
    assert service.store.records('one', 'image') == service.store.records('two', 'image') == {}
    assert service.client.get('/materials/batch/' + TOKEN + '/preview').mimetype == 'image/png'


def test_queue_capacity_keeps_saved_photo_recoverable(service, monkeypatch):
    for index in range(20):
        module._pending.add(('occupied', 'other', str(index)))
    assert prepare(service).status_code == 429
    assert service.store.record('one', 'image_upload', TOKEN)['status'] == 'queued'
    module._pending.clear()
    assert prepare(service).status_code == 200
    run_jobs(service, monkeypatch)
    assert service.client.get('/materials/batch/' + TOKEN).json['status'] == 'ready'


def test_status_requeues_job_after_restart(service, monkeypatch):
    prepare(service)
    service.queue.get_nowait()
    service.queue.task_done()
    module._pending.clear()
    status = service.client.get('/materials/batch/' + TOKEN)
    assert status.json['status'] == 'queued' and service.queue.qsize() == 1
    run_jobs(service, monkeypatch)
    assert service.client.get('/materials/batch/' + TOKEN).json['status'] == 'ready'


def test_unavailable_classifier_leaves_manual_review_ready(service, monkeypatch):
    service.classifier.side_effect = image_classification.Unavailable('Bildmodell fehlt')
    prepare(service)
    run_jobs(service, monkeypatch)
    result = service.client.get('/materials/batch/' + TOKEN).json
    assert result['status'] == 'ready' and result['category'] == ''
    assert result['message'] == 'Bildmodell fehlt'
    assert commit(service).status_code == 200


def test_failed_database_write_does_not_leave_unretryable_file(service, monkeypatch):
    with monkeypatch.context() as scoped:
        scoped.setattr(service.store, 'put_record', Mock(side_effect=StorageError('database temporarily unavailable')))
        with pytest.raises(StorageError):
            prepare(service)
    assert not (service.store.directory / 'images' / (TOKEN + '.png')).exists()
    assert prepare(service).status_code == 202


def test_worker_recovers_after_database_failure(service, monkeypatch):
    prepare(service)
    with monkeypatch.context() as scoped:
        scoped.setattr(service.store, 'put_record', Mock(side_effect=StorageError('database temporarily unavailable')))
        run_jobs(service, scoped)
    assert module._pending == set()
    assert service.store.record('one', 'image_upload', TOKEN)['status'] == 'queued'
    assert service.client.get('/materials/batch/' + TOKEN).status_code == 200
    run_jobs(service, monkeypatch)
    assert service.store.record('one', 'image_upload', TOKEN)['status'] == 'ready'


def test_queued_photo_cannot_be_published_early(service):
    prepare(service)
    assert commit(service).status_code == 409
    assert service.store.records('one', 'image') == {}


def test_missing_file_prevents_whole_batch_commit(service, monkeypatch):
    prepare(service)
    run_jobs(service, monkeypatch)
    (service.store.directory / 'images' / (TOKEN + '.png')).unlink()
    assert commit(service).status_code == 409
    assert service.store.records('one', 'image') == {}


def test_database_failure_mid_commit_rolls_back_first_photo_and_batch(service, monkeypatch):
    for token in (TOKEN, TOKEN2):
        prepare(service, token)
    run_jobs(service, monkeypatch)
    with sqlite3.connect(service.store.path) as db:
        db.execute("CREATE TRIGGER reject_second BEFORE INSERT ON records "
                   "WHEN NEW.kind='image' AND NEW.id='bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb' "
                   "BEGIN SELECT RAISE(ABORT, 'simulated disk failure'); END")
    with pytest.raises(StorageError):
        commit(service, [dict(token=TOKEN, **SUGGESTION), dict(token=TOKEN2, **SUGGESTION)])
    assert service.store.records('one', 'image') == {}
    assert service.store.record('one', 'image_upload_batch', BATCH) is None
    assert all(service.store.record('one', 'image_upload', token)['status'] == 'ready' for token in (TOKEN, TOKEN2))


def test_separate_accounts_can_use_same_batch_id_independently(service, monkeypatch):
    prepare(service, TOKEN, account='one')
    prepare(service, TOKEN2, account='two')
    run_jobs(service, monkeypatch)
    assert commit(service, account='one').status_code == 200
    assert commit(service, [dict(token=TOKEN2, **SUGGESTION)], account='two').status_code == 200
    assert set(service.store.records('one', 'image')) == {TOKEN}
    assert set(service.store.records('two', 'image')) == {TOKEN2}


def test_duplicate_photo_or_oversized_batch_is_rejected(service):
    repeated = [dict(token=TOKEN, **SUGGESTION)] * 2
    assert commit(service, repeated).status_code == 400
    many = [dict(token=f'{index:032x}', **SUGGESTION) for index in range(21)]
    assert commit(service, many).status_code == 400
    assert service.store.records('one', 'image') == {}
