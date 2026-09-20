import base64
import io
import json
import threading

from PIL import Image
import pytest

import image_classification
import local_ai
import project_photo
from project_ai import AIError


@pytest.fixture
def photo():
    data = io.BytesIO()
    Image.new('RGB', (20, 30), 'white').save(data, 'PNG')
    return data.getvalue()


@pytest.fixture
def value():
    return dict(summary='Handzettel', transcript='BM 3\nMK ||||', components=[
        dict(description='BM', quantity=3, evidence='BM 3'),
        dict(description='MK', quantity=None, evidence='MK ||||')], questions=[])


@pytest.fixture
def wire(monkeypatch, value):
    calls = []
    monkeypatch.setenv('OLLAMA_VISION_MODEL', 'gemma3:4b')
    monkeypatch.setenv('OLLAMA_URL', 'http://localhost:11434')
    monkeypatch.setattr(local_ai, '_busy', threading.Lock())
    def post(url, payload, timeout):
        calls.append((url, payload, timeout))
        if url.endswith('/api/show'):
            return {'capabilities': ['vision']}
        return {'done': True, 'done_reason': 'stop', 'message': {'content': json.dumps(value)}}
    monkeypatch.setattr(image_classification, '_post', post)
    return calls


def test_local_photo_proposal_retains_abbreviations_and_review(photo, value, wire):
    result = project_photo.extract_photo(photo)
    assert result['components'] == value['components']
    assert result['provider'] == 'ollama' and result['model'] == 'gemma3:4b'
    assert result['review_required'] is True and result['questions']
    assert [c[0].rsplit('/', 1)[-1] for c in wire] == ['show', 'chat']
    assert wire[1][1]['stream'] is False and wire[1][2] == (3, 120)
    assert not local_ai._busy.locked()


@pytest.mark.parametrize('quantity', [True, float('nan'), float('inf'), 0, -1, 100001])
def test_invalid_quantity_rejected(value, quantity):
    value['components'][0]['quantity'] = quantity
    with pytest.raises(ValueError):
        project_photo._validate(value, '', 'gemma3:4b')


def test_tally_or_unbacked_quantity_becomes_question(value):
    value['components'][0]['quantity'] = 9
    value['components'][1]['quantity'] = 4
    result = project_photo._validate(value, '', 'gemma3:4b')
    assert all(c['quantity'] is None for c in result['components'])
    assert result['questions']


def test_notes_are_valid_evidence_but_not_instructions(value):
    value['components'].append(dict(description='Sirene', quantity=2, evidence='2 Sirene'))
    result = project_photo._validate(value, '2 Sirene', 'gemma3:4b')
    assert result['components'][-1]['quantity'] == 2
    value['components'][-1]['description'] = 'StreetSiren DoubleDeck'
    with pytest.raises(ValueError):
        project_photo._validate(value, '2 Sirene', 'gemma3:4b')


@pytest.mark.parametrize('change', ['extra', 'evidence', 'long', 'boollist'])
def test_strict_shape_and_bounds(value, change):
    if change == 'extra':
        value['provider'] = 'cloud'
    elif change == 'evidence':
        value['components'][0]['evidence'] = 'not on page'
    elif change == 'long':
        value['transcript'] = 'a' * 12001
    else:
        value['questions'] = False
    with pytest.raises(ValueError):
        project_photo._validate(value, '', 'gemma3:4b')


@pytest.mark.parametrize('info', [{'capabilities': ['completion']},
    {'capabilities': ['vision'], 'remote_host': 'external'},
    {'capabilities': ['vision'], 'remote_model': 'remote'}])
def test_nonlocal_or_nonvision_never_receives_image(photo, wire, monkeypatch, info):
    calls = []
    monkeypatch.setattr(image_classification, '_post', lambda *args: (calls.append(args) or info))
    with pytest.raises(AIError):
        project_photo.extract_photo(photo)
    assert len(calls) == 1 and calls[0][0].endswith('/api/show')
    assert not local_ai._busy.locked()


def test_busy_and_missing_model_do_not_send(photo, wire, monkeypatch):
    local_ai._busy.acquire()
    with pytest.raises(AIError):
        project_photo.extract_photo(photo)
    local_ai._busy.release()
    monkeypatch.delenv('OLLAMA_VISION_MODEL')
    with pytest.raises(AIError):
        project_photo.extract_photo(photo)
    assert not wire


def test_bad_response_releases_gate(photo, wire, monkeypatch):
    def post(url, *args):
        return {'capabilities': ['vision']} if url.endswith('show') else {'done': False}
    monkeypatch.setattr(image_classification, '_post', post)
    with pytest.raises(AIError):
        project_photo.extract_photo(photo)
    assert not local_ai._busy.locked()


def test_preview_strips_metadata_and_limits_dimensions():
    source = io.BytesIO()
    image = Image.new('RGB', (1700, 20), 'white')
    exif = Image.Exif()
    exif[270] = 'private metadata'
    image.save(source, 'JPEG', exif=exif)
    preview = Image.open(io.BytesIO(base64.b64decode(project_photo._preview(source.getvalue()))))
    assert max(preview.size) <= 1600 and not preview.getexif()


def test_invalid_photo_rejected_before_transport(wire):
    with pytest.raises(AIError):
        project_photo.extract_photo(b'not an image')
    assert not wire


def test_multiple_numbers_never_choose_an_arbitrary_count(value):
    value['transcript'] = 'BM 3, MK 2'
    value['components'] = [dict(description='BM', quantity=3, evidence='BM 3, MK 2')]
    result = project_photo._validate(value, '', 'gemma3:4b')
    assert result['components'][0]['quantity'] is None and result['questions']


def test_component_must_belong_to_its_evidence(value):
    value['components'][0]['evidence'] = 'MK ||||'
    with pytest.raises(ValueError):
        project_photo._validate(value, '', 'gemma3:4b')


def test_evidence_limit_matches_editable_ui(value):
    assert project_photo.SCHEMA['properties']['components']['items']['properties']['evidence']['maxLength'] == 500
    value['transcript'] = 'BM ' + 'a' * 498
    value['components'] = [dict(description='BM', quantity=None, evidence=value['transcript'])]
    with pytest.raises(ValueError):
        project_photo._validate(value, '', 'gemma3:4b')
    value['components'][0]['evidence'] = value['transcript'][:500]
    assert project_photo._validate(value, '', 'gemma3:4b')['components']


def test_unicode_photo_text_is_retained(value):
    text = 'Hüseyin Gökçay – Türöffnungsmelder 2'
    value.update(transcript=text, summary='Prüfung für Hüseyin Gökçay',
                 components=[dict(description='Türöffnungsmelder', quantity=2, evidence=text)])
    result = project_photo._validate(value, '', 'gemma3:4b')
    assert result['transcript'] == text and result['components'][0]['quantity'] == 2


@pytest.mark.parametrize('url', ['https://example.com', 'http://localhost:11434/api/chat',
                                'http://user:password@localhost:11434'])
def test_unsafe_endpoint_never_receives_photo(photo, wire, monkeypatch, url):
    monkeypatch.setenv('OLLAMA_URL', url)
    with pytest.raises(AIError):
        project_photo.extract_photo(photo)
    assert not wire


def test_cloud_model_never_receives_photo(photo, wire, monkeypatch):
    monkeypatch.setenv('OLLAMA_VISION_MODEL', 'gemma3:cloud')
    with pytest.raises(AIError):
        project_photo.extract_photo(photo)
    assert not wire


def test_question_budget_reserves_uncertain_quantity_question(value):
    schema = project_photo.SCHEMA['properties']['questions']
    assert schema['maxItems'] == 9 and schema['items']['maxLength'] == 300
    questions = [str(n) + '?' + 'a' * 298 for n in range(9)]
    value['questions'] = questions.copy()
    result = project_photo._validate(value, '', 'gemma3:4b')
    assert len(result['questions']) == 10
    assert result['questions'][:9] == questions
    assert 'unklare Mengen' in result['questions'][-1]
    assert value['questions'] == questions


@pytest.mark.parametrize('questions', [['Frage?'] * 10, ['x' * 301]])
def test_excess_questions_rejected_without_truncation(value, questions):
    value['questions'] = questions
    with pytest.raises(ValueError):
        project_photo._validate(value, '', 'gemma3:4b')
    assert value['questions'] == questions
