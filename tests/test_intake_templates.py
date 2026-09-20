"""Explicit Ajax shortcuts and room-aware, reviewable technician requirements."""
import re
from copy import deepcopy

import pytest

import project_intake as intake
from quote_drafts import components as quote_components
from test_persistence import isolated_storage
from test_project_intake import HEADERS, PATH, fields, ui


def posted_rows(value):
    return {key: [row.get(key, '') for row in value['components']]
            for key in ('description', 'quantity', 'evidence', 'location')}


@pytest.mark.parametrize('choice,label', [
    ('motion', 'Bewegungsmelder'), ('contact', 'Magnetkontakt'),
    ('indoor_siren', 'Innensirene'), ('outdoor_siren', 'Außensirene'),
    ('indoor_keypad', 'Bedienteil innen'), ('outdoor_keypad', 'Bedienteil außen'),
    ('central', 'Zentrale'),
])
def test_shortcut_adds_only_requested_type_with_no_amount_and_keeps_entered_fields(ui, choice, label):
    client, store, model, project = ui
    values = fields(client, action='add_component:' + choice,
                    description=['Meine vorhandene Komponente'], quantity=['2,5'],
                    evidence=['Nachgemessen'], location=['Flur EG'], notes='Neu eingetippte Notiz',
                    installation='Montage besprechen', reviewed='yes')
    response = client.post(PATH, data=values, headers=HEADERS)
    assert response.status_code == 303
    assert response.headers['Location'].endswith('?saved=1#intake-components')
    saved = store.record('one', intake.KIND, 'job-1')
    assert saved['components'] == [
        {'description': 'Meine vorhandene Komponente', 'quantity': '2.5', 'evidence': 'Nachgemessen', 'location': 'Flur EG'},
        {'description': 'Ajax ' + label, 'quantity': '', 'evidence': '', 'location': ''},
    ]
    assert saved['fields']['notes'] == 'Neu eingetippte Notiz'
    assert saved['fields']['installation'] == 'Montage besprechen'
    assert saved['review_required'] is True
    assert store.record('one', 'project', 'job-1') == project
    page = client.get(PATH).text
    assert not re.search(r'<input[^>]*name="reviewed"[^>]*\bchecked\b', page)
    model.assert_not_called()


def test_room_is_private_until_explicit_review_and_visible_in_calculation_requirement(ui):
    client, store, model, project = ui
    values = fields(client, description=['Bewegungsmelder'], quantity=['6'], evidence=['Vor Ort'],
                    location=[' Flur EG '])
    assert client.post(PATH, data=values).status_code == 303
    saved = store.record('one', intake.KIND, 'job-1')
    assert saved['components'][0]['location'] == 'Flur EG'
    assert store.record('one', 'project', 'job-1') == project
    assert 'value="Flur EG"' in client.get(PATH).text
    values = fields(client, action='apply', **posted_rows(saved))
    assert client.post(PATH, data=values).status_code == 400
    assert store.record('one', 'project', 'job-1') == project
    values['reviewed'] = 'yes'
    assert client.post(PATH, data=values).status_code == 303
    updated = store.record('one', 'project', 'job-1')
    requirement = quote_components(updated)[0]
    assert requirement['description'] == 'Ajax Bewegungsmelder · Raum / Montageort: Flur EG'
    assert requirement['quantity'] == '6'
    assert updated['analysis']['components'][0]['source_description'] == 'Bewegungsmelder'
    assert updated['analysis']['components'][0]['location'] == 'Flur EG'
    assert 'Raum / Montageort: Flur EG' in client.get('/projects/job-1').text
    model.assert_not_called()


def test_legacy_records_and_forms_without_room_remain_usable(ui):
    client, store, model, project = ui
    old = intake.initial(project)
    old['components'] = [{'description': 'BM', 'quantity': '2', 'evidence': '2 BM'}]
    store.put_record('one', intake.KIND, 'job-1', old)
    page = client.get(PATH)
    assert page.status_code == 200
    assert 'name="location" maxlength="150" value=""' in page.text
    values = fields(client, action='apply', reviewed='yes', description=['BM'], quantity=['2'], evidence=['2 BM'])
    assert 'location' not in values
    assert client.post(PATH, data=values).status_code == 303
    assert quote_components(store.record('one', 'project', 'job-1')) == [
        {'description': 'Ajax BM', 'quantity': '2', 'evidence': '2 BM'},
    ]
    model.assert_not_called()


@pytest.mark.parametrize('changes,message', [
    ({'quantity': ['0']}, 'positive Zahl'),
    ({'location': ['Ort ' * 40]}, 'höchstens 150 Zeichen'),
    ({'description': ['Bewegungsmelder ' * 18], 'location': ['Flur im Erdgeschoss']}, 'höchstens 300 Zeichen'),
])
def test_invalid_edits_keep_room_and_all_other_inputs_without_confirming(ui, changes, message):
    client, store, model, project = ui
    values = fields(client, action='apply', reviewed='yes', description=['Bewegungsmelder'], quantity=['6'],
                    evidence=['Mein Beleg'], location=['Flur EG'], summary='Zusammenfassung geändert')
    values.update(changes)
    response = client.post(PATH, data=values)
    assert response.status_code == 400
    assert message in response.text
    for key in ('description', 'quantity', 'location', 'evidence'):
        assert 'value="' + values[key][0] + '"' in response.text
    assert 'Zusammenfassung geändert' in response.text
    assert not re.search(r'<input[^>]*name="reviewed"[^>]*\bchecked\b', response.text)
    assert store.record('one', intake.KIND, 'job-1') is None
    assert store.record('one', 'project', 'job-1') == project
    model.assert_not_called()


def test_shortcut_limit_never_truncates_or_changes_thirty_existing_components(ui):
    client, store, model, project = ui
    values = fields(client, action='add_component:central', description=['BM ' + str(i) for i in range(29)],
                    quantity=[''] * 29, evidence=['Beleg'] * 29, location=['Raum ' + str(i) for i in range(29)])
    assert client.post(PATH, data=values).status_code == 303
    saved = store.record('one', intake.KIND, 'job-1')
    assert len(saved['components']) == 30
    assert saved['components'][-1]['description'] == 'Ajax Zentrale'
    values = fields(client, action='add_component:motion', **posted_rows(saved))
    response = client.post(PATH, data=values)
    assert response.status_code == 400
    assert 'bereits 30 Komponenten' in response.text
    assert response.text.count('name="location"') == 30
    assert 'value="Raum 28"' in response.text
    assert store.record('one', intake.KIND, 'job-1') == saved
    assert store.record('one', 'project', 'job-1') == project
    model.assert_not_called()


@pytest.mark.parametrize('field,value,status', [('csrf', 'forged', 400), ('account', 'two', 409),
                                              ('revision', 'old', 409), ('action', 'add_component:unknown', 400)])
def test_shortcut_cannot_bypass_form_identity_revision_or_type_validation(ui, field, value, status):
    client, store, model, project = ui
    values = fields(client, action='add_component:motion', description=['MK'], quantity=['2'], evidence=['Manuell'], location=['Tür'])
    values[field] = value
    assert client.post(PATH, data=values).status_code == status
    assert store.record('one', intake.KIND, 'job-1') is None
    assert store.record('one', 'project', 'job-1') == project
    model.assert_not_called()


def test_conflict_keeps_unsaved_room_and_revision_without_overwriting(ui):
    client, store, model, project = ui
    values = fields(client, action='add_component:motion', description=['MK'], quantity=['2'],
                    evidence=['Manuell'], location=['Neue Tür'])
    other = deepcopy(project)
    other['notes'] = 'Parallel geändert'
    store.put_record('one', 'project', 'job-1', other)
    response = client.post(PATH, data=values)
    assert response.status_code == 409
    assert 'value="Neue Tür"' in response.text
    assert 'name="project_revision" value="' + values['project_revision'] + '"' in response.text
    assert store.record('one', 'project', 'job-1') == other
    assert store.record('one', intake.KIND, 'job-1') is None
    model.assert_not_called()
