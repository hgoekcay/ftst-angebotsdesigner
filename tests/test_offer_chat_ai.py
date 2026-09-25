import json
from copy import deepcopy

import offer_chat_ai as chat_ai
import pytest

SOURCE = 'Für Hüseyin Beispiel, Hafenstraße 15, 68305 Mannheim. Mail kunde@example.org. Sechs Bewegungsmelder und zwei Türkontakte.'


def test_address_block_preserves_draft_without_model(monkeypatch):
    def unavailable(*args, **kwargs):
        pytest.fail('Postal address must not require the model')
    monkeypatch.setattr(chat_ai, 'request_local', unavailable)
    previous = value()
    original = deepcopy(previous)
    result = chat_ai.extract(previous, [{'role': 'user', 'text':
        'Hüseyin Beispiel\nBeispielstrasse 10\n12345 Beispielstadt'}])
    assert result['name'] == 'Hüseyin Beispiel'
    assert result['street'] == 'Beispielstrasse 10'
    assert result['zip'] == '12345' and result['city'] == 'Beispielstadt'
    assert result['rows'] == previous['rows']
    assert result['recipient'] == previous['recipient']
    assert result['country_code'] == ''
    result['rows'][0]['quantity'] = 99
    assert previous == original


@pytest.mark.parametrize('text', [
    '6 Bewegungsmelder\n2 Türkontakte\n1 Sirene',
    'Testkunde\nBeispielstrasse 10\n12345 Beispielstadt\nstatt 6 jetzt 8 Bewegungsmelder',
    'Testkunde\nUnbekannt\n12345 Beispielstadt',
    'Testkunde\nBeispielstrasse 10\nBeispielstadt',
])
def test_ambiguous_or_mixed_message_still_requires_model(text):
    assert chat_ai.address_update(chat_ai.EMPTY, text) is None


def value():
    return deepcopy(chat_ai.EMPTY) | {
        'name': 'Hüseyin Beispiel', 'street': 'Hafenstraße 15', 'zip': '68305',
        'city': 'Mannheim', 'recipient': 'kunde@example.org', 'title': 'Alarmanlage',
        'rows': [{'description': 'Bewegungsmelder', 'quantity': 6,
                  'evidence': 'Sechs Bewegungsmelder'},
                 {'description': 'Türkontakte', 'quantity': 2, 'evidence': 'zwei Türkontakte'}],
    }


def run(monkeypatch, model_value, source=SOURCE, state=None):
    def request(context, prompt, schema, validator, **kwargs):
        return validator(model_value, context)
    monkeypatch.setattr(chat_ai, 'request_local', request)
    return chat_ai.extract(state or chat_ai.EMPTY, [{'role': 'user', 'text': source}])


def test_valid_unicode_full_state_is_copied(monkeypatch):
    model_value = value()
    result = run(monkeypatch, model_value)
    assert result == model_value
    result['rows'][0]['quantity'] = 1
    assert model_value['rows'][0]['quantity'] == 6


def test_latest_explicit_correction_cannot_reuse_old_quantity(monkeypatch):
    latest = 'Korrektur: statt 6 jetzt 8 Bewegungsmelder. Die 2 Türkontakte bleiben unverändert.'
    model_value = value()
    def request(context, prompt, schema, validator, **kwargs):
        assert json.loads(context)['neueste_nachricht'] == latest
        return validator(model_value, context)
    monkeypatch.setattr(chat_ai, 'request_local', request)
    messages = [{'role': 'user', 'text': SOURCE}, {'role': 'user', 'text': latest}]
    with pytest.raises(ValueError, match='Mengenkorrektur'):
        chat_ai.extract(value(), messages)
    model_value['rows'][0].update(quantity=8, evidence='statt 6 jetzt 8 Bewegungsmelder')
    assert chat_ai.extract(value(), messages)['rows'][0]['quantity'] == 8


@pytest.mark.parametrize('key,text', [('name', 'Erfundene GmbH'), ('recipient', 'hacker@example.org'),
                                    ('street', 'Andere Straße 42'), ('zip', '99999'), ('city', 'Berlin')])
def test_contact_must_come_from_user(monkeypatch, key, text):
    model_value = value()
    model_value[key] = text
    with pytest.raises(ValueError, match='Kundendaten'):
        run(monkeypatch, model_value)


@pytest.mark.parametrize('quantity', [7, float('nan'), float('inf'), -1, 0, True, '6'])
def test_unsupported_or_invalid_quantities(monkeypatch, quantity):
    model_value = value()
    model_value['rows'][0]['quantity'] = quantity
    with pytest.raises(ValueError):
        run(monkeypatch, model_value)


def test_absent_quantity_stays_unknown(monkeypatch):
    model_value = deepcopy(chat_ai.EMPTY)
    model_value['rows'] = [{'description': 'Bewegungsmelder', 'quantity': None, 'evidence': 'Bewegungsmelder'}]
    assert run(monkeypatch, model_value, 'Bewegungsmelder')['rows'][0]['quantity'] is None


@pytest.mark.parametrize('change', ['missing', 'extra', 'price', 'action', 'badrows', 'questions', 'evidence'])
def test_wrong_schema_and_unsupported_evidence(monkeypatch, change):
    model_value = value()
    if change == 'missing':
        del model_value['name']
    elif change == 'extra':
        model_value['send_email'] = True
    elif change in ('price', 'action'):
        model_value['rows'][0][change] = 100
    elif change == 'badrows':
        model_value['rows'] = 'six'
    elif change == 'questions':
        model_value['questions'] = {'send': True}
    else:
        model_value['rows'][0]['evidence'] = 'Nicht vom Benutzer genannt'
    with pytest.raises(ValueError):
        run(monkeypatch, model_value)


def test_maximum_twenty_rows(monkeypatch):
    model_value = value()
    model_value['rows'] = [deepcopy(model_value['rows'][0]) for _ in range(20)]
    assert len(run(monkeypatch, model_value)['rows']) == 20
    model_value['rows'].append(deepcopy(model_value['rows'][0]))
    with pytest.raises(ValueError, match='20'):
        run(monkeypatch, model_value)


def test_full_state_and_user_history_sent_not_assistant_claims(monkeypatch):
    state = value()
    messages = [{'role': 'user', 'text': SOURCE}, {'role': 'assistant', 'text': 'Invented private data'},
                {'role': 'user', 'text': 'Jetzt acht Bewegungsmelder.'}]
    def request(context, prompt, schema, validator, **kwargs):
        parsed = json.loads(context)
        assert parsed['bisher'] == state
        assert parsed['Benutzernachrichten'] == SOURCE + '\nJetzt acht Bewegungsmelder.'
        assert kwargs == {'max_chars': 12000, 'num_ctx': 8192, 'num_predict': 2400}
        assert schema['additionalProperties'] is False
        return 'checked'
    monkeypatch.setattr(chat_ai, 'request_local', request)
    assert chat_ai.extract(state, messages) == 'checked'


def test_context_limit_does_not_truncate_or_call_model(monkeypatch):
    monkeypatch.setattr(chat_ai, 'request_local', lambda *_args, **_kwargs: pytest.fail('must not call'))
    with pytest.raises(ValueError, match='umfangreich'):
        chat_ai.extract(value(), [{'role': 'user', 'text': 'x' * 12001}])


@pytest.mark.parametrize('code,country', [('DE', 'Deutschland'), ('AT', 'Österreich'),
                                        ('CH', 'Schweiz'), ('FR', 'Frankreich')])
def test_country_requires_source_and_allows_name(monkeypatch, code, country):
    model_value = value()
    model_value['country_code'] = code
    with pytest.raises(ValueError, match='Land'):
        run(monkeypatch, model_value)
    assert run(monkeypatch, model_value, SOURCE + ' Land: ' + country)['country_code'] == code


def test_new_device_contradicting_evidence_rejected(monkeypatch):
    model_value = value()
    model_value['rows'][0]['description'] = 'Sirene'
    with pytest.raises(ValueError, match='widerspricht'):
        run(monkeypatch, model_value)


def test_previous_device_quantity_correction_preserved(monkeypatch):
    state = value()
    model_value = value()
    model_value['rows'][0].update(quantity=8, evidence='Davon bitte acht.')
    result = run(monkeypatch, model_value, SOURCE + ' Davon bitte acht.', state)
    assert result['rows'][0]['quantity'] == 8
    assert result['rows'][1] == state['rows'][1]
