from copy import deepcopy

import pytest
import project_intake as intake
from intake_systems import SYSTEMS
from test_persistence import isolated_storage  # noqa: F401
from test_project_intake import ui, fields, PATH, HEADERS  # noqa: F401


@pytest.mark.parametrize('system,shortcut', [('video','camera'), ('access','reader'), ('cylinder','cylinder'), ('intercom','outdoor')])
def test_system_switch_review_and_handoff_keep_scope(ui, system, shortcut):
    client, store, model, original = ui
    old = intake.initial(original)
    old['questions'] = intake.open_questions(old['fields']) + ['Kabelweg mit Kunde klären']
    store.put_record('one', intake.KIND, 'job-1', old)
    values = fields(client, system_type=system, questions='\n'.join(old['questions']))
    assert client.post(PATH, data=values).status_code == 303
    saved = store.record('one', intake.KIND, 'job-1')
    assert saved['fields']['manufacturer'] == ''
    assert 'Kabelweg mit Kunde klären' in saved['questions']
    assert not any('Ajax' in q or 'Sirene' in q for q in saved['questions'])
    page = client.get(PATH, headers=HEADERS).text
    assert 'FTST-Technikeraufnahme-' + SYSTEMS[system][2] + '.pdf' in page
    assert 'Ajax-Komponente schnell ergänzen' not in page
    assert '<label for="intake-central">' not in page
    assert client.post(PATH, data=fields(client, system_type=system, manufacturer='', action='add_component:'+shortcut)).status_code == 303
    saved = store.record('one', intake.KIND, 'job-1')
    label = SYSTEMS[system][4][shortcut]
    assert saved['components'] == [{'description': label, 'quantity': '', 'location': '', 'evidence': ''}]
    assert store.record('one', 'project', 'job-1') == original
    values = fields(client, system_type=system, manufacturer='Dahua', variant='Vor Ort prüfen',
                    action='apply', reviewed='yes', description=['Dahua '+label, 'Montage'],
                    quantity=['2','3'], evidence=['Vor Ort','3 Stunden'], location=['Eingang','Objekt'],
                    system_details='Bestand dokumentiert; Leitung prüfen', installation='Nach Aufmaß')
    assert client.post(PATH, data=values).status_code == 303
    project = store.record('one', 'project', 'job-1')
    assert project['intake_fields']['system_type'] == system
    assert project['analysis']['components'][0]['description'] == 'Dahua '+label+' · Raum / Montageort: Eingang'
    assert project['analysis']['components'][1]['description'] == 'Montage · Raum / Montageort: Objekt'
    assert 'Systemart: '+SYSTEMS[system][0] in project['notes']
    assert 'Bestand dokumentiert' in project['notes']
    model.assert_not_called()


def test_switch_requires_separate_save_and_rejects_wrong_shortcuts(ui):
    client, store, _, original = ui
    values = fields(client, system_type='video', action='apply', reviewed='yes', description=['Kamera'], quantity=['2'], evidence=['2 Kameras'])
    assert client.post(PATH, data=values).status_code == 400
    assert store.record('one', 'project', 'job-1') == original
    assert client.post(PATH, data=fields(client, system_type='video')).status_code == 303
    saved = deepcopy(store.record('one', intake.KIND, 'job-1'))
    assert client.post(PATH, data=fields(client, system_type='video', action='add_component:motion')).status_code == 400
    assert client.post(PATH, data=fields(client, system_type='bad')).status_code == 400
    assert store.record('one', intake.KIND, 'job-1') == saved


def test_legacy_alarm_and_explicit_brand_preserved():
    value = intake.initial({})
    value['fields'].pop('system_type')
    value['components'] = [{'description':'Dahua Türkontakt','quantity':'1','evidence':''}]
    assert intake.confirmed_components(value)[0]['description'] == 'Dahua Türkontakt'
    assert 'Ist eine Ajax-Zentrale vorhanden oder wird eine neue benötigt?' in intake.open_questions(value['fields'])
