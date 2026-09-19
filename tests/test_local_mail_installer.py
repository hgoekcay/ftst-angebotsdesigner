import importlib.util
from pathlib import Path

import pytest


def module():
    spec = importlib.util.spec_from_file_location('local_mail_installer', Path(__file__).parents[1] / 'scripts/install_local_mail.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_provision_preserves_unrelated_settings_and_never_prints_secrets(monkeypatch, capsys):
    m = module()
    original_mail = {'email': 'info@ftst.eu', 'password': 'private-mail', 'login_password': 'private-login',
                     'public_url': 'https://mail.example.invalid', 'accounts': []}
    original_designer = {'billomat_id': 'ftst', 'billomat_api_key': 'private-billomat', 'ai_provider': 'ollama'}
    details = {m.MAIL: {'version': '0.3.0', 'options': original_mail},
               m.DESIGNER: {'version': '0.12.0', 'options': original_designer}}
    monkeypatch.setattr(m, 'info', lambda slug: details[slug])
    calls = []
    def api(path, payload):
        calls.append((path, payload))
        return {'valid': True}
    monkeypatch.setattr(m, 'api', api)
    m.connect()
    writes = {path: values['options'] for path, values in calls if path.endswith('/options')}
    first = writes['/addons/' + m.MAIL + '/options']
    second = writes['/addons/' + m.DESIGNER + '/options']
    assert first['bridge_token'] == second['strato_bridge_token']
    assert len(first['bridge_token']) >= 43
    assert first['password'] == original_mail['password']
    assert second['billomat_api_key'] == original_designer['billomat_api_key']
    assert 'password' not in second
    assert 'bridge_token' not in original_mail
    output = capsys.readouterr().out
    assert 'private-' not in output
    assert first['bridge_token'] not in output


def test_second_config_failure_restores_first_without_restarts(monkeypatch):
    m = module()
    options = {m.MAIL: {'email': 'info@ftst.eu', 'password': 'private'}, m.DESIGNER: {'billomat_id': 'ftst'}}
    monkeypatch.setattr(m, 'info', lambda slug: {'version': m.VERSIONS[slug], 'options': options[slug]})
    calls = []
    def api(path, payload):
        calls.append((path, payload))
        if path == '/addons/' + m.DESIGNER + '/options':
            raise RuntimeError()
        return {'valid': True}
    monkeypatch.setattr(m, 'api', api)
    with pytest.raises(RuntimeError):
        m.connect()
    assert calls[-1] == ('/addons/' + m.MAIL + '/options', {'options': options[m.MAIL]})
    assert not any(path.endswith('/restart') for path, _ in calls)


def test_invalid_options_do_not_write(monkeypatch):
    m = module()
    monkeypatch.setattr(m, 'info', lambda slug: {'version': m.VERSIONS[slug], 'options':
        {'email': 'info@ftst.eu', 'password': 'private', 'billomat_id': 'ftst'}})
    calls = []
    monkeypatch.setattr(m, 'api', lambda path, payload: calls.append(path) or {'valid': False})
    with pytest.raises(RuntimeError):
        m.connect()
    assert calls and all(path.endswith('/validate') for path in calls)
