import base64
import io
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image
import pytest
import requests

import image_classification as module
import local_ai


CATEGORIES = ['Alarmanlage', 'Videoüberwachung', 'Kombination']
VALUE = {'title': 'Domekamera an der Decke', 'category': 'Videoüberwachung',
         'description': 'Montierte Kamera im Innenbereich.', 'confidence': 0.9}


def picture(size=(16, 16)):
    target = io.BytesIO()
    image = Image.new('RGB', size, 'white')
    metadata = Image.Exif()
    metadata[270] = 'Private Adresse nicht übertragen'
    image.save(target, format='JPEG', exif=metadata)
    return target.getvalue()


def response(value, status=200):
    result = Mock(status_code=status)
    result.iter_content.return_value = [json.dumps(value).encode()]
    return result


def completion(value=None, **kwargs):
    return dict(done=True, done_reason='stop', message={'content': json.dumps(value or VALUE)}, **kwargs)


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv('OLLAMA_VISION_MODEL', 'gemma3:4b')
    monkeypatch.delenv('OLLAMA_URL', raising=False)
    monkeypatch.setenv('OPENAI_API_KEY', 'must-not-use')
    post = Mock(side_effect=[response({'capabilities': ['completion', 'vision']}), response(completion())])
    monkeypatch.setattr(module._http, 'post', post)
    return post


def test_model_is_opt_in_and_absence_makes_no_network_request(server, monkeypatch):
    monkeypatch.delenv('OLLAMA_VISION_MODEL')
    assert module.configured_model() == ''
    with pytest.raises(module.Unavailable, match='noch nicht eingerichtet'):
        module.classify(picture(), CATEGORIES)
    server.assert_not_called()


def test_local_request_removes_metadata_and_limits_pixels_and_returns_editable_result(server):
    result = module.classify(picture((2000, 1500)), CATEGORIES)
    assert result == dict(VALUE, source='ollama:gemma3:4b', review_required=True)
    assert server.call_count == 2
    assert server.call_args_list[0].args[0].endswith('/api/show')
    call = server.call_args
    assert call.args[0] == 'http://76b650ab-ftst-local-ai:11434/api/chat'
    assert call.kwargs['allow_redirects'] is False
    assert call.kwargs['stream'] is True
    assert call.kwargs['timeout'] == (3, 120)
    assert 'verify' not in call.kwargs and 'headers' not in call.kwargs
    payload = call.kwargs['json']
    assert payload['keep_alive'] == 0 and payload['stream'] is False
    assert 'tools' not in payload and 'must-not-use' not in json.dumps(payload)
    preview = Image.open(io.BytesIO(base64.b64decode(payload['messages'][1]['images'][0])))
    assert preview.size == (1024, 768) and not preview.getexif()
    assert module._http.trust_env is False


@pytest.mark.parametrize('info', [
    {'capabilities': ['completion']},
    {'capabilities': ['vision'], 'remote_host': 'https://ollama.com'},
    {'capabilities': ['vision'], 'remote_model': 'remote-model'},
])
def test_text_only_and_cloud_backed_models_never_receive_photo(server, info):
    server.side_effect = [response(info)]
    with pytest.raises(module.Unavailable, match='lokales Vision-Modell'):
        module.classify(picture(), CATEGORIES)
    assert server.call_count == 1
    assert 'images' not in json.dumps(server.call_args.kwargs['json'])


@pytest.mark.parametrize('model', ['gemma3:cloud', 'evil-cloud:4b', 'https://remote/model', '../model'])
def test_cloud_model_or_invalid_name_rejected_without_request(server, monkeypatch, model):
    monkeypatch.setenv('OLLAMA_VISION_MODEL', model)
    with pytest.raises(module.Unavailable):
        module.classify(picture(), CATEGORIES)
    server.assert_not_called()


@pytest.mark.parametrize('url', ['https://api.openai.com', 'http://example.com', 'http://localhost:11434/redirect'])
def test_public_endpoint_and_paths_rejected_without_request(server, monkeypatch, url):
    monkeypatch.setenv('OLLAMA_URL', url)
    with pytest.raises(module.Unavailable):
        module.classify(picture(), CATEGORIES)
    server.assert_not_called()


def test_uncertain_category_is_never_assigned(server):
    server.side_effect = [response({'capabilities': ['vision']}), response(completion(dict(VALUE, confidence=0.7)))]
    result = module.classify(picture(), CATEGORIES)
    assert result['category'] == '' and result['review_required'] is True


@pytest.mark.parametrize('value', [dict(VALUE, category='Invented'), dict(VALUE, confidence=True),
                                  dict(VALUE, confidence=float('nan')), dict(VALUE, confidence=3),
                                  dict(VALUE, title='<script>x</script>'), dict(VALUE, title=''),
                                  dict(VALUE, description='a' * 501)])
def test_invalid_output_is_not_returned_as_valid_classification(server, value):
    server.side_effect = [response({'capabilities': ['vision']}), response(completion(value))]
    with pytest.raises(module.Unavailable, match='keinen verlässlichen'):
        module.classify(picture(), CATEGORIES)


@pytest.mark.parametrize('failure', [requests.Timeout(), requests.ConnectionError()])
def test_network_failure_releases_shared_lock_without_fallback(server, failure):
    server.side_effect = failure
    with pytest.raises(module.Unavailable):
        module.classify(picture(), CATEGORIES)
    assert server.call_count == 1
    assert local_ai._busy.acquire(blocking=False)
    local_ai._busy.release()


def test_concurrent_text_analysis_has_bounded_wait_without_parallel_image_request(server, monkeypatch):
    monkeypatch.setattr(module, 'LOCK_WAIT_SECONDS', 0)
    with local_ai._busy:
        with pytest.raises(module.Unavailable, match='weiterhin beschäftigt'):
            module.classify(picture(), CATEGORIES)
    server.assert_not_called()


def test_background_photo_waits_for_text_analysis_and_resumes_after_release(server, monkeypatch):
    gate = threading.Lock()
    gate.acquire()
    waiting = threading.Event()
    captured_timeouts, results, failures = [], [], []

    def acquire(*, timeout):
        captured_timeouts.append(timeout)
        waiting.set()
        return gate.acquire(timeout=timeout)

    monkeypatch.setattr(module, 'LOCK_WAIT_SECONDS', 1)
    monkeypatch.setattr(local_ai, '_busy', SimpleNamespace(acquire=acquire, release=gate.release))

    def classify_in_background():
        try:
            results.append(module.classify(picture(), CATEGORIES))
        except Exception as exc:
            failures.append(exc)

    worker = threading.Thread(target=classify_in_background, daemon=True)
    worker.start()
    try:
        assert waiting.wait(timeout=2), 'Photo worker must reach the shared gate'
        assert captured_timeouts == [1]
        server.assert_not_called()
    finally:
        gate.release()
        worker.join(timeout=2)
    assert not worker.is_alive()
    assert failures == []
    assert results == [dict(VALUE, source='ollama:gemma3:4b', review_required=True)]
    assert server.call_count == 2
    assert not gate.locked()


def test_oversized_response_stops_reading_and_closes_connection(server):
    giant = response({})
    giant.iter_content.return_value = [b'x' * 4096] * (module.MAX_RESPONSE_BYTES // 4096 + 2)
    server.side_effect = [giant]
    with pytest.raises(module.Unavailable):
        module.classify(picture(), CATEGORIES)
    giant.close.assert_called_once()


def test_redirect_is_not_followed_and_missing_model_is_not_downloaded(server):
    unavailable = response({}, status=302)
    server.side_effect = [unavailable]
    with pytest.raises(module.Unavailable):
        module.classify(picture(), CATEGORIES)
    assert server.call_count == 1
    unavailable.close.assert_called_once()


@pytest.mark.parametrize('data', [b'', b'invalid image'])
def test_invalid_photo_rejected_before_network(server, data):
    with pytest.raises(module.Unavailable):
        module.classify(data, CATEGORIES)
    server.assert_not_called()


def test_input_byte_limit_applies_before_decoding(server, monkeypatch):
    monkeypatch.setattr(module, 'MAX_INPUT_BYTES', 10)
    with pytest.raises(module.Unavailable, match='zu groß'):
        module.classify(b'x' * 11, CATEGORIES)
    server.assert_not_called()


def test_pixel_limit_applies_before_network(server, monkeypatch):
    monkeypatch.setattr(module, 'MAX_PIXELS', 10)
    with pytest.raises(module.Unavailable):
        module.classify(picture(), CATEGORIES)
    server.assert_not_called()


@pytest.mark.parametrize('reply', [
    {'done': False},
    {'done': True, 'done_reason': 'length', 'message': {'content': json.dumps(VALUE)}},
    {'done': True, 'done_reason': 'stop', 'message': {'content': json.dumps(VALUE), 'tool_calls': [{'name': 'arbitrary'}]}},
])
def test_incomplete_or_tool_invoking_response_is_rejected(server, reply):
    server.side_effect = [response({'capabilities': ['vision']}), response(reply)]
    with pytest.raises(module.Unavailable):
        module.classify(picture(), CATEGORIES)


def test_stream_deadline_rejects_slow_response_and_closes_connection(server, monkeypatch):
    reply = response({'capabilities': ['vision']})
    monkeypatch.setattr(module.time, 'monotonic', Mock(side_effect=[0, 100]))
    server.side_effect = [reply]
    with pytest.raises(module.Unavailable):
        module.classify(picture(), CATEGORIES)
    reply.close.assert_called_once()
